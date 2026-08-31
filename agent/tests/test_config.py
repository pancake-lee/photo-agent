import pathlib
import tempfile
import unittest

import yaml

import infra.config as config


class ConfigTest(unittest.TestCase):
    def test_template_uses_unified_sections(self):
        project_root = pathlib.Path(__file__).resolve().parents[2]
        cfg = config.Config(str(project_root / "configs" / "config.yaml"))

        self.assertEqual(cfg.go_backend_url, "http://127.0.0.1:10004")
        self.assertEqual(cfg.agent_addr, "0.0.0.0:10005")
        self.assertEqual(cfg.agent_url, "http://127.0.0.1:10005")
        self.assertEqual(cfg.agent_port, 10005)
        self.assertEqual(cfg.chunk_strategy, "none")
        self.assertEqual(cfg.project_root, project_root)

    def test_rejects_invalid_chunk_combination(self):
        project_root = pathlib.Path(__file__).resolve().parents[2]
        data = yaml.safe_load((project_root / "configs" / "config.yaml").read_text())
        data["Embedding"].update({"ChunkStrategy": "fixed_size", "ChunkSize": 10, "ChunkOverlap": 10})
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml") as file:
            yaml.safe_dump(data, file)
            file.flush()
            with self.assertRaisesRegex(ValueError, "ChunkOverlap"):
                config.Config(file.name)

    def test_template_runtime_budget_keys(self):
        project_root = pathlib.Path(__file__).resolve().parents[2]
        cfg = config.Config(str(project_root / "configs" / "config.yaml"))
        self.assertEqual(cfg.runtime_max_steps, 12)
        self.assertEqual(cfg.runtime_timeout_seconds, 300.0)
        self.assertEqual(cfg.runtime_cost_limit, 2.0)

    def test_rejects_invalid_runtime_budget(self):
        project_root = pathlib.Path(__file__).resolve().parents[2]
        data = yaml.safe_load((project_root / "configs" / "config.yaml").read_text())
        data["Agent"]["RuntimeMaxSteps"] = 0
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml") as file:
            yaml.safe_dump(data, file)
            file.flush()
            with self.assertRaisesRegex(ValueError, "RuntimeMaxSteps"):
                config.Config(file.name)


if __name__ == "__main__":
    unittest.main()
