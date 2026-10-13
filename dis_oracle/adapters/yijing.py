"""Three-coin mechanics, ordered bottom to top, without invented text mapping."""

import secrets

from ..contracts import ContractError, digest, now_iso, text

SOURCE = "https://www.biroco.com/yijing/basics.htm"


def calculate(throws):
    if not isinstance(throws, list) or len(throws) != 6:
        raise ContractError("need six ordered three-coin throws, bottom to top")
    for throw in throws:
        if not isinstance(throw, list) or len(throw) != 3 or any(type(c) is not int or c not in (2, 3) for c in throw):
            raise ContractError("each throw contains exactly three integer values 2/3")
    lines = [sum(throw) for throw in throws]
    return {"throws_bottom_up": throws, "lines_bottom_up": lines,
            "yin_yang_bottom_up": ["yang" if line in (7, 9) else "yin" for line in lines],
            "moving_lines": [i for i, line in enumerate(lines, 1) if line in (6, 9)],
            "transformed_lines_bottom_up": [7 if line == 6 else 8 if line == 9 else line for line in lines],
            "king_wen_number": None, "text_corpus": None}


def run(journal, run_id, event_id, throws=None):
    text(run_id, "run_id"); text(event_id, "event_id")
    key = f"adapter:yijing:{run_id}"
    journal.verify()
    existing = journal.get(key)
    if existing:
        if existing["inputs"]["event_id"] != event_id:
            raise ContractError("yijing run is bound to another event")
        if throws is not None and existing["raw_result"]["throws_bottom_up"] != throws:
            raise ContractError("repeat must preserve original throws")
        return existing
    physical = throws is not None
    if throws is None:
        rng = secrets.SystemRandom()
        throws = [[rng.choice((2, 3)) for _ in range(3)] for _ in range(6)]
    raw = calculate(throws)
    raw.update(generated_at=now_iso(), method="reported-three-coins" if physical else "digital-three-coins",
               source=SOURCE)
    inputs = {"event_id": event_id, "run_id": run_id, "procedure": "three-coins",
              "coin_values": [2, 3], "order": "bottom-up", "reported_throws": throws if physical else None}
    card = {"core_id": "yijing", "status": "ABSTAIN", "reason": "TEXT_CORPUS_AND_READING_RULES_NOT_FIXED",
            "protocol_version": "yijing-three-coins-v1", "inputs": inputs, "input_hash": digest(inputs),
            "raw_result": raw, "interpretation": "Raw six-line result only; no traditional reading or forecast assigned.",
            "claims": []}
    journal.append(key, card)
    return card
