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
from pathlib import Path
import secrets
import sqlite3
import zipfile

from research_stats.core import fields, hits, exact_sign, load_json
from .contracts import canonical, digest, now_iso, timestamp

VERSION = "oracle-workflow-v1"
GAMES = ("hunt", "four_of_twenty")


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


def frequency(rows, game, draw, cutoff, limit=100):
    """Only records received by this ledger at cutoff; never backfill timestamps."""
    identity(game, draw)
    if limit != 100 or type(limit) is not int:
        raise ValueError("frequency100-v1 requires limit=100")
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
             hashlib.sha256(f"frequency100-v1|{game}|{draw}|field={f}|number={n}".encode()).hexdigest()))[:4]) for f in (1, 2)]
    return {"state": "PICK", "method_id": "frequency100-v1", "fields": picks,
            "n": len(window), "window_limit": limit, "draws": [r["draw"] for r in window],
            "history_hash": digest(window), "counts": [{str(n): c[n] for n in range(1, 21)} for c in counts],
            "probability_claim": None, "validated_advantage": False}


class Workflow:
    def __init__(self, path, *, _clock=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
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
        previous = "0" * 64
        count = 0
        for row in self.db.execute("SELECT * FROM workflow_events ORDER BY seq"):
            count += 1
            body = {k: row[k] for k in ("seq", "kind", "key", "at", "previous")}
            body["payload"] = json.loads(row["payload"])
            if row["seq"] != count or row["previous"] != previous or digest(body) != row["hash"]:
                raise ValueError("workflow hash chain corrupted")
            previous = row["hash"]
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
        self.db.execute("INSERT INTO workflow_events VALUES(?,?,?,?,?,?,?)",
                        (body["seq"], kind, key, body["at"], canonical(payload), body["previous"], digest(body)))

    def state(self):
        self.verify()
        result = {"outcomes": {}, "forecasts": {}, "cancellations": {}, "protocols": {}, "legacy_summaries": []}
        for row in self.db.execute("SELECT kind,payload FROM workflow_events ORDER BY seq"):
            p = json.loads(row["payload"])
            if row["kind"] == "migration":
                for r in p["outcomes"]:
                    result["outcomes"][identity(r["game"], r["draw"])] = r
                for r in p["forecasts"]:
                    result["forecasts"][identity(r["game"], r["draw"])] = r
                for r in p["cancellations"]:
                    result["cancellations"][identity(r["game"], r["draw"])] = r
                result["legacy_summaries"] = p["legacy_summaries"]
            elif row["kind"] in ("outcome", "correction"):
                result["outcomes"][identity(p["game"], p["draw"])] = p
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
                    'cancellation': state['cancellations'].get(key)}

    def register(self, protocol):
        """Immutable plan for FUTURE observations; no automatic activation on import."""
        p = deepcopy(protocol)
        nonempty(p["study_id"]); nonempty(p["hypothesis"])
        if p["game"] not in GAMES or p["method"] not in ("frequency100-v1", "lottery-rune-hash-v2"):
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
            if occurred_at and timestamp(occurred_at) > timestamp(now):
                raise ValueError("outcome occurrence is in the future")
            forecast = state["forecasts"].get(key)
            if occurred_at and forecast and timestamp(occurred_at) < timestamp(forecast["target_at"]):
                raise ValueError("outcome occurrence precedes declared target; audit target separately")
            previous = state["outcomes"].get(key)
            if previous and previous["fields"] == value:
                return previous
            if previous:
                if correction_of != digest(previous):
                    raise ValueError("conflicting outcome; supply expected previous digest and reason")
                nonempty(reason)
            elif correction_of:
                raise ValueError("no outcome to correct")
            record = {"game": game, "draw": draw, "fields": value, "source": source,
                      "received_at": now, "occurred_at": occurred_at,
                      "numeric_eligible": True, "source_verification": "USER_SUPPLIED_UNATTESTED"}
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

    def forecast(self, game, draw, target_at, *, template=None, study_id=None, max_history_gap=5):
        key = identity(game, draw); target = timestamp(target_at).isoformat()
        if type(max_history_gap) is not int or max_history_gap < 0:
            raise ValueError("max_history_gap must be nonnegative")
        request = {"game": game, "draw": draw, "target_at": target, "study_id": study_id,
                   "template_hash": digest(template) if template is not None else None,
                   "max_history_gap": max_history_gap, "version": VERSION}
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
                if not timestamp(spec["starts_at"]) <= timestamp(now) < timestamp(target) <= timestamp(spec["ends_at"]):
                    raise ValueError("outside study interval")
                if sum(r.get("study_id") == study_id for r in state["forecasts"].values()) >= spec["sample_size"]:
                    raise ValueError("study sample cap reached (cancelled slots also count)")
                if spec["method"] == "lottery-rune-hash-v2" and template is None:
                    raise ValueError("rune study requires a cycle template")
            baseline = frequency(list(state["outcomes"].values()), game, draw, now)
            latest_draw = max(baseline.get("draws", []), default=None)
            gap = draw-latest_draw-1 if latest_draw is not None else None
            if gap is None or gap > max_history_gap:
                raise ValueError(f"stale or missing history: gap={gap}; import results or explicitly set max_history_gap")
            methods = {"frequency100-v1": baseline,
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
        """Read structured archive data only. Never execute/extract archived scripts."""
        archive = Path(archive)
        archive_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
        with zipfile.ZipFile(archive) as z:
            if len(z.namelist()) != len(set(z.namelist())) or len(z.namelist()) > 20000:
                raise ValueError("duplicate or excessive ZIP members")
            def read(name):
                if z.getinfo(name).file_size > 20_000_000: raise ValueError("oversize JSON")
                return load_json(z.read(name))
            base = "Oracle_2026-10-22/"
            latest_name = max(n for n in z.namelist() if n.endswith('/latest-archive-state.json'))
            latest = read(latest_name)
            outcomes = read(base+'updates/'+latest['observations_ref'])
            forecasts = [(n, read(n)) for n in z.namelist() if n.endswith('/numeric-selection.json')]
            summaries = [read(base+'updates/'+r) for r in latest['summary_refs']]
            cancellations = latest.get('cancelled_forecasts', [])
        with self.transaction():
            if self.db.execute("SELECT 1 FROM workflow_events WHERE key=?", ('migration:'+archive_hash,)).fetchone():
                return {"state": "ALREADY_IMPORTED", "archive_hash": archive_hash}
            state = self.state(); receipt = self.clock(); added = []; predictions = []
            for r in outcomes:
                key = identity(r['game'], r['draw']); nums = normalized(r['fields'])
                if key in state['outcomes']:
                    if state['outcomes'][key]['fields'] != nums: raise ValueError('archive outcome conflict '+key)
                    continue
                if any(identity(x['game'], x['draw']) == key for x in added): raise ValueError('duplicate archive outcome')
                added.append({'game': r['game'], 'draw': r['draw'], 'fields': nums, 'received_at': receipt,
                              'occurred_at': r.get('occurred_at'), 'source_recorded_at': r.get('recorded_at'),
                              'source': r.get('source', latest_name), 'numeric_eligible': r.get('numeric_eligible', True),
                              'source_verification': 'LEGACY_DECLARATION_UNATTESTED'})
            seen_forecasts = set()
            for name, r in forecasts:
                key = identity(r['game'], r['draw'])
                if key in seen_forecasts:
                    raise ValueError('duplicate archive forecast '+key)
                seen_forecasts.add(key)
                methods = {'lottery-rune-hash-v2': {'state': 'PICK', 'fields': normalized(r['fields'])},
                           'random': {'state': 'PICK', 'fields': normalized(r['random_control'])}}
                for arm, mid in [('frequency100_v1', 'frequency100-v1'), ('frequency20_v1', 'frequency20-v1')]:
                    if r.get(arm, {}).get('fields') is not None:
                        methods[mid] = {'state': 'PICK', 'fields': normalized(r[arm]['fields'])}
                item = {'game': r['game'], 'draw': r['draw'], 'target_at': r.get('target_at_declared', r.get('target_at', r.get('target_at_assumed'))),
                        'legacy_time_classification': r.get('timing_classification'),
                        'target_time_assumed': 'target_at_assumed' in r,
                        'fixed_at': r['fixed_at'], 'origin': 'LEGACY_UNATTESTED', 'methods': methods,
                        'source_path': name, 'original_hash': digest(r), 'study_id': None}
                if key in state['forecasts']:
                    if state['forecasts'][key].get('original_hash') != item['original_hash']:
                        raise ValueError('archive forecast conflict '+key)
                else: predictions.append(item)
            for c in cancellations:
                key = identity(c['game'], c['draw'])
                if key in state['forecasts'] and key not in state['cancellations']:
                    raise ValueError('archive cannot newly cancel an existing ledger forecast '+key)
                if key in state['cancellations'] and state['cancellations'][key] != c:
                    raise ValueError('archive cancellation conflict '+key)
            payload = {'archive_hash': archive_hash, 'received_at': receipt, 'outcomes': added,
                       'forecasts': predictions, 'cancellations': cancellations, 'legacy_summaries': summaries}
            self._append('migration', 'migration:'+archive_hash, payload)
            return {'state': 'IMPORTED', 'outcomes_added': len(added), 'forecasts_added': len(predictions),
                    'cancellations': len(cancellations), 'archive_hash': archive_hash}

    def report(self):
        with self.transaction():
            s = self.state(); trials = []; pending = []; cancelled = []
            for key, p in sorted(s['forecasts'].items()):
                if key in s['cancellations']:
                    cancelled.append(key); continue
                outcome = s['outcomes'].get(key)
                if outcome is None:
                    pending.append(key); continue
                scores = {m: hits(v['fields'], outcome['fields']) if v['state'] == 'PICK' else None for m,v in p['methods'].items()}
                trials.append({'game': p['game'], 'draw': p['draw'], 'origin': p['origin'], 'study_id': p.get('study_id'),
                               'scores': scores, 'corrected_outcome': 'correction_of' in outcome,
                               'source_conflict': p['game']=='hunt' and p['draw']==47129,
                               'independent_time_attestation': False})
            groups = []
            for origin in ('LEGACY_UNATTESTED', 'LOCAL_FUTURE_UNATTESTED'):
                for game in GAMES:
                    for method in ('lottery-rune-hash-v2','frequency100-v1','frequency20-v1'):
                        tt = [t for t in trials if t['origin']==origin and t['game']==game and not t['source_conflict']
                              and t['scores'].get(method) is not None and t['scores'].get('random') is not None]
                        a = [sum(t['scores'][method]) for t in tt]; c = [sum(t['scores']['random']) for t in tt]
                        groups.append({'origin':origin,'game':game,'method':method,'n':len(tt),
                                       'method_hits':sum(a),'control_hits':sum(c),'method_mean':sum(a)/len(a) if a else None,
                                       'control_mean':sum(c)/len(c) if c else None,'uniform_expected_mean':1.6,
                                       'diagnostic_only_sign_test':exact_sign([x-y for x,y in zip(a,c)]),
                                       'chronological_totals':[{'draw':t['draw'],'method':x,'control':y} for t,x,y in zip(tt,a,c)]})
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
                    'resolved': len(resolved), 'paired': len(paired),
                    'abstentions': len(resolved)-len(paired),
                    'method_hits': sum(sum(t['scores'][method]) for t in paired),
                    'control_hits': sum(sum(t['scores']['random']) for t in paired),
                    'corrected_outcomes': sum(t['corrected_outcome'] for t in resolved),
                    'enrollment_closed': len(enrolled) >= protocol['spec']['sample_size'],
                    'independent_time_attestation': False})
            return {'version':VERSION,'chain':self.verify(),'outcomes':len(s['outcomes']), 'forecasts':len(s['forecasts']),
                    'outcomes_by_game':dict(Counter(r['game'] for r in s['outcomes'].values())),
                    'pending':pending,'cancelled':cancelled,'trials':trials,'groups':groups,
                    'registered_studies':list(s['protocols'].values()), 'study_summaries':studies,
                    'legacy_published_summaries':s['legacy_summaries'],
                    'legacy_reconciliation':legacy_reconciliation,
                    'notice':'DESCRIPTIVE_ONLY. Same numbered draw only; legacy reuse summaries retained separately. No independent time attestation or demonstrated foresight.'}

    def backup(self, destination):
        destination = Path(destination)
        if destination.exists(): raise ValueError('backup destination already exists')
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction():
            pass
        # SQLite's backup API includes committed WAL contents in a consistent snapshot.
        with sqlite3.connect(destination) as target: self.db.backup(target)
        with Workflow(destination) as copied: return copied.verify()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True)
    sub = parser.add_subparsers(dest='command', required=True)
    migrate = sub.add_parser('migrate'); migrate.add_argument('archive')
    reg = sub.add_parser('register'); reg.add_argument('protocol')
    pred = sub.add_parser('forecast')
    for p in (pred,):
        p.add_argument('game', choices=GAMES); p.add_argument('draw', type=int); p.add_argument('target_at')
    pred.add_argument('--template'); pred.add_argument('--study-id'); pred.add_argument('--max-history-gap',type=int,default=5)
    out = sub.add_parser('outcome'); out.add_argument('game',choices=GAMES); out.add_argument('draw',type=int)
    out.add_argument('json_file'); out.add_argument('--correction-of'); out.add_argument('--reason')
    can = sub.add_parser('cancel'); can.add_argument('game',choices=GAMES); can.add_argument('draw',type=int); can.add_argument('reason')
    show = sub.add_parser('show'); show.add_argument('game', choices=GAMES); show.add_argument('draw', type=int)
    sub.add_parser('report'); sub.add_parser('verify')
    backup = sub.add_parser('backup'); backup.add_argument('destination')
    args = parser.parse_args(argv)
    try:
        with Workflow(args.db) as w:
            if args.command=='migrate': result=w.migrate(args.archive)
            elif args.command=='register': result=w.register(load_json(Path(args.protocol).read_text(encoding='utf-8')))
            elif args.command=='forecast': result=w.forecast(args.game,args.draw,args.target_at,
                template=load_json(Path(args.template).read_text(encoding='utf-8')) if args.template else None,
                study_id=args.study_id,max_history_gap=args.max_history_gap)
            elif args.command=='outcome':
                doc=load_json(Path(args.json_file).read_text(encoding='utf-8'))
                result=w.ingest(args.game,args.draw,doc['fields'],doc['source'],occurred_at=doc.get('occurred_at'),
                                correction_of=args.correction_of,reason=args.reason)
            elif args.command=='cancel': result=w.cancel(args.game,args.draw,args.reason)
            elif args.command=='backup': result=w.backup(args.destination)
            elif args.command=='report': result=w.report()
            elif args.command=='show': result=w.lookup(args.game,args.draw)
            else: result=w.verify()
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    except (ValueError,KeyError,TypeError,sqlite3.Error,OSError,zipfile.BadZipFile) as exc:
        print(json.dumps({'state':'REJECTED','reason':str(exc)},ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
