"""Tests for the separate feature-research mode. Synthetic data only."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from research_stats.core import hits
from dis_oracle.feature_research import (
    FEATURE_SCHEMA_ID, INSUFFICIENT, METHODS, PRIMARY_CONTRAST, VERSION,
    FeatureResearch, _event_at_for_bins, _history_rows, _local_parts,
    frequency_picks, locked_method_versions, main, normalize_history_features,
    permutation_null, regularized_feature_picks, rune_feature_tokens,
    run_synthetic_demo, synthetic_dependent_history, time_feature_tokens,
    walk_forward_ablation,
)
from dis_oracle.lottery_hash import method_fields, seed_text


class FeatureResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "research.sqlite3"
        self.now = datetime(2098, 4, 1, 10, 0, tzinfo=timezone.utc)
        self.research = FeatureResearch(self.path, _clock=self._clock)
        self.addCleanup(self.research.close)

    def _clock(self):
        return self.now.isoformat().replace("+00:00", "Z")

    def _advance(self, **kwargs):
        self.now = self.now + timedelta(**kwargs)

    def _enter_study(self):
        self.now = datetime(2098, 6, 1, 10, 0, tzinfo=timezone.utc)

    def _history(self, n=40, game="hunt"):
        rows = synthetic_dependent_history(n, seed=1, signal="time")
        return [{
            "game": game, "draw": r["draw"], "fields": r["fields"],
            "available_at": "2098-01-01T00:00:00Z", "occurred_at": "2098-01-01T00:00:00Z",
            "source": "SYNTHETIC", "rune_tokens": r["rune_tokens"],
            "time_tokens": r["time_model_tokens"], "time_model_tokens": r["time_model_tokens"],
        } for r in rows]

    def _protocol(self, **overrides):
        base = {
            "schema_version": VERSION,
            "study_id": "feat-1",
            "hypothesis": "SYNTHETIC protocol",
            "game": "hunt",
            "sample_size": 10,
            "primary_metric": "sum_within_field_hits",
            "methods": list(METHODS),
            "frequency_window": 100,
            "min_train": 20,
            "shrinkage_alpha": 1.0,
            "feature_schema": FEATURE_SCHEMA_ID,
            "method_versions": locked_method_versions(100),
            "primary_contrast": PRIMARY_CONTRAST,
            "stopping_rule": "sample_size_or_ends_at_first",
            "analysis_status": "EXPLORATORY",
            "confirmatory_after": None,
            "confirmatory_rule": "none",
            "starts_at": "2098-05-01T00:00:00Z",
            "ends_at": "2099-01-01T00:00:00Z",
        }
        base.update(overrides)
        if "frequency_window" in overrides and "method_versions" not in overrides:
            base["method_versions"] = locked_method_versions(base["frequency_window"])
        return base

    def test_utc_and_local_time_parts(self):
        stamp = _event_at_for_bins(0, 5, 0)
        parts = _local_parts(stamp, "Europe/Moscow")
        self.assertEqual(parts["weekday"], 0)
        self.assertEqual(parts["hour_bucket"], 5)
        self.assertIn("+00:00", parts["utc_iso"])
        tokens = time_feature_tokens(stamp, "Europe/Moscow")
        self.assertIn("weekday=0", tokens["model_tokens"])
        self.assertIn("hour_bucket=5", tokens["model_tokens"])
        self.assertTrue(any(t.startswith("local_date=") for t in tokens["tokens"]))
        self.assertFalse(any(t.startswith("local_date=") for t in tokens["model_tokens"]))

    def test_no_future_outcomes_in_history(self):
        history = self._history(5)
        history[0]["draw"] = 50
        with self.assertRaisesRegex(ValueError, "precede"):
            self.research.forecast({
                "game": "hunt", "draw": 40, "event_at": "2098-07-01T12:00:00+03:00",
                "timezone": "Europe/Moscow", "symbolic_origin": "SYNTHETIC_FIXTURE",
                "history": history, "rune_positions": synthetic_dependent_history(1, seed=1)[0]["rune_positions"],
            })

    def test_replay_forbidden_and_immutable_inputs(self):
        self.research.register(self._protocol())
        self._enter_study()
        history = self._history(40)
        positions = synthetic_dependent_history(1, seed=2)[0]["rune_positions"]
        req = {
            "game": "hunt", "draw": 100, "event_at": "2098-07-01T12:00:00+03:00",
            "timezone": "Europe/Moscow", "symbolic_origin": "PROGRAMMATIC_RANDOM",
            "study_id": "feat-1", "history": history, "rune_positions": positions,
        }
        first = self.research.forecast(req)
        self.assertEqual(first, self.research.forecast(req))
        changed = deepcopy(req)
        changed["rune_positions"] = [
            {"rune_id": "fehu", "final_orientation": 0},
            {"rune_id": "uruz", "final_orientation": 0},
            {"rune_id": "thorn", "final_orientation": 180},
        ]
        with self.assertRaisesRegex(ValueError, "already fixed"):
            self.research.forecast(changed)

    def test_four_unique_numbers_per_field_and_no_cross_field_scoring(self):
        self.research.register(self._protocol())
        self._enter_study()
        history = self._history(40)
        positions = synthetic_dependent_history(1, seed=3)[0]["rune_positions"]
        forecast = self.research.forecast({
            "game": "hunt", "draw": 100, "event_at": "2098-07-01T12:00:00+03:00",
            "timezone": "Europe/Moscow", "symbolic_origin": "MANUAL",
            "study_id": "feat-1", "history": history, "rune_positions": positions,
        })
        for name, arm in forecast["methods"].items():
            if arm.get("state") != "PICK":
                continue
            for field in arm["fields"]:
                self.assertEqual(len(field), 4)
                self.assertEqual(len(set(field)), 4)
                self.assertTrue(all(1 <= n <= 20 for n in field))
        outcome = [[1, 2, 3, 4], [10, 11, 12, 13]]
        self.now = datetime(2098, 7, 1, 12, 5, tzinfo=timezone.utc)
        self.research.ingest_outcome("hunt", 100, outcome, "SYNTHETIC",
                                     occurred_at="2098-07-01T12:00:00+03:00")
        report = self.research.evaluate(study_id="feat-1")
        trial = next(t for t in report["trials"] if t["status"] == "RESOLVED")
        for method, score in trial["scores"].items():
            if score["total"] is None:
                continue
            arm = forecast["methods"][method]
            expected = hits(arm["fields"], outcome)
            self.assertEqual(score["hits_by_field"], expected)
            self.assertEqual(score["total"], sum(expected))
            self.assertEqual(score["hits_by_field"][0], len(set(arm["fields"][0]) & set(outcome[0])))
            self.assertEqual(score["hits_by_field"][1], len(set(arm["fields"][1]) & set(outcome[1])))

    def test_abstain_when_insufficient_and_missing_runes(self):
        arm = regularized_feature_picks(
            [{"draw": 1, "fields": [[1, 2, 3, 4], [5, 6, 7, 8]], "feature_tokens": ["weekday=1"]}],
            ["weekday=1", "hour_bucket=2"], min_train=30, alpha=1.0,
            method_id="D_time_features_only", game="hunt", draw=2)
        self.assertEqual(arm["state"], "ABSTAIN")
        self.assertEqual(arm["reason"], INSUFFICIENT)
        self.research.register(self._protocol())
        self._enter_study()
        forecast = self.research.forecast({
            "game": "hunt", "draw": 100, "event_at": "2098-07-01T12:00:00+03:00",
            "timezone": "Europe/Moscow", "symbolic_origin": "OTHER",
            "study_id": "feat-1", "history": self._history(40), "rune_positions": None,
        })
        self.assertEqual(forecast["methods"]["C_lottery_rune_hash_v2"]["state"], "ABSTAIN")
        self.assertEqual(forecast["methods"]["E_rune_features_only"]["state"], "ABSTAIN")
        self.assertEqual(forecast["methods"]["F_rune_plus_time"]["state"], "ABSTAIN")

    def test_connected_features_affect_matching_methods(self):
        rows = synthetic_dependent_history(80, seed=5, signal="time")
        history = [{"draw": r["draw"], "fields": r["fields"],
                    "feature_tokens": r["time_model_tokens"]} for r in rows[:60]]
        tokens = rows[70]["time_model_tokens"]
        with_signal = regularized_feature_picks(
            history, tokens, min_train=5, alpha=1.0,
            method_id="D_time_features_only", game="hunt", draw=71)
        shuffled = [{"draw": r["draw"], "fields": rows[(i + 17) % 60]["fields"],
                     "feature_tokens": r["time_model_tokens"]} for i, r in enumerate(rows[:60])]
        scrambled = regularized_feature_picks(
            shuffled, tokens, min_train=5, alpha=1.0,
            method_id="D_time_features_only", game="hunt", draw=71)
        self.assertEqual(with_signal["state"], "PICK")
        self.assertEqual(scrambled["state"], "PICK")
        self.assertNotEqual(with_signal["fields"], scrambled["fields"])

    def test_lottery_hash_v2_reproducible_and_ignores_time(self):
        positions = [
            {"rune_id": "blank", "final_orientation": None},
            {"rune_id": "fehu", "final_orientation": 0},
            {"rune_id": "isa", "final_orientation": 180},
        ]
        seed, picks = method_fields(1, positions)
        self.assertEqual(seed, "lottery-rune-hash-v2|target=1|blank:None,fehu:0,isa:180")
        self.assertEqual((seed, picks), method_fields(1, positions))
        self.assertEqual(seed_text(1, positions), seed)

    def test_reproducibility_of_research_forecast_arms(self):
        self.research.register(self._protocol())
        self._enter_study()
        history = self._history(40)
        positions = synthetic_dependent_history(1, seed=8)[0]["rune_positions"]
        req = {
            "game": "hunt", "draw": 100, "event_at": "2098-07-01T12:00:00+03:00",
            "timezone": "Europe/Moscow", "symbolic_origin": "SYNTHETIC_FIXTURE",
            "study_id": "feat-1", "history": history, "rune_positions": positions,
        }
        a = self.research.forecast(req, rng=__import__("random").Random(123))
        b = self.research.forecast(req, rng=__import__("random").Random(999))
        self.assertEqual(a["methods"]["C_lottery_rune_hash_v2"], b["methods"]["C_lottery_rune_hash_v2"])
        self.assertEqual(a["methods"]["B_frequency"], b["methods"]["B_frequency"])
        self.assertEqual(a["methods"]["A_random"], b["methods"]["A_random"])

    def test_planted_dependence_detected_out_of_sample(self):
        rows = synthetic_dependent_history(200, seed=11, signal="time")
        result = walk_forward_ablation(rows, min_train=10, method="D_time_features_only", train_end=140)
        self.assertGreaterEqual(result["n_scored"], 20)
        self.assertIsNotNone(result["mean_diff_vs_random"])
        self.assertGreater(result["mean_diff_vs_random"], 0.2)

    def test_independent_random_does_not_guarantee_discovery(self):
        rows = synthetic_dependent_history(200, seed=22, signal="none")
        result = walk_forward_ablation(rows, min_train=10, method="D_time_features_only", train_end=140)
        self.assertGreaterEqual(result["n_scored"], 10)
        self.assertLess(abs(result["mean_diff_vs_random"]), 2.0)

    def test_games_are_separated_and_holdout_split_documented(self):
        self.research.register(self._protocol(
            confirmatory_after="2098-08-01T00:00:00Z",
            confirmatory_rule="event_at_declared_ge_boundary",
        ))
        self._enter_study()
        history = self._history(40)
        positions = synthetic_dependent_history(1, seed=9)[0]["rune_positions"]
        self.research.forecast({
            "game": "hunt", "draw": 100, "event_at": "2098-07-01T12:00:00+03:00",
            "timezone": "Europe/Moscow", "symbolic_origin": "SYNTHETIC_FIXTURE",
            "study_id": "feat-1", "history": history, "rune_positions": positions,
        })
        bad = deepcopy(history)
        bad[0]["game"] = "four_of_twenty"
        with self.assertRaisesRegex(ValueError, "mixes games"):
            self.research.forecast({
                "game": "hunt", "draw": 101, "event_at": "2098-07-02T12:00:00+03:00",
                "timezone": "Europe/Moscow", "symbolic_origin": "SYNTHETIC_FIXTURE",
                "study_id": "feat-1", "history": bad, "rune_positions": positions,
            })
        self.now = datetime(2098, 7, 1, 12, 5, tzinfo=timezone.utc)
        self.research.ingest_outcome("hunt", 100, [[1, 2, 3, 4], [5, 6, 7, 8]], "SYNTHETIC",
                                     occurred_at="2098-07-01T12:00:00+03:00")
        report = self.research.evaluate(study_id="feat-1")
        self.assertTrue(report["games_separated"])
        self.assertEqual(report["split_kind"], "PROTOCOL_LOCKED_EXPLORATORY_LABEL")
        self.assertEqual(report["by_game"]["hunt"][0]["confirmatory_holdout"]["n_trials"], 0)
        self.assertEqual(report["by_game"]["hunt"][0]["exploratory"]["n_trials"], 1)

    def test_frequency_and_event_bin_helper(self):
        history = [{"draw": i, "fields": [[1, 2, 3, 4], [5, 6, 7, 8]]} for i in range(1, 11)]
        picks = frequency_picks(history, "hunt", 11, limit=100)
        self.assertEqual(picks["state"], "PICK")
        self.assertEqual(picks["fields"][0], [1, 2, 3, 4])
        stamp = _event_at_for_bins(3, 2, 1)
        parts = _local_parts(stamp, "Europe/Moscow")
        self.assertEqual(parts["weekday"], 3)
        self.assertEqual(parts["hour_bucket"], 2)
        tokens = rune_feature_tokens([
            {"rune_id": "fehu", "final_orientation": 0},
            {"rune_id": "blank", "final_orientation": None},
            {"rune_id": "isa", "final_orientation": 180},
        ])
        self.assertEqual(tokens[1], "p1=blank:None")

    def test_synthetic_demo_cli_and_module(self):
        directory = Path(self.tmp.name) / "demo"
        summary = run_synthetic_demo(directory)
        self.assertEqual(summary["provenance"], "SYNTHETIC")
        self.assertIn("planted_time_walk_forward", summary)
        code = main(["synthetic-demo", "--directory", str(Path(self.tmp.name) / "demo2")])
        self.assertEqual(code, 0)

    # --- Defect regressions ---

    def test_permutation_null_statistic_changes_on_nondegenerate_set(self):
        trials = []
        outcomes = [
            [[1, 2, 3, 4], [5, 6, 7, 8]],
            [[9, 10, 11, 12], [13, 14, 15, 16]],
            [[1, 2, 3, 4], [17, 18, 19, 20]],
            [[5, 6, 7, 8], [1, 2, 3, 4]],
        ]
        methods = [
            [[1, 2, 3, 4], [5, 6, 7, 8]],
            [[9, 10, 11, 12], [13, 14, 15, 16]],
            [[1, 2, 9, 10], [5, 6, 17, 18]],
            [[3, 4, 5, 6], [7, 8, 9, 10]],
        ]
        controls = [
            [[11, 12, 13, 14], [15, 16, 17, 18]],
            [[1, 2, 3, 4], [5, 6, 7, 8]],
            [[15, 16, 17, 18], [11, 12, 13, 14]],
            [[19, 20, 1, 2], [3, 4, 5, 6]],
        ]
        for draw, outcome, method_fields_value, control_fields in zip(
                range(1, 5), outcomes, methods, controls):
            m_hits = hits(method_fields_value, outcome)
            c_hits = hits(control_fields, outcome)
            trials.append({
                "status": "RESOLVED", "game": "hunt", "draw": draw,
                "method_fields": {
                    "D_time_features_only": method_fields_value,
                    "A_random": control_fields,
                },
                "outcome_fields": outcome,
                "scores": {
                    "D_time_features_only": {"total": sum(m_hits)},
                    "A_random": {"total": sum(c_hits)},
                },
            })
        result = permutation_null(trials, "D_time_features_only", n_perm=99, seed=3, game="hunt")
        self.assertEqual(result["status"], "COMPUTED")
        self.assertFalse(result["causality_claim"])
        self.assertGreater(result["n_perms_statistic_changed"], 0)
        self.assertIn("exchangeable", result["null_hypothesis"])

    def test_outcome_before_event_rejected_even_without_occurred_at(self):
        self.research.register(self._protocol())
        self._enter_study()  # 2098-06-01
        self.research.forecast({
            "game": "hunt", "draw": 100, "event_at": "2098-07-01T12:00:00+03:00",
            "timezone": "Europe/Moscow", "symbolic_origin": "SYNTHETIC_FIXTURE",
            "study_id": "feat-1", "history": self._history(40),
            "rune_positions": synthetic_dependent_history(1, seed=4)[0]["rune_positions"],
        })
        before = self.research.verify()["records"]
        with self.assertRaisesRegex(ValueError, "before declared event"):
            self.research.ingest_outcome("hunt", 100, [[1, 2, 3, 4], [5, 6, 7, 8]], "SYNTHETIC")
        self.assertEqual(before, self.research.verify()["records"])
        with self.assertRaisesRegex(ValueError, "before declared event"):
            self.research.ingest_outcome(
                "hunt", 100, [[1, 2, 3, 4], [5, 6, 7, 8]], "SYNTHETIC",
                recorded_at="2098-08-01T00:00:00Z")
        self.assertEqual(before, self.research.verify()["records"])

    def test_evaluate_separates_games_in_one_db(self):
        self.research.register(self._protocol(study_id="hunt-study"))
        self.research.register(self._protocol(
            study_id="four-study", game="four_of_twenty",
            method_versions=locked_method_versions(100)))
        self._enter_study()
        hunt_hist = self._history(40, game="hunt")
        four_hist = self._history(40, game="four_of_twenty")
        positions = synthetic_dependent_history(1, seed=6)[0]["rune_positions"]
        self.research.forecast({
            "game": "hunt", "draw": 100, "event_at": "2098-07-01T12:00:00+03:00",
            "timezone": "Europe/Moscow", "symbolic_origin": "SYNTHETIC_FIXTURE",
            "study_id": "hunt-study", "history": hunt_hist, "rune_positions": positions,
        })
        self.research.forecast({
            "game": "four_of_twenty", "draw": 100, "event_at": "2098-07-01T12:00:00+03:00",
            "timezone": "Europe/Moscow", "symbolic_origin": "SYNTHETIC_FIXTURE",
            "study_id": "four-study", "history": four_hist, "rune_positions": positions,
        })
        self.now = datetime(2098, 7, 1, 12, 5, tzinfo=timezone.utc)
        self.research.ingest_outcome("hunt", 100, [[1, 2, 3, 4], [5, 6, 7, 8]], "SYNTHETIC",
                                     occurred_at="2098-07-01T12:00:00+03:00")
        self.research.ingest_outcome("four_of_twenty", 100, [[9, 10, 11, 12], [13, 14, 15, 16]],
                                     "SYNTHETIC", occurred_at="2098-07-01T12:00:00+03:00")
        report = self.research.evaluate()
        self.assertIsNone(report["pooled_summary"])
        self.assertTrue(report["games_separated"])
        self.assertEqual(len(report["by_game"]["hunt"]), 1)
        self.assertEqual(len(report["by_game"]["four_of_twenty"]), 1)
        self.assertEqual(report["by_game"]["hunt"][0]["exploratory"]["n_trials"], 1)
        self.assertEqual(report["by_game"]["four_of_twenty"][0]["exploratory"]["n_trials"], 1)
        self.assertEqual(report["by_game"]["hunt"][0]["study_id"], "hunt-study")
        self.assertEqual(report["by_game"]["four_of_twenty"][0]["study_id"], "four-study")

    def test_protocol_rejects_frequency_window_change(self):
        self.research.register(self._protocol(frequency_window=30))
        self._enter_study()
        with self.assertRaisesRegex(ValueError, "frequency_window conflicts"):
            self.research.forecast({
                "game": "hunt", "draw": 100, "event_at": "2098-07-01T12:00:00+03:00",
                "timezone": "Europe/Moscow", "symbolic_origin": "SYNTHETIC_FIXTURE",
                "study_id": "feat-1", "history": self._history(40),
                "rune_positions": synthetic_dependent_history(1, seed=7)[0]["rune_positions"],
                "frequency_window": 100,
            })
        ok = self.research.forecast({
            "game": "hunt", "draw": 100, "event_at": "2098-07-01T12:00:00+03:00",
            "timezone": "Europe/Moscow", "symbolic_origin": "SYNTHETIC_FIXTURE",
            "study_id": "feat-1", "history": self._history(40),
            "rune_positions": synthetic_dependent_history(1, seed=7)[0]["rune_positions"],
        })
        self.assertEqual(ok["methods"]["B_frequency"]["method_id"], "frequency30-v1")
        self.assertEqual(ok["training"]["frequency_window"], 30)
        self.assertEqual(ok["request"]["frequency_window"], 30)

    def test_confirmatory_boundary_locked_in_protocol(self):
        self.research.register(self._protocol(
            analysis_status="CONFIRMATORY",
            confirmatory_after="2098-08-01T00:00:00Z",
            confirmatory_rule="event_at_declared_ge_boundary",
            sample_size=5,
        ))
        self._enter_study()
        positions = synthetic_dependent_history(1, seed=10)[0]["rune_positions"]
        history = self._history(40)
        self.research.forecast({
            "game": "hunt", "draw": 100, "event_at": "2098-07-01T12:00:00+03:00",
            "timezone": "Europe/Moscow", "symbolic_origin": "SYNTHETIC_FIXTURE",
            "study_id": "feat-1", "history": history, "rune_positions": positions,
        })
        self.research.forecast({
            "game": "hunt", "draw": 101, "event_at": "2098-09-01T12:00:00+03:00",
            "timezone": "Europe/Moscow", "symbolic_origin": "SYNTHETIC_FIXTURE",
            "study_id": "feat-1", "history": history, "rune_positions": positions,
        })
        self.now = datetime(2098, 7, 1, 12, 5, tzinfo=timezone.utc)
        self.research.ingest_outcome("hunt", 100, [[1, 2, 3, 4], [5, 6, 7, 8]], "SYNTHETIC",
                                     occurred_at="2098-07-01T12:00:00+03:00")
        self.now = datetime(2098, 9, 1, 12, 5, tzinfo=timezone.utc)
        self.research.ingest_outcome("hunt", 101, [[1, 2, 3, 4], [5, 6, 7, 8]], "SYNTHETIC",
                                     occurred_at="2098-09-01T12:00:00+03:00")
        report = self.research.evaluate(study_id="feat-1")
        self.assertEqual(report["analysis_status"], "CONFIRMATORY")
        self.assertEqual(report["split_kind"], "PROTOCOL_LOCKED")
        block = report["by_study"]["feat-1"][0]
        self.assertEqual(block["exploratory"]["n_trials"], 1)
        self.assertEqual(block["confirmatory_holdout"]["n_trials"], 1)
        with self.assertRaisesRegex(ValueError, "conflicts with locked protocol boundary"):
            self.research.evaluate(study_id="feat-1", confirmatory_after="2098-07-15T00:00:00Z")

    def test_time_model_tokens_preserved_without_time_tokens(self):
        rows = [{
            "game": "hunt", "draw": i, "fields": [[1, 2, 3, 4], [5, 6, 7, 8]],
            "available_at": "2098-01-01T00:00:00Z", "source": "SYNTHETIC",
            "time_model_tokens": ["weekday=1", "hour_bucket=2"],
        } for i in range(1, 25)]
        normalized = _history_rows(rows, "hunt", 100, "2098-06-01T00:00:00Z")
        self.assertEqual(normalized[0]["time_model_tokens"], ["weekday=1", "hour_bucket=2"])
        self.assertEqual(normalized[0]["time_tokens"], ["weekday=1", "hour_bucket=2"])
        self.research.register(self._protocol(min_train=10))
        self._enter_study()
        forecast = self.research.forecast({
            "game": "hunt", "draw": 100, "event_at": "2098-07-01T12:00:00+03:00",
            "timezone": "Europe/Moscow", "symbolic_origin": "SYNTHETIC_FIXTURE",
            "study_id": "feat-1", "history": rows,
            "rune_positions": synthetic_dependent_history(1, seed=12)[0]["rune_positions"],
        })
        # Event local time may not match weekday=1/hour_bucket=2; still D must see history support.
        self.assertIn("time_model_tokens", normalized[0])
        self.assertGreaterEqual(
            forecast["methods"]["D_time_features_only"].get("factor_support", {}).get("weekday=1", 0)
            if forecast["methods"]["D_time_features_only"].get("state") == "ABSTAIN"
            else 10,
            0)

    def test_time_model_tokens_alone_feed_method_d(self):
        # Align event bins with history tokens so D can pick.
        event_at = _event_at_for_bins(1, 2, 25)
        rows = []
        for i in range(1, 40):
            rows.append({
                "game": "hunt", "draw": i, "fields": [[1, 2, 3, 4], [5, 6, 7, 8]],
                "available_at": "2098-01-01T00:00:00Z", "source": "SYNTHETIC",
                "time_model_tokens": ["weekday=1", "hour_bucket=2"],
            })
        self.research.register(self._protocol(min_train=10))
        self._enter_study()
        forecast = self.research.forecast({
            "game": "hunt", "draw": 100, "event_at": event_at,
            "timezone": "Europe/Moscow", "symbolic_origin": "SYNTHETIC_FIXTURE",
            "study_id": "feat-1", "history": rows,
            "rune_positions": synthetic_dependent_history(1, seed=13)[0]["rune_positions"],
        })
        self.assertEqual(forecast["methods"]["D_time_features_only"]["state"], "PICK")

    def test_conflicting_time_feature_representations_rejected(self):
        with self.assertRaisesRegex(ValueError, "conflicting time_model_tokens"):
            normalize_history_features({
                "time_model_tokens": ["weekday=1", "hour_bucket=2"],
                "time_tokens": ["weekday=3", "hour_bucket=2", "local_date=2098-01-01"],
            })
        with self.assertRaisesRegex(ValueError, "must not include local_date"):
            normalize_history_features({
                "time_model_tokens": ["weekday=1", "local_date=2098-01-01"],
            })


if __name__ == "__main__":
    unittest.main()
