"""Tool Calling 多轮循环测试（CQ2）。

覆盖：
- 模型多轮工具调用后给出文本，循环正常收敛并传递工具结果
- 每轮都发起工具调用时，达到配置的最大轮数（cfg.tool_max_rounds）停止，
  以不带工具的兜底调用返回总结，不死循环

运行方式:
    cd agent && .venv/bin/python -m unittest discover -s tests -v
"""

import unittest
import unittest.mock

import langchain_core.messages as lc_messages

import cli.photo_agent as photo_agent


class _FakeToolClient:
    def __init__(self):
        self.execute_calls: list[tuple[str, dict]] = []

    def get_tools(self):
        return [{"type": "function", "function": {"name": "get_timelines"}}]

    def execute(self, name, args):
        self.execute_calls.append((name, args))
        return '{"timelines":["山西"]}'


class _FakeConfig:
    go_backend_url = "http://backend.example"
    # 测试用小上限，加快兜底用例执行
    tool_max_rounds = 3


def _tool_call_msg(call_id: str = "call_1") -> lc_messages.AIMessage:
    return lc_messages.AIMessage(
        content="",
        tool_calls=[{"name": "get_timelines", "args": {}, "id": call_id}],
    )


class TestMultiRoundLoop(unittest.TestCase):
    """两轮场景：第 1 轮工具调用，第 2 轮给出文本。"""

    def test_loop_until_model_returns_text(self):
        scripted = [
            _tool_call_msg(),
            lc_messages.AIMessage(content="山西时间线共 258 张照片"),
        ]
        seen_messages: list[list] = []

        class _ScriptedLLM:
            def invoke(self, messages):
                seen_messages.append(list(messages))
                return scripted.pop(0)

        tool_client = _FakeToolClient()
        with unittest.mock.patch.object(
            photo_agent, "_get_tool_client", return_value=tool_client,
        ), unittest.mock.patch.object(
            photo_agent.llm_factory, "create_llm",
            side_effect=lambda *_args, **_kwargs: _ScriptedLLM(),
        ):
            result = photo_agent._tool_node(
                {"question": "山西旅游第一天的照片", "granularity": "photo"},
                {"configurable": {"cfg": _FakeConfig()}},
            )

        self.assertEqual(result, {"tool_answer": "山西时间线共 258 张照片"})
        self.assertEqual(len(tool_client.execute_calls), 1)
        self.assertEqual(tool_client.execute_calls[0][0], "get_timelines")
        # 第 2 轮调用时，对话中应包含第 1 轮的 AIMessage(带 tool_calls) 与 ToolMessage
        round2_messages = seen_messages[1]
        self.assertIsInstance(round2_messages[-2], lc_messages.AIMessage)
        self.assertTrue(round2_messages[-2].tool_calls)
        self.assertIsInstance(round2_messages[-1], lc_messages.ToolMessage)
        self.assertEqual(round2_messages[-1].content, '{"timelines":["山西"]}')


class TestMaxRoundsFallback(unittest.TestCase):
    """上限场景：模型每轮都发起工具调用，到达上限后兜底总结。"""

    def test_max_rounds_stops_loop_and_returns_summary(self):
        invoke_counter = {"n": 0}

        class _AlwaysToolLLM:
            def invoke(self, _messages):
                invoke_counter["n"] += 1
                return _tool_call_msg(f"call_{invoke_counter['n']}")

        plain_messages: list[list] = []

        class _PlainLLM:
            def invoke(self, messages):
                plain_messages.append(list(messages))
                return lc_messages.AIMessage(content="兜底总结")

        def _fake_create_llm(*_args, **kwargs):
            if kwargs.get("tools"):
                return _AlwaysToolLLM()
            return _PlainLLM()

        tool_client = _FakeToolClient()
        with unittest.mock.patch.object(
            photo_agent, "_get_tool_client", return_value=tool_client,
        ), unittest.mock.patch.object(
            photo_agent.llm_factory, "create_llm",
            side_effect=_fake_create_llm,
        ):
            result = photo_agent._tool_node(
                {"question": "山西旅游第一天的照片", "granularity": "photo"},
                {"configurable": {"cfg": _FakeConfig()}},
            )

        self.assertEqual(result, {"tool_answer": "兜底总结"})
        # 带工具的模型恰好调用最大轮数次，工具也执行了同样多次
        self.assertEqual(invoke_counter["n"], _FakeConfig.tool_max_rounds)
        self.assertEqual(len(tool_client.execute_calls), _FakeConfig.tool_max_rounds)
        # 兜底调用只发生一次，对话 = 初始 2 条 + 每轮 2 条 + 末尾追加的总结指令
        self.assertEqual(len(plain_messages), 1)
        self.assertEqual(
            len(plain_messages[0]),
            2 + 2 * _FakeConfig.tool_max_rounds + 1,
        )


if __name__ == "__main__":
    unittest.main()
