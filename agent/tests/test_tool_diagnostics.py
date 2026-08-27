"""通用 Tool Calling 诊断日志测试（unittest 风格）。

运行方式（项目统一用 unittest，见 docs/archive/v1.0.13.md）:
    cd agent && .venv/bin/python -m unittest discover -s tests -v
"""

import logging
import unittest
import unittest.mock

import chain.photo_agent as photo_agent
import tools.openapi_client as openapi_client


class _FakeToolClient:
    def get_tools(self):
        return [{"type": "function", "function": {"name": "get_timelines"}}]


class _FakeResponse:
    content = "让我换个方式查询"
    tool_calls = []


class _FakeLLM:
    def invoke(self, _messages):
        return _FakeResponse()


class _FakeConfig:
    go_backend_url = "http://backend.example"
    tool_max_rounds = 20


class TestToolNodeDiagnostics(unittest.TestCase):

    def test_tool_node_logs_when_model_skips_tool(self):
        with unittest.mock.patch.object(
            photo_agent, "_get_tool_client", return_value=_FakeToolClient(),
        ), unittest.mock.patch.object(
            photo_agent.llm_factory, "create_llm",
            side_effect=lambda *_args, **_kwargs: _FakeLLM(),
        ), self.assertLogs("chain.photo_agent", level=logging.INFO) as captured:
            result = photo_agent._tool_node(
                {"question": "列出时间线", "granularity": "photo"},
                {"configurable": {"cfg": _FakeConfig()}},
            )

        self.assertEqual(result, {"tool_answer": "让我换个方式查询"})
        text = "\n".join(captured.output)
        self.assertIn("工具已加载: count=1", text)
        self.assertIn("第 1 轮模型未发起工具调用，直接返回文本", text)


class _FakeHTTPResponse:
    status_code = 200
    text = '{"timelines":["山西"]}'

    def raise_for_status(self):
        return None


class _FakeHTTPClient:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def get(self, _url, params):
        assert params == {}
        return _FakeHTTPResponse()


class TestOpenAPIClientDiagnostics(unittest.TestCase):

    def test_openapi_client_logs_successful_tool_request(self):
        client = openapi_client.OpenAPIClient.__new__(openapi_client.OpenAPIClient)
        client.base_url = "http://backend.example"
        client._tool_map = {
            "get_timelines": ("GET", "/timelines", {"parameters": []}),
        }
        with unittest.mock.patch.object(
            openapi_client.http_utils, "create_client",
            return_value=_FakeHTTPClient(),
        ), self.assertLogs("tools.openapi_client", level=logging.INFO) as captured:
            result = client.execute("get_timelines", {})

        self.assertEqual(result, '{"timelines":["山西"]}')
        self.assertIn(
            "工具请求完成: name=get_timelines, status=200",
            "\n".join(captured.output),
        )


if __name__ == "__main__":
    unittest.main()
