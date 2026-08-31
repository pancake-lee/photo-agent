import pathlib
import tempfile
import unittest
import unittest.mock

import yaml

import cli.photo_agent as photo_agent
import infra.token_tracker as token_tracker


class TokenTrackerTest(unittest.TestCase):
    def test_uses_yuan_per_million_tokens(self):
        with tempfile.TemporaryDirectory() as directory:
            tracker = token_tracker.TokenTracker(pathlib.Path(directory, "tokens.db").as_posix(), {"m": {"input": 2, "output": 4}})
            self.assertEqual(tracker.record("m", 1_000_000, 500_000), 4)
            self.assertEqual(tracker.record_embedding("m", 500_000), 1)

    def test_rejects_invalid_price_configuration_and_missing_model(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml") as file:
            yaml.safe_dump({"currency": "USD", "unit": "yuan_per_million_tokens", "models": {"m": {"input": 1}}}, file)
            file.flush()
            with self.assertRaises(ValueError):
                token_tracker.load_prices(file.name)
        with self.assertRaisesRegex(ValueError, "缺少"):
            token_tracker.validate_model_prices({"m": {"input": 1}}, "m", "missing")

    def test_marks_usage_without_price_configuration_as_untracked(self):
        with tempfile.TemporaryDirectory() as directory:
            tracker = token_tracker.TokenTracker(pathlib.Path(directory, "tokens.db").as_posix())
            self.assertFalse(tracker.pricing_available)
            self.assertEqual(tracker.record("m", 1_000_000, 1_000_000), 0)
            summary = tracker.summary()
            self.assertEqual(summary[0]["cost_tracked"], 0)
            self.assertEqual(summary[0]["total_cost"], 0)

    def test_price_configuration_failures_do_not_block_agent_initialization(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)

            class Config:
                prices_path = ""
                llm_model = "llm"
                llm_fallback_model = ""
                embedding_model = "embedding"
                retry_enabled = True
                retry_max_attempts = 3

                @staticmethod
                def resolve_path(path: str) -> pathlib.Path:
                    return pathlib.Path(path)

                @staticmethod
                def agent_path(*parts: str) -> pathlib.Path:
                    return root.joinpath("agent", *parts)

            cases = {
                "missing": root / "missing.yaml",
                "malformed": root / "malformed.yaml",
                "invalid_structure": root / "invalid-structure.yaml",
                "missing_model": root / "missing-model.yaml",
            }
            cases["malformed"].write_text("models: [invalid", encoding="utf-8")
            cases["invalid_structure"].write_text(
                "currency: CNY\nunit: yuan_per_million_tokens\nmodels: {}\n",
                encoding="utf-8",
            )
            cases["missing_model"].write_text(
                "currency: CNY\nunit: yuan_per_million_tokens\n"
                "models:\n  llm:\n    input: 1\n    output: 1\n",
                encoding="utf-8",
            )

            with unittest.mock.patch.object(photo_agent, "_get_graph", return_value=object()):
                for name, prices_path in cases.items():
                    with self.subTest(name=name):
                        Config.prices_path = prices_path.as_posix()
                        agent = photo_agent.PhotoAgent(Config())
                        self.assertFalse(agent.pricing_status["available"])
                        self.assertTrue(agent.pricing_status["error"])
                        self.assertFalse(agent.tracker.pricing_available)
