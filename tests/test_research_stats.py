from copy import deepcopy
from fractions import Fraction
from itertools import combinations
from math import comb
import json
from pathlib import Path
import subprocess
import sys
import unittest

from research_stats.core import (binary_brier, exact_sign, field_distribution, fields,
                                 hits, joint_distribution, paired_summary, report,
                                 simulate, total_distribution)
from research_stats.core import load_json
from research_stats.design import binary_plan

EXAMPLES = Path(__file__).resolve().parents[1] / "research/science/examples"


class ResearchStatisticsTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((EXAMPLES / "synthetic_study.json").read_text())

    def test_exact_distribution_against_complete_enumeration(self):
        counts = [0] * 5
        selected = {1, 2, 3, 4}
        for draw in combinations(range(1, 21), 4):
            counts[len(selected.intersection(draw))] += 1
        self.assertEqual(counts, [1820, 2240, 720, 64, 1])
        self.assertEqual(field_distribution(), [Fraction(n, 4845) for n in counts])
        self.assertEqual(sum(field_distribution()), 1)

    def test_joint_and_total_normalize_and_have_correct_moments(self):
        joint = joint_distribution()
        self.assertEqual(sum(map(sum, joint)), 1)
        self.assertEqual(joint[4][4], Fraction(1, 23474025))
        self.assertEqual(sum(total_distribution()), 1)
        self.assertEqual(sum(i * p for i, p in enumerate(field_distribution())), Fraction(4, 5))
        self.assertEqual(sum(i * p for i, p in enumerate(total_distribution())), Fraction(8, 5))

    def test_fields_are_scored_separately_and_order_matters(self):
        picks = [[1, 2, 3, 4], [5, 6, 7, 8]]
        draw = [[1, 2, 9, 10], [5, 11, 12, 13]]
        self.assertEqual(hits(picks, draw), [2, 1])
        self.assertEqual(hits(picks[::-1], draw), [0, 0])
        self.assertEqual(hits(picks, picks), [4, 4])

    def test_invalid_numbers_duplicates_and_shapes_are_rejected(self):
        for field in ([0, 1, 2, 3], [1, 2, 3, 21], [1, 1, 2, 3], [1, 2, 3],
                      [True, 2, 3, 4], [1.0, 2, 3, 4], ["1", 2, 3, 4]):
            with self.subTest(field=field), self.assertRaises(ValueError):
                fields([field, [1, 2, 3, 4]])
        with self.assertRaises(ValueError):
            fields([[1, 2, 3, 4]])

    def test_all_registry_slots_and_zero_hits_are_retained(self):
        result = report(self.data)
        self.assertEqual(len(result["trials"]), 16)
        self.assertEqual(result["registered_events"], 8)
        self.assertEqual(result["inventory"]["method-v1"]["scored"], 2)
        self.assertEqual(result["inventory"]["control-v1"]["scored"], 7)
        self.assertEqual(result["inventory"]["method-v1"]["hit_histograms"][0][0], 1)
        self.assertEqual(result["paired_total"]["n"], 2)
        self.assertEqual([p["event_id"] for p in result["matched_pairs"]], ["synthetic-01", "synthetic-02"])

    def test_late_retrospective_and_unconfirmed_are_separate(self):
        rows = [r for r in report(self.data)["trials"] if r["strategy_id"] == "method-v1"]
        self.assertEqual(rows[2]["classification"], "RETROSPECTIVE")
        self.assertEqual(rows[3]["classification"], "UNCONFIRMED")
        self.assertEqual(rows[7]["classification"], "LATE")
        for row in (rows[2], rows[3], rows[7]):
            self.assertIsNone(row["hits_by_field"])
            self.assertIsNotNone(row["descriptive_hits_not_prospective"])
        late = next(p for p in self.data["predictions"] if p["prediction_id"] == "synthetic-08-method-v1")
        late.update(confirmation="UNCONFIRMED", evidence_ref=None)
        result = report(self.data)
        self.assertEqual(result["inventory"]["method-v1"]["confirmation_counts"]["UNCONFIRMED"], 2)
        self.assertEqual(result["inventory"]["method-v1"]["classification_counts"]["LATE"], 1)

    def test_missing_predictions_outcomes_and_abstentions_are_not_zero(self):
        rows = [r for r in report(self.data)["trials"] if r["strategy_id"] == "method-v1"]
        self.assertIn("MISSING_PREDICTION", rows[4]["exclusion_reasons"])
        self.assertIn("ABSTAIN", rows[5]["exclusion_reasons"])
        self.assertIn("MISSING_OUTCOME", rows[6]["exclusion_reasons"])
        for row in rows[4:7]:
            self.assertIsNone(row["hits_by_field"])

    def test_event_and_strategy_identity_mismatches_are_rejected(self):
        for key in ("event_id", "strategy_id"):
            bad = deepcopy(self.data)
            bad["predictions"][0][key] = "unregistered"
            with self.assertRaises(ValueError):
                report(bad)
        self.data["outcomes"][0]["event_id"] = "unknown"
        with self.assertRaises(ValueError):
            report(self.data)

    def test_duplicate_slots_prevent_cherry_picking(self):
        duplicate = deepcopy(self.data["predictions"][0])
        duplicate["prediction_id"] = "different-id-same-event-and-strategy"
        self.data["predictions"].append(duplicate)
        with self.assertRaises(ValueError):
            report(self.data)

    def test_json_duplicate_keys_and_nonfinite_literals_are_rejected(self):
        for raw in ('{"event_id":"first","event_id":"second"}', '{"p":NaN}', '{"p":Infinity}'):
            with self.assertRaises(ValueError):
                load_json(raw)

    def test_duplicate_events_and_outcomes_are_rejected(self):
        for key in ("events", "outcomes"):
            bad = deepcopy(self.data)
            bad[key].append(deepcopy(bad[key][0]))
            with self.assertRaises(ValueError):
                report(bad)

    def test_invalid_outcome_times_and_naive_forecast_time_are_rejected(self):
        for key, value in (("occurred_at", "2025-01-01T00:00:00Z"),
                           ("recorded_at", "2027-01-01T00:00:00Z")):
            bad = deepcopy(self.data)
            bad["outcomes"][0][key] = value
            with self.assertRaises(ValueError):
                report(bad)
        self.data["predictions"][0]["fixed_at"] = "2026-01-03T00:00:00"
        with self.assertRaises(ValueError):
            report(self.data)

    def test_registration_violation_is_retained_but_not_scored(self):
        self.data["events"][0]["registered_at"] = "2026-01-05T00:00:00Z"
        row = report(self.data)["trials"][0]
        self.assertEqual(row["classification"], "REGISTRATION_VIOLATION")
        self.assertIsNone(row["hits_by_field"])

    def test_unconfirmed_outcomes_do_not_enter_matched_analysis(self):
        self.data["outcomes"][0]["confirmation"] = "UNCONFIRMED"
        result = report(self.data)
        self.assertEqual(result["paired_total"]["n"], 1)
        self.assertIn("UNCONFIRMED_OUTCOME", result["trials"][0]["exclusion_reasons"])

    def test_exact_paired_sign_test_ties_and_empty_sample(self):
        self.assertEqual(exact_sign([1] * 6 + [0])["p_exact"], "1/32")
        self.assertEqual(exact_sign([1, -1, 0])["p_two_sided"], 1)
        self.assertEqual(exact_sign([0, 0])["ties"], 2)
        self.assertIsNone(exact_sign([])["p_two_sided"])

    def test_future_target_design_uses_exact_prespecified_threshold(self):
        plan = binary_plan()
        self.assertEqual(plan["critical_successes"], 542)
        self.assertLessEqual(plan["actual_null_tail"], .005)
        self.assertGreater(float(Fraction(sum(comb(1000, k) for k in range(541, 1001)), 2**1000)), .005)
        self.assertAlmostEqual(plan["power"], .8806228420448081)
        self.assertIsNone(binary_plan(1)["critical_successes"])

    def test_uncertainty_interval_is_bounded_and_nonzero_at_perfect_scores(self):
        result = paired_summary([8] * 100, 8)
        self.assertLess(result["mean_ci"][0], 8)
        self.assertEqual(result["mean_ci"][1], 8)
        self.assertIsNone(paired_summary([], 8)["mean_ci"])
        with self.assertRaises(ValueError):
            paired_summary([9], 8)

    def test_brier_requires_frozen_probability_for_same_binary_target(self):
        self.assertAlmostEqual(binary_brier(0.2, 1), 0.64)
        result = report(self.data)
        self.assertEqual(len(result["matched_brier_pairs"]), 2)
        self.assertEqual(result["brier_mean_method_minus_control"], 0)
        self.data["predictions"][0].pop("probability")
        self.assertEqual(len(report(self.data)["matched_brier_pairs"]), 1)
        self.data.pop("binary_event")
        with self.assertRaises(ValueError):
            report(self.data)

    def test_support_weights_and_invalid_probabilities_are_rejected(self):
        for value in (True, -0.1, 1.1, float("nan"), float("inf"), "0.5"):
            with self.assertRaises(ValueError):
                binary_brier(value, 1)
        self.data["predictions"][0]["support_percent"] = 50
        with self.assertRaises(ValueError):
            report(self.data)

    def test_seeded_simulation_is_reproducible_and_marked_synthetic(self):
        first = simulate(1000, 20261016)
        self.assertEqual(first, simulate(1000, 20261016))
        self.assertNotEqual(first["hit_histograms"], simulate(1000, 7)["hit_histograms"])
        self.assertEqual(first["provenance"], "SYNTHETIC")
        self.assertEqual([sum(h) for h in first["hit_histograms"]], [1000, 1000])

    def test_reports_do_not_mutate_inputs_and_empty_sample_has_no_inference(self):
        original = deepcopy(self.data)
        report(self.data)
        self.assertEqual(self.data, original)
        self.data.update(events=[], predictions=[], outcomes=[])
        result = report(self.data)
        self.assertEqual(result["trials"], [])
        self.assertIsNone(result["paired_total"]["mean_ci"])

    def test_cli_saved_artifacts_are_reproducible_and_failure_is_nonzero(self):
        result = subprocess.run([sys.executable, "-m", "research_stats", "report", str(EXAMPLES / "synthetic_study.json")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), json.loads((EXAMPLES / "synthetic_report.json").read_text()))
        bad = subprocess.run([sys.executable, "-m", "research_stats", "simulate", "--n", "0", "--seed", "7"],
                             capture_output=True, text=True)
        self.assertEqual(bad.returncode, 2)
        self.assertEqual(bad.stdout, "")


if __name__ == "__main__":
    unittest.main()
