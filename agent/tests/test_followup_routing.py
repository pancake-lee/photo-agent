"""V4 跟进消息识别与全路径接入测试（AR4-2）。

全部使用伪 LLM 与 mock 能力，不依赖真实 LLM 与外部服务。
"""

import unittest
import unittest.mock

import cli.photo_agent as photo_agent
import internal.runtime.state as rt_state


def _cfg(**overrides):
    attrs = {
        "go_backend_url": "http://backend",
        "compose_group_limit": 20,
        "compose_cover_limit": 40,
        "rag_distance_threshold": None,
        "rag_auto_distance_ratio": 1.8,
        "runtime_max_steps": 6,
        "runtime_timeout_seconds": 300.0,
        "runtime_cost_limit": 2.0,
        "runtime_retry_max": 2,
        "runtime_repair_max": 2,
        "runtime_redecide_max": 2,
    }
    attrs.update(overrides)
    return type("Config", (), attrs)()


def _queue_llm(contents: list[str]) -> tuple[unittest.mock.MagicMock, list[str]]:
    """伪 LLM（MagicMock，可进入 prompt | llm 管道）。

    管道把 MagicMock 当可调用对象包装，调用走 mock 本体而非 .invoke，
    因此脚本消费挂在 side_effect 上；按调用次序返回脚本回复，
    并把渲染后的提示词全文记入 prompts 列表。
    """
    prompts: list[str] = []
    remaining = list(contents)

    def call(value, *args, **kwargs):
        messages = getattr(value, "messages", value)
        prompts.append("".join(str(getattr(m, "content", m)) for m in messages))
        resp = unittest.mock.MagicMock()
        resp.content = remaining.pop(0) if remaining else ""
        return resp

    llm = unittest.mock.MagicMock()
    llm.side_effect = call
    return llm, prompts


def _state(**overrides) -> dict:
    """构造 classify/resolve 节点所需的最小 RouterState。"""
    base = {
        "question": "不要那么文艺",
        "history_block": "[最近会话]\n用户：找山西旅游第一天的照片并生成发布文案",
        "effective_question": "不要那么文艺",
        "followup": False,
        "granularity": "photo",
        "runtime_affected": [],
        "runtime_prior_task_json": "",
    }
    base.update(overrides)
    return base


class ClassifyFollowupTest(unittest.TestCase):
    """分类节点：有历史时可识别 followup，无历史行为不变。"""

    def test_history_and_followup_label_routes_to_followup(self):
        llm, prompts = _queue_llm(["followup"])
        with unittest.mock.patch.object(photo_agent.llm_factory, "create_llm", return_value=llm):
            update = photo_agent._classify_node(_state(), {"configurable": {"cfg": _cfg()}})
        self.assertEqual(update["query_type"], "followup")
        # 有历史时提示词包含 followup 标签与会话历史块
        self.assertIn("followup:", prompts[0])
        self.assertIn("会话历史", prompts[0])
        self.assertIn("山西旅游第一天", prompts[0])

    def test_without_history_followup_label_falls_back_to_rag(self):
        """无历史时不启用 followup 分支（首条消息行为与 V3 完全一致）。"""
        llm, prompts = _queue_llm(["followup"])
        with unittest.mock.patch.object(photo_agent.llm_factory, "create_llm", return_value=llm):
            update = photo_agent._classify_node(
                _state(question="不要那么文艺", history_block=""),
                {"configurable": {"cfg": _cfg()}},
            )
        self.assertEqual(update["query_type"], "rag")
        self.assertNotIn("followup:", prompts[0])
        self.assertNotIn("会话历史", prompts[0])

    def test_history_with_normal_label_still_classifies(self):
        llm, prompts = _queue_llm(["sql"])
        with unittest.mock.patch.object(photo_agent.llm_factory, "create_llm", return_value=llm):
            update = photo_agent._classify_node(
                _state(question="我有多少张照片？"),
                {"configurable": {"cfg": _cfg()}},
            )
        self.assertEqual(update["query_type"], "sql")


