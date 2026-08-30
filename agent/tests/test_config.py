import pathlib
import unittest

import config


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


if __name__ == "__main__":
    unittest.main()
