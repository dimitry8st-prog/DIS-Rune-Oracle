"""End-to-end import, freeze, score, snapshot and recovery of synthetic data."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from dis_oracle.archive_cycle import LOTTERY_METHOD
from dis_oracle.contracts import now_iso
from dis_oracle.journal import Journal
from dis_oracle.workflow import Workflow


EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "workflow"
NUMBERS = [[1, 2, 3, 4], [5, 6, 7, 8]]
CONTROL = [[9, 10, 11, 12], [13, 14, 15, 16]]


class WorkflowRecoveryTest(unittest.TestCase):
    def test_mixed_archive_round_trip_preserves_records_and_symbolic_chains(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        live = root / "live"
        standalone = live / "standalone_runs" / "synthetic-draw-98" / "cycle-v03.sqlite3"
        plan = {
            "game": "hunt", "draw": 98, "method_version": LOTTERY_METHOD,
            "target_at": "2026-01-01T11:00:00Z",
            "control_rule": "uniform without replacement: four distinct integers 1..20 in each of two fields",
        }
        fixed_at = "2026-01-01T10:00:00Z"
        journal = Journal(standalone)
        try:
            journal.append("cycle:synthetic:registered", {
                "manifest": {"lottery_plan": plan, "provenance": "SYNTHETIC"},
                "registered_at": fixed_at,
            })
            journal.append("cycle:synthetic:" + LOTTERY_METHOD, {
                **plan, "state": "LOTTERY_NUMERIC_FIXED", "registered_at": fixed_at,
                "fixed_at": fixed_at, "method_fields": NUMBERS, "control_fields": CONTROL,
            })
            standalone_chain = journal.verify()
        finally:
            journal.close()

        archive = root / "synthetic.zip"
        with ZipFile(archive, "w") as bundle:
            bundle.writestr("Oracle/updates/20260102/latest-archive-state.json", json.dumps({
                "observations_ref": "20260102/history.json", "summary_refs": [],
            }))
            bundle.writestr("Oracle/updates/20260102/history.json", json.dumps([
                {"game": "hunt", "draw": 99, "fields": NUMBERS},
                {"game": "four_of_twenty", "draw": 98, "fields": CONTROL},
            ]))
            bundle.writestr("Oracle/four-98/numeric-selection.json", json.dumps({
                "game": "four_of_twenty", "draw": 98, "fields": NUMBERS, "random_control": CONTROL,
                "target_at_declared": plan["target_at"], "fixed_at": fixed_at,
            }))
            bundle.write(standalone, "Oracle/standalone_runs/synthetic-draw-98/cycle-v03.sqlite3")
        originals = {file: hashlib.sha256(file.read_bytes()).hexdigest() for file in (archive, standalone)}

        template = json.loads((EXAMPLES / "manifest.json").read_text(encoding="utf-8"))
        target = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        recorded_time = None
        with Workflow(live / "oracle.sqlite3", _clock=lambda: recorded_time or now_iso()) as workflow:
            imported = workflow.migrate(archive)
            self.assertEqual((2, 2), (imported["outcomes_added"], imported["forecasts_added"]))
            imported_chain = workflow.verify()
            self.assertEqual(workflow.migrate(archive)["state"], "ALREADY_IMPORTED")
            self.assertEqual(workflow.verify(), imported_chain)

            forecast = workflow.forecast("hunt", 100, target, template=template)
            self.assertEqual(forecast["methods"][LOTTERY_METHOD]["state"], "PICK")
            before = workflow.verify()
            with self.assertRaisesRegex(ValueError, "receipt precedes declared target"):
                workflow.ingest("hunt", 100, NUMBERS, "SYNTHETIC early receipt")
            self.assertEqual(workflow.verify(), before)

            recorded_time = target
            observation = workflow.ingest("hunt", 100, NUMBERS, "SYNTHETIC declared outcome")
            self.assertIsNone(observation["occurred_at"])
            report = workflow.report()
            self.assertEqual((3, 3), (report["forecasts"], report["outcomes"]))
            self.assertEqual(len(report["trials"]), 2)
            expected_draws = [workflow.lookup(game, draw) for game, draw in (
                ("hunt", 98), ("four_of_twenty", 98), ("hunt", 100),
            )]
            backup = workflow.backup(root / "bundle")

        restored = Workflow.restore(root / "bundle", root / "recovered")
        self.assertEqual(restored["workflow_chain"], report["chain"])
        self.assertEqual(backup["journal_chains"], restored["journal_chains"])
        self.assertEqual(restored["journal_chains"][standalone.relative_to(live).as_posix()], standalone_chain)
        self.assertEqual(len(restored["journal_chains"]), 2)
        with Workflow(restored["database"]) as recovered:
            self.assertEqual(recovered.report(), report)
            for expected in expected_draws:
                self.assertEqual(recovered.lookup(expected["game"], expected["draw"]), expected)
        for path, source_hash in originals.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), source_hash)
