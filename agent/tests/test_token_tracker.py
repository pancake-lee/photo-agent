import pathlib
import tempfile
import unittest

import yaml

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
