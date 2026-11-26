"""Local study workflow. No networking, bets, model calls or claimed foresight.

One SQLite append per operation, under BEGIN IMMEDIATE. Receipt times are local
claims; hash chains detect edits but do not independently attest time.
"""
import argparse
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import tempfile
import zipfile

from research_stats.core import fields, hits, exact_sign, load_json
from .archive_migration import ARCHIVE_VERSION, forecast_record, join_forecasts, read_archive
from .contracts import canonical, digest, now_iso, timestamp

VERSION = "oracle-workflow-v1"
GAMES = ("hunt", "four_of_twenty")
WORKFLOW_FREQUENCY_TIE_BREAK = "SHA256_ASC_METHOD_GAME_DRAW_FIELD_NUMBER"
_OUTCOME_TIME_ERRORS = {
    "INVALID_RECEIVED_AT": "invalid outcome receipt time",
    "INVALID_OCCURRED_AT": "invalid outcome occurrence time; use ISO time with a timezone",
    "INVALID_TARGET_AT": "invalid forecast target time",
    "INVALID_FIXED_AT": "invalid forecast fixation time",
    "OCCURRED_AFTER_RECEIPT": "outcome occurrence is in the future at receipt",
    "OCCURRED_BEFORE_TARGET": "outcome occurrence precedes declared target; audit target separately",
    "RECEIVED_BEFORE_TARGET": "outcome receipt precedes declared target; audit target separately",
    "OCCURRED_BEFORE_FORECAST_FIX": "outcome occurrence precedes forecast fixation",
    "RECEIVED_BEFORE_FORECAST_FIX": "outcome receipt precedes forecast fixation",
}


def identity(game, draw):
    if game not in GAMES or type(draw) is not int or not 1 <= draw <= 10**9:
        raise ValueError("invalid game or draw")
    return f"{game}:{draw}"


