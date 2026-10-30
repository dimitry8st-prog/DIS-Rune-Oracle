"""Finite decision matrices and two-player pure-strategy games, local advice only.

Cultural notes remain attributed context and cannot adjust utilities, facts or
probabilities. No LLM, network, payments or external actions are invoked.
"""
from copy import deepcopy
from fractions import Fraction
import math

from .contracts import ContractError, digest, now_iso, shape, text, timestamp
from .journal import JournalError

VERSION = "oracle-strategy-v1"
NOTE_SOURCES = ("rune", "yijing", "mo", "qiuqian", "daliuren", "slavic",
                "calendar:japanese_rokuyo", "calendar:egyptian_cairo")


def _number(value):
    if type(value) not in (int, float) or abs(value) > 10**9 or not math.isfinite(value):
        raise ContractError("utilities/probabilities must be finite JSON numbers, absolute value <= 1e9")
    return Fraction(str(value))


def _ids(values, name):
    if not isinstance(values, list) or not 2 <= len(values) <= 50:
        raise ContractError(f"{name} needs 2..50 identifiers")
    for value in values:
        text(value, name)
        if len(value) > 128:
            raise ContractError("identifier too long")
    if len(set(values)) != len(values):
        raise ContractError(f"duplicate {name}")
    return values


def _matrix(values, rows, columns, convert):
    if not isinstance(values, list) or len(values) != rows:
        raise ContractError("payoff row count differs from registered actions")
    result = []
    for row in values:
        if not isinstance(row, list) or len(row) != columns:
            raise ContractError("every payoff row needs every state/opponent action")
        result.append([convert(value) for value in row])
    return result


def _decision(model):
    shape(model, ("kind", "actions", "states", "payoffs", "probabilities"))
    actions, states = _ids(model["actions"], "actions"), _ids(model["states"], "states")
    matrix = _matrix(model["payoffs"], len(actions), len(states), _number)
    worst = [min(row) for row in matrix]
    best_by_state = [max(row[j] for row in matrix) for j in range(len(states))]
    regret = [[best_by_state[j] - value for j, value in enumerate(row)] for row in matrix]
    worst_regret = [max(row) for row in regret]
    dominated = [actions[i] for i, row in enumerate(matrix)
                 if any(all(x > y for x, y in zip(other, row)) for other in matrix)]
    result = {
        "kind": "DECISION_UNDER_UNCERTAINTY", "actions": actions, "states": states,
        "maximin": {"actions": [a for a, v in zip(actions, worst) if v == max(worst)],
                    "worst_payoffs": dict(zip(actions, map(float, worst)))},
        "minimax_regret": {"actions": [a for a, v in zip(actions, worst_regret) if v == min(worst_regret)],
                           "maximum_regrets": dict(zip(actions, map(float, worst_regret))),
                           "regret_matrix": [[float(v) for v in row] for row in regret]},
        "strictly_dominated_actions": dominated,
        "expected_utility": None,
        "recommendation": None,
        "notice": "Choose a decision criterion explicitly; ties and different criteria remain visible.",
    }
    probabilities = model["probabilities"]
    if probabilities is not None:
        if not isinstance(probabilities, list) or len(probabilities) != len(states):
            raise ContractError("one declared probability per state is required")
        probabilities = [_number(v) for v in probabilities]
        if any(v < 0 or v > 1 for v in probabilities) or sum(probabilities) != 1:
            raise ContractError("declared state probabilities must be in [0,1] and sum exactly to 1")
        expected = [sum(v * p for v, p in zip(row, probabilities)) for row in matrix]
        result["expected_utility"] = {"actions": [a for a, v in zip(actions, expected) if v == max(expected)],
                                      "values": dict(zip(actions, map(float, expected))),
                                      "probability_status": "USER_DECLARED_NOT_INFERRED_FROM_SYMBOLS"}
    return result


