"""Integrated checks using a private synthetic journal and Cairo corpus."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dis_oracle import calendar_context
from dis_oracle.contracts import ContractError, digest
from dis_oracle.pipeline import Cycle


EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "audited_cores"
REGISTERED = "2026-01-01T00:00:00Z"
FROZEN = "2098-12-31T00:00:00Z"


class AuditedCoreCycleTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.manifest = json.loads((EXAMPLES / "manifest.synthetic.json").read_text(encoding="utf-8"))
        self.corpus = self.root / "cairo.json"
        self.corpus.write_bytes((EXAMPLES / "cairo_corpus.synthetic.json").read_bytes())
        self.enterContext(patch.object(calendar_context, "CAIRO_CORPUS_PATH", self.corpus))
        self.enterContext(patch("secrets.SystemRandom", side_effect=AssertionError("no random draw expected")))

    def cycle(self, run_id):
        return Cycle(self.root / "journal", run_id)

    def test_complete_cycle_and_reread_with_corpus_removed(self):
        with self.cycle("complete") as cycle:
            started = cycle.start(self.manifest, at=REGISTERED)
            cards = {card["core_id"]: card for card in started["cards"]}
            self.assertEqual(set(cards), {"egypt", "shakuna", "slavic", "name_grids"})
            for card in cards.values():
                self.assertEqual(card["status"], "ABSTAIN")
                self.assertEqual(card["input_hash"], digest(card["inputs"]))
                self.assertEqual(card["claims"], [])

            cairo = cards["egypt"]["raw_result"]
            self.assertEqual([row["source_label"] for row in cairo["segments"]], ["G", "S", "G"])
            self.assertEqual(cairo["day_quality"], "mixed")
            self.assertEqual(cards["shakuna"]["raw_result"]["observation"], self.manifest["adapters"]["shakuna"]["observation"])
            draw = cards["slavic"]["raw_result"]["observed_rounds"][0]
            self.assertEqual(draw, self.manifest["adapters"]["slavic"]["rounds"][0])
            grids = cards["name_grids"]["raw_result"]["grids"]
            self.assertEqual(grids, {"tenkaku": 8, "jinkaku": 6, "chikaku": 3, "gaikaku": 5, "sokaku": 11})

            with self.assertRaisesRegex(ContractError, "explicit review required"):
                cycle.freeze(at=FROZEN)
            cycle.review({"claims_by_core": {}})
            original = cycle.freeze(at=FROZEN)
            comparison = original["frozen"]["comparison"]
            self.assertEqual(len(comparison["cores"]), 10)
            self.assertEqual(comparison["core_weight"], "0.10")
            self.assertEqual(comparison["axes"]["target"]["comparison_coverage_percent"], 0)
            self.assertIsNone(comparison["axes"]["target"]["prediction"])
            outcome = cycle.evaluate({
                "event_id": self.manifest["event"]["event_id"],
                "axis_id": "target",
                "scenario_id": "A",
                "source": "SYNTHETIC outcome",
                "observed_at": "2099-01-01T00:00:00Z",
            }, at="2099-01-01T00:00:01Z")
            self.assertTrue(outcome["abstained"])
            science = cycle.science({"report_id": "checked", "reason": "SYNTHETIC cycle"})
            self.assertEqual(science["original_report_hash"], digest(original))
            chain = cycle.journal.verify()

        self.corpus.unlink()
        with self.cycle("complete") as cycle:
            self.assertEqual(cycle.start(self.manifest, at=REGISTERED)["cards"], started["cards"])
            self.assertEqual(digest(cycle.freeze()), science["original_report_hash"])
            self.assertEqual(cycle.freeze(), original)
            self.assertEqual(cycle.journal.verify(), chain)

    def test_resumes_collection_from_the_cairo_snapshot(self):
        with self.cycle("interrupted") as cycle:
            with patch.object(cycle, "_collect", side_effect=RuntimeError("simulated interruption")):
                with self.assertRaisesRegex(RuntimeError, "simulated interruption"):
                    cycle.start(self.manifest, at=REGISTERED)
            saved = cycle._get("registered")["egypt_card"]

        self.corpus.write_text("unreadable replacement", encoding="utf-8")
        with self.cycle("interrupted") as cycle:
            cards = cycle.start(self.manifest, at=REGISTERED)["cards"]
            self.assertEqual(next(card for card in cards if card["core_id"] == "egypt"), saved)

    def test_missing_adapters_have_specific_reasons_and_replay(self):
        self.manifest["adapters"] = {}
        with self.cycle("missing") as cycle:
            self.assertEqual(cycle.start(self.manifest, at=REGISTERED)["cards"], [])
            cycle.review({"claims_by_core": {}})
            original = cycle.freeze(at=FROZEN)
            cores = original["frozen"]["comparison"]["cores"]
            for core, reason in {
                "daliuren": "APPROVED_DALIUREN_PROFILE_UNAVAILABLE",
                "egypt": "MISSING_MODERN_CORRELATION",
                "shakuna": "MISSING_MANUAL_OBSERVATION",
                "slavic": "MISSING_REGIONAL_DRAW_OBSERVATION",
                "name_grids": "MISSING_NAME_AND_STROKE_INPUTS",
            }.items():
                self.assertEqual(cores[core], {"status": "UNAVAILABLE", "reason": reason})
            chain = cycle.journal.verify()
        with self.cycle("missing") as cycle:
            self.assertEqual(digest(cycle.freeze()), digest(original))
            self.assertEqual(cycle.journal.verify(), chain)

    def test_invalid_inputs_and_unapproved_daliuren_fail_before_registration(self):
        configs = self.manifest["adapters"]
        invalid_egypt = deepcopy(configs["egypt"])
        invalid_egypt["correlation"]["calendar_date"] = "2099-01-02"
        invalid_shakuna = deepcopy(configs["shakuna"])
        del invalid_shakuna["observation"]["evidence_ref"]
        invalid_slavic = deepcopy(configs["slavic"])
        invalid_slavic["rounds"][0]["participant_id"] = "unknown"
        invalid_name = deepcopy(configs["name_grids"])
        invalid_name["given_strokes"] = [1, True]
        for core, config, error in (
            ("egypt", invalid_egypt, "calendar_date differs"),
            ("shakuna", invalid_shakuna, "evidence_ref"),
            ("slavic", invalid_slavic, "binding mismatch"),
            ("name_grids", invalid_name, "given_strokes"),
            ("daliuren", {}, "approved calendar and chart-construction profile"),
            ("daliuren", {"event_at": "bad timestamp"}, "approved calendar and chart-construction profile"),
            ("daliuren", {"event_at": "2025-12-31T23:00:00+08:00", "timezone": "Asia/Shanghai",
                          "location": "SYNTHETIC location"}, "approved calendar and chart-construction profile"),
        ):
            with self.subTest(core=core, config=config), self.cycle("invalid") as cycle:
                manifest = dict(self.manifest, adapters={core: config})
                with self.assertRaisesRegex(ContractError, error):
                    cycle.start(manifest, at=REGISTERED)
                self.assertEqual(cycle.journal.verify()["records"], 0)
