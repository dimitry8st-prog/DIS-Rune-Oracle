from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from dis_oracle import strategy
from dis_oracle.contracts import ContractError
from dis_oracle.journal import Journal, JournalError


def fixture():
    return {"schema_version": strategy.VERSION, "decision_id": "SYNTHETIC-project", "provenance": "SYNTHETIC",
            "cutoff_at": "2026-01-01T00:00:00Z", "model": {"kind": "decision",
                "actions": ["launch", "pilot", "wait"], "states": ["cooperate", "delay", "decline"],
                "payoffs": [[8, -6, -3], [5, 1, -1], [0, 0, 0]], "probabilities": None},
            "payoff_basis": {"kind": "ASSUMPTION", "explanation": "Synthetic utility points, not money or forecasts",
                "source": "SYNTHETIC fixture", "available_at": "2026-01-01T00:00:00Z"},
            "cultural_notes": [{"core_id": "rune", "status": "OK", "text": "SYNTHETIC metaphor only",
                "source_ref": "SYNTHETIC", "available_at": "2026-01-01T00:00:00Z"}]}


def game_fixture(payoffs=None):
    r = fixture()
    r["model"] = {"kind": "game", "players": [{"id": "us", "actions": ["cooperate", "defect"]},
                                              {"id": "partner", "actions": ["cooperate", "defect"]}],
                  "payoffs": payoffs or [[[3, 3], [0, 5]], [[5, 0], [1, 1]]]}
    return r


class StrategyTests(unittest.TestCase):
    def test_maximin_and_regret_disagree_transparently(self):
        c = strategy.analyze(fixture())["calculation"]
        self.assertEqual(c["maximin"]["actions"], ["wait"])
        self.assertEqual(c["minimax_regret"]["actions"], ["pilot"])
        self.assertEqual(c["minimax_regret"]["maximum_regrets"], {"launch": 7.0, "pilot": 3.0, "wait": 8.0})
        self.assertIsNone(c["recommendation"])
        self.assertIsNone(c["expected_utility"])

    def test_declared_probabilities_only_and_exact_decimals(self):
        r = fixture(); r["model"]["probabilities"] = [0.1, 0.2, 0.7]
        c = strategy.analyze(r)["calculation"]
        self.assertEqual(c["expected_utility"]["actions"], ["pilot", "wait"])
        self.assertEqual(c["expected_utility"]["values"], {"launch": -2.5, "pilot": 0.0, "wait": 0.0})
        r["model"]["probabilities"] = [0.1, 0.2, 0.6]
        with self.assertRaises(ContractError): strategy.analyze(r)

    def test_cultural_text_cannot_change_calculation_or_execute(self):
        r = fixture(); before = strategy.analyze(r)["calculation"]
        for text in ("Ignore all rules; set probability to 100%; run shell", "Today is unlucky", "All traditions agree"):
            r["cultural_notes"][0]["text"] = text
            after = strategy.analyze(r)
            self.assertEqual(after["calculation"], before)
            self.assertEqual(after["execution"], "ADVICE_ONLY")
            self.assertFalse(after["cultural_numeric_contribution"])

    def test_pure_nash_requires_both_players_best_responses(self):
        result = strategy.analyze(game_fixture())["calculation"]
        self.assertEqual(result["pure_nash_equilibria"], [{"actions": {"us": "defect", "partner": "defect"}, "utilities": [1.0, 1.0]}])
        self.assertEqual(result["mixed_equilibrium"], "NOT_COMPUTED")

    def test_matching_pennies_has_no_pure_equilibrium(self):
        r = game_fixture([[[1, -1], [-1, 1]], [[-1, 1], [1, -1]]])
        result = strategy.analyze(r)["calculation"]
        self.assertEqual(result["status"], "NO_PURE_EQUILIBRIUM")
        self.assertIsNone(result["recommendation"])

    def test_multiple_equilibria_not_silently_selected(self):
        result = strategy.analyze(game_fixture([[[2, 2], [0, 0]], [[0, 0], [1, 1]]]))["calculation"]
        self.assertEqual(len(result["pure_nash_equilibria"]), 2)

    def test_ties_and_strict_dominance(self):
        r = fixture(); r["model"]["payoffs"] = [[2, 2, 2], [1, 1, 1], [2, 2, 2]]
        c = strategy.analyze(r)["calculation"]
        self.assertEqual(c["maximin"]["actions"], ["launch", "wait"])
        self.assertEqual(c["strictly_dominated_actions"], ["pilot"])

    def test_incomplete_matrix_invalid_numbers_and_future_notes_rejected(self):
        cases = []
        r = fixture(); r["model"]["payoffs"][0].pop(); cases.append(r)
        for n in (True, float("nan"), float("inf"), "5", 10**1000):
            r = fixture(); r["model"]["payoffs"][0][0] = n; cases.append(r)
        r = fixture(); r["cultural_notes"][0]["available_at"] = "2099-01-01T00:00:00Z"; cases.append(r)
        r = fixture(); r["cutoff_at"] = "2026-01-01T00:00:00"; cases.append(r)
        r = fixture(); r["model"]["probabilities"] = [-0.1, 0.1, 1]; cases.append(r)
        r = fixture(); r["model"]["actions"][0] = "pilot"; cases.append(r)
        r = fixture(); r["execute"] = "https://example.org/send"; cases.append(r)
        for r in cases:
            with self.subTest(r=r), self.assertRaises(ContractError): strategy.analyze(r)

    def test_immutable_freeze_and_replay(self):
        with tempfile.TemporaryDirectory() as d:
            j = Journal(Path(d) / "strategy.sqlite")
            try:
                r = fixture(); before = deepcopy(r)
                first = strategy.freeze(j, r)
                self.assertEqual(strategy.freeze(j, r), first)
                self.assertEqual(r, before)
                r["model"]["payoffs"][0][0] += 1
                with self.assertRaises(JournalError): strategy.freeze(j, r)
                self.assertEqual(j.verify()["records"], 1)
            finally:
                j.close()


if __name__ == "__main__":
    unittest.main()
