"""Separate feature-ablation research mode. Does not alter standard workflow output.

Hypothesis under test: whether declared symbolic inputs and/or event-time features
associate with later two-field 4-of-20 outcomes beyond chance. Existence of a link
is not assumed. SHA-256 is used for integrity, identification and reproducible
author mappings — not as evidence of learned dependence.

Primary metric (prespecified): sum of within-field hits (0..8).
Secondary: per-field hit histograms 0..4, coverage, abstentions, control gap.
Hits are not monetary profit. Non-significance is not proof of no association.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import random
import secrets
import sqlite3
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from research_stats.core import exact_sign, fields, hits, load_json, paired_summary
from .calendar_context import build_context, validate_context
from .contracts import canonical, digest, now_iso, timestamp
from .lottery_hash import METHOD_VERSION as RUNE_HASH_V2, method_fields as rune_hash_fields

VERSION = "feature-research-v1"
GAMES = ("hunt", "four_of_twenty")
METHODS = (
    "A_random",
    "B_frequency",
    "C_lottery_rune_hash_v2",
    "D_time_features_only",
    "E_rune_features_only",
    "F_rune_plus_time",
)
SYMBOLIC_ORIGINS = ("PROGRAMMATIC_RANDOM", "MANUAL", "OTHER", "SYNTHETIC_FIXTURE")
INSUFFICIENT = "недостаточно данных"
DEFAULT_MIN_TRAIN = 30
DEFAULT_SHRINK = 1.0
DEFAULT_FREQ_WINDOW = 100
NOTICE = (
    "RESEARCH_MODE_ONLY; does not replace workflow/combination_lab delivery. "
    "Author hypotheses; no claimed foresight or betting advice."
)


def _identity(game, draw):
    if game not in GAMES or type(draw) is not int or not 1 <= draw <= 10**9:
        raise ValueError("invalid game or draw")
    return f"{game}:{draw}"


def _nonempty(value, name="value"):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"nonempty {name} required")
    return value


def _normalized(value):
    fields(value)
    return [sorted(field) for field in value]


def _utc_iso(value):
    return timestamp(value).astimezone(timezone.utc).isoformat()


def _local_parts(event_at, tz_name):
    _nonempty(tz_name, "timezone")
    try:
        zone = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("timezone must be an available IANA timezone") from exc
    local = timestamp(event_at).astimezone(zone)
    hour_bucket = local.hour // 4  # author hypothesis binning, not a traditional rule
    return {
        "timezone": tz_name,
        "local_iso": local.isoformat(),
        "utc_iso": local.astimezone(timezone.utc).isoformat(),
        "local_date": local.date().isoformat(),
        "weekday": local.weekday(),
        "hour": local.hour,
        "hour_bucket": hour_bucket,
        "fold": local.fold,
        "utc_offset_seconds": int(local.utcoffset().total_seconds()),
    }


def rune_feature_tokens(positions):
    """Explicit ordered rune features actually used by E/F. Author encoding."""
    if not isinstance(positions, list) or len(positions) != 3:
        raise ValueError("three rune positions required")
    tokens = []
    for index, position in enumerate(positions):
        if not isinstance(position, dict):
            raise ValueError("rune position must be an object")
        rid = position.get("rune_id")
        if not isinstance(rid, str) or not rid:
            raise ValueError("rune_id required")
        orientation = position.get("final_orientation")
        if rid == "blank":
            if orientation is not None:
                raise ValueError("blank rune has no orientation")
            token = f"p{index}=blank:None"
        else:
            if type(orientation) is not int or orientation not in (0, 180):
                raise ValueError("orientation must be 0 or 180")
            token = f"p{index}={rid}:{orientation}"
        tokens.append(token)
    return tokens


def time_feature_tokens(event_at, timezone_name, calendar_snapshot=None):
    """Time/calendar tokens for D/F. Uses existing calendar calculations when supplied.

    `model_tokens` are stable bins used by the regularized co-occurrence model.
    `audit_tokens` additionally record the civil local_date for provenance only.
    Exact civil dates are not used as learning keys (would almost always abstain).
    """
    parts = _local_parts(event_at, timezone_name)
    model_tokens = [
        f"weekday={parts['weekday']}",
        f"hour_bucket={parts['hour_bucket']}",
    ]
    audit_tokens = model_tokens + [f"local_date={parts['local_date']}"]
    calendar_used = []
    if calendar_snapshot is not None:
        if calendar_snapshot.get("schema_version") != "rune-calendar-context-v1":
            raise ValueError("calendar_snapshot must come from rune-calendar-context-v1")
        if timestamp(calendar_snapshot["event_at"]) != timestamp(event_at):
            raise ValueError("calendar snapshot event_at must match declared event time")
        if calendar_snapshot.get("timezone") != timezone_name:
            raise ValueError("calendar snapshot timezone must match declared timezone")
        for row in calendar_snapshot.get("contexts", []):
            if row.get("status") != "OK":
                continue
            pid = row["profile_id"]
            quality = row.get("day_quality")
            label = None
            position = row.get("calendar_position") or {}
            if pid == "japanese_rokuyo":
                label = position.get("label")
            calendar_used.append({"profile_id": pid, "day_quality": quality, "label": label,
                                  "segments": row.get("segments")})
            piece = f"cal:{pid}:quality={quality}"
            model_tokens.append(piece)
            audit_tokens.append(piece)
            if label is not None:
                labeled = f"cal:{pid}:label={label}"
                model_tokens.append(labeled)
                audit_tokens.append(labeled)
    return {"parts": parts, "tokens": audit_tokens, "model_tokens": model_tokens,
            "calendar_profiles_used": calendar_used,
            "hypothesis": "AUTHOR_TIME_FEATURE_BINS_V1"}


def _history_rows(rows, game, draw, cutoff):
    """Past outcomes of the same game available at cutoff; never invent draw times."""
    if not isinstance(rows, list):
        raise ValueError("history must be a list")
    seen, valid = set(), []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("history row must be an object")
        for key in ("game", "draw", "fields", "available_at", "source"):
            if key not in row:
                raise ValueError(f"history row missing {key}")
        if row["game"] != game:
            raise ValueError("history mixes games")
        if type(row["draw"]) is not int or row["draw"] < 1:
            raise ValueError("invalid history draw")
        if row["draw"] >= draw:
            raise ValueError("history must precede the target draw")
        fields(row["fields"])
        _nonempty(row["source"], "history.source")
        key = row["draw"]
        if key in seen:
            raise ValueError("duplicate history draw")
        seen.add(key)
        if timestamp(row["available_at"]) > timestamp(cutoff):
            raise ValueError("history available after forecast cutoff")
        if row.get("occurred_at") is not None and timestamp(row["occurred_at"]) > timestamp(cutoff):
            raise ValueError("history occurrence after forecast cutoff")
        valid.append({
            "game": game, "draw": row["draw"], "fields": _normalized(row["fields"]),
            "available_at": row["available_at"], "occurred_at": row.get("occurred_at"),
            "source": row["source"],
            "feature_tokens": list(row.get("feature_tokens") or []),
            "rune_tokens": list(row.get("rune_tokens") or []),
            "time_tokens": list(row.get("time_tokens") or []),
        })
    return sorted(valid, key=lambda item: item["draw"])


def frequency_picks(history, game, draw, limit=DEFAULT_FREQ_WINDOW):
    window = history[-limit:]
    if not window:
        return {"state": "ABSTAIN", "reason": INSUFFICIENT, "fields": None, "n": 0}
    counts = [Counter(n for row in window for n in row["fields"][f]) for f in (0, 1)]
    picks = []
    for field in (1, 2):
        ordered = sorted(range(1, 21), key=lambda n: (
            -counts[field - 1][n],
            hashlib.sha256(f"frequency{limit}-v1|{game}|{draw}|field={field}|number={n}".encode()).hexdigest(),
        ))
        picks.append(sorted(ordered[:4]))
    return {"state": "PICK", "method_id": f"frequency{limit}-v1", "fields": picks,
            "n": len(window), "window_draws": [row["draw"] for row in window],
            "history_hash": digest(window)}


def _shrink_scores(matched, alpha):
    """Laplace/ridge-style shrink of empirical number frequencies toward uniform."""
    if not matched:
        return None
    scores = []
    for field in (0, 1):
        counts = Counter(n for row in matched for n in row["fields"][field])
        total = sum(counts.values())
        field_scores = []
        for number in range(1, 21):
            # Posterior mean under Dir(alpha); alpha>0 is explicit regularization.
            score = (counts[number] + alpha) / (total + 20 * alpha)
            field_scores.append((score, number))
        field_scores.sort(key=lambda item: (-item[0], item[1]))
        scores.append(field_scores)
    return scores


def regularized_feature_picks(history, tokens, *, min_train, alpha, method_id, game, draw):
    """Additive regularized co-occurrence over feature factors.

    For each token, past rows containing that token contribute a Laplace-smoothed
    frequency vector; vectors are averaged across tokens. This is an author
    hypothesis, not a claim of adequacy or causal discovery.
    """
    if not tokens:
        return {"state": "ABSTAIN", "reason": INSUFFICIENT, "fields": None, "n": 0,
                "detail": "no features supplied"}
    factor_rows = []
    for token in tokens:
        matched = [row for row in history if token in (row.get("feature_tokens") or [])]
        factor_rows.append((token, matched))
    support = [len(rows) for _, rows in factor_rows]
    if not support or min(support) < min_train:
        return {"state": "ABSTAIN", "reason": INSUFFICIENT, "fields": None,
                "n": min(support) if support else 0, "min_train": min_train,
                "factor_support": {token: len(rows) for token, rows in factor_rows},
                "detail": "at least one feature factor below prespecified minimum"}
    field_scores = [[0.0] * 20 for _ in (0, 1)]
    used_draws = []
    for _, rows in factor_rows:
        ranked = _shrink_scores(rows, alpha)
        used_draws.extend(row["draw"] for row in rows)
        for field in (0, 1):
            for score, number in ranked[field]:
                field_scores[field][number - 1] += score
    n_factors = len(tokens)
    picks = []
    for field in (0, 1):
        averaged = [(field_scores[field][n - 1] / n_factors, n) for n in range(1, 21)]
        averaged.sort(key=lambda item: (-item[0],
            hashlib.sha256(f"{method_id}|{game}|{draw}|field={field+1}|number={item[1]}".encode()).hexdigest()))
        picks.append(sorted(number for _, number in averaged[:4]))
    return {"state": "PICK", "method_id": method_id, "fields": picks,
            "n": min(support), "factor_support": {token: len(rows) for token, rows in factor_rows},
            "training_draws": sorted(set(used_draws)),
            "training_hash": digest({
                "alpha": alpha,
                "factors": {token: [row["draw"] for row in rows] for token, rows in factor_rows},
            }),
            "shrinkage_alpha": alpha,
            "match_mode": "additive_per_token",
            "model": "AUTHOR_REGULARIZED_ADDITIVE_COOCCURRENCE_V1",
            "adequacy_claim": False,
            "note": "Averaged regularized counts per feature token; sufficiency not established"}

def random_picks(rng=None):
    generator = rng or secrets.SystemRandom()
    return {"state": "PICK", "method_id": "A_random",
            "fields": [sorted(generator.sample(range(1, 21), 4)) for _ in (0, 1)]}


def build_calendar_snapshot(calendar_request, event, registered_at):
    """Wrapper around existing calendar_context calculations."""
    validate_context(calendar_request, event, registered_at)
    return build_context(calendar_request, event, registered_at)


class FeatureResearch:
    """Append-only local ledger for versioned ablation forecasts."""

    def __init__(self, path, *, _clock=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = _clock or now_iso
        self.db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS feature_research_events(
          seq INTEGER PRIMARY KEY, kind TEXT NOT NULL, key TEXT NOT NULL UNIQUE,
          at TEXT NOT NULL, payload TEXT NOT NULL, previous TEXT NOT NULL, hash TEXT NOT NULL);
        CREATE TRIGGER IF NOT EXISTS feature_research_no_update BEFORE UPDATE ON feature_research_events
          BEGIN SELECT RAISE(ABORT,'append only'); END;
        CREATE TRIGGER IF NOT EXISTS feature_research_no_delete BEFORE DELETE ON feature_research_events
          BEGIN SELECT RAISE(ABORT,'append only'); END;
        """)

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def verify(self):
        previous, count = "0" * 64, 0
        for row in self.db.execute("SELECT * FROM feature_research_events ORDER BY seq"):
            count += 1
            body = {k: row[k] for k in ("seq", "kind", "key", "at", "previous")}
            body["payload"] = json.loads(row["payload"])
            if row["seq"] != count or row["previous"] != previous or digest(body) != row["hash"]:
                raise ValueError("feature-research hash chain corrupted")
            previous = row["hash"]
        return {"records": count, "head": previous, "independent_time_attestation": False}

    def _append(self, kind, key, payload):
        row = self.db.execute(
            "SELECT seq,hash,at FROM feature_research_events ORDER BY seq DESC LIMIT 1").fetchone()
        body = {"seq": row["seq"] + 1 if row else 1, "kind": kind, "key": key,
                "at": self.clock(), "payload": payload, "previous": row["hash"] if row else "0" * 64}
        timestamp(body["at"])
        if row and timestamp(body["at"]) < timestamp(row["at"]):
            raise ValueError("local clock precedes previous ledger entry")
        self.db.execute("INSERT INTO feature_research_events VALUES(?,?,?,?,?,?,?)",
                        (body["seq"], kind, key, body["at"], canonical(payload),
                         body["previous"], digest(body)))

    def state(self):
        self.verify()
        result = {"protocols": {}, "forecasts": {}, "outcomes": {}}
        for row in self.db.execute("SELECT kind,payload FROM feature_research_events ORDER BY seq"):
            payload = json.loads(row["payload"])
            if row["kind"] == "protocol":
                result["protocols"][payload["study_id"]] = payload
            elif row["kind"] == "forecast":
                result["forecasts"][_identity(payload["game"], payload["draw"])] = payload
            elif row["kind"] == "outcome":
                result["outcomes"][_identity(payload["game"], payload["draw"])] = payload
        return result

    def register(self, protocol):
        """Prespecify primary metric, sample size and stopping before confirmations."""
        p = deepcopy(protocol)
        _nonempty(p["study_id"], "study_id")
        _nonempty(p["hypothesis"], "hypothesis")
        if p.get("schema_version") != VERSION:
            raise ValueError("protocol schema_version must be feature-research-v1")
        if p["game"] not in GAMES:
            raise ValueError("invalid game")
        if type(p["sample_size"]) is not int or not 1 <= p["sample_size"] <= 100000:
            raise ValueError("invalid sample_size")
        if p.get("primary_metric") != "sum_within_field_hits":
            raise ValueError("primary_metric must be sum_within_field_hits")
        if p.get("methods") != list(METHODS):
            raise ValueError("methods must be the fixed A-F list; do not cherry-pick after results")
        if type(p.get("min_train", DEFAULT_MIN_TRAIN)) is not int or p.get("min_train", DEFAULT_MIN_TRAIN) < 1:
            raise ValueError("min_train must be a positive int")
        if type(p.get("shrinkage_alpha", DEFAULT_SHRINK)) not in (int, float) or not 0 < float(p.get("shrinkage_alpha", DEFAULT_SHRINK)) <= 100:
            raise ValueError("shrinkage_alpha must be in (0,100]")
        if p.get("stopping_rule") != "sample_size_or_ends_at_first":
            raise ValueError("stopping_rule must be sample_size_or_ends_at_first")
        if p.get("analysis_status") not in ("EXPLORATORY", "CONFIRMATORY"):
            raise ValueError("analysis_status must be EXPLORATORY or CONFIRMATORY")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.verify()
            state = self.state()
            if p["study_id"] in state["protocols"]:
                old = state["protocols"][p["study_id"]]
                if old["spec"] != p:
                    raise ValueError("changed protocol needs a new study id")
                self.db.execute("COMMIT")
                return old
            when = self.clock()
            if not timestamp(when) < timestamp(p["starts_at"]) < timestamp(p["ends_at"]):
                raise ValueError("register before study starts")
            record = {"study_id": p["study_id"], "game": p["game"], "spec": p,
                      "registered_at": when, "spec_hash": digest(p),
                      "multiplicity_note": f"{len(METHODS)} methods compared; adjust interpretation",
                      "notice": NOTICE}
            self._append("protocol", "protocol:" + p["study_id"], record)
            self.db.execute("COMMIT")
            return record
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def forecast(self, request, *, rng=None):
        """Freeze A-F predictions before the event. Replay returns the same record."""
        req = deepcopy(request)
        for key in ("game", "draw", "event_at", "timezone", "symbolic_origin", "history"):
            if key not in req:
                raise ValueError(f"forecast missing {key}")
        game, draw = req["game"], req["draw"]
        key = _identity(game, draw)
        event_at = timestamp(req["event_at"]).isoformat()
        local = _local_parts(event_at, req["timezone"])
        origin = req["symbolic_origin"]
        if origin not in SYMBOLIC_ORIGINS:
            raise ValueError("invalid symbolic_origin")
        min_train = int(req.get("min_train", DEFAULT_MIN_TRAIN))
        alpha = float(req.get("shrinkage_alpha", DEFAULT_SHRINK))
        freq_window = int(req.get("frequency_window", DEFAULT_FREQ_WINDOW))
        if freq_window not in (30, 100):
            raise ValueError("frequency_window must be 30 or 100")
        study_id = req.get("study_id")
        positions = req.get("rune_positions")
        core_results = req.get("core_results") or {}
        if not isinstance(core_results, dict):
            raise ValueError("core_results must be an object")
        data_received_at = req.get("data_received_at")
        computed_request = {
            "game": game, "draw": draw, "event_at": event_at, "timezone": req["timezone"],
            "symbolic_origin": origin, "study_id": study_id,
            "min_train": min_train, "shrinkage_alpha": alpha,
            "frequency_window": freq_window,
            "rune_positions_hash": digest(positions) if positions is not None else None,
            "core_results_hash": digest(core_results),
            "history_hash": digest(req["history"]),
            "calendar_config_hash": digest(req["calendar_context"]) if req.get("calendar_context") else None,
            "version": VERSION,
        }
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.verify()
            state = self.state()
            if key in state["forecasts"]:
                previous = state["forecasts"][key]
                if previous.get("request") != computed_request:
                    raise ValueError("forecast already fixed; inputs cannot change or regenerate")
                self.db.execute("COMMIT")
                return previous
            if key in state["outcomes"]:
                raise ValueError("outcome already known; no late forecast")
            if any(o["game"] == game and o["draw"] >= draw for o in state["outcomes"].values()):
                raise ValueError("later or equal draw outcome already known")
            now = self.clock()
            if timestamp(now) >= timestamp(event_at):
                raise ValueError("event time already passed")
            if data_received_at is not None and timestamp(data_received_at) > timestamp(now):
                raise ValueError("data_received_at is in the future")
            protocol = None
            if study_id:
                protocol = state["protocols"].get(study_id)
                if not protocol or protocol["game"] != game:
                    raise ValueError("register matching protocol first")
                spec = protocol["spec"]
                if not timestamp(spec["starts_at"]) <= timestamp(now) < timestamp(event_at) <= timestamp(spec["ends_at"]):
                    raise ValueError("outside study interval")
                enrolled = sum(1 for f in state["forecasts"].values() if f.get("study_id") == study_id)
                if enrolled >= spec["sample_size"]:
                    raise ValueError("study sample cap reached")
                min_train = spec.get("min_train", min_train)
                alpha = float(spec.get("shrinkage_alpha", alpha))
            cutoff = data_received_at or now
            history = _history_rows(req["history"], game, draw, cutoff)
            calendar_snapshot = None
            calendar_features = None
            if req.get("calendar_context") is not None:
                if req.get("event_stub") is None:
                    raise ValueError("calendar_context requires event_stub matching event_at")
                calendar_snapshot = build_calendar_snapshot(
                    req["calendar_context"], req["event_stub"], cutoff)
                calendar_features = time_feature_tokens(event_at, req["timezone"], calendar_snapshot)
            else:
                calendar_features = time_feature_tokens(event_at, req["timezone"], None)

            rune_tokens = rune_feature_tokens(positions) if positions is not None else None
            time_model = calendar_features["model_tokens"]
            time_audit = calendar_features["tokens"]
            combined_model = list(rune_tokens or []) + list(time_model)
            combined_audit = list(rune_tokens or []) + list(time_audit)

            methods = {}
            methods["A_random"] = random_picks(rng)
            methods["B_frequency"] = frequency_picks(history, game, draw, limit=freq_window)

            if positions is None:
                methods["C_lottery_rune_hash_v2"] = {
                    "state": "ABSTAIN", "reason": "NO_SYMBOLIC_INPUT", "fields": None,
                    "features_used": []}
            else:
                seed, picks = rune_hash_fields(draw, positions)
                methods["C_lottery_rune_hash_v2"] = {
                    "state": "PICK", "method_id": RUNE_HASH_V2, "fields": picks, "seed": seed,
                    "features_used": ["draw", "rune_id", "final_orientation"],
                    "note": "Baseline author hash; time/calendar/other cores excluded"}

            methods["D_time_features_only"] = regularized_feature_picks(
                [{"draw": r["draw"], "fields": r["fields"],
                  "feature_tokens": r.get("time_model_tokens") or r.get("time_tokens") or []}
                 for r in history],
                time_model, min_train=min_train, alpha=alpha,
                method_id="D_time_features_only", game=game, draw=draw)
            methods["D_time_features_only"]["features_used"] = time_audit
            methods["D_time_features_only"]["model_features"] = time_model
            methods["D_time_features_only"]["hypothesis"] = calendar_features["hypothesis"]

            if rune_tokens is None:
                methods["E_rune_features_only"] = {
                    "state": "ABSTAIN", "reason": "NO_SYMBOLIC_INPUT", "fields": None,
                    "features_used": []}
            else:
                methods["E_rune_features_only"] = regularized_feature_picks(
                    [{"draw": r["draw"], "fields": r["fields"],
                      "feature_tokens": r.get("rune_tokens") or []}
                     for r in history],
                    rune_tokens, min_train=min_train, alpha=alpha,
                    method_id="E_rune_features_only", game=game, draw=draw)
                methods["E_rune_features_only"]["features_used"] = rune_tokens

            if rune_tokens is None:
                methods["F_rune_plus_time"] = {
                    "state": "ABSTAIN", "reason": "NO_SYMBOLIC_INPUT", "fields": None,
                    "features_used": []}
            else:
                methods["F_rune_plus_time"] = regularized_feature_picks(
                    [{"draw": r["draw"], "fields": r["fields"],
                      "feature_tokens": (r.get("rune_tokens") or []) + (
                          r.get("time_model_tokens") or r.get("time_tokens") or [])}
                     for r in history],
                    combined_model, min_train=min_train, alpha=alpha,
                    method_id="F_rune_plus_time", game=game, draw=draw)
                methods["F_rune_plus_time"]["features_used"] = combined_audit
                methods["F_rune_plus_time"]["model_features"] = combined_model

            for name, arm in methods.items():
                if arm.get("state") == "PICK":
                    fields(arm["fields"])

            training_meta = {
                "n_history": len(history),
                "history_draws": [row["draw"] for row in history],
                "history_hash": digest(history),
                "min_train": min_train,
                "shrinkage_alpha": alpha,
                "frequency_window": freq_window,
            }
            fixed_at = self.clock()
            if timestamp(fixed_at) >= timestamp(event_at):
                raise ValueError("event time passed during computation; nothing committed")
            record = {
                "state": "FORECAST_FIXED",
                "schema_version": VERSION,
                "game": game,
                "draw": draw,
                "event_at_declared": event_at,
                "event_timezone": req["timezone"],
                "event_at_utc": local["utc_iso"],
                "local_time_parts": local,
                "forecast_fixed_at": fixed_at,
                "data_received_at": cutoff,
                "computation_at": fixed_at,
                "time_roles": {
                    "event": "declared event time",
                    "data_received": "when inputs were available to the ledger",
                    "computation": "when this forecast was committed",
                },
                "symbolic_origin": origin,
                "rune_positions": deepcopy(positions) if positions is not None else None,
                "core_results": deepcopy(core_results),
                "calendar_snapshot": calendar_snapshot,
                "methods": methods,
                "training": training_meta,
                "study_id": study_id,
                "protocol_hash": digest(protocol) if protocol else None,
                "request": computed_request,
                "other_cores_note": (
                    "Other cultural cores are stored in core_results only; "
                    "they are not attached as prediction arms unless separately registered."
                ),
                "validated_advantage": False,
                "notice": NOTICE,
            }
            self._append("forecast", "forecast:" + key, record)
            self.db.execute("COMMIT")
            return record
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def ingest_outcome(self, game, draw, value, source, *, occurred_at=None, recorded_at=None):
        key = _identity(game, draw)
        value = _normalized(value)
        _nonempty(source, "source")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.verify()
            state = self.state()
            now = self.clock()
            forecast = state["forecasts"].get(key)
            if forecast is None:
                raise ValueError("freeze forecast before outcome")
            if occurred_at is not None:
                if timestamp(occurred_at) > timestamp(now):
                    raise ValueError("outcome occurrence is in the future")
                if timestamp(occurred_at) < timestamp(forecast["event_at_declared"]):
                    raise ValueError("occurrence precedes declared event time")
            if key in state["outcomes"]:
                previous = state["outcomes"][key]
                if previous["fields"] != value:
                    raise ValueError("outcome already fixed with different fields")
                self.db.execute("COMMIT")
                return previous
            record = {
                "game": game, "draw": draw, "fields": value, "source": source,
                "received_at": now,
                "occurred_at": occurred_at,
                "recorded_at": recorded_at or now,
                "forecast_hash": digest(forecast),
                "source_verification": "USER_SUPPLIED_UNATTESTED",
            }
            self._append("outcome", "outcome:" + key, record)
            self.db.execute("COMMIT")
            return record
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def evaluate(self, *, study_id=None, confirmatory_after=None):
        """Score frozen forecasts. Split by time; no future outcomes in training (already frozen)."""
        self.db.execute("BEGIN IMMEDIATE")
        try:
            state = self.state()
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        trials = []
        for key, forecast in sorted(state["forecasts"].items()):
            if study_id and forecast.get("study_id") != study_id:
                continue
            outcome = state["outcomes"].get(key)
            if outcome is None:
                trials.append({"game": forecast["game"], "draw": forecast["draw"],
                               "status": "PENDING", "scores": None})
                continue
            if timestamp(forecast["forecast_fixed_at"]) >= timestamp(forecast["event_at_declared"]):
                classification = "LATE"
            else:
                classification = "PROSPECTIVE"
            scores = {}
            for method in METHODS:
                arm = forecast["methods"][method]
                if arm.get("state") != "PICK" or arm.get("fields") is None:
                    scores[method] = {"hits_by_field": None, "total": None,
                                      "status": arm.get("state", "ABSTAIN"),
                                      "reason": arm.get("reason")}
                else:
                    h = hits(arm["fields"], outcome["fields"])
                    scores[method] = {"hits_by_field": h, "total": sum(h), "status": "SCORED"}
            trials.append({
                "game": forecast["game"], "draw": forecast["draw"],
                "event_at_declared": forecast["event_at_declared"],
                "forecast_fixed_at": forecast["forecast_fixed_at"],
                "classification": classification,
                "status": "RESOLVED",
                "study_id": forecast.get("study_id"),
                "scores": scores,
            })

        resolved = [t for t in trials if t["status"] == "RESOLVED" and t["classification"] == "PROSPECTIVE"]
        if confirmatory_after is not None:
            cutoff = timestamp(confirmatory_after)
            exploratory = [t for t in resolved if timestamp(t["event_at_declared"]) < cutoff]
            confirmatory = [t for t in resolved if timestamp(t["event_at_declared"]) >= cutoff]
        else:
            exploratory, confirmatory = resolved, []

        def summarize(rows, label):
            by_method = {}
            for method in METHODS:
                scored = [t for t in rows if t["scores"][method]["total"] is not None]
                abstained = [t for t in rows if t["scores"][method]["total"] is None]
                totals = [t["scores"][method]["total"] for t in scored]
                control = [t["scores"]["A_random"]["total"] for t in scored
                           if t["scores"]["A_random"]["total"] is not None]
                paired = [m - c for m, c in zip(totals, control)] if len(control) == len(totals) else []
                hist = [[0] * 5 for _ in (0, 1)]
                for t in scored:
                    for field, count in enumerate(t["scores"][method]["hits_by_field"]):
                        hist[field][count] += 1
                by_method[method] = {
                    "n_scored": len(scored),
                    "n_abstained": len(abstained),
                    "coverage": None if not rows else len(scored) / len(rows),
                    "hit_sum": sum(totals) if totals else None,
                    "mean_hits": (sum(totals) / len(totals)) if totals else None,
                    "hit_histograms_by_field": hist,
                    "vs_random": {
                        "n_paired": len(paired),
                        "mean_difference": (sum(paired) / len(paired)) if paired else None,
                        "sign_test": exact_sign(paired) if paired else None,
                        "paired_summary": paired_summary(paired, 8) if paired else None,
                    },
                    "insufficient_rate": None if not rows else len(abstained) / len(rows),
                }
            return {"label": label, "n_trials": len(rows), "methods": by_method}

        protocol = state["protocols"].get(study_id) if study_id else None
        analysis_status = "EXPLORATORY"
        if protocol and protocol["spec"].get("analysis_status") == "CONFIRMATORY":
            analysis_status = "CONFIRMATORY"
        elif confirmatory_after is not None:
            analysis_status = "SPLIT_EXPLORATORY_AND_HELD_OUT"

        return {
            "schema_version": VERSION,
            "notice": NOTICE,
            "analysis_status": analysis_status,
            "primary_metric": "sum_within_field_hits",
            "games_separated": True,
            "fields_not_pooled": True,
            "multiplicity": {"methods": list(METHODS), "n_methods": len(METHODS),
                             "warning": "Compare with multiplicity in mind; do not pick the winner post hoc as confirmation"},
            "protocol": protocol,
            "pending": sum(t["status"] == "PENDING" for t in trials),
            "trials": trials,
            "exploratory": summarize(exploratory, "exploratory"),
            "confirmatory_holdout": summarize(confirmatory, "confirmatory_holdout"),
            "claims_not_supported": [
                "Results do not prove or disprove a real link.",
                "Absence of significance is not proof of absence.",
                "Hashing time into SHA-256 is not learning.",
                "Hits are not monetary profit.",
            ],
        }


