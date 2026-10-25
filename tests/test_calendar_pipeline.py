"""Calendar sidecars must survive restarts without becoming votes or new draws."""
from copy import deepcopy
import json
from pathlib import Path
import random
import secrets
import tempfile
import unittest
from unittest.mock import patch

from dis_oracle.contracts import CORES, ContractError, digest
from dis_oracle.journal import JournalError
from dis_oracle.pipeline import Cycle


FIXTURE = Path(__file__).parents[1] / "examples/v0_3/manifest.json"
REGISTERED = "2098-12-29T00:00:00Z"
FROZEN = "2098-12-30T00:00:00Z"


def manifest(with_calendar=True):
    result = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if with_calendar:
        common = {
            "calendar_date": "2099-01-01",
            "source_ref": "https://example.org/synthetic-calendar-fixture",
            "source_locator": "SYNTHETIC test row; no historical claim",
            "available_at": "2025-12-31T00:00:00Z",
        }
        result["calendar_context"] = {
            "schema_version": "rune-calendar-context-v1",
            "event_at": result["event"]["axes"][0]["deadline"],
            "timezone": "UTC",
            "day_boundary": "civil_midnight",
            "profiles": {
                "japanese_rokuyo": {
                    **common, "lunar_month": 1, "lunar_day": 5,
                    "is_leap_month": False,
                },
                "egyptian_cairo": {
                    **common, "month": 1, "day": 1,
                    "mapping_rule": "DECLARED_MODERN_CORRELATION",
                },
            },
        }
    return result


def corpus(segments):
    return {
        "schema_version": "cairo-calendar-prognoses-v1",
        "source_ref": "https://example.org/synthetic-cairo-fixture",
        "rights_notice": "SYNTHETIC test labels, not a historical transcription",
        "rows": [{"month": 1, "day": 1, "segments": segments}],
    }


class CalendarPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.corpus_path = self.directory / "synthetic-cairo.json"
        self.write_corpus(["G", "G", "G"])
        self.addCleanup(patch.stopall)
        patch("dis_oracle.calendar_context.CAIRO_CORPUS_PATH", self.corpus_path).start()

    def write_corpus(self, segments):
        self.corpus_path.write_text(json.dumps(corpus(segments)), encoding="utf-8")

    def assert_binding(self, attachment, cards):
        rune = next(card for card in cards if card["core_id"] == "rune")
        self.assertEqual(attachment["relation"], "CULTURAL_CONTEXT_ONLY")
        self.assertEqual(attachment["snapshot_hash"], digest(attachment["snapshot"]))
        self.assertEqual(attachment["rune_binding"], {
            "status": "BOUND", "core_id": "rune",
            "card_input_hash": rune["input_hash"],
            "procedure_commitment": rune["raw_result"]["commitment"],
        })

    def test_invalid_calendar_inputs_fail_before_randomness_or_registration(self):
        invalid = []
        bad = manifest(); bad["calendar_context"] = None; invalid.append(bad)
        bad = manifest(); bad["calendar_context"]["timezone"] = "Unknown/Zone"; invalid.append(bad)
        bad = manifest(); bad["calendar_context"]["event_at"] = FROZEN; invalid.append(bad)
        bad = manifest(); bad["calendar_context"]["profiles"]["other"] = {}; invalid.append(bad)
        bad = manifest(); bad["calendar_context"]["profiles"]["japanese_rokuyo"]["lunar_month"] = True; invalid.append(bad)
        bad = manifest(); bad["calendar_context"]["profiles"]["japanese_rokuyo"]["available_at"] = REGISTERED; invalid.append(bad)
        bad = manifest(); bad["calendar_context"]["profiles"]["egyptian_cairo"]["mapping_rule"] = "inferred"; invalid.append(bad)
        for index, data in enumerate(invalid):
            with self.subTest(index=index), Cycle(self.directory / str(index), "invalid") as cycle:
                with patch("secrets.SystemRandom", side_effect=AssertionError("unexpected RNG")), \
                     patch("secrets.token_hex", side_effect=AssertionError("unexpected nonce")):
                    with self.assertRaises(ContractError):
                        cycle.start(data, at=REGISTERED)
                self.assertEqual(cycle.journal.export(), [])
                self.assertIsNone(cycle._get("registered"))
                self.assertEqual(list(cycle.private.glob("*.sqlite3")), [])

    def test_invalid_local_corpus_fails_before_randomness_or_registration(self):
        self.write_corpus(["G", "invented", "G"])
        with Cycle(self.directory / "bad-corpus", "invalid") as cycle:
            with patch("secrets.SystemRandom", side_effect=AssertionError("unexpected RNG")), \
                 patch("secrets.token_hex", side_effect=AssertionError("unexpected nonce")):
                with self.assertRaises(ContractError):
                    cycle.start(manifest(), at=REGISTERED)
            self.assertEqual(cycle.journal.export(), [])
            self.assertEqual(list(cycle.private.glob("*.sqlite3")), [])

    def test_calendar_snapshot_is_durable_before_every_adapter_rng_call(self):
        data = manifest()
        data["adapters"].update({
            "yijing": {"mode": "digital"},
            "mo": {"mode": "digital"},
            "qiuqian": {"mode": "digital", "max_attempts": 0},
        })
        system_random, token_hex = secrets.SystemRandom, secrets.token_hex
        checks = []
        with Cycle(self.directory / "ordered", "ordered") as cycle:
            def check_saved():
                registration = cycle._get("registered")
                self.assertIsNotNone(registration)
                self.assertEqual(cycle._get("calendar-context-v1"), registration["calendar_snapshot"])
                checks.append(True)

            def checked_rng(*args, **kwargs):
                check_saved()
                return system_random(*args, **kwargs)

            def checked_nonce(*args, **kwargs):
                check_saved()
                return token_hex(*args, **kwargs)

            with patch("secrets.SystemRandom", side_effect=checked_rng), \
                 patch("secrets.token_hex", side_effect=checked_nonce):
                state = cycle.start(data, at=REGISTERED)
            self.assertGreaterEqual(len(checks), 5)  # Four adapters and the rune nonce.
            self.assert_binding(state["calendar_context"], state["cards"])

    def test_restart_reuses_snapshot_when_corpus_changes_or_disappears(self):
        for condition in ("changed", "missing"):
            with self.subTest(condition=condition):
                self.write_corpus(["G", "G", "G"])
                root = self.directory / condition
                data = manifest()
                with Cycle(root, condition) as cycle:
                    first = cycle.start(data, at=REGISTERED)
                    saved = first["calendar_context"]
                    cycle.review({"claims_by_core": {}})
                    original = cycle.freeze(at=FROZEN)
                    request = {"report_id": "v1", "reason": "SYNTHETIC restart audit"}
                    report = cycle.science(request, at=FROZEN)
                if condition == "changed":
                    self.write_corpus(["S", "S", "S"])
                else:
                    self.corpus_path.unlink()
                with Cycle(root, condition) as cycle:
                    with patch("dis_oracle.calendar_context._cairo_corpus", side_effect=AssertionError("corpus reread")), \
                         patch("dis_oracle.pipeline.build_context", side_effect=AssertionError("snapshot rebuilt")), \
                         patch("dis_oracle.pipeline.validate_context", side_effect=AssertionError("source revalidation")), \
                         patch("secrets.SystemRandom", side_effect=AssertionError("redraw")), \
                         patch("secrets.token_hex", side_effect=AssertionError("new nonce")):
                        replay = cycle.start(data, at=REGISTERED)
                        self.assertEqual(replay["calendar_context"], saved)
                        self.assertEqual(replay["cards"], first["cards"])
                        self.assertEqual(cycle.freeze(), original)
                        self.assertEqual(cycle.science(request, at=FROZEN), report)
                        self.assertEqual(cycle.status()["calendar_context"], saved)

    def test_crash_before_collection_resumes_registered_snapshot_without_reread(self):
        for point in ("before_collection", "before_first_adapter"):
            with self.subTest(point=point):
                self.write_corpus(["G", "G", "G"])
                root = self.directory / point
                data = manifest()
                target = "dis_oracle.pipeline.Cycle._collect" if point == "before_collection" else "dis_oracle.pipeline.RuneSessions.prepare"
                with Cycle(root, point) as cycle:
                    with patch(target, side_effect=RuntimeError("SYNTHETIC interruption")):
                        with self.assertRaises(RuntimeError):
                            cycle.start(data, at=REGISTERED)
                    saved = deepcopy(cycle._get("registered")["calendar_snapshot"])
                    self.assertIsNone(cycle._get("collected"))
                    self.assertEqual(cycle._get("calendar-context-v1"), None if point == "before_collection" else saved)
                self.corpus_path.unlink()
                with Cycle(root, point) as cycle:
                    with patch("dis_oracle.calendar_context._cairo_corpus", side_effect=AssertionError("corpus reread")), \
                         patch("dis_oracle.pipeline.build_context", side_effect=AssertionError("snapshot rebuilt")), \
                         patch("dis_oracle.pipeline.validate_context", side_effect=AssertionError("source revalidation")):
                        resumed = cycle.start(data, at=REGISTERED)
                    self.assertEqual(resumed["calendar_context"]["snapshot"], saved)
                    self.assertEqual(cycle._get("calendar-context-v1"), saved)
                    self.assert_binding(resumed["calendar_context"], resumed["cards"])
                    records = [entry for entry in cycle.journal.export()
                               if entry["record_key"].endswith(":calendar-context-v1")]
                    self.assertEqual(len(records), 1)

    def test_freeze_and_science_bind_actual_rune_card_and_snapshot(self):
        with Cycle(self.directory / "binding", "binding") as cycle:
            state = cycle.start(manifest(), at=REGISTERED)
            attachment = state["calendar_context"]
            cycle.review({"claims_by_core": {}})
            original = cycle.freeze(at=FROZEN)
            report = cycle.science({"report_id": "v1", "reason": "SYNTHETIC binding audit"}, at=FROZEN)
            self.assertEqual(original["calendar_context"], attachment)
            self.assertEqual(report["calendar_context"], attachment)
            self.assert_binding(original["calendar_context"], original["frozen"]["raw_cards"])
            self.assert_binding(report["calendar_context"], original["frozen"]["raw_cards"])
            self.assertEqual(report["method_versions"]["rune"]["input_hash"], attachment["rune_binding"]["card_input_hash"])
            self.assertNotIn("calendar_context", original["frozen"])
            self.assertTrue(all("calendar_context" not in card["inputs"] for card in state["cards"]))

    def test_changed_calendar_manifest_is_refused_without_new_records_or_rng(self):
        data = manifest()
        with Cycle(self.directory / "fixed", "fixed") as cycle:
            first = cycle.start(data, at=REGISTERED)
            recorded = cycle.journal.export()
            changed = deepcopy(data)
            changed["calendar_context"]["profiles"]["japanese_rokuyo"]["lunar_day"] = 6
            removed = deepcopy(data)
            del removed["calendar_context"]
            for altered in (changed, removed):
                with self.subTest(calendar_present="calendar_context" in altered):
                    with patch("dis_oracle.calendar_context._cairo_corpus", side_effect=AssertionError("corpus reread")), \
                         patch("secrets.SystemRandom", side_effect=AssertionError("redraw")):
                        with self.assertRaises(JournalError):
                            cycle.start(altered, at=REGISTERED)
                    self.assertEqual(cycle.journal.export(), recorded)
            self.assertEqual(cycle.start(data, at=REGISTERED)["calendar_context"], first["calendar_context"])

    def test_calendar_cannot_change_legacy_cards_numeric_study_or_router(self):
        results = []
        for with_calendar in (False, True):
            data = manifest(with_calendar)
            with Cycle(self.directory / str(with_calendar), "same-run") as cycle:
                with patch("secrets.SystemRandom", side_effect=lambda: random.Random(12345)), \
                     patch("secrets.token_hex", return_value="00" * 16), \
                     patch("dis_oracle.adapters.runes.now_iso", return_value=REGISTERED), \
                     patch("dis_oracle.adapters.yijing.now_iso", return_value=REGISTERED), \
                     patch("dis_oracle.adapters.mo.now_iso", return_value=REGISTERED), \
                     patch("dis_oracle.adapters.qiuqian.now_iso", return_value=REGISTERED):
                    state = cycle.start(data, at=REGISTERED)
                cycle.review({"claims_by_core": {}})
                original = cycle.freeze(at=FROZEN)
                report = cycle.science({"report_id": "v1", "reason": "SYNTHETIC compatibility audit"}, at=FROZEN)
                if not with_calendar:
                    self.assertEqual(set(state), {"run_id", "registration", "cards", "review", "original", "chain"})
                    self.assertEqual(set(original), {"state", "pipeline_version", "registration_hash", "review_hash", "frozen"})
                    self.assertNotIn("calendar_snapshot", state["registration"])
                    self.assertNotIn("calendar_context", report)
                    self.assertIsNone(cycle._get("calendar-context-v1"))
                results.append((state, original, report))
        legacy, contextual = results
        self.assertEqual(contextual[0]["cards"], legacy[0]["cards"])
        self.assertEqual(contextual[1]["frozen"], legacy[1]["frozen"])
        self.assertEqual(contextual[2]["numeric_external_method"], legacy[2]["numeric_external_method"])
        self.assertEqual(contextual[2]["router"], legacy[2]["router"])
        self.assertEqual(contextual[2]["method_versions"], legacy[2]["method_versions"])

    def test_missing_rune_is_explicit_abstention_and_calendars_never_vote(self):
        data = manifest()
        data["adapters"] = {}
        with Cycle(self.directory / "no-rune", "no-rune") as cycle:
            with patch("secrets.SystemRandom", side_effect=AssertionError("calendar RNG")):
                state = cycle.start(data, at=REGISTERED)
            self.assertEqual(state["cards"], [])
            attachment = state["calendar_context"]
            self.assertTrue(all(item["status"] == "OK" for item in attachment["snapshot"]["contexts"]))
            self.assertEqual(attachment["rune_binding"], {
                "status": "ABSTAIN", "core_id": "rune", "reason": "RUNE_UNAVAILABLE",
            })
            before = cycle.journal.export()
            for core in ("calendar", "japanese_rokuyo", "egyptian_cairo", "egypt"):
                with self.subTest(core=core), self.assertRaises(ContractError):
                    cycle.review({"claims_by_core": {core: []}})
            self.assertEqual(cycle.journal.export(), before)
            cycle.review({"claims_by_core": {}})
            original = cycle.freeze(at=FROZEN)
            comparison = original["frozen"]["comparison"]
            self.assertEqual(set(comparison["cores"]), set(CORES))
            self.assertEqual(comparison["core_weight"], "0.10")
            self.assertTrue(all(core["status"] == "UNAVAILABLE" for core in comparison["cores"].values()))
            self.assertIsNone(comparison["axes"]["target"]["prediction"])
            self.assertEqual(comparison["axes"]["target"]["comparison_coverage_percent"], 0)
            report = cycle.science({"report_id": "v1", "reason": "SYNTHETIC abstention audit"}, at=FROZEN)
            self.assertEqual(report["calendar_context"], attachment)
            self.assertEqual(report["method_versions"], {})


if __name__ == "__main__":
    unittest.main()
