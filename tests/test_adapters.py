from copy import deepcopy
import hashlib
import itertools
from pathlib import Path
import sqlite3
import tempfile
import unittest

from dis_oracle.adapters.runes import RuneSessions, catalog, read_rune
from dis_oracle.adapters.yijing import calculate, run as yijing_run
from dis_oracle.contracts import ContractError
from dis_oracle.engine import freeze
from dis_oracle.journal import Journal
from dis_oracle.router import compare
from tests.test_engine import event, card


class RuneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.path = Path(self.temp.name) / "runes.sqlite"
        self.sessions = RuneSessions(self.path)
        self.sessions.prepare("s", "synthetic-only")

    def tearDown(self):
        self.sessions.close(); self.temp.cleanup()

    def complete(self):
        for slot in (1, 2, 3): result = self.sessions.select("s", slot, 0)
        return result

    def test_closed_until_third_selection(self):
        initial = self.sessions.status("s")
        self.assertIsNone(initial["card"]); self.assertNotIn("manifest", initial)
        for slot in (1, 2):
            r = self.sessions.select("s", slot, 180)
            self.assertIsNone(r["card"]); self.assertNotIn("nonce", r)
        final = self.sessions.select("s", 3, 0)
        self.assertEqual(final["state"], "READING_FIXED")
        self.assertNotIn("manifest", final["card"]["raw_result"])

    def test_reveal_blocked_before_reading(self):
        for count in range(3):
            with self.assertRaises(ContractError): self.sessions.reveal("s")
            self.sessions.select("s", count + 1, 0)

    def test_manifest_unique_nonce_and_exact_hash(self):
        self.complete(); r = self.sessions.reveal("s")
        lines = r["manifest"].splitlines()
        self.assertEqual(len(lines), 27)
        self.assertEqual(len(lines[1].split("=")[1]), 32)
        self.assertFalse(r["manifest"].endswith("\n"))
        self.assertEqual(len({line.split("|")[1] for line in lines[2:]}), 25)
        self.assertEqual(hashlib.sha256(r["manifest"].encode()).hexdigest(), r["commitment"])

    def test_duplicate_and_invalid_selection_leave_state_unchanged(self):
        self.sessions.select("s", 1, 0); original = self.sessions.status("s")
        for slot, rotation in ((1, 0), (0, 0), (26, 0), (2, 90), (True, 0)):
            with self.assertRaises(ContractError): self.sessions.select("s", slot, rotation)
            self.assertEqual(original, self.sessions.status("s"))

    def test_prepare_repeat_and_restart_preserve_manifest(self):
        first = self.sessions.status("s")
        self.sessions.close(); self.sessions = RuneSessions(self.path)
        self.assertEqual(first, self.sessions.prepare("s", "synthetic-only"))
        with self.assertRaises(ContractError): self.sessions.prepare("s", "other-event")

    def test_completed_reading_cannot_be_redrawn(self):
        original = self.complete()
        with self.assertRaises(ContractError): self.sessions.select("s", 4, 0)
        self.assertEqual(original, self.sessions.status("s"))

    def test_rune_card_is_valid_without_forecast_vote(self):
        r = compare(event(), [self.complete()["card"]])
        self.assertEqual(r["procedural_coverage_percent"], 10)
        self.assertEqual(r["axes"]["primary"]["status"], "NO_COMPARABLE_DATA")

    def test_all_orientations_and_blank(self):
        meanings = catalog()
        for rune in meanings["runes"]:
            for base, rotation in itertools.product((0, 180), repeat=2):
                row = {"slot": 1, "rune_id": rune["rune_id"],
                       "base_orientation": base if rune["index"] else None}
                r = read_rune(row, rotation, meanings)
                if rune["index"] == 0:
                    self.assertIsNone(r["final_orientation"])
                else:
                    self.assertEqual(r["final_orientation"], (base + rotation) % 360)
                if rune["reversed"] is None:
                    self.assertFalse(r["reversed_reading"]); self.assertEqual(r["meaning"], rune["upright"])

    def test_nine_noninvertible_runes(self):
        noninvertible = {r["rune_id"] for r in catalog()["runes"] if r["index"] and r["reversed"] is None}
        self.assertEqual(noninvertible, {"gebo", "hagalaz", "nauthiz", "isa", "jera", "eihwaz", "sowilo", "ingwaz", "dagaz"})

    def test_commitment_tamper_stops_session(self):
        c = self.sessions.connection; c.execute("DROP TRIGGER rune_manifest_immutable")
        c.execute("UPDATE rune_sessions SET manifest=manifest || 'x'"); c.commit()
        with self.assertRaises(ContractError): self.sessions.select("s", 1, 0)

    def test_completed_card_and_manifest_updates_blocked(self):
        self.complete()
        for query in ("UPDATE rune_sessions SET card='{}'", "UPDATE rune_sessions SET manifest='x'",
                      "DELETE FROM rune_sessions"):
            with self.assertRaises(sqlite3.IntegrityError): self.sessions.connection.execute(query)


