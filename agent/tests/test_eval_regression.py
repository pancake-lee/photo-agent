import json
import unittest
from pathlib import Path

from scripts import eval_regression


class TestEvalRegressionSeeds(unittest.TestCase):
    def test_seed_cases_cover_retrieval_and_all_granularities(self):
        cases = eval_regression._load_cases(
            Path(__file__).parents[2] / "data/eval_seed_cases.json"
        )
        self.assertEqual({case["id"] for case in cases}, {
            "retrieval-buddha-person",
            "burst-buddha-person",
        })
        burst = next(case for case in cases if case["id"] == "burst-buddha-person")
        self.assertEqual(
            set(burst["levels"]["L1"]["expected_top_photo_ids"]),
            {"photo", "fine", "coarse"},
        )

    def test_seed_cases_are_json_serializable(self):
        path = Path(__file__).parents[2] / "data/eval_seed_cases.json"
        self.assertIsInstance(json.loads(path.read_text(encoding="utf-8")), list)

    def test_filename_normalization(self):
        self.assertEqual(eval_regression._normalize_filename("DSC_2215.jpg"), "DSC_2215")
        self.assertEqual(eval_regression._normalize_filename("DSC_2215.nef"), "DSC_2215")
