import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from dis_oracle.contracts import CORES, digest
from dis_oracle.engine import freeze
from dis_oracle.journal import Journal
from dis_oracle.router import compare
from tests.test_engine import card, event


class CoreAvailabilityRouterTests(unittest.TestCase):
    def test_missing_cards_explain_each_dependency_and_keep_fixed_weights(self):
        result = compare(event(), [card("rune")])
        self.assertEqual(tuple(result["cores"]), CORES)
        self.assertEqual(result["core_weight"], "0.10")
        self.assertEqual(result["procedural_coverage_percent"], 10)
        self.assertEqual(result["axes"]["primary"]["support_percent"], {"A": 10, "B": 0})
        self.assertEqual(result["axes"]["primary"]["unfilled_percent"], 90)
        expected = {
            "daliuren": "APPROVED_DALIUREN_PROFILE_UNAVAILABLE",
            "egypt": "MISSING_MODERN_CORRELATION",
            "shakuna": "MISSING_MANUAL_OBSERVATION",
            "slavic": "MISSING_REGIONAL_DRAW_OBSERVATION",
            "name_grids": "MISSING_NAME_AND_STROKE_INPUTS",
            "maya": "NOT_SUPPLIED",
        }
        for core, reason in expected.items():
            with self.subTest(core=core):
                self.assertEqual(result["cores"][core], {"status": "UNAVAILABLE", "reason": reason})

    def test_imported_cards_keep_their_status_and_reason(self):
        cores = ("daliuren", "egypt", "shakuna", "slavic", "name_grids")
        for core in cores:
            for status in ("ABSTAIN", "UNAVAILABLE"):
                with self.subTest(core=core, status=status):
                    imported = card(core)
                    imported.update(status=status, reason="SYNTHETIC_IMPORTED_REASON", claims=[])
                    result = compare(event(), [imported])
                    self.assertEqual(result["cores"][core], {"status": status, "reason": imported["reason"]})
                    self.assertEqual(result["procedural_coverage_percent"], 0)
                    self.assertEqual(result["axes"]["primary"]["unfilled_percent"], 100)

    def test_rereading_prior_frozen_result_preserves_original_reason_and_hash(self):
        synthetic_event = event()
        cards = [card("rune")]
        frozen_at = "2026-10-12T06:02:00Z"
        prior_comparison = compare(synthetic_event, cards)
        for core in CORES:
            if prior_comparison["cores"][core]["status"] == "UNAVAILABLE":
                prior_comparison["cores"][core]["reason"] = "NOT_SUPPLIED"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic-router.sqlite3"
            with closing(Journal(path)) as journal:
                with patch("dis_oracle.engine.compare", return_value=prior_comparison):
                    original = freeze(journal, "synthetic", synthetic_event, cards, frozen_at=frozen_at)
                original_hash = digest(original)
                original_chain = journal.verify()
            with closing(Journal(path)) as reopened:
                reread = freeze(reopened, "synthetic", synthetic_event, cards)
                self.assertEqual(reread["comparison"]["cores"]["daliuren"]["reason"], "NOT_SUPPLIED")
                self.assertEqual(digest(reread), original_hash)
                self.assertEqual(reopened.verify(), original_chain)