class YijingTests(unittest.TestCase):
    def test_all_four_line_types_and_moving_positions(self):
        r = calculate([[2,2,2],[2,2,3],[2,3,3],[3,3,3],[2,3,2],[3,2,3]])
        self.assertEqual(r["lines_bottom_up"], [6,7,8,9,7,8])
        self.assertEqual(r["moving_lines"], [1,4])
        self.assertEqual(r["transformed_lines_bottom_up"], [7,7,8,8,7,8])

    def test_all_eight_coin_combinations(self):
        counts = {6:0,7:0,8:0,9:0}
        for throw in itertools.product((2,3), repeat=3):
            result = calculate([list(throw)]*6); counts[result["lines_bottom_up"][0]] += 1
        self.assertEqual(counts, {6:1,7:3,8:3,9:1})

    def test_invalid_throws_rejected(self):
        for throws in ([], [[2,2,2]]*5, [[2,2,4]]*6, [[True,2,3]]*6, [[2,3]]*6):
            with self.assertRaises(ContractError): calculate(throws)

    def test_repeat_preserves_original_and_abstains(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = Journal(Path(tmp)/"yi.sqlite")
            try:
                original = yijing_run(j,"s","synthetic-only")
                self.assertEqual(original,yijing_run(j,"s","synthetic-only"))
                self.assertEqual(j.verify()["records"],1)
                self.assertEqual(original["status"],"ABSTAIN")
                self.assertEqual(compare(event(),[original])["axes"]["primary"]["comparison_coverage_percent"],0)
                with self.assertRaises(ContractError): yijing_run(j,"s","another-event")
            finally: j.close()

    def test_reported_throws_cannot_be_substituted(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = Journal(Path(tmp)/"yi.sqlite")
            try:
                yijing_run(j,"s","synthetic-only",[[2,2,2]]*6)
                with self.assertRaises(ContractError): yijing_run(j,"s","synthetic-only",[[3,3,3]]*6)
            finally: j.close()

    def test_card_event_binding(self):
        c=card("rune");c["inputs"]["event_id"]="different"
        from dis_oracle.contracts import digest
        c["input_hash"]=digest(c["inputs"])
        with self.assertRaises(ContractError): compare(event(),[c])

    def test_future_adapter_timestamp_rejected(self):
        c=card("rune");c["raw_result"]["generated_at"]="2098-01-01T00:00:00Z"
        with tempfile.TemporaryDirectory() as tmp:
            j=Journal(Path(tmp)/"run.sqlite")
            try:
                with self.assertRaises(ContractError): freeze(j,"test",event(),[c],frozen_at="2026-10-12T06:02:00Z")
                self.assertEqual(j.verify()["records"],0)
            finally: j.close()
