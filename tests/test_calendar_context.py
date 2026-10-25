"""Calendar labels are conditional cultural context, never forecast evidence."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dis_oracle import calendar_context as calendar
from dis_oracle.contracts import ContractError, digest


REGISTERED = "2026-10-25T12:00:00Z"
SOURCE_AVAILABLE = "2026-10-25T10:00:00Z"
DEADLINE = "2026-10-25T18:07:00Z"


def event_fixture(deadline=DEADLINE):
    return {
        "event_id": "synthetic-calendar-unit-test",
        "question": "Synthetic calendar contract only; no lottery prediction",
        "mode": "forecast",
        "cutoff_at": "2026-10-25T11:00:00Z",
        "facts": [],
        "axes": [{
            "axis_id": "target",
            "condition_id": "synthetic-condition",
            "deadline": deadline,
            "scenarios": [
                {"scenario_id": "A", "criterion": "Synthetic A"},
                {"scenario_id": "B", "criterion": "Synthetic B"},
            ],
            "baseline": "B",
        }],
    }


def profile_fixture(profile_id):
    result = {
        "calendar_date": "2026-10-25",
        "source_ref": "https://example.org/declared-calendar",
        "source_locator": "Synthetic fixture, page 1",
        "available_at": SOURCE_AVAILABLE,
    }
    if profile_id == "japanese_rokuyo":
        result.update(lunar_month=1, lunar_day=1, is_leap_month=False)
    else:
        result.update(month=1, day=1, mapping_rule="DECLARED_MODERN_CORRELATION")
    return result


def context_fixture(profile_id="japanese_rokuyo"):
    return {
        "schema_version": "rune-calendar-context-v1",
        "event_at": DEADLINE,
        "timezone": "Europe/Moscow",
        "day_boundary": "civil_midnight",
        "profiles": {profile_id: profile_fixture(profile_id)},
    }


class CalendarContextTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.corpus_path = Path(self.temporary.name) / "cairo-calendar.json"
        corpus_patch = patch.object(calendar, "CAIRO_CORPUS_PATH", self.corpus_path)
        corpus_patch.start()
        self.addCleanup(corpus_patch.stop)

    def build(self, config=None, event=None, registered=REGISTERED):
        return calendar.build_context(
            config if config is not None else context_fixture(),
            event if event is not None else event_fixture(), registered)

    def write_corpus(self, segments=None, rows=None, **updates):
        if rows is None:
            rows = [{"month": 1, "day": 1,
                     "segments": segments if segments is not None else ["G", "G", "G"]}]
        corpus = {
            "schema_version": "cairo-calendar-prognoses-v1",
            "source_ref": "https://example.org/declared-cairo-source",
            "rights_notice": "Synthetic test labels, no historical text reproduced",
            "rows": rows,
        }
        corpus.update(updates)
        raw = (json.dumps(corpus, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        self.corpus_path.write_bytes(raw)
        return raw

    def egypt(self):
        return self.build(context_fixture("egyptian_cairo"))["contexts"][0]

    def test_rokuyo_first_six_lunar_days_have_documented_order(self):
        expected = ["Sensho", "Tomobiki", "Senbu", "Butsumetsu", "Taian", "Shakko"]
        for day, label in enumerate(expected, 1):
            config = context_fixture()
            config["profiles"]["japanese_rokuyo"]["lunar_day"] = day
            with self.subTest(day=day):
                result = self.build(config)["contexts"][0]
                self.assertEqual(result["calendar_position"]["label"], label)
                self.assertEqual(result["status"], "OK")

    def test_rokuyo_restarts_from_lunar_month_not_civil_day_continuation(self):
        # Month 1 ends on Shakko at day 30, but month 2 starts on Tomobiki.
        config = context_fixture()
        profile = config["profiles"]["japanese_rokuyo"]
        profile["lunar_day"] = 30
        self.assertEqual(self.build(config)["contexts"][0]["calendar_position"]["label"], "Shakko")
        starts = ["Sensho", "Tomobiki", "Senbu", "Butsumetsu", "Taian", "Shakko"] * 2
        for month, expected in enumerate(starts, 1):
            profile.update(lunar_month=month, lunar_day=1)
            with self.subTest(month=month):
                self.assertEqual(self.build(config)["contexts"][0]["calendar_position"]["label"], expected)

    def test_rokuyo_leap_month_retains_declared_month_number(self):
        config = context_fixture()
        profile = config["profiles"]["japanese_rokuyo"]
        profile.update(lunar_month=2, lunar_day=1)
        ordinary = self.build(config)["contexts"][0]
        profile["is_leap_month"] = True
        leap = self.build(config)["contexts"][0]
        self.assertEqual(ordinary["calendar_position"]["label"], "Tomobiki")
        self.assertEqual(leap["calendar_position"]["label"], "Tomobiki")
        self.assertTrue(leap["calendar_position"]["is_leap_month"])
        self.assertNotEqual(ordinary["input_hash"], leap["input_hash"])

    def test_rokuyo_quality_and_morning_afternoon_are_not_numeric_clock_ranges(self):
        cases = {
            1: ("mixed", ["favorable", "unfavorable"]),
            2: ("mixed", []),
            3: ("mixed", ["unfavorable", "favorable"]),
            4: ("unfavorable", []),
            5: ("favorable", []),
            6: ("mixed", []),
        }
        for day, (quality, segments) in cases.items():
            config = context_fixture()
            config["profiles"]["japanese_rokuyo"]["lunar_day"] = day
            with self.subTest(day=day):
                result = self.build(config)["contexts"][0]
                self.assertEqual(result["day_quality"], quality)
                self.assertEqual([x["quality"] for x in result["segments"]], segments)
                self.assertFalse(result["clock_boundaries_assigned"])
                if segments:
                    self.assertEqual([x["period"] for x in result["segments"]], ["morning", "afternoon"])

    def test_lunar_numbers_reject_bool_float_strings_and_invalid_bounds(self):
        for key, values in {
            "lunar_month": [True, False, 1.0, "1", None, 0, 13],
            "lunar_day": [True, False, 1.0, "1", None, 0, 31],
            "is_leap_month": [0, 1, "false", None],
        }.items():
            for value in values:
                config = context_fixture()
                config["profiles"]["japanese_rokuyo"][key] = value
                with self.subTest(key=key, value=value), self.assertRaises(ContractError):
                    self.build(config)

    def test_context_shape_schema_day_boundary_and_profile_shapes_are_strict(self):
        bad_configs = []
        for key, value in (("schema_version", "other"), ("day_boundary", "sunrise"),
                           ("profiles", []), ("profiles", {"unknown_tradition": {}})):
            config = context_fixture()
            config[key] = value
            bad_configs.append(config)
        config = context_fixture(); config["unknown"] = True; bad_configs.append(config)
        config = context_fixture(); del config["timezone"]; bad_configs.append(config)
        for value in (None, [], "missing", {"lunar_month": 1}):
            config = context_fixture(); config["profiles"]["japanese_rokuyo"] = value
            bad_configs.append(config)
        config = context_fixture(); config["profiles"]["japanese_rokuyo"]["probability"] = 0.9
        bad_configs.append(config)
        for config in bad_configs:
            with self.subTest(config=config), self.assertRaises(ContractError):
                self.build(config)

    def test_source_urls_and_locators_reject_non_sources_and_embedded_secrets(self):
        for url in ("", "example.org", "file:///tmp/source", "javascript:alert(1)",
                    "https://user:secret@example.org/page", "https://example.org/a b",
                    "https://example.org:wrong/page", "https://"):
            config = context_fixture()
            config["profiles"]["japanese_rokuyo"]["source_ref"] = url
            with self.subTest(url=url), self.assertRaises(ContractError):
                self.build(config)
        for locator in ("", " ", None, 1):
            config = context_fixture()
            config["profiles"]["japanese_rokuyo"]["source_locator"] = locator
            with self.subTest(locator=locator), self.assertRaises(ContractError):
                self.build(config)

    def test_source_availability_respects_both_cutoff_and_registration(self):
        config = context_fixture()
        profile = config["profiles"]["japanese_rokuyo"]
        profile["available_at"] = "2026-10-25T11:00:00Z"
        self.build(config)  # Exact cutoff is permitted.
        profile["available_at"] = "2026-10-25T11:00:00.000001Z"
        with self.assertRaises(ContractError):
            self.build(config)
        profile["available_at"] = "2026-10-25T10:30:00Z"
        self.build(config, registered="2026-10-25T10:30:00Z")
        with self.assertRaises(ContractError):
            self.build(config, registered="2026-10-25T10:29:59Z")

    def test_timestamps_need_timezone_and_event_at_must_equal_a_deadline(self):
        for key, value in (("event_at", "2026-10-25T18:07:00"),
                           ("event_at", "2026-10-25T18:07:01Z")):
            config = context_fixture(); config[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ContractError):
                self.build(config)
        config = context_fixture()
        config["event_at"] = "2026-10-25T21:07:00+03:00"
        self.assertEqual(self.build(config)["local_time"], "21:07:00")
        config["profiles"]["japanese_rokuyo"]["available_at"] = "2026-10-25T10:00:00"
        with self.assertRaises(ContractError):
            self.build(config)
        with self.assertRaises(ContractError):
            self.build(registered="2026-10-25T12:00:00")

    def test_timezone_local_date_rollover_and_bad_iana_names(self):
        deadline = "2026-10-25T22:30:00Z"
        config = context_fixture(); config["event_at"] = deadline
        config["profiles"]["japanese_rokuyo"]["calendar_date"] = "2026-10-26"
        result = self.build(config, event_fixture(deadline))
        self.assertEqual(result["local_date"], "2026-10-26")
        self.assertEqual(result["local_time"], "01:30:00")
        self.assertEqual(result["utc_offset_seconds"], 10800)
        config["profiles"]["japanese_rokuyo"]["calendar_date"] = "2026-10-25"
        with self.assertRaises(ContractError):
            self.build(config, event_fixture(deadline))
        for zone in ("Missing/Timezone", "", "+03:00", 3):
            config = context_fixture(); config["timezone"] = zone
            with self.subTest(zone=zone), self.assertRaises(ContractError):
                self.build(config)

    def test_calendar_dates_require_exact_valid_iso_civil_date(self):
        for value in ("2026-10-24", "2026-2-1", "2026-02-29", "2026-13-01",
                      "20261025", "2026-10-25T00:00:00", "0000-01-01", None):
            config = context_fixture()
            config["profiles"]["japanese_rokuyo"]["calendar_date"] = value
            with self.subTest(value=value), self.assertRaises(ContractError):
                self.build(config)

    def test_missing_profiles_abstain_without_fabricated_calendar_conversion(self):
        config = context_fixture(); config["profiles"] = {}
        self.assertEqual(self.build(config)["contexts"], [])
        config["profiles"] = {"egyptian_cairo": {}, "japanese_rokuyo": {}}
        result = self.build(config)
        self.assertEqual([x["profile_id"] for x in result["contexts"]],
                         ["japanese_rokuyo", "egyptian_cairo"])
        for profile in result["contexts"]:
            self.assertEqual(profile["status"], "ABSTAIN")
            self.assertEqual(profile["reason"], "MISSING_INPUTS")
            self.assertIsNone(profile["day_quality"])
            self.assertEqual(profile["segments"], [])

    def test_egyptian_numbers_and_modern_correlation_must_be_declared(self):
        for key, values in {
            "month": [True, 1.0, "1", None, 0, 14],
            "day": [True, 1.0, "1", None, 0, 31],
            "mapping_rule": ["", "historically_verified", None],
        }.items():
            for value in values:
                config = context_fixture("egyptian_cairo")
                config["profiles"]["egyptian_cairo"][key] = value
                with self.subTest(key=key, value=value), self.assertRaises(ContractError):
                    self.build(config)

    def test_egyptian_missing_corpus_and_missing_day_abstain(self):
        result = self.egypt()
        self.assertEqual((result["status"], result["reason"]), ("ABSTAIN", "CORPUS_UNAVAILABLE"))
        self.write_corpus(rows=[{"month": 1, "day": 2, "segments": ["G", "G", "G"]}])
        result = self.egypt()
        self.assertEqual((result["status"], result["reason"]), ("ABSTAIN", "CORPUS_ROW_UNAVAILABLE"))
        self.assertIsNone(result["day_quality"])

    def test_egyptian_epagomenal_days_one_to_five_always_abstain(self):
        # No extrapolation from the 360 ordinary days, even if a file is unreadable.
        config = context_fixture("egyptian_cairo")
        profile = config["profiles"]["egyptian_cairo"]
        profile["month"] = 13
        with patch.object(Path, "read_bytes", side_effect=AssertionError("epagomenal corpus lookup forbidden")):
            for day in range(1, 6):
                profile["day"] = day
                with self.subTest(day=day):
                    result = self.build(config)["contexts"][0]
                    self.assertEqual(result["status"], "ABSTAIN")
                    self.assertEqual(result["reason"], "EPAGOMENAL_PROGNOSES_UNAVAILABLE")
                    self.assertIsNone(result["day_quality"])
        for day in (0, 6, True, 1.0):
            profile["day"] = day
            with self.subTest(invalid_day=day), self.assertRaises(ContractError):
                self.build(config)

    def test_cairo_three_good_three_bad_and_mixed_preserve_all_segments(self):
        cases = [(["G", "G", "G"], "favorable"),
                 (["S", "S", "S"], "unfavorable"),
                 (["G", "S", "G"], "mixed"),
                 (["S", "G", "S"], "mixed")]
        for segments, quality in cases:
            self.write_corpus(segments=segments)
            with self.subTest(segments=segments):
                result = self.egypt()
                self.assertEqual(result["status"], "OK")
                self.assertEqual(result["day_quality"], quality)
                self.assertEqual([x["source_label"] for x in result["segments"]], segments)
                self.assertEqual([x["segment"] for x in result["segments"]], [1, 2, 3])
                self.assertFalse(result["clock_boundaries_assigned"])
                self.assertEqual(result["forecast_status"], "ABSTAIN")

    def test_cairo_all_null_is_unreadable_evidence_not_an_unfavorable_day(self):
        self.write_corpus(segments=[None, None, None])
        result = self.egypt()
        self.assertEqual((result["status"], result["reason"]), ("ABSTAIN", "UNREADABLE_SOURCE_ROW"))
        self.assertIsNone(result["day_quality"])
        self.assertEqual([x["quality"] for x in result["segments"]], [None, None, None])
        self.assertEqual([x["source_label"] for x in result["segments"]], [None, None, None])
        self.assertFalse(result["clock_boundaries_assigned"])

    def test_cairo_partial_null_unknown_labels_and_bad_triples_are_rejected(self):
        for segments in (["G", None, "S"], [None, "G", None], ["G", "G"],
                         ["G", "G", "G", "G"], ["G", "B", "S"],
                         ["G", "g", "S"], [True, True, True], "GGG", None):
            rows = [{"month": 1, "day": 1, "segments": segments}]
            self.write_corpus(rows=rows)
            with self.subTest(segments=segments), self.assertRaises(ContractError):
                self.egypt()

    def test_cairo_raw_hash_source_and_rights_are_preserved_in_snapshot(self):
        raw = self.write_corpus()
        result = self.egypt()
        self.assertEqual(result["corpus"]["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(result["corpus"]["source_ref"], "https://example.org/declared-cairo-source")
        self.assertIn("Synthetic test labels", result["corpus"]["rights_notice"])
        self.assertNotIn("rows", result["corpus"])
        # Hash authenticates bytes, not a licence or historical interpretation.
        self.corpus_path.write_bytes(raw + b" ")
        changed = self.egypt()
        self.assertNotEqual(changed["corpus"]["sha256"], result["corpus"]["sha256"])
        self.assertEqual(changed["day_quality"], result["day_quality"])
        self.assertEqual(changed["source_verification"], "USER_DECLARED")

    def test_cairo_unreadable_file_is_error_not_silent_corpus_unavailable(self):
        self.write_corpus()
        for failure in (PermissionError("denied"), OSError("read failed")):
            with self.subTest(failure=type(failure).__name__), \
                    patch.object(Path, "read_bytes", side_effect=failure), self.assertRaises(ContractError):
                self.egypt()

    def test_cairo_bad_json_unicode_and_duplicate_keys_are_rejected(self):
        for raw in (b"{", b"\xff", b'{"schema_version":"x","schema_version":"y"}',
                    b'{"rows":[{"month":1,"month":2}]}'):
            self.corpus_path.write_bytes(raw)
            with self.subTest(raw=raw), self.assertRaises(ContractError):
                self.egypt()

    def test_cairo_requires_schema_source_rights_and_only_known_fields(self):
        for updates in ({"schema_version": "other"}, {"rights_notice": " "},
                        {"rights_notice": None}, {"source_ref": "file:///tmp/corpus"},
                        {"rows": {}}, {"extra": "not part of schema"}):
            self.write_corpus(**updates)
            with self.subTest(updates=updates), self.assertRaises(ContractError):
                self.egypt()
        for missing in ("rights_notice", "source_ref", "schema_version", "rows"):
            self.write_corpus()
            corpus = json.loads(self.corpus_path.read_text())
            del corpus[missing]
            self.corpus_path.write_text(json.dumps(corpus), encoding="utf-8")
            with self.subTest(missing=missing), self.assertRaises(ContractError):
                self.egypt()

    def test_cairo_rows_reject_duplicates_bad_dates_and_partial_objects(self):
        good = {"month": 1, "day": 1, "segments": ["G", "G", "G"]}
        bad_rows = [[good, deepcopy(good)], [{"month": 1, "day": 1}],
                    [{**good, "extra": True}], [{**good, "month": 13}],
                    [{**good, "month": 0}], [{**good, "month": True}],
                    [{**good, "day": 31}], [{**good, "day": 0}],
                    [{**good, "day": 1.0}], [{**good, "day": "1"}]]
        for rows in bad_rows:
            self.write_corpus(rows=rows)
            with self.subTest(rows=rows), self.assertRaises(ContractError):
                self.egypt()

    def test_context_is_deterministic_detached_and_never_generates_random_choices(self):
        self.write_corpus()
        config = context_fixture()
        config["profiles"]["egyptian_cairo"] = profile_fixture("egyptian_cairo")
        before_config, before_event = deepcopy(config), event_fixture()
        with patch("secrets.SystemRandom", side_effect=AssertionError("RNG forbidden")):
            first = self.build(config, before_event)
            second = self.build(config, before_event)
        self.assertEqual(first, second)
        self.assertEqual(config, before_config)
        self.assertEqual(before_event, event_fixture())
        self.assertEqual(first["config_hash"], digest(config))
        self.assertEqual(first["source_verification"], "USER_DECLARED")
        self.assertEqual(first["scope"], "CULTURAL_CONTEXT_ONLY")
        self.assertEqual([x["profile_id"] for x in first["contexts"]],
                         ["japanese_rokuyo", "egyptian_cairo"])
        for result in first["contexts"]:
            self.assertEqual(result["forecast_status"], "ABSTAIN")
            self.assertEqual(result["source_verification"], "USER_DECLARED")
            self.assertNotIn("claims", result)
            self.assertNotIn("probability", result)
        config["profiles"]["japanese_rokuyo"]["lunar_day"] = 9
        self.assertEqual(first["contexts"][0]["inputs"]["lunar_day"], 1)


if __name__ == "__main__":
    unittest.main()
