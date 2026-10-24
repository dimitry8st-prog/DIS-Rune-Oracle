"""Two-field research importer and exact finite-population null model.

Confirmation/evidence references are imported declarations, not verified TSA
signatures. Reports deliberately retain every registered event and both slots.
"""

from collections import Counter
from datetime import datetime, timezone
from fractions import Fraction
from math import comb, isfinite, log, sqrt
import json
import random


def load_json(raw):
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError(f"non-finite JSON constant: {value}")

    return json.loads(raw, object_pairs_hook=unique_keys, parse_constant=invalid_constant)


def shape(value, required, optional=()):
    if not isinstance(value, dict) or set(required) - value.keys() or value.keys() - set(required) - set(optional):
        raise ValueError(f"invalid object; required={required}, optional={optional}")


def text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("nonempty identifier/reference required")
    return value


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("timestamp must be an ISO string")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamp timezone required")
    return result.astimezone(timezone.utc)


def optional_timestamp(value):
    """None is an unknown time. It is stored unknown and is not invented."""
    if value is None:
        return None
    return timestamp(value)


def fields(value):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("two ordered fields required")
    for field in value:
        if (not isinstance(field, list) or len(field) != 4
                or any(type(n) is not int or not 1 <= n <= 20 for n in field)
                or len(set(field)) != 4):
            raise ValueError("each field needs four distinct integers in 1..20")
    return value


def hits(picks, outcome):
    fields(picks)
    fields(outcome)
    return [len(set(pick) & set(result)) for pick, result in zip(picks, outcome)]


def field_distribution():
    """P(K=k)=C(4,k)C(16,4-k)/C(20,4), k=0..4, exactly."""
    return [Fraction(comb(4, k) * comb(16, 4 - k), comb(20, 4)) for k in range(5)]


def joint_distribution():
    """Product law REQUIRES independent uniform fields in the null model."""
    p = field_distribution()
    return [[a * b for b in p] for a in p]


def total_distribution():
    joint = joint_distribution()
    return [sum((joint[i][j] for i in range(5) for j in range(5) if i + j == s), Fraction(0))
            for s in range(9)]


def exact_sign(differences):
    """Two-sided exact binomial sign test, ties reported and excluded.

    Null: independent nonzero signs with P(positive | nonzero)=1/2.
    This is a win-probability test, not a test of equal means.
    """
    wins = sum(d > 0 for d in differences)
    losses = sum(d < 0 for d in differences)
    n = wins + losses
    p = min(Fraction(1), Fraction(2 * sum(comb(n, k) for k in range(min(wins, losses) + 1)), 2**n))
    return {"wins": wins, "losses": losses, "ties": len(differences) - n,
            "non_ties": n, "p_two_sided": float(p) if n else None,
            "p_exact": str(p) if n else None}


def paired_summary(differences, bound, alpha=0.05):
    """Hoeffding CI for mean of independent differences in [-bound,bound]."""
    if not 0 < alpha < 1 or bound <= 0 or any(abs(d) > bound for d in differences):
        raise ValueError("invalid confidence parameters/differences")
    n = len(differences)
    mean = sum(differences) / n if n else None
    half = 2 * bound * sqrt(log(2 / alpha) / (2 * n)) if n else None
    return {"n": n, "mean_method_minus_control": mean,
            "confidence": 1 - alpha, "ci_method": "Hoeffding; independent bounded event pairs",
            "mean_ci": [max(-bound, mean - half), min(bound, mean + half)] if n else None,
            "sign_test": exact_sign(differences)}


def probability(value):
    if type(value) not in (int, float) or not isfinite(value) or not 0 <= value <= 1:
        raise ValueError("probability must be finite, numeric and in [0,1]")
    return value


def binary_brier(p, y):
    probability(p)
    if type(y) is not int or y not in (0, 1):
        raise ValueError("binary observation required")
    return (p - y) ** 2


