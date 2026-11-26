"""Synthetic migration tests. The private v136 archive is not part of the fixtures."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from dis_oracle.contracts import digest
from dis_oracle.workflow import Workflow


FIXED = "2026-01-02T09:00:00Z"
TARGET = "2026-01-02T10:00:00Z"
RECEIVED = "2026-01-03T10:00:00Z"
PICK = [[1, 2, 3, 4], [5, 6, 7, 8]]
CONTROL = [[9, 10, 11, 12], [13, 14, 15, 16]]


def forecast(game, draw, *, tie_break=None):
    arm = {"fields": CONTROL, "method_version": "synthetic-frequency-version"}
    if tie_break is not None:
        arm["tie_break"] = tie_break
    return {"game": game, "draw": draw, "fields": PICK, "random_control": CONTROL,
            "fixed_at": FIXED, "target_at_declared": TARGET, "frequency100_v1": arm}


def outcome(game, draw):
    return {"game": game, "draw": draw, "fields": PICK, "recorded_at": TARGET}


class ArchiveMigrationTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.workflow = Workflow(self.root / "ledger.sqlite3", _clock=lambda: RECEIVED)
        self.addCleanup(self.workflow.close)

    def archive(self, name, members, *, outcomes=(), summaries=()):
        archive = self.root / name
        with ZipFile(archive, "w") as zf:
            zf.writestr("Oracle/updates/20260102/latest-archive-state.json", json.dumps({
                "observations_ref": "20260102/history.json", "summary_refs": ["20260102/summary.json"],
            }))
            zf.writestr("Oracle/updates/20260102/history.json", json.dumps(list(outcomes)))
            zf.writestr("Oracle/updates/20260102/summary.json", json.dumps({"trials": list(summaries)}))
            for member, body in members.items():
                zf.writestr(member, body if isinstance(body, bytes) else json.dumps(body))
        return archive

    def test_joins_exact_identities_preserves_sources_and_round_trips_original_bytes(self):
        main = forecast("hunt", 5, tie_break="synthetic-hash")
        extra = forecast("four_of_twenty", 5, tie_break="synthetic-numeric-order")
        standalone = "Oracle/standalone_runs/other-game/numeric-selection.json"
        path = self.archive("combined.zip", {
            "Oracle/main/pick/numeric-selection.json": main,
            "Oracle/standalone_runs/duplicate/numeric-selection.json": main,
            standalone: extra,
            "Oracle/standalone_runs/other-game/private-runes.bin": b"original\x00runes\xff",
        }, outcomes=[outcome("hunt", 5), outcome("four_of_twenty", 5)])
        original = path.read_bytes()
        result = self.workflow.migrate(path)
        self.assertEqual((result["outcomes_added"], result["forecasts_added"]), (2, 2))
        self.assertEqual(result["archive_hash"], sha256(original).hexdigest())
        first = self.workflow.lookup("hunt", 5)
        self.assertEqual(len(first["forecast"]["archive_sources"]), 2)
        self.assertEqual(first["forecast"]["fixed_at"], FIXED)
        self.assertEqual(first["outcome"]["received_at"], RECEIVED)
        self.assertEqual(first["outcome"]["source_recorded_at"], TARGET)
        self.assertEqual(first["archive_outcome_sources"][0]["original_hash"], digest(outcome("hunt", 5)))
        other = self.workflow.lookup("four_of_twenty", 5)["forecast"]
        self.assertEqual(other["archive_sources"][0]["path"], standalone)
        with ZipFile(path) as zf:
            self.assertEqual(other["archive_sources"][0]["sha256"], sha256(zf.read(standalone)).hexdigest())
        before = self.workflow.verify()
        self.assertEqual(self.workflow.migrate(path)["state"], "ALREADY_IMPORTED")
        self.assertEqual(self.workflow.verify(), before)
        destination = self.root / "verified-original.zip"
        self.workflow.export_archive(result["archive_hash"], destination)
        self.assertEqual(destination.read_bytes(), original)
        self.assertEqual(path.read_bytes(), original)
        with self.assertRaises(FileExistsError):
            self.workflow.export_archive(result["archive_hash"], destination)
        self.assertEqual(destination.read_bytes(), original)

    def test_old_same_zip_marker_does_not_skip_standalone_and_retains_ledger_rows(self):
        old_row = forecast("hunt", 5, tie_break="synthetic-number")
        archive = self.archive("same.zip", {
            "Oracle/main/numeric-selection.json": old_row,
            "Oracle/standalone_runs/separate/numeric-selection.json": forecast("hunt", 6),
        }, outcomes=[outcome("hunt", 5)])
        archive_hash = sha256(archive.read_bytes()).hexdigest()
        with self.workflow.transaction():
            self.workflow._append("migration", "migration:" + archive_hash, {
                "archive_hash": archive_hash, "received_at": RECEIVED, "legacy_summaries": [],
                "outcomes": [], "cancellations": [], "forecasts": [{
                    "game": "hunt", "draw": 5, "target_at": TARGET, "fixed_at": FIXED,
                    "origin": "LEGACY_UNATTESTED", "original_hash": digest(old_row),
                    "methods": {"lottery-rune-hash-v2": {"state": "PICK", "fields": PICK}},
                }],
            })
        first = tuple(self.workflow.db.execute("SELECT * FROM workflow_events WHERE seq=1").fetchone())
        result = self.workflow.migrate(archive)
        self.assertEqual((result["forecasts_added"], result["forecasts_enriched"]), (1, 1))
        self.assertEqual(first, tuple(self.workflow.db.execute("SELECT * FROM workflow_events WHERE seq=1").fetchone()))
        arm = self.workflow.lookup("hunt", 5)["forecast"]["methods"]["frequency100-v1"]
        self.assertEqual(arm["tie_break"], "synthetic-number")

    def test_archive_cannot_deliver_outcome_to_a_current_forecast_before_target(self):
        self.workflow.clock = lambda: FIXED
        self.workflow.ingest("hunt", 4, PICK, "SYNTHETIC")
        self.workflow.forecast("hunt", 5, TARGET)
        archive = self.archive("early.zip", {}, outcomes=[outcome("four_of_twenty", 5), outcome("hunt", 5)])
        before = self.workflow.verify()
        with self.assertRaisesRegex(ValueError, "archive outcome hunt:5: outcome receipt precedes declared target"):
            self.workflow.migrate(archive)
        self.assertEqual(self.workflow.verify(), before)
        self.assertIsNone(self.workflow.lookup("four_of_twenty", 5)["outcome"])
        self.assertEqual(self.workflow.db.execute("SELECT count(*) FROM workflow_archives").fetchone()[0], 0)

        self.workflow.clock = lambda: TARGET
        self.assertEqual(self.workflow.migrate(archive)["outcomes_added"], 2)
        self.assertEqual(self.workflow.lookup("hunt", 5)["outcome"]["received_at"], TARGET)
        self.assertEqual(self.workflow.migrate(archive)["state"], "ALREADY_IMPORTED")

    def test_conflicting_forecast_or_outcome_does_not_change_chain_or_archive_storage(self):
        valid = self.archive("valid.zip", {"Oracle/main/numeric-selection.json": forecast("hunt", 5)},
                             outcomes=[outcome("hunt", 5)])
        self.workflow.migrate(valid)
        before = self.workflow.verify()
        for differing in ("fields", "fixed_at", "tie_break", "outcome"):
            with self.subTest(differing=differing):
                original = forecast("hunt", 5, tie_break="original-rule")
                conflicting = deepcopy(original)
                outcomes = [outcome("four_of_twenty", 100)]
                if differing == "fields":
                    conflicting["fields"] = CONTROL
                elif differing == "fixed_at":
                    conflicting["fixed_at"] = TARGET
                elif differing == "tie_break":
                    conflicting["frequency100_v1"]["tie_break"] = "different-rule"
                else:
                    outcomes.append({**outcome("hunt", 5), "fields": CONTROL})
                archive = self.archive("conflict.zip", {
                    "Oracle/main/numeric-selection.json": original,
                    "Oracle/standalone_runs/alternative/numeric-selection.json": conflicting,
                }, outcomes=outcomes)
                with self.assertRaisesRegex(ValueError, "archive (forecast|outcome) conflict hunt:5"):
                    self.workflow.migrate(archive)
                self.assertEqual(self.workflow.verify(), before)
                self.assertEqual(self.workflow.db.execute("SELECT count(*) FROM workflow_archives").fetchone()[0], 1)

    def test_frequency_variants_and_unknown_standalone_are_reconciled_without_picks(self):
        archives = {
            "Oracle/run-5/numeric-selection.json": forecast("hunt", 5, tie_break="declared-a"),
            "Oracle/run-6/numeric-selection.json": forecast("hunt", 6, tie_break="declared-b"),
            "Oracle/run-7/numeric-selection.json": forecast("hunt", 7),
            "Oracle/standalone_runs/unscored/report.json": {"game": "hunt", "draw": 8, "scores": [0, 1]},
            "Oracle/standalone_runs/unscored/auxiliary.json": b"not JSON",
        }
        path = self.archive("variants.zip", archives, outcomes=[outcome("hunt", i) for i in range(5, 9)],
                            summaries=[{"game": "hunt", "draw": 8, "scores": [0, 1]}])
        result = self.workflow.migrate(path)
        self.assertEqual(result["standalone_runs"][0]["state"], "NO_CANONICAL_NUMERIC_PICK")
        self.assertEqual(result["standalone_runs"][0]["identities"], [{"game": "hunt", "draw": 8}])
        self.assertEqual(len(result["standalone_runs"][0]["unreadable_json"]), 1)
        report = self.workflow.report()
        groups = [g for g in report["groups"] if g["method"] == "frequency100-v1"]
        self.assertEqual([(g["tie_break"], g["n"]) for g in groups], [("declared-a", 1), ("declared-b", 1)])
        self.assertEqual(report["trials"][2]["scores"]["frequency100-v1"], [0, 0])
        self.assertEqual({r["state"] for r in report["archive_reconciliation"]},
                         {"NO_CANONICAL_NUMERIC_PICK", "FREQUENCY_TIE_BREAK_UNDECLARED"})
        self.assertEqual(report["legacy_reconciliation"][0]["draw"], 8)
        self.assertIsNone(self.workflow.lookup("hunt", 8)["forecast"])

    def test_invalid_canonical_json_and_tampered_blob_are_rejected(self):
        invalid = self.archive("invalid.zip", {"Oracle/standalone_runs/bad/numeric-selection.json": b"not JSON"})
        with self.assertRaisesRegex(ValueError, "invalid archive JSON"):
            self.workflow.migrate(invalid)
        self.assertEqual(self.workflow.verify()["records"], 0)
        valid = self.archive("valid.zip", {"Oracle/standalone_runs/good/numeric-selection.json": forecast("hunt", 5)})
        self.workflow.migrate(valid)
        with self.assertRaisesRegex(sqlite3.IntegrityError, "append only"):
            self.workflow.db.execute("UPDATE workflow_archives SET contents=x'00'")
        self.workflow.db.execute("DROP TRIGGER workflow_archive_no_update")
        self.workflow.db.execute("UPDATE workflow_archives SET contents=x'00'")
        with self.assertRaisesRegex(ValueError, "archive bytes do not match SHA256"):
            self.workflow.verify()
