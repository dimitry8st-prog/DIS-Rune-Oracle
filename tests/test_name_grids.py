import unittest

from dis_oracle.adapters.audited_inputs import card
from dis_oracle.contracts import ContractError, digest


def declared_strokes(surname, given_name, surname_strokes, given_strokes):
    return {
        "mode": "manual_strokes",
        "profile": "author-five-grid-arithmetic-v1",
        "surname": surname,
        "given_name": given_name,
        "surname_strokes": surname_strokes,
        "given_strokes": given_strokes,
        "stroke_standard": "SYNTHETIC declared counts",
        "evidence_ref": "SYNTHETIC arithmetic fixture",
    }


class FiveGridAuthorProfileTests(unittest.TestCase):
    def test_all_five_grids_for_each_name_length_case(self):
        # Synthetic controls for the fixed author profile, including the audit counterexample.
        controls = (
            ("山田", "一二", [3, 5], [1, 2], (8, 6, 3, 5, 11)),
            ("山", "一二", [3], [1, 2], (4, 4, 3, 3, 6)),
            ("山田", "一", [3, 5], [1], (8, 6, 2, 4, 9)),
            ("山", "一", [3], [1], (4, 4, 2, 2, 4)),
        )
        grids = ("tenkaku", "jinkaku", "chikaku", "gaikaku", "sokaku")
        for surname, given_name, surname_strokes, given_strokes, expected in controls:
            with self.subTest(surname=surname, given_name=given_name):
                config = declared_strokes(surname, given_name, surname_strokes, given_strokes)
                result = card("name_grids", "test-event", config)
                self.assertEqual(result["raw_result"]["grids"], dict(zip(grids, expected)))
                self.assertEqual(result["status"], "ABSTAIN")
                self.assertEqual(result["claims"], [])

    def test_exact_ideographs_and_stroke_provenance_are_preserved(self):
        config = declared_strokes("𠮷", "﨑", [6], [11])
        result = card("name_grids", "test-event", config)
        self.assertEqual(result["inputs"], {"event_id": "test-event", **config})
        self.assertEqual(result["input_hash"], digest(result["inputs"]))
        self.assertEqual(result["raw_result"]["stroke_provenance"], {
            "profile": "author-five-grid-arithmetic-v1",
            "stroke_standard": "SYNTHETIC declared counts",
            "evidence_ref": "SYNTHETIC arithmetic fixture",
        })
        self.assertEqual(result["raw_result"]["stroke_verification"], "USER_DECLARED_NOT_AUTHENTICATED")
        self.assertEqual(result["raw_result"]["grids"]["sokaku"], 17)

    def test_missing_provenance_or_unsupported_character_is_rejected(self):
        for field in ("profile", "stroke_standard", "evidence_ref", "surname_strokes", "given_strokes"):
            with self.subTest(missing=field):
                config = declared_strokes("山", "一", [3], [1])
                del config[field]
                with self.assertRaisesRegex(ContractError, field):
                    card("name_grids", "test-event", config)
        for invalid_name in ("山々", "Иванов", "あ", "𠮷\ufe00"):
            with self.subTest(given_name=invalid_name):
                config = declared_strokes("山", invalid_name, [3], [1])
                with self.assertRaisesRegex(ContractError, "given_name must contain only explicit CJK ideographs"):
                    card("name_grids", "test-event", config)
