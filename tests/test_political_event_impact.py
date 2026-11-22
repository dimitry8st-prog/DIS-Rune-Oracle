from copy import deepcopy
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from dis_oracle.contracts import ContractError
from dis_oracle.journal import Journal
from dis_oracle.political_event_impact import evaluate, freeze
from examples.political_event_impact.demo import fixtures


class PoliticalEventImpactTests(unittest.TestCase):
    def setUp(self):
        self.request, self.outcomes = fixtures()

    def report(self):
        return evaluate(freeze(**self.request), self.outcomes["bars"], self.outcomes["as_of_utc"])

    def test_synthetic_windows_control_and_reversal(self):
        report = self.report()
        self.assertEqual(report["provenance"], "SYNTHETIC")
        self.assertEqual(report["market_validation"], "NOT_VALIDATED_ON_REAL_MARKET")
        self.assertEqual(report["first_full_post_minute_utc"], "2026-11-18T15:31:00+00:00")
        self.assertEqual(report["publication_to_observation_seconds"], 5)
        self.assertTrue(report["publication_minute_excluded"])
        for minutes, closing in ((1, 100.30), (5, 101.0), (15, 102.0), (60, 101.5)):
            row = report["windows"][str(minutes)]
            expected_return = closing / 100 - 1
            expected_benchmark = (100 + minutes / 300) / 100 - 1
            self.assertEqual(row["status"], "OK")
            self.assertEqual(row["asset_ohlcv"]["volume"], minutes * 100)
            self.assertAlmostEqual(row["return"], expected_return)
            self.assertAlmostEqual(row["benchmark_return"], expected_benchmark)
            self.assertAlmostEqual(row["matched"]["excess_abnormal_return"], expected_return - expected_benchmark)
            self.assertEqual(row["controls"]["SYNTH-CONTROL"]["abnormal_return"], 0)
        self.assertEqual(report["reaction"], {
            "first_move_seconds": 90, "returned_within_band_seconds": 150, "reversed_seconds": 210,
        })
        self.assertEqual(report["primary_status"], "OK")
        self.assertGreater(report["primary_value"], 0)

    def test_freeze_rejects_late_or_postpublication_bars(self):
        row = self.request["feature_bars"][0]
        row["available_at_utc"] = "2026-11-18T15:30:41+00:00"
        with self.assertRaisesRegex(ContractError, "look-ahead"):
            freeze(**self.request)
        self.request, self.outcomes = fixtures()
        self.request["protocol"]["decision_cutoff_utc"] = "2026-11-18T16:00:00+00:00"
        self.request["feature_bars"].append(self.outcomes["bars"][0])
        with self.assertRaisesRegex(ContractError, "look-ahead"):
            freeze(**self.request)

    def test_chronology_and_duplicate_identifiers(self):
        self.request["event"]["observed_at_utc"] = "2026-11-18T15:30:29+00:00"
        with self.assertRaisesRegex(ContractError, "out of order"):
            freeze(**self.request)
        self.request, _ = fixtures()
        controls = self.request["protocol"]["controls"]
        controls.append(deepcopy(controls[0]))
        with self.assertRaisesRegex(ContractError, "duplicate control"):
            freeze(**self.request)
        self.request, _ = fixtures()
        self.request["feature_bars"].append(self.request["feature_bars"][0])
        with self.assertRaisesRegex(ContractError, "duplicate M1"):
            freeze(**self.request)

    def test_missing_benchmark_abstains_without_selecting_another_control(self):
        self.outcomes["bars"] = [
            bar for bar in self.outcomes["bars"]
            if not (bar["symbol"] == "INDEX" and bar["start_at_utc"] == "2026-11-11T15:31:00+00:00")
        ]
        report = self.report()
        minute = report["windows"]["1"]
        self.assertEqual(minute["status"], "OK")
        self.assertEqual(minute["controls"]["SYNTH-CONTROL"]["reason"], "MISSING_COMPLETED_M1")
        self.assertEqual(report["primary_status"], "ABSTAIN")
        self.assertIsNone(report["primary_value"])

    def test_zero_volume_and_outside_session_abstain(self):
        self.outcomes["bars"][0]["volume"] = 0
        self.assertEqual(self.report()["windows"]["1"]["reason"], "ZERO_TRADED_VOLUME")
        self.request, self.outcomes = fixtures()
        self.request["protocol"]["session"]["close_at_utc"] = "2026-11-18T15:45:00+00:00"
        self.assertEqual(self.report()["windows"]["60"]["reason"], "OUTSIDE_REGISTERED_SESSION")

    def test_flat_and_neutral_reaction(self):
        for bars in (self.request["feature_bars"], self.outcomes["bars"]):
            for row in bars:
                row.update(open=100, high=100, low=100, close=100)
        self.assertEqual(self.report()["windows"]["60"]["reason"], "FLAT_MARKET")
        self.request, self.outcomes = fixtures()
        benchmark = {row["start_at_utc"]: row for row in self.outcomes["bars"] if row["symbol"] == "INDEX"}
        for row in self.outcomes["bars"]:
            if row["symbol"] == "DEMO":
                row.update({key: benchmark[row["start_at_utc"]][key] for key in ("open", "high", "low", "close")})
        report = self.report()
        self.assertEqual(report["primary_status"], "OK")
        self.assertAlmostEqual(report["primary_value"], 0)
        self.assertIsNone(report["reaction"]["first_move_seconds"])

    def test_evaluation_rejects_unavailable_bars_and_changed_pre_event_evidence(self):
        self.outcomes["bars"][0]["available_at_utc"] = "2026-11-18T17:00:00+00:00"
        with self.assertRaisesRegex(ContractError, "look-ahead"):
            self.report()
        self.request, self.outcomes = fixtures()
        changed = deepcopy(self.request["feature_bars"][0])
        changed["volume"] = 777
        self.outcomes["bars"].append(changed)
        with self.assertRaisesRegex(ContractError, "revises"):
            self.report()

    def test_date_alignments_reject_wrong_control_local_time_and_naive_times(self):
        self.request["protocol"]["controls"][0]["reference_at_utc"] = "2026-11-11T15:30:31+00:00"
        with self.assertRaisesRegex(ContractError, "local weekday/time"):
            freeze(**self.request)
        self.request, _ = fixtures()
        self.request["event"]["observed_at_utc"] = "2026-11-18T15:30:35"
        with self.assertRaisesRegex(ContractError, "timezone"):
            freeze(**self.request)

    def test_order_independent_replay_and_integrity(self):
        first = self.report()
        self.request["feature_bars"].reverse()
        self.outcomes["bars"].reverse()
        self.assertEqual(first, self.report())
        frozen = freeze(**self.request)
        frozen["event"]["actor"] = "Another actor"
        with self.assertRaisesRegex(ContractError, "integrity"):
            evaluate(frozen, self.outcomes["bars"], self.outcomes["as_of_utc"])

    def test_cli_journal_is_idempotent_and_preserves_original(self):
        with TemporaryDirectory() as temporary:
            folder = Path(temporary)
            inputs, db = folder / "inputs", folder / "study.sqlite3"
            subprocess.run([sys.executable, "-m", "examples.political_event_impact.demo", "--directory", str(inputs)], check=True)
            cli = [sys.executable, "-m", "dis_oracle.political_event_impact", "--db", str(db)]
            first = subprocess.check_output(cli + ["freeze", str(inputs / "freeze.json")])
            self.assertEqual(first, subprocess.check_output(cli + ["freeze", str(inputs / "freeze.json")]))
            frozen_path = inputs / "freeze.json"
            changed = folder / "conflict.json"
            changed.write_text(frozen_path.read_text().replace("Synthetic policymaker", "Changed actor"))
            conflict = subprocess.run(cli + ["freeze", str(changed)], capture_output=True)
            self.assertNotEqual(conflict.returncode, 0)
            self.assertIn(b"record key exists with different content", conflict.stderr)
            later = subprocess.check_output(cli + ["evaluate", str(inputs / "evaluate.json")])
            self.assertEqual(later, subprocess.check_output(cli + ["evaluate", str(inputs / "evaluate.json")]))
            journal = Journal(db)
            try:
                self.assertEqual(journal.verify()["records"], 2)
            finally:
                journal.close()
