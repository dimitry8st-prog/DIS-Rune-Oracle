"""Synthetic manual observations for the audited Shakuna and Slavic inputs."""

from copy import deepcopy
import unittest

from dis_oracle.adapters.audited_inputs import card
from dis_oracle.contracts import ContractError, digest
from tests.test_audited_inputs import fixture


class ObservationInputTests(unittest.TestCase):
    def test_shakuna_preserves_declared_observation_and_evidence(self):
        config = fixture()["adapters"]["shakuna"]
        observation = deepcopy(config["observation"])
        observation["observed_at"] = "2025-12-31T15:00:00+03:00"
        observation["evidence_ref"] = "SYNTHETIC field notes #1"
        config["observation"] = deepcopy(observation)

        result = card("shakuna", "synthetic", config)

        self.assertEqual(result["status"], "ABSTAIN")
        self.assertEqual(result["reason"], "NO_SOURCE_VERIFIED_RULE_CORPUS")
        self.assertEqual(result["claims"], [])
        self.assertEqual(result["input_hash"], digest(result["inputs"]))
        self.assertEqual(result["raw_result"]["observation"], observation)
        self.assertEqual(result["raw_result"]["observation_evidence_status"], "USER_DECLARED_NOT_AUTHENTICATED")

    def test_shakuna_rejects_invalid_observation_attributes(self):
        original = fixture()["adapters"]["shakuna"]
        invalid = (
            ("object", " "), ("action", 10), ("direction", []), ("side", {}),
            ("observed_at", "2025-12-31T15:00:00"),
            ("observed_at", "2025-02-29T15:00:00Z"),
            ("observed_at", "0001-01-01T00:00:00+01:00"),
            ("location", None), ("context", ""), ("evidence_ref", " "),
        )
        for field, value in invalid:
            with self.subTest(field=field, value=value):
                config = deepcopy(original)
                config["observation"][field] = value
                with self.assertRaisesRegex(ContractError, rf"observation\.{field}"):
                    card("shakuna", "synthetic", config)

    def test_slavic_preserves_both_sources_and_marks_legacy_evidence_gaps(self):
        config = fixture()["adapters"]["slavic"]
        legacy = card("slavic", "synthetic", config)
        self.assertEqual(legacy["status"], "ABSTAIN")
        self.assertEqual(legacy["raw_result"]["observation_evidence_status"], "INCOMPLETE")
        self.assertEqual(legacy["raw_result"]["songs_missing_observation_evidence"], config["song_order"])
        self.assertNotIn("evidence_ref", legacy["inputs"]["rounds"][0])

        for index, row in enumerate(config["rounds"], start=1):
            row["evidence_ref"] = f"SYNTHETIC round {index} field notes"
        result = card("slavic", "synthetic", config)

        self.assertEqual(result["status"], "ABSTAIN")
        self.assertEqual(result["reason"], "REGIONAL_PROTOCOL_AND_SONG_CORPUS_UNVERIFIED")
        self.assertEqual(result["claims"], [])
        self.assertEqual(result["input_hash"], digest(result["inputs"]))
        self.assertEqual(result["inputs"]["rounds"], config["rounds"])
        self.assertEqual(result["raw_result"]["observed_rounds"], config["rounds"])
        self.assertEqual(result["raw_result"]["observation_evidence_status"], "USER_DECLARED_NOT_AUTHENTICATED")
        self.assertEqual(result["raw_result"]["songs_missing_observation_evidence"], [])

    def test_slavic_rejects_invalid_round_reference_identifiers_and_timestamps(self):
        original = fixture()["adapters"]["slavic"]
        for field, value in (("song_source_ref", " "), ("evidence_ref", {}), ("item_id", []),
                             ("participant_id", 7), ("drawn_at", "2025-12-31T10:01:10"),
                             ("returned_at", "9999-12-31T23:59:59-01:00")):
            with self.subTest(field=field):
                config = deepcopy(original)
                config["rounds"][0][field] = value
                with self.assertRaisesRegex(ContractError, rf"rounds\[0\]\.{field}"):
                    card("slavic", "synthetic", config)

    def test_slavic_checks_round_chronology_across_timezone_offsets(self):
        config = fixture()["adapters"]["slavic"]
        config["rounds"][0]["drawn_at"] = "2025-12-31T13:01:10+03:00"
        result = card("slavic", "synthetic", config)
        self.assertEqual(result["raw_result"]["procedure_status"], "OBSERVATIONS_RECORDED")

        config["rounds"][0]["drawn_at"] = "2025-12-31T13:01:10+02:00"
        with self.assertRaisesRegex(ContractError, "chronology"):
            card("slavic", "synthetic", config)
