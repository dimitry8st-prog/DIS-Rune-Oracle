"""JSON contracts. Validation is procedural, never a certificate of truth."""

from datetime import datetime, timezone
import hashlib
import json

CORES = ("rune", "yijing", "mo", "qiuqian", "daliuren", "egypt",
         "maya", "shakuna", "slavic", "name_grids")
STATUSES = {"OK", "ABSTAIN", "UNAVAILABLE", "ERROR"}


class ContractError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def timestamp(value):
    if not isinstance(value, str):
        raise ContractError("timestamp must be a string with a timezone")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError("invalid timestamp") from exc
    if result.tzinfo is None:
        raise ContractError("timezone is required")
    return result.astimezone(timezone.utc)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def shape(value, required, optional=()):
    if not isinstance(value, dict):
        raise ContractError("expected an object")
    missing = set(required) - value.keys()
    extra = value.keys() - set(required) - set(optional)
    if missing or extra:
        raise ContractError(f"missing={sorted(missing)}, unknown={sorted(extra)}")


def text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{name} must be a nonempty string")


def sequence(value, name):
    if not isinstance(value, list):
        raise ContractError(f"{name} must be an array")


def validate_event(event):
    shape(event, ("event_id", "question", "mode", "cutoff_at", "axes", "facts"))
    text(event["event_id"], "event_id")
    if event["question"] is not None:
        text(event["question"], "question")
    if event["mode"] not in {"forecast", "analysis", "retrospective"}:
        raise ContractError("invalid mode")
    cutoff = timestamp(event["cutoff_at"])
    sequence(event["axes"], "axes")
    if not event["axes"]:
        raise ContractError("at least one axis is required")
    axes, scopes = {}, set()
    for axis in event["axes"]:
        shape(axis, ("axis_id", "condition_id", "deadline", "scenarios", "baseline"))
        for key in ("axis_id", "condition_id"):
            text(axis[key], key)
        if axis["axis_id"] in axes:
            raise ContractError("duplicate axis_id")
        deadline = timestamp(axis["deadline"])
        scope = (axis["condition_id"], deadline)
        if scope in scopes:
            raise ContractError("duplicate comparison scope under different axis IDs")
        scopes.add(scope)
        if event["mode"] == "forecast" and deadline <= cutoff:
            raise ContractError("forecast deadline must be after cutoff")
        sequence(axis["scenarios"], "scenarios")
        scenarios = set()
        for scenario in axis["scenarios"]:
            shape(scenario, ("scenario_id", "criterion"))
            text(scenario["scenario_id"], "scenario_id")
            text(scenario["criterion"], "criterion")
            if scenario["scenario_id"] in scenarios:
                raise ContractError("duplicate scenario_id")
            scenarios.add(scenario["scenario_id"])
        if len(scenarios) < 2 or axis["baseline"] not in scenarios:
            raise ContractError("need mutually exclusive scenarios and a registered baseline")
        axes[axis["axis_id"]] = axis
    sequence(event["facts"], "facts")
    for fact in event["facts"]:
        shape(fact, ("text", "source", "available_at"))
        text(fact["text"], "fact.text")
        text(fact["source"], "fact.source")
        if timestamp(fact["available_at"]) > cutoff:
            raise ContractError("fact available after cutoff: temporal leakage")
    return axes


def validate_cards(cards, axes):
    sequence(cards, "cards")
    seen_cores, seen_claims = set(), set()
    for card in cards:
        shape(card, ("core_id", "status", "reason", "protocol_version", "inputs",
                     "input_hash", "raw_result", "interpretation", "claims"))
        core = card["core_id"]
        if core not in CORES or core in seen_cores:
            raise ContractError("unknown or duplicate core_id")
        seen_cores.add(core)
        if card["status"] not in STATUSES:
            raise ContractError("invalid core status")
        text(card["protocol_version"], "protocol_version")
        if card["input_hash"] != digest(card["inputs"]):
            raise ContractError("core input_hash mismatch")
        if card["status"] != "OK":
            text(card["reason"], "reason")
        else:
            text(card["interpretation"], "interpretation")
            if card["raw_result"] is None:
                raise ContractError("OK requires a raw result")
        sequence(card["claims"], "claims")
        if card["status"] != "OK" and card["claims"]:
            raise ContractError("non-OK cards cannot vote")
        for claim in card["claims"]:
            shape(claim, ("claim_id", "type", "text", "source_fragment", "axis_id", "scenario_id", "polarity",
                          "review_status"), ("reviewed_by", "reviewed_at"))
            text(claim["claim_id"], "claim_id")
            text(claim["text"], "claim.text")
            text(claim["source_fragment"], "source_fragment")
            if claim["source_fragment"] not in card["interpretation"]:
                raise ContractError("claim source_fragment is absent from the original interpretation")
            if claim["claim_id"] in seen_claims:
                raise ContractError("duplicate claim_id")
            seen_claims.add(claim["claim_id"])
            if claim["type"] not in {"SYMBOLIC", "FORECAST", "FACT", "ADVICE"}:
                raise ContractError("invalid claim type")
            axis = axes.get(claim["axis_id"])
            if axis is None or claim["scenario_id"] not in {
                    s["scenario_id"] for s in axis["scenarios"]}:
                raise ContractError("claim does not match registered axis/scenario")
            if claim["polarity"] not in {"SUPPORT", "OPPOSE", "UNSPECIFIED"}:
                raise ContractError("invalid polarity")
            if claim["review_status"] not in {"PENDING", "ACCEPTED", "REJECTED"}:
                raise ContractError("invalid review_status")
            if claim["review_status"] in {"ACCEPTED", "REJECTED"}:
                text(claim.get("reviewed_by"), "reviewed_by")
                timestamp(claim.get("reviewed_at"))
    return seen_cores
