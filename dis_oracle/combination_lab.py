"""Prespecified author mappings, separate from cultural core votes and old runs.

All source identities/times are declarations. A local journal is not a timestamp
authority. Missing readings are abstentions, never negative forecasts.
"""
from collections import Counter
from copy import deepcopy
from functools import wraps
import hashlib
from pathlib import Path
import secrets

from research_stats.core import fields, hits
from .contracts import (ContractError, digest, now_iso, shape, text, timestamp,
                        validate_event, validate_cards)
from .journal import JournalError

VERSION = "combination-lab-v1"
ARMS = ("A", "B", "C", "D", "frequency20", "random")
EAST = ("yijing", "mo", "qiuqian", "daliuren")
CALENDARS = ("japanese_rokuyo", "egyptian_cairo")
NOTICE = "AUTHOR_EXPERIMENT; not historical number correspondences or validated probabilities"


def _serialized(function):
    """Serialize registration/RNG/cap checks across local CLI processes."""
    @wraps(function)
    def call(journal, *args, **kwargs):
        import fcntl
        database = journal.connection.execute("PRAGMA database_list").fetchone()[2]
        if not database:
            raise ContractError("laboratory needs a persistent local journal")
        with Path(database + ".lab.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return function(journal, *args, **kwargs)
    return call


def _integer(value, name, lower, upper):
    if type(value) is not int or not lower <= value <= upper:
        raise ContractError(f"{name} must be an integer in {lower}..{upper}")


def _list(value, name, allowed):
    if not isinstance(value, list) or not value or len(set(value)) != len(value) or any(x not in allowed for x in value):
        raise ContractError(f"invalid {name}")


def _time(provenance, at):
    if at is not None and provenance != "SYNTHETIC":
        raise ContractError("clock overrides are allowed only for SYNTHETIC studies")
    result = at or now_iso()
    timestamp(result)
    return result


@_serialized
def register(journal, protocol, *, at=None):
    """Register fixed hypotheses, dates, sample cap and missing-data policy."""
    journal.verify()
    shape(protocol, ("schema_version", "study_id", "provenance", "game", "starts_at", "ends_at",
                     "sample_size", "east_cores", "calendar_profiles", "east_sources", "excluded_draws"))
    if protocol["schema_version"] != VERSION or protocol["provenance"] not in ("SYNTHETIC", "IMPORTED"):
        raise ContractError("unsupported laboratory schema/provenance")
    text(protocol["study_id"], "study_id")
    if protocol["game"] not in ("hunt", "four_of_twenty"):
        raise ContractError("unsupported game")
    _integer(protocol["sample_size"], "sample_size", 1, 100000)
    _list(protocol["east_cores"], "east_cores", EAST)
    _list(protocol["calendar_profiles"], "calendar_profiles", CALENDARS)
    shape(protocol["east_sources"], protocol["east_cores"])
    for source in protocol["east_sources"].values():
        if source is not None:
            shape(source, ("corpus_version", "corpus_sha256", "source_ref"))
            for name, value in source.items():
                text(value, name)
            if len(source["corpus_sha256"]) != 64 or any(c not in "0123456789abcdef" for c in source["corpus_sha256"]):
                raise ContractError("invalid corpus SHA256")
    if not isinstance(protocol["excluded_draws"], list) or len(set(protocol["excluded_draws"])) != len(protocol["excluded_draws"]):
        raise ContractError("excluded_draws must be unique draw numbers")
    for draw in protocol["excluded_draws"]:
        _integer(draw, "excluded draw", 1, 10**9)
    key = "lab:protocol:" + digest(protocol["study_id"])
    when = _time(protocol["provenance"], at)
    old = journal.get(key)
    if old:
        if old["protocol"] != protocol:
            raise JournalError("protocol is immutable; changed rules need a new future study")
        return old
    if not timestamp(when) < timestamp(protocol["starts_at"]) < timestamp(protocol["ends_at"]):
        raise ContractError("register protocol before starts_at < ends_at")
    result = {"state": "LAB_REGISTERED", "registered_at": when, "synthetic_clock": at is not None, "protocol": deepcopy(protocol),
              "protocol_hash": digest(protocol), "arms": list(ARMS),
              "primary_contrast": "D_minus_A_on_complete_pairs",
              "metric": "sum_of_within_field_hits_0_to_8", "missing_policy": "ABSTAIN_AND_REPORT_COVERAGE",
              "stopping_rule": "sample_size_or_ends_at_first", "notice": NOTICE}
    journal.append(key, result)
    return result


def _protocol(journal, study_id):
    journal.verify()
    value = journal.get("lab:protocol:" + digest(study_id))
    if value is None:
        raise ContractError("register study first")
    return value


def _source(original, target, at):
    # A copied frozen report is validated as an import, not authenticated.
    shape(original, ("state", "pipeline_version", "registration_hash", "review_hash", "frozen"), ("calendar_context",))
    if original["state"] != "ORIGINAL_REPORT":
        raise ContractError("source must be an original frozen cycle report")
    frozen = original["frozen"]
    event = frozen["event"]
    if frozen.get("state") != "FROZEN" or frozen.get("input_hash") != digest({
            "event": event, "cards": frozen["raw_cards"], "engine_version": frozen["engine_version"]}):
        raise ContractError("source frozen input hash mismatch")
    axes = validate_event(event)
    validate_cards(frozen["raw_cards"], axes)
    if event["mode"] != "forecast" or len(axes) != 1:
        raise ContractError("laboratory needs one forecast axis")
    if timestamp(next(iter(axes.values()))["deadline"]) != target:
        raise ContractError("target does not match cycle deadline")
    if not timestamp(event["cutoff_at"]) <= timestamp(frozen["frozen_at"]) <= timestamp(at) < target:
        raise ContractError("source freeze/cutoff must precede lab freeze and future target")
    for card in frozen["raw_cards"]:
        if card["inputs"].get("event_id") != event["event_id"]:
            raise ContractError("card belongs to another event")
        for claim in card["claims"]:
            if claim.get("reviewed_at") and timestamp(claim["reviewed_at"]) > timestamp(frozen["frozen_at"]):
                raise ContractError("claim reviewed after source freeze")
    return event, {c["core_id"]: c for c in frozen["raw_cards"]}


def _runes(card):
    if not card or card["status"] != "OK":
        return None
    positions = card["raw_result"].get("positions")
    if not isinstance(positions, list) or len(positions) != 3:
        raise ContractError("three frozen rune positions required")
    result = []
    for p in positions:
        rid, orientation = p["rune_id"], p["final_orientation"]
        if not isinstance(rid, str) or not rid or any(c not in "abcdefghijklmnopqrstuvwxyz_" for c in rid):
            raise ContractError("invalid rune identifier")
        if rid == "blank":
            if orientation is not None:
                raise ContractError("blank rune has no orientation")
        elif type(orientation) is not int or orientation not in (0, 180):
            raise ContractError("invalid rune orientation")
        result.append({"rune_id": rid, "final_orientation": orientation})
    return result


def _calendar(original, profiles, event, rune_card):
    attachment = original.get("calendar_context")
    if attachment is None:
        return None
    snapshot = attachment["snapshot"]
    if attachment["snapshot_hash"] != digest(snapshot) or snapshot["event_id"] != event["event_id"]:
        raise ContractError("calendar snapshot hash/event mismatch")
    if timestamp(snapshot["event_at"]) != timestamp(event["axes"][0]["deadline"]):
        raise ContractError("calendar belongs to another target time")
    if not rune_card:
        return None
    expected = {"status": "BOUND", "core_id": "rune", "card_input_hash": rune_card["input_hash"],
                "procedure_commitment": rune_card["raw_result"]["commitment"]}
    if attachment.get("rune_binding") != expected:
        raise ContractError("calendar is not bound to the frozen rune card")
    by_id = {x["profile_id"]: x for x in snapshot["contexts"]}
    tokens = []
    for pid in profiles:
        row = by_id.get(pid)
        if not row or row["status"] != "OK":
            return None
        if row["input_hash"] != digest(row["inputs"]):
            raise ContractError("calendar profile input hash mismatch")
        if timestamp(row["inputs"]["available_at"]) > timestamp(event["cutoff_at"]):
            raise ContractError("late calendar source")
        tokens.append({"profile_id": pid, "profile_version": row["profile_version"],
                       "label": row["calendar_position"].get("label"),
                       "day_quality": row["day_quality"], "segments": row["segments"]})
    return tokens


def _east(cards, protocol, axis):
    tokens = []
    for core in protocol["east_cores"]:
        card, source = cards.get(core), protocol["east_sources"][core]
        if not card or card["status"] != "OK" or source is None:
            return None
        corpus = card["raw_result"].get("text_corpus")
        if corpus != source:
            return None
        forecasts = [c for c in card["claims"] if c["axis_id"] == axis and c["type"] == "FORECAST"]
        if any(c["review_status"] == "PENDING" for c in forecasts):
            return None
        claims = [c for c in forecasts if c["review_status"] == "ACCEPTED"]
        support = {c["scenario_id"] for c in claims if c["polarity"] == "SUPPORT"}
        oppose = {c["scenario_id"] for c in claims if c["polarity"] == "OPPOSE"}
        if len(support) != 1 or support & oppose:
            return None
        tokens.append({"core_id": core, "protocol_version": card["protocol_version"],
                       "corpus": source, "scenario_id": next(iter(support))})
    return tokens


def _picks(seed):
    return [sorted(sorted(range(1, 21), key=lambda n: hashlib.sha256(
        f"{seed}|field={f}|number={n}".encode()).digest())[:4]) for f in (1, 2)]


def _history(rows, protocol, draw, cutoff):
    if not isinstance(rows, list) or len(rows) > 10000:
        raise ContractError("history must contain at most 10000 normalized rows")
    seen, valid = set(), []
    for row in rows:
        shape(row, ("game", "draw", "fields", "available_at", "source"))
        _integer(row["draw"], "history draw", 1, 10**9)
        fields(row["fields"]); text(row["source"], "history.source")
        key = (row["game"], row["draw"])
        if key in seen:
            raise ContractError("duplicate history outcome, including duplicate/conflicting fields")
        seen.add(key)
        if row["game"] != protocol["game"] or row["draw"] >= draw:
            raise ContractError("history contains another game, target or later draw")
        if timestamp(row["available_at"]) > cutoff:
            raise ContractError("history available after source cutoff")
        if row["draw"] not in protocol["excluded_draws"]:
            valid.append(row)
    return sorted(valid, key=lambda x: x["draw"])[-20:]


@_serialized
def freeze(journal, study_id, request, *, at=None):
    """One irreversible local freeze; exact replay returns the recorded control."""
    registered = _protocol(journal, study_id)
    protocol = registered["protocol"]
    shape(request, ("game", "draw", "target_at", "original", "history"))
    if request["game"] != protocol["game"]:
        raise ContractError("game differs from protocol")
    when = _time(protocol["provenance"], at)
    _integer(request["draw"], "draw", 1, 10**9)
    key = "lab:trial:" + digest([study_id, request["game"], request["draw"]])
    old = journal.get(key)
    if old:
        if old["request_hash"] != digest(request):
            raise JournalError("frozen inputs cannot change or be redrawn")
        return old
    target = timestamp(request["target_at"])
    if not timestamp(protocol["starts_at"]) <= timestamp(when) < target <= timestamp(protocol["ends_at"]):
        raise ContractError("trial is outside study dates or target has passed")
    trials = [x["payload"] for x in journal.export() if x["record_key"].startswith("lab:trial:")
              and x["payload"].get("state") == "LAB_FROZEN"]
    if any(x["game"] == request["game"] and x["draw"] == request["draw"] for x in trials):
        raise ContractError("target already registered in a laboratory study")
    if sum(x["study_id"] == study_id for x in trials) >= protocol["sample_size"]:
        raise ContractError("registered sample cap reached")
    event, cards = _source(request["original"], target, when)
    if any(x["source_event_id"] == event["event_id"] for x in trials):
        raise ContractError("source event already used; do not relabel one reading as multiple trials")
    if timestamp(request["original"]["frozen"]["frozen_at"]) < timestamp(registered["registered_at"]):
        raise ContractError("study must be registered before the source reading is frozen")
    for card in cards.values():
        raw = card["raw_result"]
        reading = raw.get("reading_fixed_at", raw.get("generated_at")) if isinstance(raw, dict) else None
        if card["status"] == "OK" and reading is None:
            raise ContractError("completed reading needs a creation timestamp")
        if reading and not timestamp(registered["registered_at"]) <= timestamp(reading) <= timestamp(request["original"]["frozen"]["frozen_at"]):
            raise ContractError("reading must be created after study registration and before source freeze")
    rune = _runes(cards.get("rune"))
    cal = _calendar(request["original"], protocol["calendar_profiles"], event, cards.get("rune"))
    east = _east(cards, protocol, event["axes"][0]["axis_id"])
    window = _history(request["history"], protocol, request["draw"], timestamp(event["cutoff_at"]))
    arms = {}
    for name, need_cal, need_east in [("A", False, False), ("B", True, False), ("C", False, True), ("D", True, True)]:
        missing = [label for label, missing in [("rune", rune is None), ("calendar", need_cal and cal is None),
                                               ("east_reading", need_east and east is None)] if missing]
        if missing:
            arms[name] = {"status": "ABSTAIN", "fields": None, "missing": missing}
            continue
        if name == "A":
            seed = f"lottery-rune-hash-v2|target={request['draw']}|" + ",".join(
                f"{p['rune_id']}:{p['final_orientation']}" for p in rune)
        else:
            features = {"runes": rune, "calendar": cal if need_cal else None, "east": east if need_east else None}
            seed = f"lottery-combination-hash-v1|game={request['game']}|draw={request['draw']}|arm={name}|features={digest(features)}"
        arms[name] = {"status": "EXPERIMENTAL", "fields": _picks(seed), "seed": seed}
    if len(window) == 20:
        counts = [Counter(n for row in window for n in row["fields"][f]) for f in (0, 1)]
        picks = [sorted(sorted(range(1, 21), key=lambda n: (-counts[f-1][n], hashlib.sha256(
            f"frequency20-v1|{request['game']}|{request['draw']}|field={f}|number={n}".encode()).hexdigest()))[:4]) for f in (1, 2)]
        arms["frequency20"] = {"status": "EXPERIMENTAL", "fields": picks, "window": deepcopy(window)}
    else:
        arms["frequency20"] = {"status": "ABSTAIN", "fields": None, "missing": ["20_available_earlier_outcomes"]}
    arms["random"] = {"status": "CONTROL", "fields": [sorted(secrets.SystemRandom().sample(range(1, 21), 4)) for _ in (1, 2)]}
    completed = _time(protocol["provenance"], at)
    if not timestamp(when) <= timestamp(completed) < target:
        raise ContractError("target passed or clock moved backwards during calculation; no selection frozen")
    result = {"state": "LAB_FROZEN", "version": VERSION, "study_id": study_id,
              "provenance": protocol["provenance"], "game": request["game"], "draw": request["draw"],
              "target_at": request["target_at"], "frozen_at": completed, "synthetic_clock": at is not None,
              "protocol_hash": registered["protocol_hash"],
              "source_event_id": event["event_id"],
              "request_hash": digest(request), "source_hash": digest(request["original"]),
              "source_snapshot": deepcopy(request["original"]), "arms": arms,
              "independently_attested": False, "notice": NOTICE}
    # The request hash includes every supplied history row, not just the selected window.
    journal.append(key, result)
    return result


@_serialized
def evaluate(journal, study_id, outcome, *, at=None):
    registration = _protocol(journal, study_id)
    when = _time(registration["protocol"]["provenance"], at)
    shape(outcome, ("game", "draw", "fields", "observed_at", "source"))
    fields(outcome["fields"]); text(outcome["source"], "outcome.source")
    key = "lab:trial:" + digest([study_id, outcome["game"], outcome["draw"]])
    trial = journal.get(key)
    if trial is None:
        raise ContractError("freeze this target before evaluating")
    old = journal.get(key + ":outcome")
    if old:
        if old["outcome"] != outcome:
            raise JournalError("outcome cannot be overwritten; resolve source conflict separately")
        return old
    if not timestamp(trial["target_at"]) <= timestamp(outcome["observed_at"]) <= timestamp(when):
        raise ContractError("outcome before target or in future")
    scores = {}
    for arm, value in trial["arms"].items():
        h = hits(value["fields"], outcome["fields"]) if value["fields"] is not None else None
        scores[arm] = {"hits_by_field": h, "total": sum(h) if h is not None else None}
    result = {"state": "LAB_EVALUATED", "study_id": study_id, "evaluated_at": when, "synthetic_clock": at is not None,
              "trial_hash": digest(trial), "outcome": deepcopy(outcome), "scores": scores,
              "evidence_status": "DESCRIPTIVE_ONLY; sources and times not independently attested"}
    journal.append(key + ":outcome", result)
    return result


@_serialized
def summary(journal, study_id):
    registration = _protocol(journal, study_id)
    trials = [x["payload"] for x in journal.export() if x["record_key"].startswith("lab:trial:")
              and x["payload"].get("state") == "LAB_FROZEN" and x["payload"]["study_id"] == study_id]
    rows = []
    for trial in trials:
        outcome = journal.get("lab:trial:" + digest([study_id, trial["game"], trial["draw"]]) + ":outcome")
        rows.append((trial, outcome))
    arms = {}
    for arm in ARMS:
        scored = [o["scores"][arm]["total"] for _, o in rows if o and o["scores"][arm]["total"] is not None]
        arms[arm] = {"registered": len(rows), "abstained": sum(t["arms"][arm]["fields"] is None for t, _ in rows),
                     "scored": len(scored), "total_hits": sum(scored),
                     "mean_hits": sum(scored) / len(scored) if scored else None}
    contrasts = {}
    for first, second in [("B", "A"), ("C", "A"), ("D", "A"), ("D", "random"), ("A", "random"), ("frequency20", "random")]:
        pairs = [o["scores"][first]["total"] - o["scores"][second]["total"] for _, o in rows
                 if o and all(o["scores"][a]["total"] is not None for a in (first, second))]
        contrasts[first + "_minus_" + second] = {"complete_pairs": len(pairs),
            "mean_difference": sum(pairs) / len(pairs) if pairs else None}
    return {"state": "LAB_SUMMARY", "protocol": registration, "registered": len(rows),
            "resolved": sum(o is not None for _, o in rows), "unresolved": sum(o is None for _, o in rows),
            "arms": arms, "primary_contrast": {"id": "D_minus_A", **contrasts["D_minus_A"]},
            "paired_contrasts": contrasts,
            "evidence_status": "DESCRIPTIVE_ONLY; no superiority claim or automatic weight updates"}