class FollowupResolveTest(unittest.TestCase):
    """跟进消解节点：改写 + 路径 + 受影响部分（LLM 输出程序校验）。"""

    def _resolve(self, content: str) -> tuple[dict, str]:
        llm, prompts = _queue_llm([content])
        with unittest.mock.patch.object(photo_agent.llm_factory, "create_llm", return_value=llm):
            update = photo_agent._followup_resolve_node(_state(), {"configurable": {"cfg": _cfg()}})
        return update, prompts[0]

    def test_happy_path_runtime_followup(self):
        content = ('{"rewritten": "找山西旅游第一天的照片并生成发布文案，文案风格平实不要文艺", '
                   '"target": "runtime", "affected": ["copy"], "goal_type": "social_post"}')
        update, prompt = self._resolve(content)
        self.assertEqual(update["query_type"], "runtime")
        self.assertEqual(update["effective_question"], "找山西旅游第一天的照片并生成发布文案，文案风格平实不要文艺")
        self.assertEqual(update["runtime_affected"], ["copy"])
        self.assertTrue(update["followup"])
        self.assertEqual(update["runtime_goal_type"], rt_state.GOAL_SOCIAL_POST)
        # 消解提示词包含历史块与用户消息
        self.assertIn("会话历史", prompt)
        self.assertIn("不要那么文艺", prompt)

    def test_invalid_target_falls_back_to_rag_with_original_question(self):
        content = '{"rewritten": "改写", "target": "no_such_path", "affected": []}'
        update, _ = self._resolve(content)
        self.assertEqual(update["query_type"], "rag")
        self.assertEqual(update["effective_question"], "改写")

    def test_affected_filtered_to_vocabulary(self):
        content = '{"rewritten": "改写", "target": "runtime", "affected": ["copy", "no_such_part"]}'
        update, _ = self._resolve(content)
        self.assertEqual(update["runtime_affected"], ["copy"])

    def test_non_json_output_degrades_gracefully(self):
        update, _ = self._resolve("这不是 JSON")
        self.assertEqual(update["query_type"], "rag")
        self.assertEqual(update["effective_question"], "不要那么文艺")


class EffectiveQuestionTest(unittest.TestCase):
    """五条下游路径统一消费 effective_question（首条消息等于原问题）。"""

    def test_sql_node_consumes_effective_question(self):
        with unittest.mock.patch.object(
            photo_agent.text_to_sql, "answer_with_sql", return_value={"answer": "a", "results": []},
        ) as sql:
            photo_agent._sql_node(
                _state(question="原始", effective_question="改写后的独立问题"),
                {"configurable": {"cfg": _cfg()}},
            )
        sql.assert_called_once_with(unittest.mock.ANY, "改写后的独立问题")

    def test_rag_node_consumes_effective_question(self):
        with unittest.mock.patch.object(
            photo_agent.photo_rag, "answer_question", return_value=("答案", []),
        ) as rag:
            photo_agent._rag_node(
                _state(question="原始", effective_question="改写后的独立问题"),
                {"configurable": {"cfg": _cfg()}},
            )
        rag.assert_called_once()
        self.assertEqual(rag.call_args.args[1], "改写后的独立问题")

    def test_defaults_to_question_when_unset(self):
        self.assertEqual(
            photo_agent._effective_question(_state(question="仅原始", effective_question="")),
            "仅原始",
        )


