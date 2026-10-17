from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import itertools
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from dis_oracle.adapters.mo import MoSessions
from dis_oracle.adapters.qiuqian import QiuqianSessions, confirmation_from_sides, MAX_ATTEMPTS
from dis_oracle.contracts import ContractError, digest, now_iso, validate_cards
from dis_oracle.engine import freeze
from dis_oracle.journal import Journal, JournalError
from dis_oracle.router import compare
from tests.test_engine import event


class MechanicalSessionsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "mechanics.sqlite"
        self.mo = MoSessions(self.path)
        self.qq = QiuqianSessions(self.path)

    def tearDown(self):
        self.mo.close(); self.qq.close(); self.temp.cleanup()

    def valid_card(self, card):
        validate_cards([card], {})
        self.assertEqual(card["input_hash"], digest(card["inputs"]))
        self.assertEqual(card["status"], "ABSTAIN")
        self.assertEqual(card["claims"], [])
        self.assertEqual(card["raw_result"]["interpretation_status"], "ABSTAIN")
        self.assertEqual(card["raw_result"]["text_corpus"], "UNAVAILABLE")

    def rows(self):
        return self.mo.connection.execute("SELECT count(*) FROM mechanical_steps").fetchone()[0]

    def test_all_36_manual_mo_ordered_pairs_and_contracts(self):
        ids = set()
        for a, b in itertools.product(range(1, 7), repeat=2):
            card = self.mo.run(f"mo-{a}-{b}", "synthetic-only", mode="manual", first_throw=a, second_throw=b)
            self.valid_card(card)
            self.assertEqual(card["raw_result"]["combination_id"], f"mo-{a}-{b}")
            self.assertEqual(card["raw_result"]["procedure_status"], "OK")
            self.assertEqual(card["raw_result"]["syllable_mapping"], "UNAVAILABLE")
            ids.add(card["raw_result"]["combination_id"])
        self.assertEqual(len(ids), 36)

    def test_mo_digital_generation_and_restart_never_redraws(self):
        with patch("dis_oracle.adapters.mo.secrets.SystemRandom") as rng:
            rng.return_value.randint.side_effect = [6, 1]
            first = self.mo.run("s", "e", mode="digital")
            self.assertEqual(rng.return_value.randint.call_count, 2)
        self.mo.close(); self.mo = MoSessions(self.path)
        with patch("dis_oracle.adapters.mo.secrets.SystemRandom", side_effect=AssertionError("redraw")):
            self.assertEqual(first, self.mo.run("s", "e", mode="digital"))
            self.assertEqual(first, self.mo.status("s", "e"))
        self.assertEqual(self.rows(), 1)

    def test_mo_changed_inputs_mode_and_event_are_rejected(self):
        original = self.mo.run("s", "e", mode="manual", first_throw=1, second_throw=2)
        for kwargs in ({"mode": "manual", "first_throw": 2, "second_throw": 1}, {"mode": "digital"}):
            with self.assertRaises(ContractError):
                self.mo.run("s", "e", **kwargs)
        with self.assertRaises(ContractError):
            self.mo.run("s", "other", mode="manual", first_throw=1, second_throw=2)
        self.assertEqual(original, self.mo.status("s", "e"))
        self.assertEqual(self.rows(), 1)

    def test_mo_invalid_types_ranges_and_partial_inputs(self):
        for a, b in ((True, 2), (1, False), (1.0, 2), (1, 2.5), (0, 2), (7, 2),
                     (1, -1), (None, 2), (1, None), (None, None), ("1", 2)):
            with self.subTest(a=a, b=b), self.assertRaises(ContractError):
                self.mo.run("bad", "e", mode="manual", first_throw=a, second_throw=b)
        self.assertEqual(self.rows(), 0)

    def test_digital_manual_conflicts_rejected_before_rng(self):
        with patch("secrets.SystemRandom", side_effect=AssertionError("unexpected randomness")):
            for kwargs in ({"first_throw": 1}, {"second_throw": 2}, {"first_throw": 0}):
                with self.assertRaises(ContractError):
                    self.mo.run("s", "e", mode="digital", **kwargs)
            for kwargs in ({"stick_number": 42}, {"confirmation_result": "yin_bei"}):
                with self.assertRaises(ContractError):
                    self.qq.start("s", "e", mode="digital", **kwargs)
        self.assertEqual(self.rows(), 0)

    def test_all_100_digital_sticks_and_final_card_contract(self):
        with patch("dis_oracle.adapters.qiuqian.secrets.SystemRandom") as rng:
            for n in range(1, 101):
                rng.return_value.randint.return_value = n
                rng.return_value.choice.side_effect = [0, 1]
                initial = self.qq.start(f"stick-{n}", "e", mode="digital", max_attempts=1)
                self.valid_card(initial)
                card = self.qq.advance(f"stick-{n}", "e", "throw-1")
                self.valid_card(card)
                self.assertEqual(card["raw_result"]["stick_number"], n)
                self.assertEqual(card["raw_result"]["final_state"], "confirmed")
                self.assertEqual(card["inputs"]["temple"], None)
                self.assertIn("independent equiprobable", card["raw_result"]["simulation_assumption"])

    def test_all_four_digital_side_pairs_cover_confirmation_branches(self):
        expected = {(0, 0): "yin_bei", (0, 1): "sheng_bei", (1, 0): "sheng_bei", (1, 1): "xiao_bei"}
        for sides, outcome in expected.items():
            self.assertEqual(confirmation_from_sides(*sides), outcome)
            sid = str(sides)
            with patch("dis_oracle.adapters.qiuqian.secrets.SystemRandom") as rng:
                rng.return_value.randint.return_value = 42
                rng.return_value.choice.side_effect = sides
                self.qq.start(sid, "e", mode="digital", max_attempts=1)
                card = self.qq.advance(sid, "e", "throw")
            self.valid_card(card)
            raw = card["raw_result"]
            self.assertEqual(raw["attempts"][0]["sides"], list(sides))
            self.assertEqual(raw["confirmation"], outcome)
            self.assertEqual(raw["final_state"], "confirmed" if outcome == "sheng_bei" else "no_confirmation")

    def test_manual_refusal_is_saved_and_waits_without_new_stick(self):
        with patch("secrets.SystemRandom", side_effect=AssertionError("manual redraw")):
            card = self.qq.start("s", "e", mode="manual", stick_number=42,
                                 confirmation_result="yin_bei", max_attempts=3)
        self.valid_card(card)
        self.assertEqual(card["raw_result"]["final_state"], "pending")
        self.assertEqual(card["raw_result"]["attempts"][0]["confirmation"], "yin_bei")
        self.assertEqual(card["raw_result"]["stick_number"], 42)
        self.assertEqual(len(card["raw_result"]["attempts"]), 1)

    def test_manual_waiting_and_explicit_observations_until_confirmation(self):
        initial = self.qq.start("s", "e", mode="manual", stick_number=25, max_attempts=3)
        self.valid_card(initial)
        self.assertEqual(initial["raw_result"]["attempts"], [])
        self.assertEqual(initial["raw_result"]["procedure_status"], "PENDING")
        second = self.qq.confirm("s", "e", "one", "xiao_bei")
        final = self.qq.confirm("s", "e", "two", "sheng_bei")
        self.valid_card(second); self.valid_card(final)
        self.assertEqual(final["raw_result"]["final_state"], "confirmed")
        self.assertEqual([a["stick_number"] for a in final["raw_result"]["attempts"]], [25, 25])
        self.assertEqual([a["confirmation"] for a in final["raw_result"]["attempts"]], ["xiao_bei", "sheng_bei"])
        self.assertEqual(final["input_hash"], digest(final["inputs"]))
        self.assertEqual(len(final["inputs"]["requests"]), 3)

    def test_limit_means_total_attempts_not_retries(self):
        self.qq.start("s", "e", mode="manual", stick_number=100, max_attempts=3)
        for n in range(1, 4):
            card = self.qq.confirm("s", "e", str(n), "yin_bei")
            self.assertEqual(card["raw_result"]["final_state"], "pending" if n < 3 else "no_confirmation")
        self.assertEqual(len(card["raw_result"]["attempts"]), 3)
        self.valid_card(card)
        with self.assertRaises(ContractError):
            self.qq.confirm("s", "e", "fourth", "sheng_bei")

    def test_digital_limit_preserves_all_refusals_and_never_redraws_stick(self):
        with patch("dis_oracle.adapters.qiuqian.secrets.SystemRandom") as rng:
            rng.return_value.randint.return_value = 17
            rng.return_value.choice.side_effect = [0, 0, 1, 1, 0, 0]
            self.qq.start("s", "e", mode="digital", max_attempts=3)
            for n in range(1, 4):
                card = self.qq.advance("s", "e", str(n))
            self.assertEqual(rng.return_value.randint.call_count, 1)
            self.assertEqual(rng.return_value.choice.call_count, 6)
            with self.assertRaises(ContractError):
                self.qq.advance("s", "e", "fourth")
            self.assertEqual(rng.return_value.choice.call_count, 6)
        self.valid_card(card)
        self.assertEqual(card["raw_result"]["final_state"], "no_confirmation")
        self.assertEqual([a["confirmation"] for a in card["raw_result"]["attempts"]], ["yin_bei", "xiao_bei", "yin_bei"])
        self.assertEqual([a["stick_number"] for a in card["raw_result"]["attempts"]], [17, 17, 17])

    def test_zero_limit_and_conflicting_zero_limit_observation(self):
        card = self.qq.start("s", "e", mode="manual", stick_number=1, max_attempts=0)
        self.valid_card(card)
        self.assertEqual(card["raw_result"]["final_state"], "no_confirmation")
        self.assertEqual(card["raw_result"]["attempts"], [])
        with self.assertRaises(ContractError):
            self.qq.start("bad", "e", mode="manual", stick_number=2, max_attempts=0, confirmation_result="yin_bei")
        with patch("dis_oracle.adapters.qiuqian.secrets.SystemRandom") as rng:
            rng.return_value.randint.return_value = 100
            digital = self.qq.start("zero-digital", "e", mode="digital", max_attempts=0)
            self.assertEqual(digital["raw_result"]["stick_number"], 100)
            rng.return_value.choice.assert_not_called()

    def test_last_allowed_attempt_can_succeed(self):
        self.qq.start("s", "e", mode="manual", stick_number=1, max_attempts=2, confirmation_result="yin_bei")
        card = self.qq.confirm("s", "e", "last", "sheng_bei")
        self.assertEqual(card["raw_result"]["final_state"], "confirmed")
        self.assertEqual(len(card["raw_result"]["attempts"]), 2)

    def test_explicit_finish_does_not_invent_an_attempt(self):
        self.qq.start("s", "e", mode="manual", stick_number=42, confirmation_result="yin_bei")
        card = self.qq.finish("s", "e", "done")
        self.valid_card(card)
        self.assertEqual(card["raw_result"]["completion_reason"], "explicit_finish")
        self.assertEqual(len(card["raw_result"]["attempts"]), 1)
        self.assertEqual(card, self.qq.finish("s", "e", "done"))

    def test_restart_preserves_pending_and_each_idempotent_command(self):
        initial = self.qq.start("s", "e", mode="manual", stick_number=50)
        first = self.qq.confirm("s", "e", "first", "yin_bei")
        self.qq.close(); self.qq = QiuqianSessions(self.path)
        with patch("secrets.SystemRandom", side_effect=AssertionError("redraw")):
            self.assertEqual(first, self.qq.status("s", "e"))
            self.assertEqual(first, self.qq.confirm("s", "e", "first", "yin_bei"))
            self.assertEqual(initial, self.qq.start("s", "e", mode="manual", stick_number=50))
            final = self.qq.confirm("s", "e", "second", "sheng_bei")
        self.qq.close(); self.qq = QiuqianSessions(self.path)
        self.assertEqual(final, self.qq.confirm("s", "e", "second", "sheng_bei"))
        self.assertEqual(final, self.qq.status("s", "e"))
        self.assertEqual(self.rows(), 3)

    def test_digital_restart_does_not_resample_stick_or_sides(self):
        with patch("dis_oracle.adapters.qiuqian.secrets.SystemRandom") as rng:
            rng.return_value.randint.return_value = 99
            rng.return_value.choice.side_effect = [0, 0]
            initial = self.qq.start("s", "e", mode="digital")
            first = self.qq.advance("s", "e", "one")
        self.qq.close(); self.qq = QiuqianSessions(self.path)
        with patch("secrets.SystemRandom", side_effect=AssertionError("redraw")):
            self.assertEqual(initial, self.qq.start("s", "e", mode="digital"))
            self.assertEqual(first, self.qq.advance("s", "e", "one"))
        with patch("dis_oracle.adapters.qiuqian.secrets.SystemRandom") as rng:
            rng.return_value.choice.side_effect = [1, 0]
            card = self.qq.advance("s", "e", "two")
            rng.return_value.randint.assert_not_called()
        self.assertEqual(card["raw_result"]["stick_number"], 99)
        self.assertEqual(len(card["raw_result"]["attempts"]), 2)

    def test_qiuqian_changed_inputs_and_event_rejected_without_changes(self):
        original = self.qq.start("s", "e", mode="manual", stick_number=42, max_attempts=2)
        for kwargs in ({"mode": "manual", "stick_number": 43, "max_attempts": 2},
                       {"mode": "manual", "stick_number": 42, "max_attempts": 3}, {"mode": "digital"},
                       {"mode": "manual", "stick_number": 42, "max_attempts": 2, "confirmation_result": "yin_bei"}):
            with self.assertRaises(ContractError):
                self.qq.start("s", "e", **kwargs)
        with self.assertRaises(ContractError):
            self.qq.confirm("s", "other", "obs", "yin_bei")
        self.qq.confirm("s", "e", "obs", "yin_bei")
        with self.assertRaises(ContractError):
            self.qq.confirm("s", "e", "obs", "sheng_bei")
        self.assertEqual(original, self.qq.start("s", "e", mode="manual", stick_number=42, max_attempts=2))
        self.assertEqual(self.rows(), 2)

    def test_manual_and_digital_continuations_cannot_be_mixed(self):
        self.qq.start("m", "e", mode="manual", stick_number=42)
        self.qq.start("d", "e", mode="digital")
        with self.assertRaises(ContractError):
            self.qq.advance("m", "e", "x")
        with self.assertRaises(ContractError):
            self.qq.confirm("d", "e", "x", "yin_bei")
        self.assertEqual(self.rows(), 2)

    def test_qiuqian_invalid_sticks_limits_and_observations(self):
        for number in (None, True, False, 1.0, 42.5, "42", 0, -1, 101):
            with self.assertRaises(ContractError):
                self.qq.start("bad", "e", mode="manual", stick_number=number)
        for limit in (True, False, 3.0, "3", None, -1, MAX_ATTEMPTS + 1):
            with self.assertRaises(ContractError):
                self.qq.start("bad", "e", mode="manual", stick_number=1, max_attempts=limit)
        for result in (True, 1, "pending", "", [], {}):
            with self.assertRaises(ContractError):
                self.qq.start("bad", "e", mode="manual", stick_number=1, confirmation_result=result)
        self.assertEqual(self.rows(), 0)
        self.qq.start("s", "e", mode="manual", stick_number=1, max_attempts=MAX_ATTEMPTS)
        for result in (None, True, 0.5, "pending"):
            with self.assertRaises(ContractError):
                self.qq.confirm("s", "e", "bad", result)
        self.assertEqual(self.rows(), 1)

    def test_historical_mode_blocked_and_invalid_modes_and_ids_rejected(self):
        for mode in ("historical", "", None, True, 1, []):
            with self.assertRaises(ContractError):
                self.mo.run("s", "e", mode=mode)
            with self.assertRaises(ContractError):
                self.qq.start("s", "e", mode=mode)
        for sid, eid in (("", "e"), (" ", "e"), (True, "e"), ("s", ""), ("s", None)):
            with self.assertRaises(ContractError):
                self.mo.run(sid, eid, mode="digital")
        self.assertEqual(self.rows(), 0)

    def test_terminal_session_rejects_new_commands_and_reserved_ids(self):
        self.qq.start("s", "e", mode="manual", stick_number=1, confirmation_result="sheng_bei")
        for operation in (lambda: self.qq.confirm("s", "e", "x", "yin_bei"),
                          lambda: self.qq.advance("s", "e", "x"), lambda: self.qq.finish("s", "e", "x"),
                          lambda: self.qq.confirm("s", "e", "start", "yin_bei")):
            with self.assertRaises(ContractError):
                operation()
        with self.assertRaises(ContractError):
            self.qq.confirm("unknown", "e", "x", "yin_bei")
        self.assertEqual(self.rows(), 1)

    def test_cards_pass_router_and_engine_without_new_forecasts_or_weights(self):
        mo = self.mo.run("m", "synthetic-only", mode="manual", first_throw=1, second_throw=2)
        qq = self.qq.start("q", "synthetic-only", mode="manual", stick_number=1, confirmation_result="sheng_bei")
        result = compare(event(), [mo, qq])
        self.assertEqual(result["core_weight"], "0.10")
        self.assertEqual(result["procedural_coverage_percent"], 0)
        self.assertEqual(result["axes"]["primary"]["status"], "NO_COMPARABLE_DATA")
        with JournalContext(Path(self.temp.name) / "new-engine.sqlite") as journal:
            frozen = freeze(journal, "mechanics", event(), [mo, qq], frozen_at=now_iso())
            self.assertEqual(frozen["state"], "FROZEN")
        changed = deepcopy(qq)
        changed["inputs"]["temple"] = "invented procedure"
        with self.assertRaises(ContractError):
            validate_cards([changed], {})

    def test_returned_objects_cannot_mutate_stored_snapshots(self):
        first = self.qq.start("s", "e", mode="manual", stick_number=1)
        first["inputs"]["max_attempts"] = 999
        self.assertEqual(self.qq.status("s", "e")["inputs"]["max_attempts"], 3)

    def test_sql_update_delete_and_corruption_are_detected(self):
        self.mo.run("s", "e", mode="manual", first_throw=1, second_throw=2)
        for sql in ("UPDATE mechanical_steps SET card='{}'", "DELETE FROM mechanical_steps"):
            with self.assertRaises(sqlite3.IntegrityError):
                self.mo.connection.execute(sql)
            self.mo.connection.rollback()
        self.mo.connection.execute("DROP TRIGGER mechanical_no_update")
        self.mo.connection.execute("UPDATE mechanical_steps SET request='{}'")
        self.mo.connection.commit()
        with self.assertRaises(JournalError):
            self.mo.status("s", "e")

    def test_existing_engine_journal_is_not_migrated(self):
        path = Path(self.temp.name) / "engine.sqlite"
        journal = Journal(path)
        journal.append("old", {"preserve": True}); journal.close()
        before = path.read_bytes()
        with self.assertRaises(JournalError):
            MoSessions(path)
        self.assertEqual(path.read_bytes(), before)

    def test_concurrent_replay_does_not_draw_twice(self):
        def run():
            with MoSessions(self.path) as store:
                return store.run("parallel", "e", mode="digital")
        with patch("dis_oracle.adapters.mo.secrets.SystemRandom") as rng:
            rng.return_value.randint.side_effect = [2, 5]
            with ThreadPoolExecutor(max_workers=2) as pool:
                cards = list(pool.map(lambda _: run(), range(2)))
            self.assertEqual(rng.return_value.randint.call_count, 2)
        self.assertEqual(cards[0], cards[1])
        self.assertEqual(self.rows(), 1)

    def test_cli_restart_and_errors_are_real_processes(self):
        args = [sys.executable, "-m", "dis_oracle.adapters.mechanics_cli", "mo-run",
                "--db", str(self.path), "--session-id", "cli", "--event-id", "e", "--mode", "digital"]
        first = subprocess.run(args, capture_output=True, text=True)
        second = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads(first.stdout), json.loads(second.stdout))
        bad = subprocess.run(args + ["--first-throw", "1"], capture_output=True, text=True)
        self.assertEqual(bad.returncode, 2)
        self.assertEqual(bad.stdout, "")


class JournalContext:
    """Keep the existing Journal implementation untouched."""
    def __init__(self, path):
        self.journal = Journal(path)

    def __enter__(self):
        return self.journal

    def __exit__(self, *args):
        self.journal.close()


if __name__ == "__main__":
    unittest.main()
