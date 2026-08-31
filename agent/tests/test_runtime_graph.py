import unittest
import unittest.mock

import cli.photo_agent as photo_agent
import internal.runtime.budget as rt_budget
import internal.runtime.graph as rt_graph
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
    }
    attrs.update(overrides)
    return type("Config", (), attrs)()


class _ScriptedLLM:
    """伪 LLM：决策提示词消费脚本队列，其余按提示词类型返回固定 JSON。"""

    def __init__(self, decisions: list[str]):
        self._decisions = list(decisions)
        self.decide_prompts: list[str] = []

    def invoke(self, messages):
        text = "".join(str(getattr(m, "content", m)) for m in messages)
        if "执行规划器" in text:
            self.decide_prompts.append(text)
            content = self._decisions.pop(0) if self._decisions else "{}"
        elif "时间线列表" in text:
            content = '{"timeline": "山西旅游"}'
        else:
            content = '{"selected_ids": ["b", "c"]}'
        resp = unittest.mock.MagicMock()
        resp.content = content
        return resp


class RunRuntimeLoopTest(unittest.TestCase):
    """伪 LLM 驱动的循环机制测试（不依赖真实 LLM 与外部服务）。"""

    def _happy_patches(self, llm):
        photos = [
            {"id": "a", "filename": "a.jpg", "description": "寺庙", "burst_group_id": "g1"},
            {"id": "b", "filename": "b.jpg", "description": "面馆", "burst_group_id": "g1",
             "is_burst_cover": True},
            {"id": "c", "filename": "c.jpg", "description": "山景"},
        ]
        return [
            unittest.mock.patch.object(rt_graph.llm_factory, "create_llm", return_value=llm),
            unittest.mock.patch.object(rt_graph.rt_capabilities.text_to_sql,
                                      "generate_filter_sql", return_value="SELECT id FROM photos"),
            unittest.mock.patch.object(rt_graph.rt_capabilities.text_to_sql,
                                      "execute_sql_for_ids", return_value=["a", "b", "c"]),
            unittest.mock.patch.object(rt_graph.rt_capabilities, "fetch_photos_batch",
                                      side_effect=lambda cfg, ids: [
                                          p for p in photos if p.get("id") in ids
                                      ]),
            unittest.mock.patch.object(rt_graph.rt_capabilities.post_studio, "generate_post",
                                      return_value=("山西第一天", "正文内容", [])),
        ]

    def test_full_loop_completes_with_title_and_photos(self):
        """SQL → 挑选 → 文案 三步走完，完成要件齐备后收尾。"""
        llm = _ScriptedLLM([
            '{"action": "sql_search", "params": {"query": "山西旅游 第一天"}, "reason": "先定位候选"}',
            '{"action": "select_photos", "params": {}, "reason": "挑选发布照片"}',
            '{"action": "write_post", "params": {}, "reason": "创作文案"}',
        ])
        patches = self._happy_patches(llm)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = rt_graph.run_runtime(_cfg(), "找山西旅游第一天的照片并生成发布文案")
        self.assertIn("# 山西第一天", result["answer"])
        self.assertEqual(result["compose_url"], "")
        # 决策提示词包含能力列表与任务状态摘要
        self.assertIn("能力列表", llm.decide_prompts[0])
        self.assertIn("候选照片", llm.decide_prompts[1])
        # 第三次决策发生在挑选之后，状态里应已有所选照片
        self.assertIn("已选照片", llm.decide_prompts[2])
        # 收尾照片引用带图片 URL（a 与 b 同连拍组被折叠，入选为 b、c）
        self.assertEqual(len(result["photos"]), 2)
        self.assertEqual(result["photos"][0]["image_url"], "http://backend/api/v1/photos/b/image")

    def test_budget_stop_reports_progress_and_missing(self):
        """缺要件且预算耗尽时，明确说明已完成与仍缺少的内容。"""
        llm = _ScriptedLLM([
            '{"action": "sql_search", "params": {"query": "山西"}, "reason": "检索"}',
            '{"action": "sql_search", "params": {"query": "山西 第一天"}, "reason": "再检索"}',
        ])
        patches = self._happy_patches(llm)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = rt_graph.run_runtime(
                _cfg(runtime_max_steps=2), "找山西旅游第一天的照片并生成发布文案",
            )
        self.assertIn("预算已耗尽（步数）", result["answer"])
        self.assertIn("已完成：检索候选照片", result["answer"])
        self.assertIn("仍缺少：入选照片、发布文案", result["answer"])

    def test_invalid_decision_becomes_error_observation(self):
        """无效决策（编造能力名/参数）转为失败观察，不炸循环。"""
        state = {
            "question": "q",
            "granularity": "photo",
            "task": rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "q", {"question": "q"}),
            "decision": {"action": "no_such_capability", "params": {}, "reason": ""},
            "step_no": 1,
        }
        update = rt_graph._execute_node(state, {"configurable": {"cfg": _cfg(), "llm_callbacks": []}})
        observation = update["observation"]
        self.assertEqual(observation.kind, rt_state.OBS_ERROR)
        self.assertIn("未知能力", observation.summary)

    def test_route_after_check_branches(self):
        task = rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "q", {"question": "q"})
        state = {"task": task, "stop_reason": ""}
        self.assertEqual(rt_graph._route_after_check(state), "decide")

        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_PHOTOS_SELECTED, "选中", {"ids": ["a"]},
        ), step_no=1, action="select_photos")
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_COPY_DRAFTED, "完成", {"title": "t", "content": "c"},
        ), step_no=2, action="write_post")
        self.assertEqual(rt_graph._route_after_check({"task": task, "stop_reason": ""}), "finish")

        self.assertEqual(rt_graph._route_after_check({"task": task, "stop_reason": "max_steps"}), "finish")

        overflow_task = rt_state.reduce_observation(
            rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "q", {"question": "q"}),
            rt_state.Observation(rt_state.OBS_SELECTION_OVERFLOW, "超限", {"url": "u"}),
            step_no=1, action="select_photos",
        )
        self.assertEqual(rt_graph._route_after_check({"task": overflow_task, "stop_reason": ""}), "finish")

    def test_cost_callback_accumulates_into_budget(self):
        prices = {"m": {"input": 1.0, "output": 2.0}}
        budget_state = rt_budget.BudgetState()
        callback = rt_graph._CostCallback(prices, budget_state)
        response = unittest.mock.MagicMock()
        response.llm_output = {
            "model_name": "m",
            "token_usage": {"prompt_tokens": 1_000_000, "completion_tokens": 500_000},
        }
        callback.on_llm_end(response)
        self.assertEqual(budget_state.cost_used, 2.0)

    def test_price_configuration_failure_disables_only_cost_budget(self):
        budget_state = rt_budget.BudgetState(cost_used=2.0)
        state = {
            "task": rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "q", {"question": "q"}),
            "budget_state": budget_state,
            "step_no": 1,
        }
        result = rt_graph._check_node(
            state,
            {"configurable": {"cfg": _cfg(runtime_cost_limit=1.0), "pricing_available": False}},
        )
        self.assertEqual(result["stop_reason"], "")

        tracked_state = {
            "task": rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "q", {"question": "q"}),
            "budget_state": rt_budget.BudgetState(cost_used=2.0),
            "step_no": 1,
        }
        tracked_result = rt_graph._check_node(
            tracked_state,
            {"configurable": {"cfg": _cfg(runtime_cost_limit=1.0), "pricing_available": True}},
        )
        self.assertEqual(tracked_result["stop_reason"], "cost")


    def test_trace_events_reconstruct_full_trajectory(self):
        """一次开放目标请求的完整轨迹可在 trace 中还原。"""
        import json
        import pathlib
        import tempfile

        import internal.evals.tracer as tracer_mod

        llm = _ScriptedLLM([
            '{"action": "resolve_trip", "params": {}, "reason": "先定位旅行"}',
            '{"action": "sql_search", "params": {"query": "山西旅游"}, "reason": "检索"}',
            '{"action": "select_photos", "params": {}, "reason": "挑选"}',
            '{"action": "write_post", "params": {}, "reason": "文案"}',
        ])
        patches = self._happy_patches(llm)
        timelines_patch = unittest.mock.patch.object(
            rt_graph.rt_capabilities, "_fetch_timelines", return_value=["山西旅游", "北京街拍"],
        )
        with tempfile.TemporaryDirectory() as tmp, \
                patches[0], patches[1], patches[2], patches[3], patches[4], timelines_patch:
            tracer = tracer_mod.Tracer(project_root=tmp, agent_data_dir=tmp)
            rt_graph.run_runtime(
                _cfg(), "找山西旅游第一天的照片并生成发布文案", tracer=tracer,
            )
            log_path = pathlib.Path(tmp) / "execution-traces" / f"{tracer._today_str()}.jsonl"
            events = [json.loads(line) for line in log_path.read_text().splitlines()]

        runtime_events = [e for e in events if e["event"].startswith("runtime.")]
        by_name = {}
        for event in runtime_events:
            by_name.setdefault(event["event"], []).append(event["data"])
        # 每步四个事件（decide/execute/observe/check），收尾一个轨迹摘要
        self.assertEqual(len(by_name["runtime.decide"]), 4)
        self.assertEqual(len(by_name["runtime.execute"]), 4)
        self.assertEqual(len(by_name["runtime.observe"]), 4)
        self.assertEqual(len(by_name["runtime.check"]), 4)
        self.assertEqual(len(by_name["runtime.trace_summary"]), 1)
        # 摘要可还原步数、能力调用与状态变化
        summary = by_name["runtime.trace_summary"][0]
        self.assertEqual(summary["steps_used"], 4)
        self.assertEqual(summary["capability_calls"], {
            "resolve_trip": 1, "sql_search": 1, "select_photos": 1, "write_post": 1,
        })
        self.assertEqual(summary["milestones_done"], ["locate", "candidates", "select", "copy"])
        self.assertTrue(summary["complete"])
        self.assertEqual(summary["photo_count"], 2)
        # 观察事件带状态计数（检索后候选 3、挑选后已选 2）
        observes = by_name["runtime.observe"]
        self.assertEqual(observes[1]["candidate_count"], 3)
        self.assertEqual(observes[2]["selected_count"], 2)