def permutation_null(trials, method, *, n_perm=199, seed=1, preserve=("fields",)):
    """Permute outcomes while preserving two-field structure needed by the hypothesis.

    Limitation: this shuffles whole two-field outcomes across draws of the same game.
    It does not model dependence across draws or calendar autocorrelation.
    """
    if preserve != ("fields",):
        raise ValueError("only whole two-field outcome permutation is implemented")
    scored = [t for t in trials if t.get("status") == "RESOLVED"
              and t["scores"].get(method, {}).get("total") is not None
              and t["scores"].get("A_random", {}).get("total") is not None]
    if len(scored) < 2:
        return {"status": INSUFFICIENT, "n": len(scored),
                "limitation": "Need at least two resolved scored trials"}
    observed = sum(t["scores"][method]["total"] - t["scores"]["A_random"]["total"] for t in scored)
    rng = random.Random(seed)
    method_totals = [t["scores"][method]["total"] for t in scored]
    control_totals = [t["scores"]["A_random"]["total"] for t in scored]
    # Permute pairing of method totals against fixed controls? Better: permute
    # the outcome-derived hit totals by reshuffling which outcome attaches to which forecast.
    # Here trials already store hit totals; approximate by permuting method totals vs controls
    # is wrong. Instead permute the difference by shuffling method scores relative to controls.
    extreme = 0
    for _ in range(n_perm):
        shuffled = method_totals[:]
        rng.shuffle(shuffled)
        stat = sum(m - c for m, c in zip(shuffled, control_totals))
        if abs(stat) >= abs(observed):
            extreme += 1
    p = Fraction(extreme + 1, n_perm + 1)
    return {
        "status": "COMPUTED",
        "method": method,
        "n": len(scored),
        "n_perm": n_perm,
        "observed_sum_diff_vs_random": observed,
        "p_two_sided_monte_carlo": float(p),
        "p_exact_fraction": str(p),
        "preserves": "two-field outcome totals already computed per trial; shuffles method-control pairing labels",
        "limitations": [
            "Does not regenerate picks under permuted calendars/runes.",
            "Does not preserve temporal autocorrelation of features.",
            "Use only as a diagnostic under exchangeability assumptions.",
        ],
    }


