from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dis_oracle import combination_lab as lab
from dis_oracle.calendar_context import build_context
from dis_oracle.contracts import ContractError, digest
from dis_oracle.engine import freeze as freeze_source
from dis_oracle.journal import Journal, JournalError


REG = "2026-11-01T10:00:00Z"
START = "2026-11-01T10:01:00Z"
CUTOFF = "2026-11-01T10:02:00Z"
READING = "2026-11-01T10:03:00Z"
SOURCE = "2026-11-01T10:04:00Z"
FREEZE = "2026-11-01T10:05:00Z"
TARGET = "2026-11-01T11:00:00Z"
RESOLVE = "2026-11-01T11:05:00Z"


def protocol():
    return {"schema_version": lab.VERSION, "study_id": "SYNTHETIC-lab", "provenance": "SYNTHETIC",
            "game": "hunt", "starts_at": START, "ends_at": "2026-11-01T12:00:00Z", "sample_size": 2,
            "east_cores": ["yijing"], "calendar_profiles": ["japanese_rokuyo"],
            "east_sources": {"yijing": {"corpus_version": "SYNTHETIC-only", "corpus_sha256": "a" * 64,
                                        "source_ref": "https://example.org/SYNTHETIC-not-a-traditional-reading"}},
            "excluded_draws": [999]}


def source(journal, draw=1000):
    event = {"event_id": f"SYNTHETIC-lab-target-{draw}", "question": "Synthetic author mappings only", "mode": "forecast",
             "cutoff_at": CUTOFF, "axes": [{"axis_id": "target", "condition_id": "synthetic-binary",
                "deadline": TARGET, "scenarios": [{"scenario_id": "A", "criterion": "Synthetic A"},
                {"scenario_id": "B", "criterion": "Synthetic B"}], "baseline": "B"}], "facts": []}
    cards = []
    for core in ("rune", "yijing"):
        inputs = {"event_id": event["event_id"]}
        raw = {"generated_at": READING}
        if core == "rune":
            raw.update(commitment="SYNTHETIC", positions=[
                {"rune_id": "sowilo", "final_orientation": 0},
                {"rune_id": "eihwaz", "final_orientation": 180},
                {"rune_id": "gebo", "final_orientation": 0}])
        else:
            raw["text_corpus"] = protocol()["east_sources"][core]
        card = {"core_id": core, "status": "OK", "reason": "", "protocol_version": "SYNTHETIC-v1",
                "inputs": inputs, "input_hash": digest(inputs), "raw_result": raw,
                "interpretation": "SYNTHETIC fixture only", "claims": []}
        if core == "yijing":
            card["claims"] = [{"claim_id": "synthetic-east", "type": "FORECAST", "text": "SYNTHETIC",
                "source_fragment": "SYNTHETIC", "axis_id": "target", "scenario_id": "A", "polarity": "SUPPORT",
                "review_status": "ACCEPTED", "reviewed_by": "SYNTHETIC-reviewer", "reviewed_at": SOURCE}]
        cards.append(card)
    frozen = freeze_source(journal, f"SYNTHETIC-source-{draw}", event, cards, frozen_at=SOURCE)
    config = {"schema_version": "rune-calendar-context-v1", "event_at": TARGET, "timezone": "Europe/Moscow",
        "day_boundary": "civil_midnight", "profiles": {"japanese_rokuyo": {
            "calendar_date": "2026-11-01", "source_ref": "https://example.org/SYNTHETIC-correlation",
            "source_locator": "SYNTHETIC date, not a real lunar correlation", "available_at": CUTOFF,
            "lunar_month": 5, "lunar_day": 1, "is_leap_month": False}}}
    snapshot = build_context(config, event, SOURCE)
    return {"state": "ORIGINAL_REPORT", "pipeline_version": "integrated-cycle-v0.3",
            "registration_hash": "SYNTHETIC", "review_hash": "SYNTHETIC", "frozen": frozen,
            "calendar_context": {"relation": "CULTURAL_CONTEXT_ONLY", "snapshot": snapshot,
                "snapshot_hash": digest(snapshot), "rune_binding": {"status": "BOUND", "core_id": "rune",
                    "card_input_hash": cards[0]["input_hash"], "procedure_commitment": "SYNTHETIC"}}}


def request(original, draw=1000):
    return {"game": "hunt", "draw": draw, "target_at": TARGET, "original": deepcopy(original),
            "history": [{"game": "hunt", "draw": n, "fields": [[1, 2, 3, 4], [5, 6, 7, 8]],
                         "available_at": REG, "source": "SYNTHETIC fixture"} for n in range(978, 1000)]}


class CombinationLabTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.db = Journal(Path(self.tmp.name) / "lab.sqlite")
        self.addCleanup(self.db.close)
        with patch.object(lab, "now_iso", return_value=REG):
            lab.register(self.db, protocol())
        self.original = source(self.db)

    def freeze(self, value=None):
        with patch.object(lab, "now_iso", return_value=FREEZE):
            return lab.freeze(self.db, "SYNTHETIC-lab", value or request(self.original))

    def resolve(self, draw=1000):
        value = {"game": "hunt", "draw": draw, "fields": [[1, 11, 16, 18], [11, 16, 18, 19]],
                 "observed_at": TARGET, "source": "SYNTHETIC outcome"}
        with patch.object(lab, "now_iso", return_value=RESOLVE):
            return lab.evaluate(self.db, "SYNTHETIC-lab", value)

    def test_all_arms_frozen_once_and_source_unchanged(self):
        before = deepcopy(self.original)
        result = self.freeze()
        self.assertEqual(list(result["arms"]), list(lab.ARMS))
        self.assertTrue(all(result["arms"][x]["fields"] for x in lab.ARMS))
        with patch.object(lab.secrets, "SystemRandom", side_effect=AssertionError("redraw")):
            self.assertEqual(self.freeze(), result)
        self.assertEqual(self.original, before)
        self.assertEqual(result["arms"]["frequency20"]["fields"], [[1, 2, 3, 4], [5, 6, 7, 8]])
        self.assertNotIn(999, [x["draw"] for x in result["arms"]["frequency20"]["window"]])

    def test_legacy_A_mapping_matches_known_original(self):
        # Historic target47272 used exactly these ordered rune positions.
        r = request(self.original, draw=47272)
        result = self.freeze(r)
        self.assertEqual(result["arms"]["A"]["fields"], [[11, 13, 16, 18], [11, 16, 18, 19]])

    def test_missing_east_not_imputed_from_calendar_or_runes(self):
        r = request(self.original)
        card = r["original"]["frozen"]["raw_cards"][1]
        card.update(status="ABSTAIN", reason="CORPUS_UNAVAILABLE", claims=[])
        f = r["original"]["frozen"]
        f["input_hash"] = digest({"event": f["event"], "cards": f["raw_cards"], "engine_version": f["engine_version"]})
        result = self.freeze(r)
        self.assertEqual(result["arms"]["C"]["status"], "ABSTAIN")
        self.assertEqual(result["arms"]["D"]["fields"], None)
        self.assertIsNotNone(result["arms"]["B"]["fields"])

    def test_missing_calendar_and_short_history_remain_null(self):
        r = request(self.original); del r["original"]["calendar_context"]; r["history"] = []
        result = self.freeze(r)
        self.assertEqual([result["arms"][a]["fields"] for a in ("B", "D", "frequency20")], [None] * 3)

    def test_late_or_changed_protocol_rejected(self):
        p = protocol(); p["sample_size"] = 3
        with self.assertRaises(JournalError): lab.register(self.db, p)
        p["study_id"] = "late"
        with patch.object(lab, "now_iso", return_value=FREEZE), self.assertRaises(ContractError):
            lab.register(self.db, p)

    def test_changed_request_and_outcome_rejected(self):
        self.freeze()
        r = request(self.original); r["history"][0]["source"] = "changed"
        with self.assertRaises(JournalError): self.freeze(r)
        resolved = self.resolve()
        bad = deepcopy(resolved["outcome"]); bad["fields"][0] = [2, 3, 4, 5]
        with self.assertRaises(JournalError): lab.evaluate(self.db, "SYNTHETIC-lab", bad)

    def test_validation_before_randomness(self):
        cases = []
        r = request(self.original); r["history"].append(deepcopy(r["history"][0])); cases.append(r)
        r = request(self.original); r["history"][0]["draw"] = 1000; cases.append(r)
        r = request(self.original); r["history"][0]["available_at"] = FREEZE; cases.append(r)
        r = request(self.original); r["original"]["calendar_context"]["snapshot_hash"] = "bad"; cases.append(r)
        r = request(self.original); r["original"]["frozen"]["raw_cards"][0]["inputs"]["event_id"] = "other"; cases.append(r)
        before = self.db.verify()
        for r in cases:
            with self.subTest(r=r), patch.object(lab.secrets, "SystemRandom", side_effect=AssertionError("RNG before validation")), self.assertRaises(ContractError):
                self.freeze(r)
        self.assertEqual(self.db.verify(), before)

    def test_closed_target_and_old_source_cannot_be_registered(self):
        with patch.object(lab, "now_iso", return_value=TARGET), self.assertRaises(ContractError):
            lab.freeze(self.db, "SYNTHETIC-lab", request(self.original))
        r = request(self.original); r["original"]["frozen"]["frozen_at"] = "2026-11-01T09:59:00Z"
        with self.assertRaises(ContractError): self.freeze(r)

    def test_summary_tracks_pending_abstention_and_complete_pairs(self):
        r = request(self.original); del r["original"]["calendar_context"]
        self.freeze(r); evaluation = self.resolve()
        self.assertIsNone(evaluation["scores"]["D"]["total"])
        self.freeze(request(source(self.db, 1001), draw=1001))
        s = lab.summary(self.db, "SYNTHETIC-lab")
        self.assertEqual((s["registered"], s["resolved"], s["unresolved"]), (2, 1, 1))
        self.assertEqual(s["arms"]["D"]["abstained"], 1)
        self.assertEqual(s["primary_contrast"]["complete_pairs"], 0)
        self.resolve(1001)
        self.assertEqual(lab.summary(self.db, "SYNTHETIC-lab")["primary_contrast"]["complete_pairs"], 1)

    def test_sample_cap_and_duplicate_target_across_studies(self):
        self.freeze()
        with self.assertRaises(ContractError): self.freeze(request(self.original, draw=1001))
        self.freeze(request(source(self.db, 1001), draw=1001))
        with self.assertRaises(ContractError): self.freeze(request(self.original, draw=1002))

    def test_outcome_timing_and_field_boundaries(self):
        t = self.freeze()
        outcome = {"game": "hunt", "draw": 1000, "fields": deepcopy(t["arms"]["A"]["fields"]),
                   "observed_at": TARGET, "source": "SYNTHETIC"}
        with patch.object(lab, "now_iso", return_value=FREEZE), self.assertRaises(ContractError):
            lab.evaluate(self.db, "SYNTHETIC-lab", outcome)
        outcome["observed_at"] = FREEZE
        with self.assertRaises(ContractError): lab.evaluate(self.db, "SYNTHETIC-lab", outcome)
        outcome["observed_at"] = TARGET
        with patch.object(lab, "now_iso", return_value=RESOLVE):
            value = lab.evaluate(self.db, "SYNTHETIC-lab", outcome)
        self.assertEqual(value["scores"]["A"]["hits_by_field"], [4, 4])

    def test_imported_studies_reject_clock_overrides(self):
        p = protocol(); p.update(study_id="IMPORTED", provenance="IMPORTED")
        with self.assertRaises(ContractError): lab.register(self.db, p, at=REG)
        with patch.object(lab, "now_iso", return_value=REG): lab.register(self.db, p)
        with self.assertRaises(ContractError): lab.freeze(self.db, "IMPORTED", request(self.original), at=FREEZE)
        with self.assertRaises(ContractError): lab.evaluate(self.db, "IMPORTED", {}, at=RESOLVE)

    def test_reaching_deadline_during_calculation_is_not_backdated(self):
        before = self.db.verify()
        with patch.object(lab, "now_iso", side_effect=[FREEZE, TARGET]), self.assertRaises(ContractError):
            lab.freeze(self.db, "SYNTHETIC-lab", request(self.original))
        self.assertEqual(self.db.verify(), before)

    def test_concurrent_exact_replay_records_one_trial(self):
        from concurrent.futures import ThreadPoolExecutor
        path = Path(self.tmp.name) / "lab.sqlite"
        def worker():
            journal = Journal(path)
            try:
                return lab.freeze(journal, "SYNTHETIC-lab", request(self.original), at=FREEZE)
            finally:
                journal.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            values = list(pool.map(lambda _: worker(), range(2)))
        self.assertEqual(values[0], values[1])
        self.assertEqual(lab.summary(self.db, "SYNTHETIC-lab")["registered"], 1)

    def test_pending_east_forecast_is_not_overridden_by_an_accepted_one(self):
        r = request(self.original)
        card = r["original"]["frozen"]["raw_cards"][1]
        other = deepcopy(card["claims"][0]); other.update(claim_id="pending", review_status="PENDING", scenario_id="B")
        card["claims"].append(other)
        f = r["original"]["frozen"]
        f["input_hash"] = digest({"event": f["event"], "cards": f["raw_cards"], "engine_version": f["engine_version"]})
        result = self.freeze(r)
        self.assertIsNone(result["arms"]["C"]["fields"])


if __name__ == "__main__":
    unittest.main()
