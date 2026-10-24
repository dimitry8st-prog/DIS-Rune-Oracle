"""Author numeric method lottery-rune-hash-v2.

The formula is not a tenth-core vote and does not rewrite a registered manifest.
Control is an independent uniform sample, saved once with the method picks.
"""
import hashlib
import secrets

from research_stats.core import field_distribution, fields, total_distribution
from .contracts import ContractError, text


METHOD_VERSION = "lottery-rune-hash-v2"
CONTROL_ID = "lottery-rune-hash-v2-uniform-control"
CONTROL_RULE = "uniform without replacement: four distinct integers 1..20 in each of two fields"
UNAVAILABLE = {
    "status": "UNAVAILABLE",
    "extension": "explicit versioned numeric_study import; no symbol conversion",
}


def orientation_token(value):
    if value is None:
        return "None"
    if type(value) is int and value in (0, 180):
        return str(value)
    raise ContractError("final_orientation must be 0, 180 or None")


def seed_text(draw, positions):
    if type(draw) is not int or draw < 1:
        raise ContractError("draw must be a positive integer; bool is not a draw number")
    if not isinstance(positions, list) or len(positions) != 3:
        raise ContractError("lottery formula needs three saved rune positions")
    parts = []
    for position in positions:
        if not isinstance(position, dict):
            raise ContractError("rune position must be an object")
        text(position.get("rune_id"), "rune_id")
        parts.append(f"{position['rune_id']}:{orientation_token(position.get('final_orientation'))}")
    return f"{METHOD_VERSION}|target={draw}|{','.join(parts)}"


def method_fields(draw, positions):
    """SHA-256 rank, first four numbers, then ascending within each field."""
    seed = seed_text(draw, positions)
    chosen = []
    for field in (1, 2):
        ranking = []
        for number in range(1, 21):
            payload = f"{seed}|field={field}|number={number}".encode("utf-8")
            ranking.append((hashlib.sha256(payload).digest(), number))
        ranking.sort(key=lambda item: item[0])
        chosen.append(sorted(number for _, number in ranking[:4]))
    return seed, chosen


def control_fields(rng=None):
    generator = rng or secrets.SystemRandom()
    return [sorted(generator.sample(range(1, 21), 4)) for _ in range(2)]


def expectation():
    per_field = sum(index * weight for index, weight in enumerate(field_distribution()))
    total = sum(index * weight for index, weight in enumerate(total_distribution()))
    return {"hits_per_field": str(per_field), "total_hits": str(total),
            "null_model": "independent uniform 4-of-20 fields from research_stats"}


def positions_from_card(card):
    raw = card.get("raw_result") if isinstance(card, dict) else None
    readings = raw.get("positions") if isinstance(raw, dict) else None
    if card.get("core_id") != "rune" or card.get("status") != "OK" or not isinstance(readings, list):
        raise ContractError("lottery numbers require a completed saved rune session")
    return [{"rune_id": item["rune_id"], "final_orientation": item["final_orientation"]}
            for item in readings]


def validate_plan(plan, adapters):
    from .contracts import shape, timestamp
    shape(plan, ("game", "draw", "target_at", "method_version", "control_rule"))
    text(plan["game"], "game")
    if type(plan["draw"]) is not int or plan["draw"] < 1:
        raise ContractError("draw must be a positive integer; bool is not a draw number")
    if plan["target_at"] is not None:
        timestamp(plan["target_at"])
    if plan["method_version"] != METHOD_VERSION:
        raise ContractError("method_version must be lottery-rune-hash-v2")
    if plan["control_rule"] != CONTROL_RULE:
        raise ContractError("control_rule does not match the registered uniform sample")
    if "rune" not in adapters:
        raise ContractError("lottery plan requires the saved rune session")


def validate_outcome(outcome, event_id, draw):
    """Reject a foreign draw before any scientific record is appended."""
    from .contracts import shape, timestamp
    shape(outcome, ("event_id", "draw", "occurred_at", "recorded_at", "confirmation", "source_ref", "fields"))
    text(outcome["event_id"], "event_id")
    if outcome["event_id"] != event_id or outcome["draw"] != draw:
        raise ContractError("numeric outcome is bound to another draw")
    for key in ("occurred_at", "recorded_at"):
        if outcome[key] is not None:
            timestamp(outcome[key])
    if outcome["confirmation"] not in ("CONFIRMED", "UNCONFIRMED"):
        raise ContractError("confirmation must be CONFIRMED or UNCONFIRMED")
    text(outcome["source_ref"], "source_ref")
    try:
        fields(outcome["fields"])
    except ValueError as exc:
        raise ContractError(str(exc)) from exc


def statistics_study(record, outcomes, analysis_at, provenance, event_id, mode):
    cleaned = []
    seen = set()
    for outcome in outcomes:
        validate_outcome(outcome, event_id, record["draw"])
        if outcome["event_id"] in seen:
            raise ContractError("duplicate numeric outcome")
        seen.add(outcome["event_id"])
        cleaned.append({key: outcome[key] for key in
                        ("event_id", "occurred_at", "recorded_at", "confirmation", "source_ref", "fields")})
    fixed = record["fixed_at"]
    evidence = record["seed"]
    def prediction(strategy, picked, suffix):
        return {"prediction_id": f"{event_id}:{record['draw']}:{suffix}",
                "event_id": event_id, "strategy_id": strategy,
                "mode": "forecast" if mode == "forecast" else "retrospective",
                "status": "PICK", "fixed_at": fixed, "confirmation": "CONFIRMED",
                "evidence_ref": evidence, "fields": picked}
    return {"schema_version": "dis-statistics-v1",
            "study_id": f"{event_id}:{record['draw']}:{METHOD_VERSION}",
            "provenance": provenance, "method_id": METHOD_VERSION, "control_id": CONTROL_ID,
            "registered_at": record["registered_at"], "analysis_at": analysis_at,
            "events": [{"event_id": event_id, "registered_at": record["registered_at"],
                        "target_at": record["target_at"]}],
            "predictions": [prediction(METHOD_VERSION, record["method_fields"], "method"),
                            prediction(CONTROL_ID, record["control_fields"], "control")],
            "outcomes": cleaned}


def author_report(stats):
    paired = stats["matched_pairs"]
    method_sum = sum(sum(pair["method"]) for pair in paired) if paired else None
    control_sum = sum(sum(pair["control"]) for pair in paired) if paired else None
    descriptive = {}
    exclusions = []
    for row in stats["trials"]:
        hits = row["hits_by_field"] if row["hits_by_field"] is not None else row["descriptive_hits_not_prospective"]
        descriptive.setdefault(row["strategy_id"], []).append(hits)
        exclusions.append({"strategy_id": row["strategy_id"], "classification": row["classification"],
                           "exclusion_reasons": row["exclusion_reasons"],
                           "hits_by_field": row["hits_by_field"],
                           "descriptive_hits_not_prospective": row["descriptive_hits_not_prospective"]})
    return {"status": "AUTHOR_METHOD", "author_method": True,
            "method_id": METHOD_VERSION, "control_id": CONTROL_ID,
            "separate_from_ten_cores": True, "core_weight": "0.10",
            "abstain_rules": "unchanged; this formula is not a core vote",
            "statistics": stats, "hits_by_field": descriptive,
            "method_hit_sum": method_sum, "control_hit_sum": control_sum,
            "difference_method_minus_control": None if method_sum is None else method_sum - control_sum,
            "expected_outcome": expectation(), "exclusion_reasons": exclusions}