class EntryRoutingTest(unittest.TestCase):
    """入口分类分流：开放目标进 Runtime，query_type 标注 runtime。"""

    def test_classify_maps_runtime_and_compose(self):
        for raw in ("runtime", "compose"):
            fake = unittest.mock.MagicMock()
            # prompt | llm 链会以可调用方式使用 mock，两条路径都给出分类文本
            fake.content = raw
            fake.return_value.content = raw
            with unittest.mock.patch.object(photo_agent.llm_factory, "create_llm",
                                            return_value=fake):
                update = photo_agent._classify_node(
                    {"question": "找山西旅游第一天的照片并生成发布文案"},
                    {"configurable": {"cfg": _cfg()}},
                )
            self.assertEqual(update["query_type"], "runtime")

    def test_runtime_node_maps_result_into_router_state(self):
        cfg = _cfg()
        with unittest.mock.patch.object(
            photo_agent.rt_graph, "run_runtime",
            return_value={"answer": "# 标题", "photos": [{"photo_id": "a"}], "compose_url": ""},
        ) as run:
            update = photo_agent._runtime_node(
                {"question": "发帖", "granularity": "fine"},
                {"configurable": {"cfg": cfg, "prices": {}}},
            )
        self.assertEqual(update["answer"], "# 标题")
        self.assertEqual(update["photos"], [{"photo_id": "a"}])
        self.assertEqual(update["compose_url"], "")
        run.assert_called_once()
        self.assertEqual(run.call_args[0][0], cfg)
        self.assertEqual(run.call_args[1]["granularity"], "fine")

    def test_outer_route_graph_injects_config_into_runtime_node(self):
        """编译后的外层图能进入 Runtime，防止节点配置注入约定回归。"""
        cfg = _cfg()
        fake = unittest.mock.MagicMock()
        fake.return_value.content = "runtime"
        initial = {
            "question": "找山西旅游第一天的照片并生成发布文案",
            "granularity": "photo",
            "query_type": "",
            "sql_result": {},
            "rag_answer": "",
            "tool_answer": "",
            "combined_result": {},
            "answer": "",
            "photos": [],
            "compose_url": "",
        }
        previous_graph = photo_agent._graph_app
        photo_agent._graph_app = None
        try:
            with unittest.mock.patch.object(
                photo_agent.llm_factory, "create_llm", return_value=fake,
            ), unittest.mock.patch.object(
                photo_agent.rt_graph, "run_runtime",
                return_value={"answer": "# 山西第一天", "photos": [{"photo_id": "a"}], "compose_url": ""},
            ) as run:
                result = photo_agent._get_graph().invoke(initial, {
                    "configurable": {"cfg": cfg, "prices": {}},
                })
        finally:
            photo_agent._graph_app = previous_graph

        self.assertEqual(result["query_type"], "runtime")
        self.assertEqual(result["answer"], "# 山西第一天")
        self.assertEqual(result["photos"], [{"photo_id": "a"}])
        run.assert_called_once()

    def test_answer_node_runtime_branch_appends_handoff(self):
        update = photo_agent._answer_node({
            "query_type": "runtime",
            "answer": "候选照片过多，请进入图文工坊自选后生成文案。",
            "photos": [],
            "compose_url": "#/post-studio?photo_ids=a,b",
        })
        self.assertIn("[进入图文工坊](#/post-studio?photo_ids=a,b)", update["answer"])


if __name__ == "__main__":
    unittest.main()
