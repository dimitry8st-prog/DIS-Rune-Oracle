"""lottery-rune-hash-v2 stays outside the ten cores and replays a saved pair."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from dis_oracle.contracts import ContractError, digest
from dis_oracle.lottery import CONTROL_RULE, method_fields, seed_text
from dis_oracle.pipeline import Cycle
from tests.test_pipeline import AFTER, BEFORE, fixture, outcome

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "lottery_rune_hash"
START = "2098-12-30T00:00:00Z"


def plan(draw=15944, target="2099-01-01T00:00:00Z"):
    return {"game": "synthetic-4-of-20", "draw": draw, "target_at": target,
            "method_version": "lottery-rune-hash-v2", "control_rule": CONTROL_RULE}


def cycle_manifest(draw=15944, target="2099-01-01T00:00:00Z"):
    manifest = fixture()
    manifest["adapters"] = {"rune": manifest["adapters"]["rune"]}
    del manifest["numeric_study"]
    manifest["lottery_plan"] = plan(draw, target)
    manifest["event"]["event_id"] = f"SYNTHETIC-draw-{draw}"
    return manifest


def numeric(event_id, draw, **changes):
    value = {"event_id": event_id, "draw": draw, "occurred_at": "2099-01-01T00:00:00Z",
             "recorded_at": "2099-01-01T00:00:01Z", "confirmation": "CONFIRMED",
             "source_ref": "SYNTHETIC declared draw; not an external certificate",
             "fields": [[1, 2, 3, 4], [5, 6, 7, 8]]}
    value.update(changes)
    return value


class FormulaTests(unittest.TestCase):
    def test_control_vectors_and_blank_orientation(self):
        vectors = (
            (15944, [("eihwaz", 180), ("isa", 180), ("sowilo", 0)], [[5, 7, 8, 15], [5, 10, 15, 17]]),
            (46878, [("perthro", 180), ("ehwaz", 180), ("mannaz", 180)], [[3, 15, 18, 19], [4, 5, 9, 14]]),
        )
        for draw, pairs, expected in vectors:
            positions = [{"rune_id": name, "final_orientation": orientation} for name, orientation in pairs]
            _, fields = method_fields(draw, positions)
            self.assertEqual(fields, expected)
        seed = seed_text(1, [{"rune_id": "blank", "final_orientation": None},
                             {"rune_id": "fehu", "final_orientation": 0},
                             {"rune_id": "isa", "final_orientation": 180}])
        self.assertEqual(seed, "lottery-rune-hash-v2|target=1|blank:None,fehu:0,isa:180")

    def test_saved_pair_survives_restart_and_does_not_rewrite_manifest(self):
        manifest = cycle_manifest()
        with tempfile.TemporaryDirectory() as directory:
            with Cycle(directory, "lottery") as cycle:
                first = cycle.start(manifest, at=START)
                pair = first["lottery-rune-hash-v2"]
                self.assertEqual(pair["method_fields"], method_fields(15944, pair["positions"])[1])
                self.assertEqual(pair["positions"], [{"rune_id": item["rune_id"], "final_orientation": item["final_orientation"]}
                                                     for item in first["cards"][0]["raw_result"]["positions"]])
                self.assertNotIn("method_fields", first["registration"]["manifest"])
                self.assertEqual(first["registration"]["manifest"], manifest)
                for field in pair["control_fields"]:
                    self.assertEqual(len(field), 4)
                    self.assertEqual(len(set(field)), 4)
                    self.assertEqual(field, sorted(field))
                    self.assertTrue(all(type(number) is int and 1 <= number <= 20 for number in field))
            with Cycle(directory, "lottery") as cycle:
                with patch("dis_oracle.lottery.secrets.SystemRandom", side_effect=AssertionError("resample")), \
                     patch("dis_oracle.adapters.runes.secrets.token_hex", side_effect=AssertionError("new manifest")):
                    second = cycle.start(manifest, at=START)
                self.assertEqual(second["cards"], first["cards"])
                self.assertEqual(second["lottery-rune-hash-v2"], pair)

    def test_concurrent_starts_return_one_saved_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "manifest.json"
            manifest_path.write_text(json.dumps(cycle_manifest()), encoding="utf-8")
            state = Path(directory) / "state"
            command = [sys.executable, "-m", "dis_oracle", "cycle-start", str(manifest_path),
                       "--directory", str(state), "--run-id", "parallel", "--at", START]
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(lambda _: subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8"), range(2)))
            for response in responses:
                self.assertEqual(response.returncode, 0, response.stderr)
            loaded = [json.loads(response.stdout) for response in responses]
            self.assertEqual(loaded[0]["cards"], loaded[1]["cards"])
            self.assertEqual(loaded[0]["lottery-rune-hash-v2"], loaded[1]["lottery-rune-hash-v2"])

    def test_invalid_plan_writes_nothing(self):
        manifest = cycle_manifest()
        manifest["lottery_plan"]["draw"] = True
        with tempfile.TemporaryDirectory() as directory, Cycle(directory, "bad-plan") as cycle:
            with self.assertRaises(ContractError):
                cycle.start(manifest, at=START)
            self.assertIsNone(cycle._get("registered"))
            self.assertEqual(cycle.journal.verify()["records"], 0)
            self.assertEqual(list(cycle.private.glob("*.sqlite3")), [])

    def test_outcome_statuses_correction_and_rejected_input(self):
        manifest = cycle_manifest()
        event_id = manifest["event"]["event_id"]
        with tempfile.TemporaryDirectory() as directory, Cycle(directory, "outcomes") as cycle:
            cycle.start(manifest, at=START)
            cycle.review({"claims_by_core": {}})
            frozen = cycle.freeze(at="2098-12-30T00:00:01Z")
            self.assertEqual(frozen["frozen"]["comparison"]["core_weight"], "0.10")
            self.assertEqual(len(frozen["frozen"]["comparison"]["cores"]), 10)
            self.assertIsNone(frozen["frozen"]["comparison"]["axes"]["target"]["prediction"])
            before = cycle.science({"report_id": "before", "reason": "Numbers fixed, outcome unknown"}, at="2098-12-30T00:00:02Z")
            self.assertEqual(before["lottery-rune-hash-v2"]["status"], "AUTHOR_METHOD")
            self.assertEqual(before["lottery-rune-hash-v2"]["expected_outcome"]["hits_per_field"], "4/5")
            self.assertEqual(before["lottery-rune-hash-v2"]["expected_outcome"]["total_hits"], "8/5")
            self.assertIn("MISSING_OUTCOME", before["lottery-rune-hash-v2"]["exclusion_reasons"][0]["exclusion_reasons"])
            self.assertTrue(before["router"]["support_is_probability"] is False)
            request = {"report_id": "confirmed", "reason": "Declared synthetic draw", "supersedes": "before",
                       "numeric_outcomes": [numeric(event_id, 15944)]}
            confirmed = cycle.science(request, at=AFTER)
            self.assertEqual(confirmed["lottery-rune-hash-v2"]["statistics"]["paired_total"]["n"], 1)
            self.assertEqual(len(confirmed["lottery-rune-hash-v2"]["hits_by_field"]["lottery-rune-hash-v2"][0]), 2)
            self.assertEqual(confirmed["lottery-rune-hash-v2"]["difference_method_minus_control"],
                             confirmed["lottery-rune-hash-v2"]["method_hit_sum"] - confirmed["lottery-rune-hash-v2"]["control_hit_sum"])
            self.assertNotIn("scenario_id", request["numeric_outcomes"][0])
            late_manifest_report = confirmed
            unconfirmed = deepcopy(request)
            unconfirmed.update(report_id="unconfirmed", reason="Receipt not confirmed", supersedes="confirmed")
            unconfirmed["numeric_outcomes"][0]["confirmation"] = "UNCONFIRMED"
            held = cycle.science(unconfirmed, at=AFTER)
            row = held["lottery-rune-hash-v2"]["exclusion_reasons"][0]
            self.assertIn("UNCONFIRMED_OUTCOME", row["exclusion_reasons"])
            self.assertIsNone(row["hits_by_field"])
            self.assertIsNotNone(row["descriptive_hits_not_prospective"])
            unknown = deepcopy(request)
            unknown.update(report_id="unknown-time", reason="Event time was not recorded", supersedes="unconfirmed")
            unknown["numeric_outcomes"][0]["confirmation"] = "CONFIRMED"
            unknown["numeric_outcomes"][0]["occurred_at"] = None
            unknown["numeric_outcomes"][0]["recorded_at"] = None
            unknown_report = cycle.science(unknown, at=AFTER)
            unknown_row = unknown_report["lottery-rune-hash-v2"]["exclusion_reasons"][0]
            self.assertIn("UNKNOWN_TIME", unknown_row["exclusion_reasons"])
            self.assertIsNone(unknown_row["hits_by_field"])
            self.assertIsNotNone(unknown_row["descriptive_hits_not_prospective"])
            self.assertIsNone(unknown_row["descriptive_hits_not_prospective"] and unknown_report["lottery-rune-hash-v2"]["statistics"]["trials"][0]["outcome_at"])
            changed = deepcopy(request)
            changed.update(report_id="correction", reason="Source corrected the draw")
            changed["numeric_outcomes"][0]["fields"] = [[17, 18, 19, 20], [5, 6, 7, 8]]
            before_records = cycle.journal.verify()["records"]
            with self.assertRaises(ContractError):
                cycle.science(changed, at=AFTER)
            self.assertEqual(cycle.journal.verify()["records"], before_records)
            self.assertIsNone(cycle._get("science:" + digest("correction")))
            changed["supersedes"] = "unknown-time"
            revised = cycle.science(changed, at=AFTER)
            self.assertEqual(revised["request"]["supersedes"], "unknown-time")
            self.assertEqual(cycle.science(request, at=AFTER)["request"], request)
            self.assertEqual(cycle.science({"report_id": "before", "reason": "Numbers fixed, outcome unknown"},
                                           at="2098-12-30T00:00:02Z"), before)
            foreign = deepcopy(request)
            foreign.update(report_id="foreign", reason="Wrong draw", supersedes="correction")
            foreign["numeric_outcomes"][0]["draw"] = 1
            foreign["numeric_outcomes"][0]["fields"] = [[1, 2, 3, 4], [5, 6, 7, 8]]
            with self.assertRaises(ContractError):
                cycle.science(foreign, at=AFTER)
            self.assertIsNone(cycle._get("science:" + digest("foreign")))
            self.assertEqual(late_manifest_report["original_report_hash"], revised["original_report_hash"])

    def test_late_draw_keeps_late_status(self):
        manifest = cycle_manifest(target="2026-10-24T00:00:00Z")
        with tempfile.TemporaryDirectory() as directory, Cycle(directory, "late") as cycle:
            cycle.start(manifest, at="2098-12-30T00:00:01Z")
            cycle.review({"claims_by_core": {}})
            cycle.freeze(at="2098-12-30T00:00:01Z")
            report = cycle.science({"report_id": "late", "reason": "Fixed after the declared target",
                                    "numeric_outcomes": [numeric(manifest["event"]["event_id"], 15944,
                                                                occurred_at="2098-12-30T00:00:00Z",
                                                                recorded_at="2098-12-30T00:00:01Z")]},
                                   at="2098-12-30T00:00:02Z")
            row = report["lottery-rune-hash-v2"]["exclusion_reasons"][0]
            self.assertEqual(row["classification"], "LATE")
            self.assertIsNone(row["hits_by_field"])
            self.assertIsNotNone(row["descriptive_hits_not_prospective"])

    def test_imported_numeric_study_remains_independent(self):
        manifest = fixture()
        manifest["lottery_plan"] = plan()
        with tempfile.TemporaryDirectory() as directory, Cycle(directory, "import") as cycle:
            cycle.start(manifest, at=START)
            cycle.review({"claims_by_core": {}})
            cycle.freeze(at=BEFORE)
            cycle.evaluate(outcome(), at=AFTER)
            from tests.test_pipeline import numeric_outcome
            from research_stats.core import report as statistics_report
            request = {"report_id": "imported", "reason": "External numbers stay imported",
                       "numeric_outcomes": [numeric_outcome()]}
            report = cycle.science(request, at=AFTER)
            data = fixture()["numeric_study"]
            data.update(analysis_at=AFTER, outcomes=[numeric_outcome()])
            self.assertEqual(report["numeric_external_method"], statistics_report(data))
            self.assertEqual(report["lottery-rune-hash-v2"]["status"], "AUTHOR_METHOD")
            self.assertIn("MISSING_OUTCOME", report["lottery-rune-hash-v2"]["exclusion_reasons"][0]["exclusion_reasons"])

    def test_documented_cli_example_replays(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"
            run = ["--directory", str(state), "--run-id", "synthetic-lottery"]

            def invoke(action, filename=None, at=None):
                command = [sys.executable, "-m", "dis_oracle", action, *run]
                if filename:
                    command.append(str(EXAMPLE / filename))
                if at:
                    command.extend(["--at", at])
                result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)

            first = invoke("cycle-start", "manifest.json", START)
            invoke("cycle-review", "review.json")
            invoke("cycle-freeze", at="2098-12-30T00:00:01Z")
            before = invoke("cycle-science", "science-before.json", "2098-12-30T00:00:02Z")
            after = invoke("cycle-science", "science-after.json", AFTER)
            second = invoke("cycle-start", "manifest.json", START)
            self.assertEqual(second["cards"], first["cards"])
            self.assertEqual(second["lottery-rune-hash-v2"], first["lottery-rune-hash-v2"])
            self.assertEqual(before["lottery-rune-hash-v2"]["status"], "AUTHOR_METHOD")
            self.assertEqual(after["lottery-rune-hash-v2"]["statistics"]["paired_total"]["n"], 1)
            self.assertEqual(after["router"]["core_weight"], "0.10")
            self.assertNotIn("scenario_id", json.loads((EXAMPLE / "science-after.json").read_text(encoding="utf-8"))["numeric_outcomes"][0])
