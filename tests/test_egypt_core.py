"""Cairo core tests with declared synthetic dates and corpus rows."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dis_oracle import calendar_context as calendar
from dis_oracle.adapters import egypt
from dis_oracle.contracts import ContractError, digest, validate_cards, validate_event
from tests.test_calendar_context import REGISTERED, event_fixture, profile_fixture


def egypt_config():
    return {
        "profile": calendar.CAIRO_PROFILE_VERSION,
        "event_at": "2026-10-25T18:07:00Z",
        "timezone": "Europe/Moscow",
        "day_boundary": "civil_midnight",
        "correlation": profile_fixture("egyptian_cairo"),
    }


class EgyptCoreTests(unittest.TestCase):
    def setUp(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.corpus_path = Path(tmp) / "synthetic-cairo.json"
        self.enterContext(patch.object(calendar, "CAIRO_CORPUS_PATH", self.corpus_path))
        self.event = event_fixture()
        self.config = egypt_config()

    def write_corpus(self, *entries):
        raw = json.dumps({
            "schema_version": calendar.CAIRO_SCHEMA,
            "source_ref": "https://example.org/synthetic-cairo-corpus",
            "rights_notice": "Synthetic fixtures only",
            "rows": [{"month": m, "day": d, "segments": segments} for m, d, segments in entries],
        }).encode("utf-8")
        self.corpus_path.write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()

    def card(self):
        return egypt.card(self.config, self.event, REGISTERED)

    def test_first_and_last_ordinary_days_preserve_labels_sources_and_hashes(self):
        corpus_hash = self.write_corpus((1, 1, ["G", "G", "G"]), (12, 30, ["G", "S", "G"]))
        for month, day, labels, quality in ((1, 1, ["G", "G", "G"], "favorable"),
                                             (12, 30, ["G", "S", "G"], "mixed")):
            with self.subTest(month=month, day=day):
                self.config["correlation"].update(month=month, day=day)
                result = self.card()
                raw = result["raw_result"]
                self.assertEqual(result["status"], "ABSTAIN")
                self.assertEqual(raw["status"], "OK")
                self.assertEqual(raw["calendar_position"], {"month": month, "day": day})
                self.assertEqual(raw["day_quality"], quality)
                self.assertEqual([segment["source_label"] for segment in raw["segments"]], labels)
                self.assertEqual(raw["inputs"], self.config["correlation"])
                self.assertEqual(raw["corpus"]["sha256"], corpus_hash)
                self.assertEqual(raw["corpus"]["source_ref"], "https://example.org/synthetic-cairo-corpus")
                self.assertEqual(raw["corpus"]["rights_notice"], "Synthetic fixtures only")
                self.assertEqual(result["input_hash"], digest(result["inputs"]))
                self.assertEqual(result, self.card())
                self.assertEqual(result["claims"], [])
                validate_cards([result], validate_event(self.event))

    def test_missing_input_file_row_and_unreadable_row_are_distinguished(self):
        for config in ({}, {**self.config, "correlation": {}}):
            result = egypt.card(config, self.event, REGISTERED)
            self.assertEqual((result["status"], result["reason"]), ("UNAVAILABLE", "MISSING_MODERN_CORRELATION"))

        result = self.card()
        self.assertEqual((result["status"], result["reason"]), ("UNAVAILABLE", "CORPUS_UNAVAILABLE"))

        self.write_corpus((1, 2, ["G", "G", "G"]))
        result = self.card()
        self.assertEqual((result["status"], result["reason"]), ("UNAVAILABLE", "CORPUS_ROW_UNAVAILABLE"))

        self.write_corpus((1, 1, [None, None, None]))
        result = self.card()
        self.assertEqual((result["status"], result["reason"]), ("ABSTAIN", "UNREADABLE_SOURCE_ROW"))
        self.assertEqual([part["source_label"] for part in result["raw_result"]["segments"]], [None] * 3)

    def test_epagomenal_boundaries_do_not_read_corpus(self):
        with patch.object(Path, "read_bytes", side_effect=AssertionError("unexpected corpus read")):
            for day in (1, 5):
                self.config["correlation"].update(month=13, day=day)
                result = self.card()
                self.assertEqual((result["status"], result["reason"]), ("ABSTAIN", "EPAGOMENAL_PROGNOSES_UNAVAILABLE"))
            self.config["correlation"]["day"] = 6
            with self.assertRaises(ContractError):
                self.card()

    def test_invalid_correlations_are_rejected_before_corpus_access(self):
        cases = (
            {"month": 0}, {"month": 14}, {"day": 31}, {"day": True},
            {"calendar_date": "2026-02-29"}, {"calendar_date": "2026-10-26"},
            {"available_at": "2026-10-25T11:01:00Z"}, {"source_ref": "not a URL"},
            {"mapping_rule": "INFERRED"},
        )
        with patch.object(Path, "read_bytes", side_effect=AssertionError("unexpected corpus read")):
            for updates in cases:
                config = deepcopy(self.config)
                config["correlation"].update(updates)
                with self.subTest(updates=updates), self.assertRaises(ContractError):
                    egypt.validate_config(config, self.event, REGISTERED)
            del self.config["correlation"]["source_locator"]
            with self.assertRaises(ContractError):
                self.card()

    def test_each_card_reads_corpus_once_and_rejects_a_malformed_row(self):
        self.write_corpus((1, 1, ["S", "S", "S"]))
        with patch.object(calendar, "_cairo_corpus", wraps=calendar._cairo_corpus) as read:
            egypt.validate_config(self.config, self.event, REGISTERED)
            read.assert_not_called()
            self.assertEqual(self.card()["raw_result"]["day_quality"], "unfavorable")
            read.assert_called_once_with()

        self.write_corpus((1, 1, ["G", None, "S"]))
        with self.assertRaisesRegex(ContractError, "Cairo calendar segments"):
            self.card()


if __name__ == "__main__":
    unittest.main()