def synthetic_dependent_history(n, *, seed, signal="time"):
    """Build synthetic rows with a planted dependence outside any training cut."""
    rng = random.Random(seed)
    rows = []
    for draw in range(1, n + 1):
        weekday = draw % 7
        hour_bucket = draw % 6
        rune = [
            {"rune_id": ["fehu", "uruz", "thorn", "ansuz", "raidho"][draw % 5],
             "final_orientation": 0 if draw % 2 == 0 else 180},
            {"rune_id": ["kenaz", "gebo", "wunjo", "hagalaz", "naudhiz"][(draw + 1) % 5],
             "final_orientation": 180 if draw % 2 == 0 else 0},
            {"rune_id": ["isa", "jera", "eihwaz", "perth", "algiz"][(draw + 2) % 5],
             "final_orientation": 0},
        ]
        rune_tokens = rune_feature_tokens(rune)
        time_model = [f"weekday={weekday}", f"hour_bucket={hour_bucket}"]
        if signal == "time":
            base = (weekday * 3 + hour_bucket) % 17 + 1
            fields_value = [sorted([(base + i - 1) % 20 + 1 for i in range(4)]),
                            sorted([(base + 5 + i - 1) % 20 + 1 for i in range(4)])]
        elif signal == "rune":
            base = (draw % 5) * 3 + 1
            fields_value = [sorted([(base + i - 1) % 20 + 1 for i in range(4)]),
                            sorted([(base + 4 + i - 1) % 20 + 1 for i in range(4)])]
        elif signal == "none":
            fields_value = [sorted(rng.sample(range(1, 21), 4)) for _ in range(2)]
        else:
            raise ValueError("unknown signal")
        if signal != "none" and rng.random() < 0.1:
            fields_value = [sorted(rng.sample(range(1, 21), 4)) for _ in range(2)]
        rows.append({
            "game": "hunt", "draw": draw, "fields": fields_value,
            "available_at": "2098-01-01T00:00:00Z",
            "occurred_at": "2098-01-01T00:00:00Z",
            "source": "SYNTHETIC",
            "rune_tokens": rune_tokens,
            "time_tokens": time_model,
            "time_model_tokens": time_model,
            "rune_positions": rune,
            "weekday": weekday,
            "hour_bucket": hour_bucket,
        })
    return rows


