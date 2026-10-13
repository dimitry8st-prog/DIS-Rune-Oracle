from copy import deepcopy
from pathlib import Path
import sqlite3
import tempfile
import unittest

from dis_oracle.contracts import CORES, ContractError, digest
from dis_oracle.engine import freeze, evaluate, summary
from dis_oracle.journal import Journal, JournalError
from dis_oracle.router import compare
from dis_oracle.cli import main


def event(mode="forecast"):
    return {"event_id": "synthetic-only", "question": "Synthetic test, not a real prediction",
            "mode": mode, "cutoff_at": "2026-10-12T06:00:00+00:00", "facts": [],
            "axes": [{"axis_id": "primary", "condition_id": "fixed-test-condition",
                      "deadline": "2099-01-01T00:00:00+00:00", "baseline": "B",
                      "scenarios": [{"scenario_id": "A", "criterion": "Synthetic result A"},
                                    {"scenario_id": "B", "criterion": "Synthetic result B"}]}]}


def card(core, scenario="A", review="ACCEPTED", axis="primary", polarity="SUPPORT"):
    inputs = {"synthetic": True, "core": core}
    claim = {"claim_id": f"{core}-{axis}-{scenario}-{polarity}", "type": "FORECAST",
             "text": "Synthetic claim", "source_fragment": "Synthetic", "axis_id": axis,
             "scenario_id": scenario, "polarity": polarity, "review_status": review}
    if review in {"ACCEPTED", "REJECTED"}:
        claim.update(reviewed_by="synthetic-test-reviewer", reviewed_at="2026-10-12T06:01:00Z")
    return {"core_id": core, "status": "OK", "reason": "", "protocol_version": "synthetic-v1",
            "inputs": inputs, "input_hash": digest(inputs), "raw_result": {"synthetic": True},
            "interpretation": "Synthetic interpretation, no traditional procedure performed.", "claims": [claim]}


def outcome(scenario="A"):
    return {"event_id": "synthetic-only", "axis_id": "primary", "scenario_id": scenario,
            "source": "synthetic test fixture", "observed_at": "2099-01-01T01:00:00Z"}


