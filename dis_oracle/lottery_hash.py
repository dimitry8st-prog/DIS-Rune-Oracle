"""Exact lottery-rune-hash-v2 formula, shared for research without rewriting archives.

This is an author mapping, not a tenth-core vote and not a learned model.
SHA-256 ranks numbers; it does not discover dependence by itself.
"""
import hashlib

from .contracts import ContractError


METHOD_VERSION = "lottery-rune-hash-v2"
CONTROL_ID = "lottery-rune-hash-v2-uniform-control"


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
        rid = position.get("rune_id")
        if not isinstance(rid, str) or not rid:
            raise ContractError("rune_id required")
        parts.append(f"{rid}:{orientation_token(position.get('final_orientation'))}")
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
