"""Freeze imported cards and evaluate outcomes under a registered criterion."""

from .contracts import ContractError, digest, now_iso, shape, text, timestamp, validate_event
from .journal import JournalError
from .router import compare


def freeze(journal, run_id, event, cards, *, frozen_at=None):
    text(run_id, "run_id")
    frozen_at = frozen_at or now_iso()
    axes = validate_event(event)
    comparison = compare(event, cards)
    fixed_input = {"event": event, "cards": cards, "engine_version": "0.1.0"}
    key = f"run:{run_id}:frozen"
    journal.verify()
    existing = journal.get(key)
    if existing:
        if existing["input_hash"] != digest(fixed_input):
            raise JournalError("run_id already frozen with different inputs")
        return existing
    at = timestamp(frozen_at)
    if timestamp(event["cutoff_at"]) > at:
        raise ContractError("cutoff cannot be in the future at freeze")
    if event["mode"] == "forecast" and any(timestamp(a["deadline"]) <= at for a in axes.values()):
        raise ContractError("forecast cannot be frozen after its deadline")
    for card in cards:
        for claim in card["claims"]:
            if claim.get("reviewed_at") and timestamp(claim["reviewed_at"]) > at:
                raise ContractError("review timestamp is after freeze")
    result = {
        "run_id": run_id, "state": "FROZEN", "engine_version": "0.1.0",
        "state_trace": ["RECEIVED", "VALIDATED", "COLLECTED", "COMPARED", "CHECKED", "FROZEN"],
        "frozen_at": frozen_at, "input_hash": digest(fixed_input),
        "event": event, "raw_cards": cards, "comparison": comparison,
        "checks": {
            "schema": "VERIFIED", "input_hashes": "VERIFIED", "temporal_metadata": "VERIFIED",
            "source_factuality": "NOT_CHECKABLE", "historical_protocol_authenticity": "NOT_CHECKABLE",
            "predictive_accuracy": "NOT_CHECKABLE",
        },
        "original_synthesis": None, "checked_synthesis": None,
        "limitations": ["Imported cards only; no automatic traditional procedures or LLM calls.",
                        "Human review metadata is a declaration, not authenticated identity.",
                        "Timestamps are declarations; no independent timestamp service is connected."],
    }
    journal.append(key, result)
    return result


def evaluate(journal, run_id, outcome, *, evaluated_at=None):
    journal.verify()
    frozen = journal.get(f"run:{run_id}:frozen")
    if frozen is None:
        raise ContractError("unknown frozen run")
    shape(outcome, ("event_id", "axis_id", "scenario_id", "source", "observed_at"))
    text(outcome["source"], "outcome.source")
    event = frozen["event"]
    if outcome["event_id"] != event["event_id"]:
        raise ContractError("outcome event_id mismatch")
    axes = {a["axis_id"]: a for a in event["axes"]}
    axis = axes.get(outcome["axis_id"])
    if axis is None or outcome["scenario_id"] not in {s["scenario_id"] for s in axis["scenarios"]}:
        raise ContractError("unregistered outcome")
    evaluated_at = evaluated_at or now_iso()
    if timestamp(outcome["observed_at"]) > timestamp(evaluated_at):
        raise ContractError("outcome is dated in the future")
    if timestamp(outcome["observed_at"]) < timestamp(axis["deadline"]):
        raise ContractError("resolve the registered deadline before evaluating the outcome")
    key = f"run:{run_id}:outcome:{outcome['axis_id']}"
    existing = journal.get(key)
    if existing:
        if existing["outcome"] != outcome:
            raise JournalError("outcome exists; corrections require a separate audit process")
        return existing
    result = frozen["comparison"]["axes"][outcome["axis_id"]]
    eligible = event["mode"] == "forecast"
    prediction = result["prediction"]
    evaluation = {
        "run_id": run_id, "state": "EVALUATED", "evaluated_at": evaluated_at,
        "outcome": outcome, "eligible_prospective": eligible,
        "metric": "categorical_0_1_error", "prediction": prediction,
        "abstained": prediction is None,
        "error": int(prediction != outcome["scenario_id"]) if eligible and prediction is not None else None,
        "baseline": axis["baseline"],
        "baseline_error": int(axis["baseline"] != outcome["scenario_id"]) if eligible else None,
        "source_verified": False,
        "notice": "Outcome source and criterion satisfaction require owner verification; no efficacy claim.",
    }
    journal.append(key, evaluation)
    return evaluation


def markdown_report(result):
    lines = [f"# Run {result['run_id']}", "", f"State: {result['state']}"]
    if result["state"] == "FROZEN":
        lines += [f"Frozen: {result['frozen_at']}", "", "| Core | Status | Reason |", "| --- | --- | --- |"]
        for core, value in result["comparison"]["cores"].items():
            lines.append(f"| {core} | {value['status']} | {value['reason']} |")
        for axis, value in result["comparison"]["axes"].items():
            lines += ["", f"## Axis {axis}", f"Status: {value['status']}; tie: {value['tie']}",
                      f"Coverage: {value['comparison_coverage_percent']}%",
                      f"Support: {value['support_percent']}", f"Oppose: {value['oppose_percent']}",
                      f"Prediction: {value['prediction'] or 'ABSTAIN'}"]
        lines += ["", result["comparison"]["notice"], "", "No LLM synthesis or scientific source verification has been performed."]
    else:
        lines += [f"Metric: {result['metric']}", f"Error: {result['error']}",
                  f"Baseline error: {result['baseline_error']}", result["notice"]]
    return "\n".join(lines) + "\n"


def summary(journal):
    records = journal.export()
    frozen = [r["payload"] for r in records if r["payload"].get("state") == "FROZEN"]
    resolved = [r["payload"] for r in records if r["payload"].get("state") == "EVALUATED"
                and r["payload"]["eligible_prospective"]]
    scored = [r for r in resolved if r["error"] is not None]
    registered = sum(len(r["event"]["axes"]) for r in frozen if r["event"]["mode"] == "forecast")
    return {
        "prospective_axes_registered": registered, "prospective_axes_resolved": len(resolved),
        "awaiting_outcome": registered - len(resolved), "scored": len(scored),
        "abstained_resolved": sum(r["abstained"] for r in resolved),
        "scoring_coverage": len(scored) / len(resolved) if resolved else None,
        "mean_error": sum(r["error"] for r in scored) / len(scored) if scored else None,
        "matched_baseline_mean_error": sum(r["baseline_error"] for r in scored) / len(scored) if scored else None,
        "all_resolved_baseline_mean_error": sum(r["baseline_error"] for r in resolved) / len(resolved) if resolved else None,
        "notice": "Descriptive summary only; source checks, uncertainty and independent replication remain required.",
    }