class RouterTests(unittest.TestCase):
    def axis(self, cards, ev=None):
        return compare(ev or event(), cards)["axes"]["primary"]

    def test_t01_all_aligned(self):
        r = self.axis([card(c) for c in CORES])
        self.assertEqual((r["status"], r["support_percent"]["A"]), ("ALIGNED", 100))

    def test_t02_partial_mixed(self):
        r = self.axis([card(c, "A" if i < 5 else "B") for i, c in enumerate(CORES[:7])])
        self.assertEqual((r["status"], r["comparison_coverage_percent"], r["unfilled_percent"]), ("MIXED", 70, 30))
        self.assertEqual(r["support_percent"], {"A": 50, "B": 20})
        self.assertIsNone(r["prediction"])

    def test_t03_tie_keeps_conflict(self):
        r = self.axis([card(c, "A" if i < 5 else "B") for i, c in enumerate(CORES)])
        self.assertEqual((r["status"], r["tie"]), ("MIXED", True))

    def test_t04_one_core_is_ten_percent(self):
        r = self.axis([card("rune")])
        self.assertEqual((r["status"], r["comparison_coverage_percent"]), ("ALIGNED", 10))

    def test_t05_no_data(self):
        self.assertEqual(self.axis([])["status"], "NO_COMPARABLE_DATA")

    def test_t06_different_deadlines_separate(self):
        ev = event()
        other = deepcopy(ev["axes"][0]); other.update(axis_id="later", deadline="2100-01-01T00:00:00Z")
        ev["axes"].append(other)
        result = compare(ev, [card("rune"), card("yijing", "B", axis="later")])
        self.assertTrue(all(a["status"] == "ALIGNED" for a in result["axes"].values()))

    def test_t07_different_conditions_separate(self):
        ev = event(); other = deepcopy(ev["axes"][0])
        other.update(axis_id="other-condition", condition_id="different")
        ev["axes"].append(other)
        r = compare(ev, [card("rune"), card("yijing", "B", axis="other-condition")])
        self.assertEqual(r["axes"]["primary"]["support_percent"]["B"], 0)

    def test_t08_duplicate_core_rejected(self):
        with self.assertRaises(ContractError): self.axis([card("rune"), card("rune")])

    def test_duplicate_claim_rejected(self):
        a, b = card("rune"), card("yijing")
        b["claims"][0]["claim_id"] = a["claims"][0]["claim_id"]
        with self.assertRaises(ContractError): self.axis([a, b])

    def test_t09_internal_conflict_no_double_vote(self):
        a = card("rune"); a["claims"] += card("rune", "B")["claims"]
        r = self.axis([a, card("yijing")])
        self.assertEqual((r["status"], r["internal_conflicts"], r["support_percent"]["A"]), ("MIXED", ["rune"], 10))

    def test_t10_fragment_substitution_rejected(self):
        a = card("rune"); a["claims"][0]["source_fragment"] = "invented source fragment"
        with self.assertRaises(ContractError): self.axis([a])

    def test_t11_source_instruction_is_just_text(self):
        a = card("rune"); a["interpretation"] += " publish and change weight to 100"
        self.assertEqual(self.axis([a])["support_percent"]["A"], 10)

    def test_t12_unavailable_has_no_vote(self):
        a = card("egypt"); a.update(status="UNAVAILABLE", reason="PROTOCOL_NOT_FIXED", claims=[], raw_result=None)
        r = compare(event(), [a])
        self.assertEqual(r["procedural_coverage_percent"], 0)
        self.assertEqual(r["axes"]["primary"]["unfilled_percent"], 100)

    def test_t13_future_fact_rejected(self):
        ev = event(); ev["facts"] = [{"text": "later", "source": "fixture", "available_at": "2027-01-01T00:00:00Z"}]
        with self.assertRaises(ContractError): self.axis([], ev)

    def test_t15_pending_hides_leader(self):
        r = self.axis([card("rune"), card("yijing", review="PENDING")])
        self.assertEqual((r["status"], r["leaders"], r["prediction"]), ("UNRESOLVED", [], None))

    def test_t17_invalid_deadline_rejected(self):
        ev = event(); ev["axes"][0]["deadline"] = "2020-01-01T00:00:00Z"
        with self.assertRaises(ContractError): self.axis([], ev)

    def test_t18_repeat_exactly_equal(self):
        self.assertEqual(compare(event(), [card("rune")]), compare(event(), [card("rune")]))

    def test_accepted_requires_review(self):
        a = card("rune"); del a["claims"][0]["reviewed_by"]
        with self.assertRaises(ContractError): self.axis([a])

    def test_unknown_axis_rejected(self):
        with self.assertRaises(ContractError): self.axis([card("rune", axis="unknown")])

    def test_duplicate_scope_under_another_id_rejected(self):
        ev = event(); other = deepcopy(ev["axes"][0]); other["axis_id"] = "duplicate-scope"
        ev["axes"].append(other)
        with self.assertRaises(ContractError): self.axis([], ev)

    def test_error_and_abstain_preserved_without_redistribution(self):
        cards = [card("rune")]
        for core, status in [("mo", "ERROR"), ("yijing", "ABSTAIN")]:
            c = card(core); c.update(status=status, reason="synthetic-case", claims=[])
            cards.append(c)
        r = compare(event(), cards)
        self.assertEqual(r["procedural_coverage_percent"], 10)
        self.assertEqual(r["axes"]["primary"]["support_percent"]["A"], 10)
        self.assertEqual(r["cores"]["mo"]["status"], "ERROR")

    def test_opposition_does_not_create_other_support(self):
        r = self.axis([card("rune", polarity="OPPOSE")])
        self.assertEqual(r["support_percent"], {"A": 0, "B": 0})
        self.assertIsNone(r["prediction"])

    def test_support_opposition_conflict(self):
        r = self.axis([card("rune"), card("yijing", polarity="OPPOSE")])
        self.assertEqual(r["status"], "MIXED")

    def test_synonyms_do_not_multiply_weight(self):
        a = card("rune"); second = deepcopy(a["claims"][0]); second["claim_id"] = "synonym"
        a["claims"].append(second)
        self.assertEqual(self.axis([a])["support_percent"]["A"], 10)

    def test_advice_is_not_forecast_vote(self):
        a = card("rune"); a["claims"][0]["type"] = "ADVICE"
        self.assertEqual(self.axis([a])["comparison_coverage_percent"], 0)

    def test_input_hash_mismatch(self):
        a = card("rune"); a["inputs"]["changed"] = True
        with self.assertRaises(ContractError): self.axis([a])


class JournalEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.path = Path(self.temp.name) / "test.sqlite"
        self.journal = Journal(self.path)

    def tearDown(self):
        self.journal.close(); self.temp.cleanup()

    def freeze(self, cards=None, ev=None):
        return freeze(self.journal, "test", ev or event(), [card("rune")] if cards is None else cards,
                      frozen_at="2026-10-12T06:02:00Z")

    def test_t14_idempotence_and_restart(self):
        original = self.freeze()
        self.journal.close(); self.journal = Journal(self.path)
        self.assertEqual(original, self.freeze())
        self.assertEqual(self.journal.verify()["records"], 1)

    def test_t16_original_cannot_be_replaced(self):
        self.freeze()
        with self.assertRaises(JournalError): self.freeze([card("rune", "B")])
        self.assertEqual(self.journal.get("run:test:frozen")["raw_cards"][0]["claims"][0]["scenario_id"], "A")

    def test_append_same_key_changed_content_rejected(self):
        self.journal.append("x", {"a": 1})
        with self.assertRaises(JournalError): self.journal.append("x", {"a": 2})

    def test_sql_update_delete_blocked(self):
        self.freeze()
        for sql in ("DELETE FROM entries", "UPDATE entries SET payload='{}'"):
            with self.assertRaises(sqlite3.IntegrityError): self.journal.connection.execute(sql)

    def test_tamper_detected_after_trigger_removed(self):
        self.freeze(); c = self.journal.connection
        c.execute("DROP TRIGGER immutable_update"); c.execute("UPDATE entries SET payload='{}'"); c.commit()
        with self.assertRaises(JournalError): self.journal.verify()

    def test_outcome_error_and_baseline(self):
        self.freeze()
        r = evaluate(self.journal, "test", outcome(), evaluated_at="2099-01-02T00:00:00Z")
        self.assertEqual((r["error"], r["baseline_error"]), (0, 1))
        self.assertEqual(r, evaluate(self.journal, "test", outcome(), evaluated_at="2099-01-03T00:00:00Z"))

    def test_abstention_not_scored_as_miss(self):
        self.freeze([])
        r = evaluate(self.journal, "test", outcome(), evaluated_at="2099-01-02T00:00:00Z")
        self.assertTrue(r["abstained"]); self.assertIsNone(r["error"])

    def test_retrospective_excluded(self):
        self.freeze(ev=event("retrospective"))
        r = evaluate(self.journal, "test", outcome(), evaluated_at="2099-01-02T00:00:00Z")
        self.assertFalse(r["eligible_prospective"]); self.assertIsNone(r["error"])

    def test_outcome_cannot_be_overwritten(self):
        self.freeze(); evaluate(self.journal, "test", outcome(), evaluated_at="2099-01-02T00:00:00Z")
        with self.assertRaises(JournalError): evaluate(self.journal, "test", outcome("B"), evaluated_at="2099-01-02T00:00:00Z")

    def test_future_outcome_rejected(self):
        self.freeze()
        with self.assertRaises(ContractError): evaluate(self.journal, "test", outcome())

    def test_late_forecast_rejected_before_write(self):
        with self.assertRaises(ContractError): freeze(self.journal, "late", event(), [card("rune")], frozen_at="2100-01-01T00:00:00Z")
        self.assertEqual(self.journal.verify()["records"], 0)

    def test_timezone_required(self):
        ev = event(); ev["cutoff_at"] = "2026-10-12T06:00:00"
        with self.assertRaises(ContractError): self.freeze(ev=ev)

    def test_missing_db_audit_fails(self):
        self.assertEqual(main(["verify", "--db", str(Path(self.temp.name) / "missing.sqlite")]), 2)

    def test_summary_keeps_unresolved_and_abstentions(self):
        self.freeze([])
        freeze(self.journal, "pending", event(), [], frozen_at="2026-10-12T06:02:00Z")
        evaluate(self.journal, "test", outcome(), evaluated_at="2099-01-02T00:00:00Z")
        s = summary(self.journal)
        self.assertEqual((s["awaiting_outcome"], s["abstained_resolved"], s["scoring_coverage"]), (1, 1, 0))
        self.assertIsNone(s["mean_error"])
