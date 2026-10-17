"""Exact fixed-weight aggregation over manually reviewed imported claims."""

from .contracts import CORES, ContractError, validate_event, validate_cards


def compare(event, cards):
    axes = validate_event(event)
    validate_cards(cards, axes)
    for card in cards:
        inputs = card["inputs"]
        if isinstance(inputs, dict) and "event_id" in inputs and inputs["event_id"] != event["event_id"]:
            raise ContractError("adapter card is bound to another event")
    present = {c["core_id"]: c for c in cards}
    results = {}
    for axis_id, axis in axes.items():
        support = {s["scenario_id"]: [] for s in axis["scenarios"]}
        oppose = {s: [] for s in support}
        pending, internal, counted = [], [], set()
        for card in cards:
            if card["status"] != "OK":
                continue
            claims = [c for c in card["claims"] if c["axis_id"] == axis_id
                      and c["type"] == "FORECAST"]
            pending.extend(c["claim_id"] for c in claims if c["review_status"] == "PENDING")
            accepted = [c for c in claims if c["review_status"] == "ACCEPTED"]
            supports = {c["scenario_id"] for c in accepted if c["polarity"] == "SUPPORT"}
            opposes = {c["scenario_id"] for c in accepted if c["polarity"] == "OPPOSE"}
            # Multiple claims never multiply a core's weight. Oppositions are not
            # converted into a vote for some third alternative.
            if len(supports) > 1 or supports & opposes:
                internal.append(card["core_id"])
                continue
            if supports or opposes:
                counted.add(card["core_id"])
            for s in supports:
                support[s].append(card["core_id"])
            for s in opposes:
                oppose[s].append(card["core_id"])
        active = [s for s, voters in support.items() if voters]
        conflict = bool(internal or len(active) > 1 or any(support[s] and oppose[s] for s in support))
        highest = max((len(v) for v in support.values()), default=0)
        leaders = [s for s, v in support.items() if highest and len(v) == highest]
        tie = len(leaders) > 1
        if not counted:
            state = "NO_COMPARABLE_DATA"
        elif pending:
            state = "UNRESOLVED"
        elif conflict:
            state = "MIXED"
        elif tie:
            state = "TIE"
        elif active:
            state = "ALIGNED"
        else:
            state = "NO_COMPARABLE_DATA"  # opposition alone is not a positive forecast
        results[axis_id] = {
            "status": state, "tie": tie, "internal_conflicts": internal,
            "pending_claims": pending, "comparison_coverage_percent": len(counted) * 10,
            "unfilled_percent": 100 - len(counted) * 10,
            "support_percent": {s: len(v) * 10 for s, v in support.items()},
            "oppose_percent": {s: len(v) * 10 for s, v in oppose.items()},
            "support_cores": support, "oppose_cores": oppose,
            "leaders": [] if pending else leaders,
            "prediction": leaders[0] if state == "ALIGNED" and len(leaders) == 1 else None,
        }
    return {
        "core_weight": "0.10", "procedural_coverage_percent": sum(c["status"] == "OK" for c in cards) * 10,
        "cores": {core: {"status": present[core]["status"], "reason": present[core]["reason"]}
                  if core in present else {"status": "UNAVAILABLE", "reason": "NOT_SUPPLIED"}
                  for core in CORES},
        "axes": results,
        "notice": "Support and coverage are not event probabilities or proof of predictive accuracy.",
    }
