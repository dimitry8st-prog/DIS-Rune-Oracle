from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest

from dis_oracle.cli import main
from dis_oracle.journal import Journal
from tests.test_combination_lab import protocol


class LabCLITests(unittest.TestCase):
    def call(self, args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(args)
        return code, json.loads(out.getvalue()) if out.getvalue() else None, err.getvalue()

    def test_synthetic_demo_round_trip_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "new-demo"
            args = ["lab-demo", "--directory", str(root)]
            code, value, _ = self.call(args)
            self.assertEqual(code, 0)
            self.assertEqual(value["provenance"], "SYNTHETIC")
            self.assertTrue(value["exact_replay"])
            self.assertEqual(value["summary"]["primary_contrast"]["complete_pairs"], 1)
            before = (root / "summary.json").read_bytes()
            self.assertEqual(self.call(args)[0], 2)
            self.assertEqual((root / "summary.json").read_bytes(), before)

    def test_protocol_and_empty_summary_through_public_cli(self):
        with tempfile.TemporaryDirectory() as d:
            p = protocol(); p.update(starts_at="2099-01-01T00:00:00Z", ends_at="2099-02-01T00:00:00Z")
            path, db = Path(d) / "protocol.json", Path(d) / "lab.sqlite"
            path.write_text(json.dumps(p))
            self.assertEqual(self.call(["lab-register", str(path), "--db", str(db)])[0], 0)
            code, value, _ = self.call(["lab-summary", "--study-id", p["study_id"], "--db", str(db)])
            self.assertEqual(code, 0)
            self.assertEqual(value["registered"], 0)
            self.assertEqual(value["unresolved"], 0)

    def test_missing_lab_database_not_created(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "missing.sqlite"
            code, _, _ = self.call(["lab-summary", "--study-id", "missing", "--db", str(db)])
            self.assertEqual(code, 2)
            self.assertFalse(db.exists())

    def test_duplicate_json_keys_rejected_before_registration(self):
        with tempfile.TemporaryDirectory() as d:
            path, db = Path(d) / "bad.json", Path(d) / "lab.sqlite"
            path.write_text('{"study_id":"A","study_id":"B"}')
            code, _, err = self.call(["lab-register", str(path), "--db", str(db)])
            self.assertEqual(code, 2)
            self.assertIn("duplicate JSON key", err)
            j = Journal(db)
            try:
                self.assertEqual(j.verify()["records"], 0)
            finally:
                j.close()
