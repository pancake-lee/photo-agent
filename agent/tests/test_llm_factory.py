"""LLM 工厂的超时与重试契约回归。"""

import unittest
import unittest.mock

import infra.llm_factory as llm_factory


class LLMFactoryTest(unittest.TestCase):
    def test_disabling_retry_also_disables_sdk_retries(self):
        cfg = type("Config", (), {
            "llm_model": "test-model",
            "llm_api_key": "test-key",
            "llm_base_url": "http://test",
            "llm_request_timeout": 30.0,
            "retry_enabled": False,
            "retry_max_attempts": 3,
            "llm_fallback_model": "",
        })()
        fake_llm = unittest.mock.MagicMock()
        with unittest.mock.patch.object(
            llm_factory.lc_openai, "ChatOpenAI", return_value=fake_llm,
        ) as chat_openai:
            self.assertIs(llm_factory.create_llm(cfg), fake_llm)
        self.assertEqual(chat_openai.call_args.kwargs["max_retries"], 0)
        self.assertEqual(chat_openai.call_args.kwargs["request_timeout"], 30.0)