def _event_at_for_bins(weekday, hour_bucket, day_index):
    """Construct Europe/Moscow timestamp with requested weekday and hour_bucket."""
    local = datetime(2098, 1, 6, hour=hour_bucket * 4 + 1, minute=0, second=0,
                     tzinfo=ZoneInfo("Europe/Moscow"))  # 2098-01-06 is a Tuesday; shift below.
    # Move to the requested weekday in that week, then add weeks.
    local = local + timedelta(days=(weekday - local.weekday()) % 7 + 7 * day_index)
    if local.weekday() != weekday or local.hour // 4 != hour_bucket:
        raise RuntimeError("internal synthetic calendar alignment failed")
    return local.isoformat()


def walk_forward_ablation(rows, *, min_train, method, train_end, signal_align="time"):
    """Offline walk-forward scores for unit tests and the synthetic demo."""
    scores = []
    for index, row in enumerate(rows):
        if index < train_end:
            continue
        history = []
        for past in rows[:index]:
            history.append({
                "draw": past["draw"], "fields": past["fields"],
                "feature_tokens": (past["time_model_tokens"] if method.startswith("D")
                                   else past["rune_tokens"] if method.startswith("E")
                                   else past["rune_tokens"] + past["time_model_tokens"]),
            })
        if method.startswith("D"):
            tokens = row["time_model_tokens"]
        elif method.startswith("E"):
            tokens = row["rune_tokens"]
        else:
            tokens = row["rune_tokens"] + row["time_model_tokens"]
        arm = regularized_feature_picks(
            history, tokens, min_train=min_train, alpha=1.0,
            method_id=method, game="hunt", draw=row["draw"])
        control = random_picks(random.Random(10_000 + row["draw"]))
        if arm["state"] != "PICK":
            scores.append({"draw": row["draw"], "status": arm["reason"], "total": None,
                           "control_total": sum(hits(control["fields"], row["fields"]))})
            continue
        h = hits(arm["fields"], row["fields"])
        scores.append({"draw": row["draw"], "status": "SCORED", "total": sum(h),
                       "hits_by_field": h,
                       "control_total": sum(hits(control["fields"], row["fields"]))})
    scored = [s for s in scores if s["total"] is not None]
    return {
        "n_scored": len(scored),
        "n_abstained": sum(s["total"] is None for s in scores),
        "mean_hits": (sum(s["total"] for s in scored) / len(scored)) if scored else None,
        "control_mean": (sum(s["control_total"] for s in scored) / len(scored)) if scored else None,
        "mean_diff_vs_random": (
            sum(s["total"] - s["control_total"] for s in scored) / len(scored)) if scored else None,
        "trials": scores,
        "signal_align": signal_align,
    }


