import types
import unittest
import unittest.mock
import pathlib
import tempfile

import cli.photo_agent as photo_agent
import infra.llm_factory as llm_factory
import infra.request_metrics as request_metrics


class RequestMetricsTest(unittest.TestCase):
    def test_callback_aggregates_tokens_and_cost_for_current_request(self):
        usage, token = request_metrics.begin_request({"model-a": {"input": 2, "output": 4}})
        try:
            callback = request_metrics.current_callbacks()[0]
            response = types.SimpleNamespace(
                llm_output={
                    "model_name": "model-a",
                    "token_usage": {"prompt_tokens": 1_000_000, "completion_tokens": 500_000},
                },
                model_name="",
            )
            callback.on_llm_end(response)
            self.assertEqual(usage.snapshot(), {
                "input_tokens": 1_000_000,
                "output_tokens": 500_000,
                "cost": 4.0,
                "llm_calls": 1,
                "cost_tracked": True,
            })
        finally:
            request_metrics.end_request(token)

    def test_outside_chat_request_no_callback_is_attached(self):
        self.assertEqual(request_metrics.current_callbacks(), [])

    def test_llm_factory_attaches_current_request_callback(self):
        class Config:
            llm_model = "model-a"
            llm_api_key = "key"
            llm_base_url = "http://example.test"
            llm_request_timeout = 10
            retry_enabled = False
            retry_max_attempts = 1
            llm_fallback_model = ""

        created = []

        class FakeLLM:
            def __init__(self, **kwargs):
                created.append(kwargs)

        usage, token = request_metrics.begin_request({"model-a": {"input": 1, "output": 1}})
        try:
            with unittest.mock.patch.object(llm_factory.lc_openai, "ChatOpenAI", FakeLLM):
                llm_factory.create_llm(Config())
            callback = created[0]["callbacks"][0]
            callback.on_llm_end(types.SimpleNamespace(
                llm_output={"model_name": "model-a", "token_usage": {"prompt_tokens": 3, "completion_tokens": 5}},
                model_name="",
            ))
            self.assertEqual(usage.snapshot()["input_tokens"], 3)
            self.assertEqual(usage.snapshot()["output_tokens"], 5)
        finally:
            request_metrics.end_request(token)

    def test_route_emits_request_level_execution_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)

            class Config:
                prices_path = ""
                llm_model = "llm"
                llm_fallback_model = ""
                embedding_model = "embedding"
                retry_enabled = False
                retry_max_attempts = 1

                @staticmethod
                def resolve_path(path):
                    return root / path

                @staticmethod
                def agent_path(*parts):
                    return root.joinpath(*parts)

            graph = unittest.mock.MagicMock()
            graph.invoke.return_value = {
                "query_type": "sql", "execution_status": "completed",
                "runtime_terminal_reason": "", "answer": "3", "photos": [],
            }
            tracer = unittest.mock.MagicMock()
            with unittest.mock.patch.object(photo_agent, "_get_graph", return_value=graph):
                agent = photo_agent.PhotoAgent(Config())
                result = agent.route("昨天拍了多少张？", tracer=tracer)

        event, data = tracer.emit.call_args.args[0:2]
        self.assertEqual(event, "chat.execution_summary")
        self.assertEqual(data["execution_mode"], "direct_sql")
        self.assertEqual(data["execution_status"], "completed")
        self.assertIn("duration_ms", data)
        self.assertEqual(result["request_usage"]["llm_calls"], 0)
