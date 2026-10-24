"""Research-audit regressions; no changes to runtime behavior or journals."""

import copy
import hashlib
import itertools
import json
import subprocess
import sys
import unittest

from dis_oracle.adapters.yijing import calculate as runtime_calculate
from scripts import yijing_audit as audit


class YijingAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.table = audit.reference_table()
        cls.outputs = audit.build_outputs()
        cls.cases = cls.outputs["corrected_results.json"]["cases"]

    def test_original_inputs_are_byte_preserved(self):
        expected = {
            audit.SPEC: "8cbf6d702be342331aa05fd713b1b673636d8b8b3e578c4cd5e3bba3157aa988",
            audit.INPUT: "d53966201cfc442e6cd3568ddbc5918a76c86f76ed5b2fea8d8b7294f3f965dc",
        }
        for path, digest in expected.items():
            canonical = path.read_bytes().replace(b"\r\n", b"\n")
            self.assertEqual(hashlib.sha256(canonical).hexdigest(), digest)

    def test_all_64_external_structures_and_names(self):
        checked = self.outputs["discrepancies.json"]["qwen_table_audit"]
        self.assertEqual((checked["rows"], checked["unique_structures"]), (64, 64))
        self.assertTrue(all(row["status"] == "MATCH" for row in checked["checks"]))
        # Asymmetric anchors detect reversal of bottom/top order and trigram swaps.
        self.assertEqual(self.table[9]["lines_binary"], [1, 1, 0, 1, 1, 1])
        self.assertEqual(self.table[9]["lower_trigram"], "☱")
        self.assertEqual(self.table[9]["upper_trigram"], "☰")
        self.assertEqual(self.table[42]["lines_binary"], [1, 1, 1, 1, 1, 0])
        self.assertEqual(self.table[9]["name"], "履")
        self.assertEqual(self.table[42]["name"], "夬")

    def test_internally_consistent_but_wrong_numbering_is_rejected(self):
        refs = copy.deepcopy(audit.references())
        refs["oeis"]["values"][9], refs["oeis"]["values"][42] = (
            refs["oeis"]["values"][42], refs["oeis"]["values"][9])
        self.assertEqual(len(set(refs["oeis"]["values"])), 64)
        with self.assertRaisesRegex(ValueError, "Wikipedia/OEIS structure disagrees"):
            audit.reference_table(refs)

    def test_recalculated_transitions_are_not_qwen_expected_answers(self):
        expected = [(9, None), (39, 63), (47, 60), (10, 37), (37, 64),
                    (10, 52), (1, 2), (2, 1), (37, 6), (47, 22)]
        for case, pair in zip(self.cases, expected):
            result = case["result"]
            self.assertEqual((result["primary_hexagram"]["king_wen_number"],
                              (result["relating_hexagram"] or {}).get("king_wen_number")), pair)

    def test_every_four_type_six_line_combination_matches_runtime_mechanics(self):
        coins = {6: [2, 2, 2], 7: [2, 2, 3], 8: [2, 3, 3], 9: [3, 3, 3]}
        executed = 0
        for lines in itertools.product(range(6, 10), repeat=6):
            throws = [coins[line] for line in lines]
            result = audit.calculate(throws, self.table)
            runtime = runtime_calculate(throws)
            for field in ("lines_bottom_up", "yin_yang_bottom_up", "moving_lines",
                          "transformed_lines_bottom_up"):
                self.assertEqual(result[field], runtime[field], (lines, field))
            primary = result["primary_hexagram"]["lines_binary"]
            secondary = [int(line % 2 == 1) for line in result["transformed_lines_bottom_up"]]
            flipped = [i + 1 for i, (before, after) in enumerate(zip(primary, secondary)) if before != after]
            self.assertEqual(flipped, result["moving_lines"])
            self.assertTrue(all(line in (7, 8) for line in result["transformed_lines_bottom_up"]))
            executed += 1
        self.assertEqual(executed, 4096)

    def test_all_eight_ordered_coin_combinations(self):
        for coins in itertools.product((2, 3), repeat=3):
            result = audit.calculate([list(coins)] * 6, self.table)
            self.assertEqual(result["lines_bottom_up"], [sum(coins)] * 6)

    def test_invalid_coins_and_input_shapes_fail(self):
        invalid = [None, [], [[2, 2, 2]] * 5, [[2, 2]] * 6,
                   [[2, 3, True]] * 6, [[2, 3, 2.0]] * 6, [[2, 3, 4]] * 6]
        for throws in invalid:
            with self.assertRaises(ValueError):
                audit.calculate(throws, self.table)

    def test_eight_inputs_preserved_and_new_ids_cover_missing_cases(self):
        original = json.loads(audit.INPUT.read_text(encoding="utf-8"))["cases"]
        for source, corrected in zip(original, self.cases[:8]):
            self.assertEqual(corrected["input"], source["input"])
            self.assertEqual(corrected["original_label"], source["label"])
        self.assertEqual(len({case["id"] for case in self.cases}), 10)
        self.assertEqual({case["result"]["moving_count"] for case in self.cases}, set(range(7)))
        self.assertEqual(self.cases[4]["result"]["moving_count"], 5)
        self.assertEqual(self.cases[8]["result"]["moving_count"], 4)
        self.assertEqual(self.cases[9]["result"]["moving_count"], 6)
        self.assertNotIn(self.cases[9]["result"]["primary_hexagram"]["king_wen_number"], (1, 2))

    def test_five_changes_uses_stable_line_in_resulting_hexagram(self):
        for index, number in ((4, 64), (5, 52)):
            rule = self.cases[index]["result"]["reading_rule"]
            self.assertEqual(rule["status"], "VERIFIED_SOURCE")
            self.assertEqual(rule["ruling_texts"], [{"type": "line", "hexagram": number, "line_number": 6}])
            self.assertEqual(rule["citation"]["pdf_page"], 65)
            self.assertEqual(rule["priority"], "stable_line_in_relating")

    def test_four_changes_lower_stable_line_is_predominant(self):
        rule = self.cases[8]["result"]["reading_rule"]
        self.assertEqual(rule["ruling_texts"][0], {"type": "line", "hexagram": 6,
                                                  "line_number": 5, "priority": "predominant"})
        self.assertEqual(rule["ruling_texts"][1]["line_number"], 6)
        self.assertNotIn("priority", rule["ruling_texts"][1])

    def test_unresolved_three_and_special_six_do_not_get_invented_rules(self):
        for index in (3, 6, 7):
            result = self.cases[index]["result"]
            self.assertEqual(result["reading_rule"]["status"], "BLOCKED_SOURCE")
            self.assertEqual(result["reading_rule"]["ruling_texts"], [])
            self.assertIsNone(result["reading_rule"]["priority"])
            self.assertEqual(result["interpretation_status"], "ABSTAIN")
        ordinary = self.cases[9]["result"]["reading_rule"]
        self.assertEqual(ordinary["ruling_texts"], [{"type": "judgment", "hexagram": 22}])

    def test_procedure_status_is_separate_from_claims_and_corpus(self):
        for case in self.cases:
            result = case["result"]
            self.assertEqual(result["procedure_status"], "OK")
            self.assertEqual(result["claims"], [])
            self.assertEqual(result["interpretation_status"], "ABSTAIN")
            self.assertFalse(result["runtime_changed"])
            self.assertEqual(result["reading_rule"]["text_corpus_status"], "EDITION_CONFLICT")

    def test_every_qwen_field_is_accounted_for(self):
        source = json.loads(audit.INPUT.read_text(encoding="utf-8"))["cases"]
        diffs = self.outputs["discrepancies.json"]["cases"]
        for case, differences in zip(source, diffs):
            self.assertEqual({path for path, _ in audit.leaves(case["qwen_expected_unverified"])},
                             {item["field"] for item in differences["comparisons"]})
        mismatches = {item["field"] for item in diffs[5]["comparisons"] if item["status"] == "MISMATCH"}
        self.assertIn("reading_rule.ruling_texts[0].hexagram", mismatches)
        self.assertIn("reading_rule.priority", mismatches)

    def test_raw_example_detects_placeholders_and_reversed_polarities(self):
        raw = self.outputs["discrepancies.json"]["current_raw_result_audit"]
        self.assertFalse(raw["valid_json"])
        self.assertTrue(raw["contains_placeholders"])
        self.assertEqual(raw["contradictory_positions"], [1, 2])

    def test_saved_results_are_reproducible_offline(self):
        for filename, output in self.outputs.items():
            self.assertEqual(json.loads((audit.AUDIT / filename).read_text(encoding="utf-8")), output)
        result = subprocess.run([sys.executable, str(audit.ROOT / "scripts/yijing_audit.py"), "--check"],
                                cwd="/tmp", capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