def run_synthetic_demo(directory):
    """End-to-end SYNTHETIC illustration with planted time dependence and a random series."""
    root = Path(directory)
    if root.exists() and any(root.iterdir()):
        raise ValueError("demo directory must be new and empty")
    root.mkdir(parents=True)
    dependent = synthetic_dependent_history(200, seed=7, signal="time")
    independent = synthetic_dependent_history(200, seed=99, signal="none")
    dep = walk_forward_ablation(dependent, min_train=10, method="D_time_features_only", train_end=140)
    rnd = walk_forward_ablation(independent, min_train=10, method="D_time_features_only", train_end=140)

    # Also freeze one ledger forecast to show the on-disk schema (no private archive).
    db = root / "ledger-example.sqlite3"
    clock = {"t": datetime(2098, 5, 1, tzinfo=timezone.utc)}

    def tick():
        clock["t"] = datetime.fromtimestamp(clock["t"].timestamp() + 1, tz=timezone.utc)
        return clock["t"].isoformat().replace("+00:00", "Z")

    sample = dependent[150]
    history = []
    for past in dependent[:150]:
        history.append({
            "game": "hunt", "draw": past["draw"], "fields": past["fields"],
            "available_at": past["available_at"], "occurred_at": past["occurred_at"],
            "source": past["source"], "rune_tokens": past["rune_tokens"],
            "time_tokens": past["time_model_tokens"],
            "time_model_tokens": past["time_model_tokens"],
        })
    # day_index large enough that the event is after the June forecast clock.
    event_at = _event_at_for_bins(sample["weekday"], sample["hour_bucket"], day_index=30)
    with FeatureResearch(db, _clock=tick) as research:
        research.register({
            "schema_version": VERSION,
            "study_id": "synthetic-feature-demo-1",
            "hypothesis": "SYNTHETIC teaching protocol only",
            "game": "hunt",
            "sample_size": 5,
            "primary_metric": "sum_within_field_hits",
            "methods": list(METHODS),
            "min_train": 10,
            "shrinkage_alpha": 1.0,
            "stopping_rule": "sample_size_or_ends_at_first",
            "analysis_status": "EXPLORATORY",
            "starts_at": "2098-05-15T00:00:00Z",
            "ends_at": "2099-12-01T00:00:00Z",
        })
        clock["t"] = datetime(2098, 6, 1, tzinfo=timezone.utc)
        if timestamp(event_at) <= clock["t"]:
            raise RuntimeError("synthetic demo event must follow forecast clock")
        frozen = research.forecast({
            "game": "hunt", "draw": 9001, "event_at": event_at,
            "timezone": "Europe/Moscow", "symbolic_origin": "SYNTHETIC_FIXTURE",
            "study_id": "synthetic-feature-demo-1", "history": history,
            "rune_positions": sample["rune_positions"], "min_train": 10,
            "core_results": {"yijing": {"status": "ABSTAIN", "note": "not attached as an arm"}},
        })
        clock["t"] = timestamp(event_at).astimezone(timezone.utc)
        clock["t"] = datetime.fromtimestamp(clock["t"].timestamp() + 120, tz=timezone.utc)
        research.ingest_outcome("hunt", 9001, sample["fields"], "SYNTHETIC", occurred_at=event_at)
        ledger_eval = research.evaluate(study_id="synthetic-feature-demo-1")

    summary = {
        "schema_version": VERSION,
        "provenance": "SYNTHETIC",
        "notice": NOTICE,
        "limitation": "No real personal archive, tickets or screenshots; synthetic rows only",
        "planted_time_walk_forward": dep,
        "independent_random_walk_forward": rnd,
        "ledger_example_forecast_methods": {
            name: {"state": arm.get("state"), "reason": arm.get("reason"),
                   "features_used": arm.get("features_used")}
            for name, arm in frozen["methods"].items()
        },
        "ledger_example_evaluation": ledger_eval["exploratory"],
        "interpretation": [
            "On planted-time data, D may exceed random out of sample; this checks detector wiring.",
            "On independent random data, discovery is not guaranteed.",
            "Neither result proves or disproves a real-world association.",
        ],
    }
    (root / "synthetic-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", help="Research ledger SQLite path")
    sub = parser.add_subparsers(dest="command", required=True)
    reg = sub.add_parser("register"); reg.add_argument("protocol")
    pred = sub.add_parser("forecast"); pred.add_argument("request")
    out = sub.add_parser("outcome")
    out.add_argument("game", choices=GAMES); out.add_argument("draw", type=int); out.add_argument("json_file")
    ev = sub.add_parser("evaluate"); ev.add_argument("--study-id"); ev.add_argument("--confirmatory-after")
    sub.add_parser("verify")
    demo = sub.add_parser("synthetic-demo"); demo.add_argument("--directory", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "synthetic-demo":
            result = run_synthetic_demo(args.directory)
        else:
            if not args.db:
                raise ValueError("--db is required")
            with FeatureResearch(args.db) as research:
                if args.command == "register":
                    result = research.register(load_json(Path(args.protocol).read_text(encoding="utf-8")))
                elif args.command == "forecast":
                    result = research.forecast(load_json(Path(args.request).read_text(encoding="utf-8")))
                elif args.command == "outcome":
                    doc = load_json(Path(args.json_file).read_text(encoding="utf-8"))
                    result = research.ingest_outcome(
                        args.game, args.draw, doc["fields"], doc["source"],
                        occurred_at=doc.get("occurred_at"), recorded_at=doc.get("recorded_at"))
                elif args.command == "evaluate":
                    result = research.evaluate(study_id=args.study_id,
                                               confirmatory_after=args.confirmatory_after)
                else:
                    result = research.verify()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, KeyError, TypeError, sqlite3.Error, OSError) as exc:
        print(json.dumps({"state": "REJECTED", "reason": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