def report(data):
    shape(data, ("schema_version", "study_id", "provenance", "method_id", "control_id",
                 "registered_at", "analysis_at", "events", "predictions", "outcomes"), ("binary_event",))
    if data["schema_version"] != "dis-statistics-v1" or data["provenance"] not in ("SYNTHETIC", "IMPORTED"):
        raise ValueError("unsupported schema/provenance")
    text(data["study_id"])
    strategies = [text(data["method_id"]), text(data["control_id"])]
    if len(set(strategies)) != 2:
        raise ValueError("method and control IDs must differ")
    registered, analysed = timestamp(data["registered_at"]), timestamp(data["analysis_at"])
    if registered > analysed:
        raise ValueError("study registered after analysis")
    if data.get("binary_event") not in (None, "field_1_contains_1"):
        raise ValueError("unsupported binary target")
    if any(not isinstance(data[key], list) for key in ("events", "predictions", "outcomes")):
        raise ValueError("events/predictions/outcomes must be arrays")
    events = {}
    for event in data["events"]:
        shape(event, ("event_id", "registered_at", "target_at"))
        eid = text(event["event_id"])
        event_registered = timestamp(event["registered_at"])
        optional_timestamp(event["target_at"])
        if eid in events or not registered <= event_registered <= analysed:
            raise ValueError("duplicate event or invalid event registration time")
        events[eid] = event
    predictions = {}
    identifiers = set()
    for pred in data["predictions"]:
        shape(pred, ("prediction_id", "event_id", "strategy_id", "mode", "status", "fixed_at",
                     "confirmation", "evidence_ref", "fields"), ("probability",))
        pid = text(pred["prediction_id"])
        key = (text(pred["event_id"]), text(pred["strategy_id"]))
        if pid in identifiers or key in predictions or key[0] not in events or key[1] not in strategies:
            raise ValueError("duplicate prediction/slot or unregistered event/strategy")
        if pred["mode"] not in ("forecast", "retrospective") or pred["status"] not in ("PICK", "ABSTAIN"):
            raise ValueError("invalid prediction mode/status")
        if pred["confirmation"] not in ("CONFIRMED", "UNCONFIRMED"):
            raise ValueError("invalid confirmation")
        if pred["confirmation"] == "CONFIRMED":
            text(pred["evidence_ref"])
        elif pred["evidence_ref"] is not None:
            text(pred["evidence_ref"])
        if timestamp(pred["fixed_at"]) > analysed:
            raise ValueError("prediction fixed after analysis")
        if pred["status"] == "PICK":
            fields(pred["fields"])
        elif pred["fields"] is not None or pred.get("probability") is not None:
            raise ValueError("ABSTAIN must not contain picks or probabilities")
        if pred.get("probability") is not None:
            probability(pred["probability"])
            if data.get("binary_event") is None:
                raise ValueError("probability requires a registered binary event")
        identifiers.add(pid)
        predictions[key] = pred
    outcomes = {}
    for outcome in data["outcomes"]:
        shape(outcome, ("event_id", "occurred_at", "recorded_at", "confirmation", "source_ref", "fields"))
        eid = text(outcome["event_id"])
        if eid not in events or eid in outcomes:
            raise ValueError("unknown or duplicate outcome event")
        occurred, recorded = optional_timestamp(outcome["occurred_at"]), optional_timestamp(outcome["recorded_at"])
        target = optional_timestamp(events[eid]["target_at"])
        if occurred is not None and recorded is not None and target is not None:
            if not target <= occurred <= recorded <= analysed:
                raise ValueError("outcome time must follow target and precede recording/analysis")
        else:
            if target is not None and occurred is not None and occurred < target:
                raise ValueError("outcome time must follow target and precede recording/analysis")
            if occurred is not None and recorded is not None and occurred > recorded:
                raise ValueError("outcome time must follow target and precede recording/analysis")
            if recorded is not None and recorded > analysed:
                raise ValueError("outcome time must follow target and precede recording/analysis")
            if occurred is not None and recorded is None and occurred > analysed:
                raise ValueError("outcome time must follow target and precede recording/analysis")
        if outcome["confirmation"] not in ("CONFIRMED", "UNCONFIRMED"):
            raise ValueError("invalid outcome confirmation")
        text(outcome["source_ref"])
        fields(outcome["fields"])
        outcomes[eid] = outcome

    rows, paired, brier_pairs = [], [], []
    for eid, event in events.items():
        scores, briers = {}, {}
        outcome = outcomes.get(eid)
        target = optional_timestamp(event["target_at"])
        for strategy in strategies:
            pred = predictions.get((eid, strategy))
            reasons = []
            classification = "MISSING"
            if pred:
                fixed = timestamp(pred["fixed_at"])
                if pred["mode"] == "retrospective":
                    classification = "RETROSPECTIVE"
                elif target is None:
                    classification = "UNKNOWN_TIME"
                elif fixed >= target:
                    classification = "LATE"
                elif not registered <= timestamp(event["registered_at"]) <= fixed < target:
                    classification = "REGISTRATION_VIOLATION"
                elif pred["confirmation"] == "UNCONFIRMED":
                    classification = "UNCONFIRMED"
                else:
                    classification = "PROSPECTIVE"
                if classification != "PROSPECTIVE":
                    reasons.append(classification)
                if (outcome is not None and (outcome["occurred_at"] is None or outcome["recorded_at"] is None)
                        and "UNKNOWN_TIME" not in reasons):
                    reasons.append("UNKNOWN_TIME")
                if pred["status"] == "ABSTAIN":
                    reasons.append("ABSTAIN")
            else:
                reasons.append("MISSING_PREDICTION")
            if outcome is None:
                reasons.append("MISSING_OUTCOME")
            elif outcome["confirmation"] != "CONFIRMED":
                reasons.append("UNCONFIRMED_OUTCOME")
            descriptive = hits(pred["fields"], outcome["fields"]) if pred and pred["status"] == "PICK" and outcome else None
            score = descriptive if not reasons else None
            p = pred.get("probability") if pred else None
            brier = binary_brier(p, int(1 in outcome["fields"][0])) if score is not None and p is not None else None
            rows.append({"event_id": eid, "strategy_id": strategy,
                         "event_registered_at": event["registered_at"], "target_at": event["target_at"],
                         "fixed_at": pred["fixed_at"] if pred else None,
                         "evidence_ref": pred["evidence_ref"] if pred else None,
                         "outcome_at": outcome["occurred_at"] if outcome else None,
                         "outcome_source": outcome["source_ref"] if outcome else None,
                         "prediction_id": pred["prediction_id"] if pred else None,
                         "classification": classification,
                         "confirmation": pred["confirmation"] if pred else None,
                         "prediction_status": pred["status"] if pred else "MISSING",
                         "exclusion_reasons": reasons, "hits_by_field": score,
                         "descriptive_hits_not_prospective": descriptive if score is None else None,
                         "brier": brier})
            scores[strategy], briers[strategy] = score, brier
        a, b = (scores[s] for s in strategies)
        if a is not None and b is not None:
            paired.append({"event_id": eid, "method": a, "control": b,
                           "differences": [x - y for x, y in zip(a, b)]})
        if all(briers[s] is not None for s in strategies):
            brier_pairs.append({"event_id": eid, "method": briers[strategies[0]], "control": briers[strategies[1]]})
    totals = [sum(pair["differences"]) for pair in paired]
    inventories = {}
    for strategy in strategies:
        subset = [row for row in rows if row["strategy_id"] == strategy]
        scored = [row["hits_by_field"] for row in subset if row["hits_by_field"] is not None]
        inventories[strategy] = {
            "registered_slots": len(subset), "scored": len(scored),
            "classification_counts": dict(Counter(row["classification"] for row in subset)),
            "confirmation_counts": dict(Counter(row["confirmation"] or "MISSING" for row in subset)),
            "status_counts": dict(Counter(row["prediction_status"] for row in subset)),
            "exclusion_reason_counts": dict(Counter(reason for row in subset for reason in row["exclusion_reasons"])),
            "hit_histograms": [[sum(score[f] == k for score in scored) for k in range(5)] for f in (0, 1)]}
    return {"study_id": data["study_id"], "provenance": data["provenance"],
            "registered_events": len(events), "inventory": inventories, "trials": rows,
            "matched_pairs": paired,
            "matched_mean_hits_by_field": {
                role: [sum(p[role][f] for p in paired) / len(paired) for f in (0, 1)] if paired else None
                for role in ("method", "control")},
            "paired_total": paired_summary(totals, 8),
            "paired_by_field_exploratory": [paired_summary([p["differences"][f] for p in paired], 4) for f in (0, 1)],
            "matched_brier_pairs": brier_pairs,
            "brier_mean_method_minus_control": sum(p["method"] - p["control"] for p in brier_pairs) / len(brier_pairs) if brier_pairs else None,
            "limitations": ["Imported confirmation/time references are declarations; signatures and sources are not authenticated.",
                            "Paired tests assume independent event pairs and prespecified sampling/stopping; missingness may select the sample.",
                            "Sign test concerns non-tie win probability; Hoeffding interval concerns the bounded mean difference.",
                            "Field tests are exploratory; no multiplicity-adjusted efficacy claim.",
                            "Technical validation is not predictive efficacy or evidence for retrocausality."]}


def simulate(n, seed):
    """Uniform independent two-field mathematical simulation, not real draws."""
    if type(n) is not int or n < 1 or type(seed) is not int:
        raise ValueError("positive integer n and integer seed required")
    rng = random.Random(seed)
    histogram = [[0] * 5 for _ in range(2)]
    fixed = [[1, 2, 3, 4], [1, 2, 3, 4]]
    for _ in range(n):
        observed = [rng.sample(range(1, 21), 4) for _ in range(2)]
        for f, count in enumerate(hits(fixed, observed)):
            histogram[f][count] += 1
    return {"provenance": "SYNTHETIC", "model": "independent uniform 4-of-20 fields",
            "n": n, "seed": seed, "hit_histograms": histogram,
            "note": "Pseudorandom educational model; no physical time loop or actual lottery data."}
