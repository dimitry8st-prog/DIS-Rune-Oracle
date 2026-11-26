"""Synthetic checks of receipt, outcome, and forecast chronology."""

import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from dis_oracle.contracts import digest
from dis_oracle.workflow import Workflow


NOW = "2030-01-01T10:00:00Z"
TARGET = "2030-01-01T12:00:00Z"
AFTER = "2030-01-01T13:00:00Z"
NUMBERS = [[1, 2, 3, 4], [5, 6, 7, 8]]
CORRECTED = [[9, 10, 11, 12], [13, 14, 15, 16]]


class WorkflowOutcomeTimeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.now = NOW
        self.workflow = Workflow(self.directory / "synthetic.sqlite3", _clock=lambda: self.now)
        self.addCleanup(self.workflow.close)

    def forecast(self, study_id=None):
        self.workflow.ingest("hunt", 99, NUMBERS, "SYNTHETIC previous outcome")
        return self.workflow.forecast("hunt", 100, TARGET, study_id=study_id)

    def record_outcome(self, **kwargs):
        return self.workflow.ingest("hunt", 100, NUMBERS, "SYNTHETIC outcome", **kwargs)

    def test_no_occurrence_time_two_hours_before_target_rolls_back(self):
        self.forecast()
        chain = self.workflow.verify()
        with self.assertRaisesRegex(ValueError, "receipt precedes declared target"):
            self.record_outcome()
        self.assertEqual(self.workflow.verify(), chain)
        self.assertIsNone(self.workflow.lookup("hunt", 100)["outcome"])
        report = self.workflow.report()
        self.assertEqual(report["pending"], ["hunt:100"])
        self.assertEqual(report["trials"], [])
        self.assertEqual(report["excluded_trials"], [])

    def test_target_boundary_without_occurrence_allows_idempotent_replay(self):
        self.forecast()
        self.now = "2030-01-01T15:00:00+03:00"
        original = self.record_outcome()
        self.assertEqual(original["received_at"], self.now)
        self.assertIsNone(original["occurred_at"])
        chain = self.workflow.verify()
        self.now = AFTER
        self.assertEqual(self.record_outcome(occurred_at=TARGET), original)
        self.assertEqual(self.workflow.verify(), chain)
        self.assertEqual(len(self.workflow.report()["trials"]), 1)

    def test_occurrence_time_must_be_between_target_and_receipt(self):
        self.forecast()
        self.now = AFTER
        chain = self.workflow.verify()
        for time_value, error in (
            (NOW, "occurrence precedes declared target"),
            ("2030-01-01T13:00:01Z", "occurrence is in the future"),
            ("2030-01-01T12:00:00", "invalid outcome occurrence time"),
            (False, "invalid outcome occurrence time"),
            ("", "invalid outcome occurrence time"),
        ):
            with self.subTest(time_value=time_value), self.assertRaisesRegex(ValueError, error):
                self.record_outcome(occurred_at=time_value)
        self.assertEqual(self.workflow.verify(), chain)
        self.assertEqual(self.record_outcome(occurred_at=TARGET)["occurred_at"], TARGET)

    def test_clock_rollback_between_receipt_and_commit_cannot_append(self):
        self.forecast()
        chain = self.workflow.verify()
        times = iter([TARGET, "2030-01-01T11:59:59Z"])
        self.workflow.clock = lambda: next(times)
        with self.assertRaisesRegex(ValueError, "clock precedes outcome receipt"):
            self.record_outcome()
        self.assertEqual(self.workflow.verify(), chain)

    def test_preexisting_early_receipt_remains_excluded_after_correction(self):
        self.now = "2030-01-01T09:00:00Z"
        self.workflow.register({
            "study_id": "SYNTHETIC chronology", "hypothesis": "SYNTHETIC test", "game": "hunt",
            "method": "frequency100-v1", "metric": "within_field_hits", "control": "random",
            "sample_size": 1, "starts_at": NOW, "ends_at": AFTER,
        })
        self.now = NOW
        self.forecast(study_id="SYNTHETIC chronology")
        original = {
            "game": "hunt", "draw": 100, "fields": NUMBERS, "source": "SYNTHETIC pre-fix format",
            "received_at": NOW, "occurred_at": None, "numeric_eligible": True,
            "source_verification": "USER_SUPPLIED_UNATTESTED",
        }
        with self.workflow.transaction():
            self.workflow._append("outcome", "synthetic-preexisting-early-outcome", original)

        self.assertEqual(self.record_outcome(), original)
        self.now = AFTER
        self.workflow.ingest(
            "hunt", 100, CORRECTED, "SYNTHETIC corrected",
            occurred_at=TARGET, correction_of=digest(original), reason="SYNTHETIC test correction",
        )
        chain = self.workflow.verify()
        report = self.workflow.report()
        self.assertEqual(self.workflow.verify(), chain)
        self.assertEqual(self.workflow.lookup("hunt", 100)["outcome"]["correction_of"], digest(original))
        self.assertEqual(self.workflow.state(include_outcome_history=True)["outcome_history"]["hunt:100"][0], original)
        self.assertEqual(report["trials"], [])
        self.assertTrue(all(group["n"] == 0 for group in report["groups"]))
        self.assertEqual(report["study_summaries"][0]["paired"], 0)
        self.assertEqual(report["study_summaries"][0]["excluded_timing"], 1)
        excluded, = report["excluded_trials"]
        self.assertEqual(excluded["reason"], "RECEIVED_BEFORE_TARGET")
        self.assertEqual(excluded["outcome_hash"], digest(original))

    def migration(self, *, occurred_at=None, target_at=TARGET, fixed_at=NOW, draw=100, include_outcome=True):
        archive = self.directory / f"synthetic-archive-{draw}.zip"
        forecast = {
            "game": "hunt", "draw": draw, "fields": NUMBERS, "random_control": CORRECTED,
            "fixed_at": fixed_at, "target_at": target_at,
        }
        outcome = {
            "game": "hunt", "draw": draw, "fields": NUMBERS, "occurred_at": occurred_at,
            "recorded_at": "2030-01-01T09:00:00Z", "source": "SYNTHETIC archived outcome",
        }
        with zipfile.ZipFile(archive, "w") as stream:
            for path, data in {
                "updates/synthetic/latest-archive-state.json": {
                    "observations_ref": "synthetic/outcomes.json", "summary_refs": [],
                },
                "updates/synthetic/outcomes.json": [outcome] if include_outcome else [],
                f"hunt-{draw}/numeric-selection.json": forecast,
            }.items():
                stream.writestr(f"Oracle_2026-10-22/{path}", json.dumps(data))
        return archive

    def test_archive_timestamp_does_not_backdate_local_receipt(self):
        archive = self.migration()
        self.now = AFTER
        self.assertEqual(self.workflow.migrate(archive)["state"], "IMPORTED")
        chain = self.workflow.verify()
        self.assertEqual(self.workflow.migrate(archive)["state"], "ALREADY_IMPORTED")
        self.assertEqual(self.workflow.verify(), chain)
        original = self.workflow.lookup("hunt", 100)["outcome"]
        self.assertEqual(original["received_at"], AFTER)
        self.assertEqual(original["source_recorded_at"], "2030-01-01T09:00:00Z")
        report = self.workflow.report()
        self.assertEqual(len(report["trials"]), 1)
        self.assertEqual(report["excluded_trials"], [])

    def test_archive_with_early_occurrence_retains_original_without_scoring(self):
        self.now = AFTER
        archive = self.migration(occurred_at=NOW)
        self.assertEqual(self.workflow.migrate(archive)["outcomes_added"], 1)
        outcome = self.workflow.lookup("hunt", 100)["outcome"]
        self.assertEqual(outcome["occurred_at"], NOW)
        report = self.workflow.report()
        self.assertEqual(report["trials"], [])
        excluded, = report["excluded_trials"]
        self.assertEqual(excluded["reason"], "OCCURRED_BEFORE_TARGET")
        self.assertEqual(excluded["outcome_hash"], digest(outcome))

    def test_known_occurrence_before_fix_excludes_archive_even_without_target(self):
        self.now = AFTER
        archive = self.migration(occurred_at="2030-01-01T09:00:00Z", target_at=None)
        self.assertEqual(self.workflow.migrate(archive)["forecasts_added"], 1)
        excluded, = self.workflow.report()["excluded_trials"]
        self.assertEqual(excluded["reason"], "OCCURRED_BEFORE_FORECAST_FIX")
        self.assertIsNone(excluded["target_at"])

    def test_forecast_fixed_at_or_after_target_can_record_outcome_but_cannot_score(self):
        self.now = AFTER
        for draw, fixed_at in ((100, TARGET), (101, "2030-01-01T12:30:00Z")):
            with self.subTest(fixed_at=fixed_at):
                archive = self.migration(draw=draw, fixed_at=fixed_at, include_outcome=False)
                self.assertEqual(self.workflow.migrate(archive)["forecasts_added"], 1)
                original_forecast = self.workflow.lookup("hunt", draw)["forecast"]
                outcome = self.workflow.ingest("hunt", draw, NUMBERS, "SYNTHETIC outcome", occurred_at=AFTER)
                original_chain = self.workflow.verify()
                report = self.workflow.report()
                self.assertEqual(report["trials"], [])
                excluded = next(trial for trial in report["excluded_trials"] if trial["draw"] == draw)
                self.assertEqual(excluded["reason"], "FORECAST_FIXED_AT_OR_AFTER_TARGET")
                self.assertEqual(excluded["outcome_hash"], digest(outcome))
                restored = self.workflow.lookup("hunt", draw)
                self.assertEqual(restored["forecast"], original_forecast)
                self.assertEqual(restored["outcome"], outcome)
                self.assertEqual(self.workflow.verify(), original_chain)