def _game(model):
    shape(model, ("kind", "players", "payoffs"))
    players = model["players"]
    if not isinstance(players, list) or len(players) != 2:
        raise ContractError("exactly two players required")
    for player in players:
        shape(player, ("id", "actions")); text(player["id"], "player.id")
        _ids(player["actions"], "player actions")
    if players[0]["id"] == players[1]["id"]:
        raise ContractError("players must be distinct")
    def payoff(value):
        if not isinstance(value, list) or len(value) != 2:
            raise ContractError("each game cell needs utilities for both players")
        return [_number(x) for x in value]
    matrix = _matrix(model["payoffs"], len(players[0]["actions"]), len(players[1]["actions"]), payoff)
    equilibria = []
    for i, row in enumerate(matrix):
        for j, cell in enumerate(row):
            if cell[0] == max(r[j][0] for r in matrix) and cell[1] == max(v[1] for v in row):
                equilibria.append({"actions": {players[0]["id"]: players[0]["actions"][i],
                                                players[1]["id"]: players[1]["actions"][j]},
                                   "utilities": [float(v) for v in cell]})
    return {"kind": "TWO_PLAYER_GAME", "players": deepcopy(players), "pure_nash_equilibria": equilibria,
            "status": "PURE_EQUILIBRIA_FOUND" if equilibria else "NO_PURE_EQUILIBRIUM",
            "mixed_equilibrium": "NOT_COMPUTED", "recommendation": None,
            "notice": "Only pure best-response equilibria; utilities do not predict actual partner behavior."}


def analyze(request):
    shape(request, ("schema_version", "decision_id", "provenance", "cutoff_at", "model", "payoff_basis", "cultural_notes"))
    if request["schema_version"] != VERSION or request["provenance"] not in ("SYNTHETIC", "IMPORTED"):
        raise ContractError("unsupported strategy schema/provenance")
    text(request["decision_id"], "decision_id")
    at = now_iso()
    cutoff = timestamp(request["cutoff_at"])
    if cutoff > timestamp(at):
        raise ContractError("cutoff cannot be in the future")
    basis = request["payoff_basis"]
    shape(basis, ("kind", "explanation", "source", "available_at"))
    if basis["kind"] not in ("ASSUMPTION", "OBSERVATION"):
        raise ContractError("payoff basis must identify assumption or observation")
    text(basis["explanation"], "payoff explanation"); text(basis["source"], "payoff source")
    if timestamp(basis["available_at"]) > cutoff:
        raise ContractError("payoff information after cutoff")
    notes = request["cultural_notes"]
    if not isinstance(notes, list) or len(notes) > 20:
        raise ContractError("at most 20 attributed cultural notes")
    for note in notes:
        shape(note, ("core_id", "status", "text", "source_ref", "available_at"))
        if note["core_id"] not in NOTE_SOURCES or note["status"] not in ("OK", "ABSTAIN", "UNAVAILABLE"):
            raise ContractError("invalid cultural note origin/status")
        text(note["text"], "note.text"); text(note["source_ref"], "note.source_ref")
        if len(note["text"]) > 10000 or timestamp(note["available_at"]) > cutoff:
            raise ContractError("cultural note too large or after cutoff")
    model = request["model"]
    if not isinstance(model, dict) or model.get("kind") not in ("decision", "game"):
        raise ContractError("model kind must be decision or game")
    calculation = _decision(model) if model["kind"] == "decision" else _game(model)
    return {"state": "STRATEGY_ANALYZED", "version": VERSION, "decision_id": request["decision_id"],
            "provenance": request["provenance"], "analyzed_at": at, "input_hash": digest(request),
            "calculation": calculation, "payoff_basis": deepcopy(basis), "cultural_notes": deepcopy(notes),
            "cultural_numeric_contribution": False, "execution": "ADVICE_ONLY",
            "limitations": ["Sources, utility assessments and probabilities are user declarations.",
                            "No medical/financial decisions or external actions are executed.",
                            "Cultural agreement is not an event probability."]}


def freeze(journal, request):
    journal.verify()
    text(request.get("decision_id"), "decision_id")
    key = "strategy:" + digest(request["decision_id"])
    old = journal.get(key)
    if old:
        if old["input_hash"] != digest(request):
            raise JournalError("strategy record immutable; use a new decision_id for revised assumptions")
        return old
    report = analyze(request)
    report["state"] = "STRATEGY_FROZEN"
    report["input_snapshot"] = deepcopy(request)
    journal.append(key, report)
    return report
