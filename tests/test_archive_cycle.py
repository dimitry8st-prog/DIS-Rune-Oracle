"""Native symbolic journal checks against synthetic source data."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from dis_oracle.archive_cycle import LOTTERY_METHOD, cycle_numeric_records, read_cycle_database
from dis_oracle.journal import Journal


REGISTERED = "2026-01-01T10:00:00Z"
TARGET = "2026-01-01T11:00:00Z"
PLAN = {
    "game": "hunt", "draw": 11999, "target_at": TARGET, "method_version": LOTTERY_METHOD,
    "control_rule": "uniform without replacement: four distinct integers 1..20 in each of two fields",
}


class ArchiveCycleTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.path = root / "cycle-v03.sqlite3"
        self.journal = Journal(self.path)
        self.addCleanup(self.journal.close)
        self.prefix = "cycle:synthetic"
        self.numeric_key = f"{self.prefix}:{LOTTERY_METHOD}"
        self.selection = {
            **PLAN,
            "state": "LOTTERY_NUMERIC_FIXED", "registered_at": REGISTERED, "fixed_at": REGISTERED,
            "method_fields": [[1, 2, 3, 4], [5, 6, 7, 8]],
            "control_fields": [[9, 10, 11, 12], [13, 14, 15, 16]],
        }

    def write_selection(self, *, plan=PLAN):
        self.journal.append(f"{self.prefix}:registered", {
            "manifest": {"lottery_plan": plan, "provenance": "SYNTHETIC"},
            "registered_at": REGISTERED,
        })
        self.journal.append(self.numeric_key, self.selection)

    def test_native_export_and_database_recover_same_literal_payload(self):
        self.write_selection()
        exported = self.journal.export()
        self.assertEqual(read_cycle_database(self.path.read_bytes()), exported)
        self.assertEqual(cycle_numeric_records(exported), [(self.numeric_key, self.selection)])

    def test_sqlite_wal_preserves_committed_selection(self):
        journal = self.journal.connection
        journal.execute("PRAGMA journal_mode=WAL")
        journal.execute("PRAGMA wal_autocheckpoint=0")
        self.write_selection()
        rows = read_cycle_database(
            self.path.read_bytes(), self.path.with_name(self.path.name + "-wal").read_bytes(),
        )
        self.assertEqual(cycle_numeric_records(rows), [(self.numeric_key, self.selection)])

    def test_corrupt_chain_is_rejected(self):
        self.write_selection()
        changed = deepcopy(self.journal.export())
        changed[-1]["payload"]["draw"] += 1
        with self.assertRaisesRegex(ValueError, "chain verification failed"):
            cycle_numeric_records(changed)

    def test_verified_chain_without_matching_registered_draw_is_rejected(self):
        self.write_selection(plan=dict(PLAN, draw=PLAN["draw"] + 1))
        with self.assertRaisesRegex(ValueError, "does not match its registered plan"):
            cycle_numeric_records(self.journal.export())
