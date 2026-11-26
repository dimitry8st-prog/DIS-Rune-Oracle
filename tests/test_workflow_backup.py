"""Recovery of synthetic workflow and standalone evidence snapshots."""
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dis_oracle.adapters.runes import RuneSessions
from dis_oracle.contracts import digest
from dis_oracle.journal import Journal
from dis_oracle.pipeline import Cycle
from dis_oracle import workflow_backup
from dis_oracle.workflow import Workflow, main


TEMPLATE = Path(__file__).resolve().parents[1] / "examples" / "workflow" / "manifest.json"
NUMBERS = [[1, 2, 3, 4], [5, 6, 7, 8]]


class WorkflowRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.source = self.root / "source" / "oracle.sqlite3"
        self.cycles = Path(str(self.source) + ".cycles")
        self.bundle = self.root / "backup"
        self.destination = self.root / "restored"
        self.w = self.enterContext(Workflow(self.source))
        self.w.ingest("hunt", 99, NUMBERS, "SYNTHETIC history")
        self.template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
        self.target = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
        self.later_target = (datetime.fromisoformat(self.target) + timedelta(hours=4)).isoformat()

    def predict(self, draw=100, workflow=None):
        workflow = self.w if workflow is None else workflow
        target = self.target if draw == 100 else self.later_target
        return workflow.forecast("hunt", draw, target, template=self.template)

    def test_backup_restores_joint_wal_and_cycle_state_without_redraw(self):
        prediction = self.predict()
        # Later cycle data extend the stored chain beyond the first forecast's prefix.
        append = self.w._append

        def fail_after_freeze(kind, key, payload):
            if kind == "forecast":
                raise OSError("synthetic interruption after cycle freeze")
            return append(kind, key, payload)

        with patch.object(self.w, "_append", side_effect=fail_after_freeze):
            with self.assertRaisesRegex(OSError, "interruption"):
                self.predict(101)
        with Cycle(self.cycles, "workflow-hunt-101") as source_cycle:
            unfinished_original = source_cycle.freeze()
            source_chain = source_cycle.journal.verify()
        # Record the outcome on a synthetic clock after the declared target.
        self.w.clock = lambda: (datetime.fromisoformat(self.target) + timedelta(hours=1)).isoformat()
        self.w.ingest("hunt", 100, NUMBERS, "SYNTHETIC outcome")
        public = self.source.parent / "standalone_runs" / "synthetic-public" / "cycle-v03.sqlite3"
        public_journal = Journal(public)
        try:
            public_journal.append("cycle:" + "a" * 64 + ":collected", {"cards": [{"core_id": "rune"}]})
            public_chain = public_journal.verify()
        finally:
            public_journal.close()
        evidence = public.parent / "original.json"
        raw = b'{"date":"2026-01-01T00:00:00Z", "method":"SYNTHETIC"}\n'
        evidence.write_bytes(raw)
        before = self.w.state()
        before_report = self.w.report()
        self.assertTrue(Path(str(self.source) + "-wal").exists())

        backup = self.w.backup(self.bundle)
        self.destination.mkdir()
        restored = Workflow.restore(self.bundle, self.destination)
        copied = self.destination / self.source.name
        self.assertEqual(backup["workflow_chain"], restored["workflow_chain"])
        self.assertEqual(backup["manifest_hash"], restored["manifest_hash"])
        self.assertEqual(restored["journal_chains"], {
            self.cycles.name + "/cycle-v03.sqlite3": source_chain,
            "standalone_runs/synthetic-public/cycle-v03.sqlite3": public_chain,
        })
        self.assertEqual((self.destination / evidence.relative_to(self.source.parent)).read_bytes(), raw)
        self.assertEqual(evidence.read_bytes(), raw)
        self.assertEqual(self.w.state(), before)
        self.assertEqual((self.bundle / workflow_backup.MANIFEST).stat().st_mode & 0o777, 0o600)
        self.assertEqual(copied.stat().st_mode & 0o777, 0o600)

        with Workflow(copied, _clock=self.w.clock) as workflow:
            self.assertEqual(workflow.state(), before)
            self.assertEqual(workflow.report(), before_report)
            with patch("secrets.SystemRandom", side_effect=AssertionError("existing forecast redrawn")):
                self.assertEqual(self.predict(workflow=workflow), prediction)
            # 101 has no main forecast. Its existing symbolic reading is reused;
            # only the as-yet uncommitted independent numeric control is generated.
            second = self.predict(101, workflow=workflow)
            self.assertEqual(second["methods"]["lottery-rune-hash-v2"]["original_report_hash"],
                             digest(unfinished_original))
        with Cycle(str(copied) + ".cycles", "workflow-hunt-101") as restored_cycle:
            self.assertEqual(restored_cycle.journal.verify(), source_chain)

    def test_restore_resumes_a_partially_selected_rune_session(self):
        original_select = RuneSessions.select

        def fail_after_first(store, session_id, slot, rotation):
            if store.status(session_id)["choices"]:
                raise OSError("synthetic interruption before second rune")
            return original_select(store, session_id, slot, rotation)

        with patch.object(RuneSessions, "select", fail_after_first):
            with self.assertRaisesRegex(OSError, "second rune"):
                self.predict()
        run_id = "workflow-hunt-100"
        session_id = "v03-" + digest([run_id, "rune"])
        relative = Path("private") / digest(run_id) / "rune.sqlite3"
        source = RuneSessions(self.cycles / relative)
        try:
            partial = source.status(session_id)
        finally:
            source.close()
        self.assertEqual(len(partial["choices"]), 1)

        self.w.backup(self.bundle)
        restored = Workflow.restore(self.bundle, self.destination)
        copied = restored["database"]
        restored_cycles = Path(copied + ".cycles")
        private = RuneSessions(restored_cycles / relative)
        try:
            self.assertEqual(private.status(session_id), partial)
        finally:
            private.close()

        with Workflow(copied) as work, patch("dis_oracle.adapters.runes.secrets.token_hex",
                                              side_effect=AssertionError("existing rune deck redrawn")):
            self.predict(workflow=work)
        with Cycle(restored_cycles, run_id) as cycle:
            rune = next(card for card in cycle.freeze()["frozen"]["raw_cards"] if card["core_id"] == "rune")
            self.assertEqual(rune["inputs"]["choices"][:1], partial["choices"])
            self.assertEqual(rune["inputs"]["commitment"], partial["commitment"])

    def test_changed_file_and_unsafe_manifest_reject_before_publication(self):
        standalone = self.source.parent / "standalone_runs"
        standalone.mkdir()
        (standalone / "frozen.json").write_text("{}", encoding="utf-8")
        self.w.backup(self.bundle)
        archived = self.bundle / "standalone_runs" / "frozen.json"
        archived.write_text("[]", encoding="utf-8")
        self.destination.mkdir()
        with self.assertRaisesRegex(ValueError, "digests"):
            Workflow.restore(self.bundle, self.destination)
        self.assertEqual(list(self.destination.iterdir()), [])
        self.assertEqual(list(self.root.glob(".workflow-snapshot-*")), [])

        path = self.bundle / workflow_backup.MANIFEST
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["database"] = "../outside.sqlite3"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "safe filename"):
            Workflow.restore(self.bundle, self.destination)
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_missing_cycle_binding_and_private_store_reject_full_backup(self):
        self.predict()
        private = next(self.cycles.glob("private/*/rune.sqlite3"))
        saved = private.read_bytes()
        private.unlink()
        with self.assertRaisesRegex(ValueError, "missing private rune"):
            self.w.backup(self.bundle)
        self.assertFalse(self.bundle.exists())
        private.write_bytes(saved)

        (self.cycles / "cycle-v03.sqlite3").unlink()
        with self.assertRaisesRegex(ValueError, "missing symbolic SQLite journal"):
            self.w.backup(self.bundle)
        self.assertFalse(self.bundle.exists())

    def test_failed_copy_and_occupied_destination_leave_data_unchanged(self):
        chain = self.w.verify()
        with patch.object(workflow_backup, "_copy_sqlite", side_effect=OSError("synthetic disk failure")):
            with self.assertRaisesRegex(OSError, "disk failure"):
                self.w.backup(self.bundle)
        self.assertFalse(self.bundle.exists())
        self.assertEqual(self.w.verify(), chain)
        self.assertEqual(list(self.root.glob(".workflow-snapshot-*")), [])
        self.w.backup(self.bundle)
        self.destination.mkdir()
        keep = self.destination / "keep"
        keep.write_bytes(b"keep")
        with self.assertRaisesRegex(ValueError, "new or empty"):
            Workflow.restore(self.bundle, self.destination)
        self.assertEqual(keep.read_bytes(), b"keep")
        with self.assertRaisesRegex(ValueError, "must be new"):
            self.w.backup(self.bundle)

    def test_symlink_and_destination_inside_symbolic_tree_are_rejected(self):
        acquired = self.source.parent / "standalone_runs"
        acquired.mkdir()
        self.assertFalse(self.bundle.exists())
        with self.assertRaisesRegex(ValueError, "outside"):
            self.w.backup(acquired / "nested")
        (acquired / "linked.sqlite3").symlink_to(self.source)
        with self.assertRaisesRegex(ValueError, "symbolic link"):
            self.w.backup(self.bundle)
        self.assertFalse(self.bundle.exists())
        self.assertFalse((acquired / "nested").exists())

    def test_cli_restores_legacy_file_and_refuses_nonexistent_backup_source(self):
        missing = self.root / "nonexistent.sqlite3"
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["--db", str(missing), "backup", str(self.bundle)]), 2)
        self.assertIn("source database does not exist", output.getvalue())
        self.assertFalse(missing.exists())
        legacy = self.root / "legacy.sqlite3"
        chain = self.w.backup(legacy)
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["restore", str(legacy), str(self.destination)]), 0)
        restored = json.loads(output.getvalue())
        self.assertEqual(restored["scope"], "DATABASE_ONLY")
        self.assertEqual(restored["workflow_chain"], chain)
        self.assertEqual(restored["journal_chains"], {})
        with Workflow(restored["database"]) as copied:
            self.assertEqual(copied.state(), self.w.state())


if __name__ == "__main__":
    unittest.main()
