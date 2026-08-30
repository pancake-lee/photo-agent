import unittest
from pathlib import Path

from scripts import eval_regression


class TestEvalRegressionGoldenCases(unittest.TestCase):
    def test_marked_golden_case_covers_all_granularities(self):
        project_root = Path(__file__).parents[2]
        cases = eval_regression._load_regression_cases(
            project_root / "data/agent/retrieval-golden-queries.json",
            project_root / "configs/evaluation.yaml",
        )
        self.assertEqual([case["id"] for case in cases], ["3ccdb0321084"])
        burst = cases[0]
        self.assertEqual(
            burst["levels"]["L1"]["expected_photo_ids"]["fine"],
            ["DSC_1813", "DSC_2167"],
        )
        self.assertEqual(
            burst["levels"]["L2"]["expected_chat_filenames"]["coarse"],
            ["DSC_1813"],
        )

    def test_marked_golden_case_uses_golden_question_and_photos(self):
        project_root = Path(__file__).parents[2]
        case = eval_regression._load_regression_cases(
            project_root / "data/agent/retrieval-golden-queries.json",
            project_root / "configs/evaluation.yaml",
        )[0]
        self.assertEqual(case["question"], "佛像和人的合照1")
        self.assertIn("DSC_2215", case["levels"]["L0"]["photo_ids"])

    def test_filename_normalization(self):
        self.assertEqual(eval_regression._normalize_filename("DSC_2215.jpg"), "DSC_2215")
        self.assertEqual(eval_regression._normalize_filename("DSC_2215.nef"), "DSC_2215")