def nonempty(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("nonempty source/reason required")
    return value


def normalized(value):
    fields(value)
    return [sorted(f) for f in value]


def _trial_time_issue(outcome, forecast, *, for_evaluation=False):
    times = {}
    for name, value in (
        ("received_at", outcome.get("received_at")),
        ("occurred_at", outcome.get("occurred_at")),
        ("target_at", forecast.get("target_at")),
        ("fixed_at", forecast.get("fixed_at")),
    ):
        try:
            times[name] = None if value is None and name != "received_at" else timestamp(value)
        except (ValueError, OverflowError):
            return "INVALID_" + name.upper()

    receipt, occurrence, target, fix = (times[name] for name in ("received_at", "occurred_at", "target_at", "fixed_at"))
    if for_evaluation and target is not None and fix is not None and fix >= target:
        return "FORECAST_FIXED_AT_OR_AFTER_TARGET"
    if occurrence is not None and occurrence > receipt:
        return "OCCURRED_AFTER_RECEIPT"
    if target is not None:
        if occurrence is not None and occurrence < target:
            return "OCCURRED_BEFORE_TARGET"
        if receipt < target:
            return "RECEIVED_BEFORE_TARGET"
    if fix is not None:
        if occurrence is not None and occurrence < fix:
            return "OCCURRED_BEFORE_FORECAST_FIX"
        if receipt < fix:
            return "RECEIVED_BEFORE_FORECAST_FIX"
    return None


def frequency(rows, game, draw, cutoff, limit=100):
    """Only records received by this ledger at cutoff; never backfill timestamps."""
    identity(game, draw)
    if type(limit) is not int or limit not in (30, 100):
        raise ValueError("frequency window must be 30 or 100")
    method_id = f"frequency{limit}-v1"
    candidates = [r for r in rows if r["game"] == game and r["draw"] < draw
                  and not (game == "hunt" and r["draw"] == 47129)
                  and r.get("numeric_eligible", True)
                  and timestamp(r["received_at"]) <= timestamp(cutoff)
                  and (r.get("occurred_at") is None or timestamp(r["occurred_at"]) <= timestamp(cutoff))]
    if len({r["draw"] for r in candidates}) != len(candidates):
        raise ValueError("duplicate history")
    window = sorted(candidates, key=lambda r: r["draw"])[-limit:]
    if not window:
        return {"state": "ABSTAIN", "reason": "NO_HISTORY", "fields": None, "n": 0}
    counts = [Counter(n for r in window for n in r["fields"][f]) for f in (0, 1)]
    picks = [sorted(sorted(range(1, 21), key=lambda n: (-counts[f-1][n],
             hashlib.sha256(f"{method_id}|{game}|{draw}|field={f}|number={n}".encode()).hexdigest()))[:4]) for f in (1, 2)]
    return {"state": "PICK", "method_id": method_id, "fields": picks,
            "n": len(window), "window_limit": limit, "draws": [r["draw"] for r in window],
            "history_hash": digest(window), "counts": [{str(n): c[n] for n in range(1, 21)} for c in counts],
            "probability_claim": None, "validated_advantage": False}


def _paired_groups(trials, forecasts):
    groups = {}
    for trial in trials:
        if trial['source_conflict'] or trial['scores'].get('random') is None:
            continue
        origin, game, draw = trial['origin'], trial['game'], trial['draw']
        arms = forecasts[identity(game, draw)]['methods']
        for method, score in trial['scores'].items():
            if method == 'random' or score is None:
                continue
            arm = arms[method]
            tie_break = None
            if method.startswith('frequency'):
                tie_break = WORKFLOW_FREQUENCY_TIE_BREAK if origin == 'LOCAL_FUTURE_UNATTESTED' else arm.get('tie_break')
                if tie_break is None:
                    continue
            variant = (origin, game, method, arm.get('method_version', method), canonical(tie_break))
            groups.setdefault(variant, []).append({'draw': draw, 'method': sum(score),
                                                   'control': sum(trial['scores']['random'])})
    result = []
    for (origin, game, method, version, tie_break), rows in sorted(groups.items()):
        paired = sorted(rows, key=lambda row: row['draw'])
        n = len(paired)
        method_hits = sum(row['method'] for row in paired)
        control_hits = sum(row['control'] for row in paired)
        result.append({'origin': origin, 'game': game, 'method': method, 'method_version': version,
                       'tie_break': json.loads(tie_break), 'n': n,
                       'method_hits': method_hits, 'control_hits': control_hits,
                       'method_mean': method_hits / n, 'control_mean': control_hits / n,
                       'uniform_expected_mean': 1.6,
                       'diagnostic_only_sign_test': exact_sign([row['method'] - row['control'] for row in paired]),
                       'chronological_totals': paired})
    return result


class Workflow:
    def __init__(self, path, *, _clock=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            try:
                self.path.touch(mode=0o600, exist_ok=False)
            except FileExistsError:
                pass
        self.clock = _clock or now_iso  # injection for tests only; not exposed in CLI
        self.db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS workflow_events(
          seq INTEGER PRIMARY KEY, kind TEXT NOT NULL, key TEXT NOT NULL UNIQUE,
          at TEXT NOT NULL, payload TEXT NOT NULL, previous TEXT NOT NULL, hash TEXT NOT NULL);
        CREATE TRIGGER IF NOT EXISTS workflow_no_update BEFORE UPDATE ON workflow_events
          BEGIN SELECT RAISE(ABORT,'append only'); END;
        CREATE TRIGGER IF NOT EXISTS workflow_no_delete BEFORE DELETE ON workflow_events
          BEGIN SELECT RAISE(ABORT,'append only'); END;
        CREATE TABLE IF NOT EXISTS workflow_archives(
          archive_hash TEXT NOT NULL PRIMARY KEY, contents BLOB NOT NULL);
        CREATE TRIGGER IF NOT EXISTS workflow_archive_no_update BEFORE UPDATE ON workflow_archives
          BEGIN SELECT RAISE(ABORT,'append only'); END;
        CREATE TRIGGER IF NOT EXISTS workflow_archive_no_delete BEFORE DELETE ON workflow_archives
          BEGIN SELECT RAISE(ABORT,'append only'); END;
        """)

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.verify()
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def verify(self):
        if self.db.in_transaction:
            return self.verify_connection(self.db)
        self.db.execute("BEGIN")
        try:
            return self.verify_connection(self.db)
        finally:
            self.db.execute("ROLLBACK")

    @staticmethod
    def verify_connection(db):
        """Verify an existing workflow connection with sqlite3.Row, read-only."""
        previous = "0" * 64
        count = 0
        archive_hashes = set()
        for row in db.execute("SELECT * FROM workflow_events ORDER BY seq"):
            count += 1
            body = {k: row[k] for k in ("seq", "kind", "key", "at", "previous")}
            body["payload"] = json.loads(row["payload"])
            if row["seq"] != count or row["previous"] != previous or digest(body) != row["hash"]:
                raise ValueError("workflow hash chain corrupted")
            previous = row["hash"]
            payload = body["payload"]
            if row["kind"] == "migration" and payload.get("archive_format") == ARCHIVE_VERSION:
                archive_hash = payload["archive_hash"]
                if archive_hash in archive_hashes or row["key"] != "migration-v2:" + archive_hash:
                    raise ValueError("invalid workflow archive anchor")
                archive_hashes.add(archive_hash)
        actual = set()
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workflow_archives'").fetchone():
            for row in db.execute("SELECT rowid, archive_hash FROM workflow_archives"):
                actual.add(row["archive_hash"])
                hasher = hashlib.sha256()
                with db.blobopen("workflow_archives", "contents", row["rowid"], readonly=True) as blob:
                    while block := blob.read(1024 * 1024):
                        hasher.update(block)
                if hasher.hexdigest() != row["archive_hash"]:
                    raise ValueError(f"workflow archive bytes do not match SHA256: {row['archive_hash']}")
        if actual != archive_hashes:
            raise ValueError("workflow archive anchors and stored originals differ")
        return {"records": count, "head": previous, "independent_time_attestation": False}

    def _append(self, kind, key, payload):
        row = self.db.execute("SELECT seq,hash,at FROM workflow_events ORDER BY seq DESC LIMIT 1").fetchone()
        body = {"seq": row["seq"] + 1 if row else 1, "kind": kind, "key": key,
                "at": self.clock(), "payload": payload, "previous": row["hash"] if row else "0" * 64}
        timestamp(body["at"])
        if row and timestamp(body["at"]) < timestamp(row["at"]):
            raise ValueError("local clock precedes previous ledger entry")
        if kind == "forecast" and timestamp(body["at"]) >= timestamp(payload["target_at"]):
            raise ValueError("deadline passed at journal commit")
        if kind in ("outcome", "correction", "migration") and timestamp(body["at"]) < timestamp(payload["received_at"]):
            raise ValueError("local clock precedes outcome receipt at journal commit")
        self.db.execute("INSERT INTO workflow_events VALUES(?,?,?,?,?,?,?)",
                        (body["seq"], kind, key, body["at"], canonical(payload), body["previous"], digest(body)))

    def state(self, *, include_outcome_history=False):
        self.verify()
        result = {"outcomes": {}, "forecasts": {}, "cancellations": {}, "protocols": {},
                  "legacy_summaries": [], "archive_imports": [], "archive_outcome_sources": {}}
        if include_outcome_history:
            result["outcome_history"] = {}

        def remember_outcome(outcome):
            key = identity(outcome["game"], outcome["draw"])
            result["outcomes"][key] = outcome
            if include_outcome_history:
                result["outcome_history"].setdefault(key, []).append(outcome)

        for row in self.db.execute("SELECT kind,payload FROM workflow_events ORDER BY seq"):
            p = json.loads(row["payload"])
            if row["kind"] == "migration":
                for r in p["outcomes"]:
                    remember_outcome(r)
                for r in p["forecasts"]:
                    result["forecasts"][identity(r["game"], r["draw"])] = r
                for r in p.get("forecasts_enriched", []):
                    result["forecasts"][identity(r["game"], r["draw"])] = r
                for r in p["cancellations"]:
                    result["cancellations"][identity(r["game"], r["draw"])] = r
                result["legacy_summaries"] = p["legacy_summaries"]
                if p.get("archive_format") == ARCHIVE_VERSION:
                    result["archive_imports"].append({"archive_hash": p["archive_hash"], "received_at": p["received_at"],
                                                       "standalone_runs": p["standalone_runs"]})
                    for key, source in p["outcome_sources"].items():
                        result["archive_outcome_sources"].setdefault(key, []).append(source)
            elif row["kind"] in ("outcome", "correction"):
                remember_outcome(p)
            elif row["kind"] == "forecast":
                result["forecasts"][identity(p["game"], p["draw"])] = p
            elif row["kind"] == "cancel":
                result["cancellations"][identity(p["game"], p["draw"])] = p
            elif row["kind"] == "protocol":
                result["protocols"][p["study_id"]] = p
        return result

    def lookup(self, game, draw):
        key = identity(game, draw)
        with self.transaction():
            state = self.state()
            outcome = state['outcomes'].get(key)
            return {'game': game, 'draw': draw, 'forecast': state['forecasts'].get(key),
                    'outcome': outcome, 'outcome_hash': digest(outcome) if outcome else None,
                    'archive_outcome_sources': state['archive_outcome_sources'].get(key, []),
                    'cancellation': state['cancellations'].get(key)}

    def register(self, protocol):
        """Immutable plan for FUTURE observations; no automatic activation on import."""
        p = deepcopy(protocol)
        nonempty(p["study_id"]); nonempty(p["hypothesis"])
        if p["game"] not in GAMES or p["method"] not in ("frequency100-v1", "frequency30-v1", "lottery-rune-hash-v2"):
            raise ValueError("invalid protocol game/method")
        if type(p["sample_size"]) is not int or not 1 <= p["sample_size"] <= 100000:
            raise ValueError("invalid sample size")
        if p.get("metric") != "within_field_hits" or p.get("control") != "random":
            raise ValueError("primary metric/control must be fixed")
        with self.transaction():
            state = self.state()
            if p["study_id"] in state["protocols"]:
                old = state["protocols"][p["study_id"]]
                if old["spec"] != p:
                    raise ValueError("changed protocol needs a new study id")
                return old
            if not timestamp(self.clock()) < timestamp(p["starts_at"]) < timestamp(p["ends_at"]):
                raise ValueError("register before study starts")
            record = {"study_id": p["study_id"], "game": p["game"], "spec": p,
                      "registered_at": self.clock(), "spec_hash": digest(p)}
            self._append("protocol", "protocol:" + p["study_id"], record)
            return record

    def ingest(self, game, draw, value, source, *, occurred_at=None, correction_of=None, reason=None):
        key = identity(game, draw); value = normalized(value); nonempty(source)
        with self.transaction():
            state = self.state(); now = self.clock()
            forecast = state["forecasts"].get(key, {})
            previous = state["outcomes"].get(key)
            record = {"game": game, "draw": draw, "fields": value, "source": source,
                      "received_at": now, "occurred_at": occurred_at,
                      "numeric_eligible": True, "source_verification": "USER_SUPPLIED_UNATTESTED"}
            issue = _trial_time_issue(record, forecast)
            if previous and previous["fields"] == value and issue in (
                None, "RECEIVED_BEFORE_TARGET", "RECEIVED_BEFORE_FORECAST_FIX",
            ):
                return previous
            if issue is not None:
                raise ValueError(_OUTCOME_TIME_ERRORS[issue])
            if previous:
                if correction_of != digest(previous):
                    raise ValueError("conflicting outcome; supply expected previous digest and reason")
                nonempty(reason)
            elif correction_of:
                raise ValueError("no outcome to correct")
            if previous:
                record.update(correction_of=correction_of, reason=reason)
            self._append("correction" if previous else "outcome", f"outcome:{key}:{digest(record)}", record)
            return record

    def cancel(self, game, draw, reason):
        key = identity(game, draw); nonempty(reason)
        with self.transaction():
            state = self.state()
            if key in state["cancellations"]:
                return state["cancellations"][key]
            if key not in state["forecasts"]:
                raise ValueError("no forecast to cancel")
            if key in state["outcomes"]:
                raise ValueError("resolved forecasts cannot be removed from scoring by cancellation")
            record = {"game": game, "draw": draw, "reason": reason, "cancelled_at": self.clock(),
                      "state": "CANCELLED_BY_USER", "operator_verified": False}
            self._append("cancel", "cancel:" + key, record)
            return record

    def forecast(self, game, draw, target_at, *, template=None, study_id=None, max_history_gap=5, frequency_window=100):
        key = identity(game, draw); target = timestamp(target_at).isoformat()
        if type(frequency_window) is not int or frequency_window not in (30, 100):
            raise ValueError("frequency window must be 30 or 100")
        if type(max_history_gap) is not int or max_history_gap < 0:
            raise ValueError("max_history_gap must be nonnegative")
        request = {"game": game, "draw": draw, "target_at": target, "study_id": study_id,
                   "template_hash": digest(template) if template is not None else None,
                   "max_history_gap": max_history_gap, "version": VERSION}
        if frequency_window != 100:
            request["frequency_window"] = frequency_window
        with self.transaction():
            state = self.state(); now = self.clock()
            if key in state["cancellations"]:
                raise ValueError("forecast is cancelled; cannot regenerate")
            if key in state["forecasts"]:
                previous = state["forecasts"][key]
                if previous.get("request") != request:
                    raise ValueError("forecast already fixed with different inputs or legacy target; no redraw")
                return previous
            if timestamp(now) >= timestamp(target):
                raise ValueError("deadline passed")
            if any(r["game"] == game and r["draw"] >= draw for r in state["outcomes"].values()):
                raise ValueError("target or later outcome already known")
            protocol = None
            if study_id:
                protocol = state["protocols"].get(study_id)
                if not protocol or protocol["game"] != game:
                    raise ValueError("register matching protocol first")
                spec = protocol["spec"]
                if spec["method"].startswith("frequency") and spec["method"] != f"frequency{frequency_window}-v1":
                    raise ValueError("frequency window does not match registered method")
                if not timestamp(spec["starts_at"]) <= timestamp(now) < timestamp(target) <= timestamp(spec["ends_at"]):
                    raise ValueError("outside study interval")
                if sum(r.get("study_id") == study_id for r in state["forecasts"].values()) >= spec["sample_size"]:
                    raise ValueError("study sample cap reached (cancelled slots also count)")
                if spec["method"] == "lottery-rune-hash-v2" and template is None:
                    raise ValueError("rune study requires a cycle template")
            baseline = frequency(list(state["outcomes"].values()), game, draw, now, limit=frequency_window)
            latest_draw = max(baseline.get("draws", []), default=None)
            gap = draw-latest_draw-1 if latest_draw is not None else None
            if gap is None or gap > max_history_gap:
                raise ValueError(f"stale or missing history: gap={gap}; import results or explicitly set max_history_gap")
            methods = {baseline["method_id"]: baseline,
                       "lottery-rune-hash-v2": {"state": "ABSTAIN", "fields": None, "reason": "NO_SYMBOLIC_INPUT"}}
            if template is not None:
                methods["lottery-rune-hash-v2"] = self._symbolic(game, draw, target, template)
            methods["random"] = {"state": "PICK", "fields": [sorted(secrets.SystemRandom().sample(range(1, 21), 4)) for _ in (1, 2)]}
            for arm in methods.values():
                if arm["state"] == "PICK": fields(arm["fields"])
            fixed = self.clock()
            if timestamp(fixed) >= timestamp(target):
                raise ValueError("deadline passed while computing; nothing committed")
            record = {"game": game, "draw": draw, "target_at": target, "fixed_at": fixed,
                      "request": request, "study_id": study_id, "protocol_hash": digest(protocol) if protocol else None,
                      "origin": "LOCAL_FUTURE_UNATTESTED", "methods": methods,
                      "history_latest_draw": latest_draw, "history_gap": gap, "history_count": baseline["n"],
                      "independent_time_attestation": False, "validated_advantage": False,
                      "note": "Symbolic mappings are author experiments; cultural consensus is not a number forecast"}
            self._append("forecast", "forecast:" + key, record)
            return record

    def _symbolic(self, game, draw, target, template):
        from .pipeline import Cycle
        from .combination_lab import _source, _runes
        if "numeric_study" in template:
            raise ValueError("use a workflow template without a separate numeric_study")
        run = f"workflow-{game}-{draw}"
        with Cycle(str(self.path)+".cycles", run) as cycle:
            prior = cycle._get("registered")
            if prior:
                m = prior["manifest"]
                if "workflow-template-sha256:" + digest(template) not in m["source_refs"]:
                    raise ValueError("unfinished cycle has a different template; no redraw")
            else:
                m = deepcopy(template)
                m.pop("calendar_context", None)
                m["source_refs"].append("workflow-template-sha256:" + digest(template))
                m["event"].update(event_id=f"{game}-{draw}", mode="forecast", cutoff_at=self.clock(),
                                  question=f"{game} draw {draw}; user-declared target {target}")
                if len(m["event"]["axes"]) != 1:
                    raise ValueError("one declared axis required")
                m["event"]["axes"][0]["deadline"] = target
                m["adapters"]["rune"]["choices"] = [{"slot": n, "rotation": secrets.choice((0, 180))}
                    for n in secrets.SystemRandom().sample(range(1, 26), 3)]
                # Calendar date must follow this target, not the copied template.
                from zoneinfo import ZoneInfo
                local = timestamp(target).astimezone(ZoneInfo("Europe/Moscow"))
                if "maya" in m["adapters"]:
                    m["adapters"]["maya"].update(year=local.year, month=local.month, day=local.day)
            cycle.start(m)
            for attempt in range(1, 4):
                card = next((c for c in cycle.status()["cards"] if c["core_id"] == "qiuqian"), None)
                if not card or card["raw_result"].get("final_state") != "pending": break
                cycle.step({"request_id": f"advance-{attempt}", "operation": "advance"})
            cycle.review({"claims_by_core": {}})
            original = cycle.freeze()
            event, cards = _source(original, timestamp(target), self.clock())
            if event["event_id"] != f"{game}-{draw}": raise ValueError("symbolic event mismatch")
            positions = _runes(cards.get("rune"))
            if positions is None: return {"state": "ABSTAIN", "fields": None, "reason": "RUNE_UNAVAILABLE"}
            seed = f"lottery-rune-hash-v2|target={draw}|" + ','.join(f"{p['rune_id']}:{p['final_orientation']}" for p in positions)
            picks = [sorted(sorted(range(1, 21), key=lambda n: hashlib.sha256(f"{seed}|field={f}|number={n}".encode()).digest())[:4]) for f in (1, 2)]
            return {"state": "PICK", "fields": picks, "seed": seed, "original_report_hash": digest(original),
                    "cycle_run_id": run, "cycle_chain": cycle.journal.verify(), "validated_advantage": False}

    def migrate(self, archive):
        """Import original numeric records and retain the exact source ZIP atomically."""
        parsed = read_archive(archive)
        migration_key = 'migration-v2:' + parsed.archive_hash
        with self.transaction():
            if self.db.execute("SELECT 1 FROM workflow_events WHERE key=?", (migration_key,)).fetchone():
                return {'state': 'ALREADY_IMPORTED', 'archive_hash': parsed.archive_hash}

            state = self.state()
            receipt = self.clock()
            added, outcome_sources = [], {}
            for row, source in parsed.outcomes:
                key = identity(row['game'], row['draw'])
                if key in outcome_sources:
                    raise ValueError('duplicate archive outcome ' + key)
                outcome_sources[key] = {**source, 'original_hash': digest(row)}
                nums = normalized(row['fields'])
                occurred = row.get('occurred_at')
                recorded = row.get('recorded_at')
                if occurred is not None:
                    timestamp(occurred)
                eligible = row.get('numeric_eligible', True)
                if type(eligible) is not bool:
                    raise ValueError('archive outcome numeric_eligible must be boolean: ' + key)
                old = state['outcomes'].get(key)
                if old:
                    previous_occurrence = old.get('occurred_at')
                    if (old['fields'] != nums or old.get('numeric_eligible', True) != eligible
                            or occurred is not None and previous_occurrence is not None
                            and timestamp(occurred) != timestamp(previous_occurrence)):
                        raise ValueError('archive outcome conflict ' + key)
                    continue
                observation = {'game': row['game'], 'draw': row['draw'], 'fields': nums, 'received_at': receipt,
                               'occurred_at': occurred, 'source_recorded_at': recorded,
                               'source': row.get('source', source['path']), 'numeric_eligible': eligible,
                               'source_verification': 'LEGACY_DECLARATION_UNATTESTED'}
                current = state['forecasts'].get(key)
                if current and current['origin'] == 'LOCAL_FUTURE_UNATTESTED':
                    issue = _trial_time_issue(observation, current)
                    if issue is not None:
                        raise ValueError(f"archive outcome {key}: {_OUTCOME_TIME_ERRORS[issue]}")
                added.append(observation)

            forecasts = {}
            for raw, source in parsed.forecasts:
                item = forecast_record(raw, source)
                key = identity(item['game'], item['draw'])
                old = forecasts.get(key, state['forecasts'].get(key))
                forecasts[key] = join_forecasts(old, item, key) if old else item
            predictions = [item for key, item in forecasts.items() if key not in state['forecasts']]
            enriched = [item for key, item in forecasts.items()
                        if key in state['forecasts'] and item != state['forecasts'][key]]

            cancellations = {}
            for row in parsed.cancellations:
                key = identity(row['game'], row['draw'])
                old = cancellations.get(key, state['cancellations'].get(key))
                if old and old != row:
                    raise ValueError('archive cancellation conflict ' + key)
                if key in state['forecasts'] and old is None:
                    raise ValueError('archive cannot newly cancel an existing ledger forecast ' + key)
                if key not in state['cancellations']:
                    cancellations[key] = row

            summaries = {digest(row): row for row in state['legacy_summaries']}
            for row in parsed.summaries:
                if not isinstance(row, dict):
                    raise ValueError('archive published summary must be an object')
                if not isinstance(row.get('trials', []), list):
                    raise ValueError('archive published trials must be an array')
                for trial in row.get('trials', []):
                    identity(trial['game'], trial['draw'])
                summaries[digest(row)] = row
            payload = {'archive_format': ARCHIVE_VERSION, 'archive_hash': parsed.archive_hash,
                       'received_at': receipt, 'outcomes': added, 'outcome_sources': outcome_sources,
                       'forecasts': predictions, 'forecasts_enriched': enriched,
                       'cancellations': list(cancellations.values()), 'legacy_summaries': list(summaries.values()),
                       'standalone_runs': parsed.standalone_runs}
            self.db.execute("INSERT INTO workflow_archives (archive_hash, contents) VALUES (?, ?)",
                            (parsed.archive_hash, parsed.contents))
            self._append('migration', migration_key, payload)
            return {'state': 'IMPORTED', 'outcomes_added': len(added), 'forecasts_added': len(predictions),
                    'forecasts_enriched': len(enriched), 'cancellations': len(cancellations),
                    'archive_hash': parsed.archive_hash, 'standalone_runs': parsed.standalone_runs}

    def export_archive(self, archive_hash, destination):
        """Publish a verified, byte-exact archive copy without replacing a file."""
        destination = Path(destination)
        with self.transaction():
            row = self.db.execute("SELECT rowid FROM workflow_archives WHERE archive_hash=?",
                                  (archive_hash,)).fetchone()
            if row is None:
                raise ValueError("archive original is unavailable for this SHA256")
            with tempfile.TemporaryDirectory(dir=destination.parent) as staging:
                staged = Path(staging) / "archive.zip"
                with self.db.blobopen("workflow_archives", "contents", row["rowid"], readonly=True) as blob, staged.open("xb") as file:
                    while chunk := blob.read(1024 * 1024):
                        file.write(chunk)
                    file.flush()
                    os.fsync(file.fileno())
                staged.chmod(0o600)
                os.link(staged, destination)
        return {'state': 'EXPORTED', 'archive_hash': archive_hash, 'destination': str(destination)}

    def report(self):
        with self.transaction():
            s = self.state(include_outcome_history=True)
            trials, pending, cancelled, excluded_trials = [], [], [], []
            for key, p in sorted(s['forecasts'].items()):
                if key in s['cancellations']:
                    cancelled.append(key); continue
                outcome = s['outcomes'].get(key)
                if outcome is None:
                    pending.append(key); continue
                for version in s['outcome_history'][key]:
                    issue = _trial_time_issue(version, p, for_evaluation=True)
                    if issue is not None:
                        excluded_trials.append({
                            'game': p['game'], 'draw': p['draw'], 'origin': p['origin'],
                            'study_id': p.get('study_id'), 'reason': issue,
                            'outcome_hash': digest(version), 'received_at': version.get('received_at'),
                            'occurred_at': version.get('occurred_at'), 'target_at': p.get('target_at'),
                            'fixed_at': p.get('fixed_at'),
                        })
                        break
                if issue is not None:
                    continue
                scores = {m: hits(v['fields'], outcome['fields']) if v['state'] == 'PICK' else None for m,v in p['methods'].items()}
                trials.append({'game': p['game'], 'draw': p['draw'], 'origin': p['origin'], 'study_id': p.get('study_id'),
                               'scores': scores, 'corrected_outcome': 'correction_of' in outcome,
                               'source_conflict': p['game']=='hunt' and p['draw']==47129,
                               'independent_time_attestation': False})
            archive_reconciliation = []
            for archive_import in s['archive_imports']:
                for run in archive_import['standalone_runs']:
                    if run['state'] == 'NO_CANONICAL_NUMERIC_PICK':
                        archive_reconciliation.append({**run, 'archive_hash': archive_import['archive_hash']})
            for forecast in s['forecasts'].values():
                if forecast['origin'] != 'LEGACY_UNATTESTED':
                    continue
                info = {'game': forecast['game'], 'draw': forecast['draw'], 'original_hash': forecast['original_hash']}
                if 'random' not in forecast['methods']:
                    archive_reconciliation.append({**info, 'state': 'NO_ARCHIVED_RANDOM_CONTROL'})
                for method, arm in forecast['methods'].items():
                    if method.startswith('frequency') and arm['state'] == 'PICK' and 'tie_break' not in arm:
                        archive_reconciliation.append({**info, 'method': method, 'state': 'FREQUENCY_TIE_BREAK_UNDECLARED'})
            legacy_reconciliation = []
            seen_legacy_gaps = set()
            for published in s['legacy_summaries']:
                for entry in published.get('trials', []):
                    key = identity(entry['game'],entry['draw'])
                    if key not in s['forecasts'] and key not in seen_legacy_gaps:
                        seen_legacy_gaps.add(key)
                        legacy_reconciliation.append({'game':entry['game'],'draw':entry['draw'],
                            'state':'LEGACY_SCORE_WITHOUT_SAME_NUMBER_ORIGINAL',
                            'action':'retained as legacy summary; no invented original or zero score'})
            studies = []
            for sid, protocol in s['protocols'].items():
                method = protocol['spec']['method']
                enrolled = [p for p in s['forecasts'].values() if p.get('study_id') == sid]
                resolved = [t for t in trials if t.get('study_id') == sid and not t['source_conflict']]
                paired = [t for t in resolved if t['scores'].get(method) is not None]
                studies.append({'study_id': sid, 'method': method, 'protocol_hash': protocol['spec_hash'],
                    'sample_size': protocol['spec']['sample_size'], 'enrolled': len(enrolled),
                    'cancelled': sum(identity(p['game'],p['draw']) in s['cancellations'] for p in enrolled),
                    'pending': sum(identity(p['game'],p['draw']) in pending for p in enrolled),
                    'excluded_timing': sum(t['study_id'] == sid for t in excluded_trials),
                    'resolved': len(resolved), 'paired': len(paired),
                    'abstentions': len(resolved)-len(paired),
                    'method_hits': sum(sum(t['scores'][method]) for t in paired),
                    'control_hits': sum(sum(t['scores']['random']) for t in paired),
                    'corrected_outcomes': sum(t['corrected_outcome'] for t in resolved),
                    'enrollment_closed': len(enrolled) >= protocol['spec']['sample_size'],
                    'independent_time_attestation': False})
            return {'version':VERSION,'chain':self.verify(),'outcomes':len(s['outcomes']), 'forecasts':len(s['forecasts']),
                    'outcomes_by_game':dict(Counter(r['game'] for r in s['outcomes'].values())),
                    'pending':pending,'cancelled':cancelled,'trials':trials,'groups':_paired_groups(trials, s['forecasts']),
                    'excluded_trials':excluded_trials,
                    'registered_studies':list(s['protocols'].values()), 'study_summaries':studies,
                    'legacy_published_summaries':s['legacy_summaries'],
                    'legacy_reconciliation':legacy_reconciliation,
                    'archive_imports':s['archive_imports'], 'archive_reconciliation':archive_reconciliation,
                    'notice':'DESCRIPTIVE_ONLY. Same numbered draw only; legacy reuse summaries retained separately. No independent time attestation or demonstrated foresight.'}

    def backup(self, destination, *, bundle=False):
        from .workflow_backup import backup
        if self.db.in_transaction:
            raise ValueError('finish the active workflow transaction before backup')
        return backup(self.path, destination, Workflow.verify_connection, bundle=bundle)

    @staticmethod
    def restore(source, destination):
        from .workflow_backup import restore
        return restore(source, destination, Workflow.verify_connection)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db')
    sub = parser.add_subparsers(dest='command', required=True)
    migrate = sub.add_parser('migrate'); migrate.add_argument('archive')
    export_archive = sub.add_parser('archive-export'); export_archive.add_argument('sha256'); export_archive.add_argument('destination')
    reg = sub.add_parser('register'); reg.add_argument('protocol')
    pred = sub.add_parser('forecast')
    for p in (pred,):
        p.add_argument('game', choices=GAMES); p.add_argument('draw', type=int); p.add_argument('target_at')
    pred.add_argument('--frequency-window',type=int,choices=(30,100),default=100)
    pred.add_argument('--template'); pred.add_argument('--study-id'); pred.add_argument('--max-history-gap',type=int,default=5)
    out = sub.add_parser('outcome'); out.add_argument('game',choices=GAMES); out.add_argument('draw',type=int)
    out.add_argument('json_file'); out.add_argument('--correction-of'); out.add_argument('--reason')
    can = sub.add_parser('cancel'); can.add_argument('game',choices=GAMES); can.add_argument('draw',type=int); can.add_argument('reason')
    show = sub.add_parser('show'); show.add_argument('game', choices=GAMES); show.add_argument('draw', type=int)
    sub.add_parser('report'); sub.add_parser('verify')
    backup = sub.add_parser('backup'); backup.add_argument('destination')
    backup.add_argument('--bundle', action='store_true', help='force a full directory backup regardless of its name')
    restore = sub.add_parser('restore'); restore.add_argument('source'); restore.add_argument('destination')
    args = parser.parse_args(argv)
    if args.command != 'restore' and args.db is None:
        parser.error('--db is required for this command')
    if args.command == 'restore' and args.db is not None:
        parser.error('restore takes a backup source and destination directory without --db')
    try:
        if args.command == 'restore':
            result = Workflow.restore(args.source, args.destination)
        elif args.command == 'backup':
            from .workflow_backup import backup as create_backup
            result = create_backup(args.db, args.destination, Workflow.verify_connection, bundle=args.bundle)
        else:
            result = _run_command(args)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    except (ValueError,KeyError,TypeError,OverflowError,sqlite3.Error,OSError,zipfile.BadZipFile) as exc:
        print(json.dumps({'state':'REJECTED','reason':str(exc)},ensure_ascii=False))
        return 2


def _run_command(args):
    with Workflow(args.db) as w:
        if args.command=='migrate': result=w.migrate(args.archive)
        elif args.command=='archive-export': result=w.export_archive(args.sha256, args.destination)
        elif args.command=='register': result=w.register(load_json(Path(args.protocol).read_text(encoding='utf-8')))
        elif args.command=='forecast': result=w.forecast(args.game,args.draw,args.target_at,
            template=load_json(Path(args.template).read_text(encoding='utf-8')) if args.template else None,
            study_id=args.study_id,max_history_gap=args.max_history_gap,frequency_window=args.frequency_window)
        elif args.command=='outcome':
            doc=load_json(Path(args.json_file).read_text(encoding='utf-8'))
            result=w.ingest(args.game,args.draw,doc['fields'],doc['source'],occurred_at=doc.get('occurred_at'),
                            correction_of=args.correction_of,reason=args.reason)
        elif args.command=='cancel': result=w.cancel(args.game,args.draw,args.reason)
        elif args.command=='report': result=w.report()
        elif args.command=='show': result=w.lookup(args.game,args.draw)
        else: result=w.verify()
    return result


if __name__ == '__main__':
    raise SystemExit(main())