class RuntimeNodeResumeTest(unittest.TestCase):
    """Runtime 节点：跟进消息携带快照时续跑，快照损坏降级全新任务。"""

    def _prior_json(self) -> str:
        import json
        task = rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "旧目标", {"question": "旧目标"})
        return json.dumps(rt_state.dump_task(task), ensure_ascii=False)

    def test_followup_with_snapshot_resumes(self):
        with unittest.mock.patch.object(
            photo_agent.rt_graph, "run_runtime",
            return_value={"answer": "a", "photos": [], "compose_url": ""},
        ) as run:
            photo_agent._runtime_node(
                _state(followup=True, runtime_prior_task_json=self._prior_json(),
                       runtime_affected=["copy"]),
                {"configurable": {"cfg": _cfg(), "prices": {}}},
            )
        kwargs = run.call_args.kwargs
        self.assertIsNotNone(kwargs["prior_task"])
        self.assertEqual(kwargs["prior_task"].goal.goal_type, rt_state.GOAL_SOCIAL_POST)
        self.assertEqual(kwargs["affected"], ["copy"])

    def test_followup_with_corrupt_snapshot_runs_fresh(self):
        with unittest.mock.patch.object(
            photo_agent.rt_graph, "run_runtime",
            return_value={"answer": "a", "photos": [], "compose_url": ""},
        ) as run:
            photo_agent._runtime_node(
                _state(followup=True, runtime_prior_task_json='{"goal_type": "broken'),
                {"configurable": {"cfg": _cfg(), "prices": {}}},
            )
        self.assertIsNone(run.call_args.kwargs["prior_task"])

    def test_non_followup_never_consumes_snapshot(self):
        """普通 runtime 请求（含澄清续跑拼接串）不读快照，行为与 V3 一致。"""
        with unittest.mock.patch.object(
            photo_agent.rt_graph, "run_runtime",
            return_value={"answer": "a", "photos": [], "compose_url": ""},
        ) as run:
            photo_agent._runtime_node(
                _state(followup=False, runtime_prior_task_json=self._prior_json()),
                {"configurable": {"cfg": _cfg(), "prices": {}}},
            )
        self.assertIsNone(run.call_args.kwargs["prior_task"])

    def test_declared_goal_mismatch_runs_fresh(self):
        """消解显式声明了不同目标类型时，不在旧目标快照上续跑。"""
        with unittest.mock.patch.object(
            photo_agent.rt_graph, "run_runtime",
            return_value={"answer": "a", "photos": [], "compose_url": ""},
        ) as run:
            photo_agent._runtime_node(
                _state(followup=True, runtime_prior_task_json=self._prior_json(),
                       runtime_goal_type=rt_state.GOAL_PHOTO_COMPARISON,
                       runtime_goal_declared=True),
                {"configurable": {"cfg": _cfg(), "prices": {}}},
            )
        self.assertIsNone(run.call_args.kwargs["prior_task"])
        self.assertEqual(run.call_args.kwargs["goal_type"], rt_state.GOAL_PHOTO_COMPARISON)

    def test_undeclared_goal_keeps_snapshot_goal(self):
        """消解未显式声明目标时沿用快照目标，不受分类默认值干扰。"""
        with unittest.mock.patch.object(
            photo_agent.rt_graph, "run_runtime",
            return_value={"answer": "a", "photos": [], "compose_url": ""},
        ) as run:
            photo_agent._runtime_node(
                _state(followup=True, runtime_prior_task_json=self._prior_json(),
                       runtime_goal_type=rt_state.GOAL_SOCIAL_POST,
                       runtime_goal_declared=False),
                {"configurable": {"cfg": _cfg(), "prices": {}}},
            )
        self.assertIsNotNone(run.call_args.kwargs["prior_task"])


class FollowupGraphPathTest(unittest.TestCase):
    """路由图级：classify → followup_resolve → runtime_query 条件边真实执行。"""

    def test_followup_flows_to_runtime_through_resolve(self):
        resolve_json = ('{"rewritten": "找山西旅游第一天的照片并生成发布文案，风格平实", '
                        '"target": "runtime", "affected": ["copy"], "goal_type": "social_post"}')
        llm, prompts = _queue_llm(["followup", resolve_json])
        initial: photo_agent.RouterState = {
            "question": "不要那么文艺",
            "history_block": "[最近会话]\n用户：找山西旅游第一天的照片并生成发布文案",
            "effective_question": "不要那么文艺",
            "followup": False,
            "granularity": "photo",
            "query_type": "",
            "sql_result": {},
            "rag_answer": "",
            "tool_answer": "",
            "combined_result": {},
            "answer": "",
            "photos": [],
            "compose_url": "",
            "runtime_terminal_reason": "",
            "runtime_clarification": {},
            "runtime_goal_type": rt_state.GOAL_SOCIAL_POST,
            "runtime_affected": [],
            "runtime_goal_declared": False,
            "runtime_prior_task_json": "",
            "runtime_task_dump": "",
        }
        with (
            unittest.mock.patch.object(photo_agent.llm_factory, "create_llm", return_value=llm),
            unittest.mock.patch.object(
                photo_agent.rt_graph, "run_runtime",
                return_value={"answer": "# 新文案", "photos": [], "compose_url": "",
                              "goal_type": rt_state.GOAL_SOCIAL_POST,
                              "task_dump": {"goal_type": "social_post"}},
            ) as run,
        ):
            app = photo_agent._get_graph()
            result = app.invoke(initial, {"configurable": {"cfg": _cfg(), "prices": {}}})
        self.assertIn("# 新文案", result["answer"])
        self.assertTrue(result["followup"])
        self.assertEqual(run.call_args.kwargs["affected"], ["copy"])
        self.assertIn("风格平实", run.call_args.args[1])
        # 两次 LLM 调用：先分类（含历史与 followup 标签），后消解
        self.assertIn("followup:", prompts[0])
        self.assertIn("消解器", prompts[1])


if __name__ == "__main__":
    unittest.main()
