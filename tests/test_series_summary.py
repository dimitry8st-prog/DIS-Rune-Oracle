"""Read-only series registry. Populations overlap and are not added together."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from dis_oracle.journal import Journal
from dis_oracle.pipeline import Cycle
from dis_oracle.series import series_summary
from research_stats.core import hits
from tests.test_lottery_rune_hash import ROOT, START, cycle_manifest, numeric
from tests.test_pipeline import AFTER


def open_cycle(directory, draw, mode="forecast", target="2099-01-01T00:00:00Z"):
    manifest = cycle_manifest(draw, target)
    manifest["event"]["mode"] = mode
    manifest["event"]["event_id"] = f"SYNTHETIC-series-{draw}"
    run_id = f"series-{draw}"
    with Cycle(directory, run_id) as cycle:
        state = cycle.start(manifest, at=START)
        cycle.review({"claims_by_core": {}})
        cycle.freeze(at="2098-12-30T00:00:01Z")
    return manifest, state["lottery-rune-hash-v2"]


class SeriesSummaryTests(unittest.TestCase):
    def test_registry_separates_populations_and_does_not_write(self):
        corrected = [[17, 18, 19, 20], [5, 6, 7, 8]]
        with tempfile.TemporaryDirectory() as directory:
            manifest, pair = open_cycle(directory, 30001)
            with Cycle(directory, "series-30001") as cycle:
                restarted = cycle.start(manifest, at=START)
                self.assertEqual(restarted["lottery-rune-hash-v2"], pair)
                event_id = manifest["event"]["event_id"]
                cycle.science({"report_id": "before", "reason": "Awaiting the draw"}, at="2098-12-30T00:00:02Z")
                cycle.science({"report_id": "confirmed", "reason": "Declared draw", "supersedes": "before",
                               "numeric_outcomes": [numeric(event_id, 30001)]}, at=AFTER)
                cycle.science({"report_id": "corrected", "reason": "Source corrected one field", "supersedes": "confirmed",
                               "lottery_outcomes": [numeric(event_id, 30001, fields=corrected)]}, at=AFTER)
            retro, _ = open_cycle(directory, 30002, mode="retrospective")
            with Cycle(directory, "series-30002") as cycle:
                cycle.science({"report_id": "retro", "reason": "Archived comparison",
                               "numeric_outcomes": [numeric(retro["event"]["event_id"], 30002)]}, at=AFTER)
            late, _ = open_cycle(directory, 30003, target="2026-10-24T00:00:00Z")
            with Cycle(directory, "series-30003") as cycle:
                cycle.science({"report_id": "late", "reason": "Fixed after the target",
                               "numeric_outcomes": [numeric(late["event"]["event_id"], 30003)]}, at=AFTER)
            quiet, _ = open_cycle(directory, 30004)
            with Cycle(directory, "series-30004") as cycle:
                cycle.science({"report_id": "quiet", "reason": "Receipt was not confirmed",
                               "numeric_outcomes": [numeric(quiet["event"]["event_id"], 30004, confirmation="UNCONFIRMED")]},
                              at=AFTER)
            open_cycle(directory, 30005)
            database = Path(directory) / "cycle-v03.sqlite3"
            journal = Journal(database)
            try:
                saved = next(row["payload"] for row in journal.export()
                             if row["record_key"].endswith(":lottery-rune-hash-v2") and row["payload"]["draw"] == 30001)
                journal.append("cycle:duplicate-import:lottery-rune-hash-v2", dict(saved))
                head = journal.verify()["head_hash"]
                with patch.object(journal, "append", side_effect=AssertionError("series summary must not write")), \
                     patch("dis_oracle.pipeline.control_fields", side_effect=AssertionError("series summary must not draw")):
                    result = series_summary(journal)
                self.assertEqual(journal.verify()["head_hash"], head)
            finally:
                journal.close()
            counts = result["counts"]
            self.assertEqual(result["real_personal_archive"], "UNAVAILABLE")
            self.assertTrue(counts["not_additive"])
            self.assertNotIn("total", counts)
            self.assertEqual(counts["prospective_trials"], 1)
            self.assertEqual(counts["descriptive_comparisons"], 3)
            self.assertEqual(counts["archival_outcomes"], 3)
            self.assertEqual(counts["overlap_archival_and_descriptive"], 3)
            self.assertEqual(counts["awaiting_outcome"], 1)
            self.assertEqual(counts["late"], 1)
            self.assertEqual(counts["retrospective"], 1)
            self.assertEqual(counts["unconfirmed"], 1)
            self.assertEqual(counts["missing_outcome"], 1)
            self.assertEqual(result["repeated_outcome_versions_excluded"], 1)
            self.assertEqual(len(result["duplicate_imports_excluded"]), 1)
            prospective = next(row for row in result["draws"] if row["draw"] == 30001)
            self.assertEqual(prospective["populations"], ["prospective"])
            self.assertEqual(prospective["outcome"]["fields"], corrected)
            self.assertEqual(prospective["method_hits"], hits(pair["method_fields"], corrected))
            self.assertEqual(prospective["difference"], sum(prospective["method_hits"]) - sum(prospective["control_hits"]))
            self.assertEqual(result["prospective"]["difference_method_minus_control"], prospective["difference"])
            self.assertEqual(len(prospective["history"]), 3)
            self.assertTrue(all(item["in_applied_chain"] for item in prospective["history"]))
            self.assertNotIn(30001, [row["draw"] for row in result["draws"] if "archival" in row["populations"]])
            self.assertIn("not added together", result["table"])
            command = [sys.executable, "-m", "dis_oracle", "series-summary", "--db", str(database)]
            completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("not added together", completed.stdout)
            payload = json.loads(completed.stdout.splitlines()[-1])
            self.assertEqual(payload["counts"], counts)
            self.assertEqual(payload["table"], result["table"])
            journal = Journal(database)
            try:
                self.assertEqual(journal.verify()["head_hash"], head)
            finally:
                journal.close()
