"""V4 多轮续跑测试：任务快照序列化、局部失效与图级多轮金用例（AR4-3 / AR4-4）。"""

import json
import unittest
import unittest.mock

import internal.chat.text_to_sql as text_to_sql
import internal.posts.post_studio as post_studio
import internal.runtime.capabilities.common as caps_common
import internal.runtime.completion as rt_completion
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
        "runtime_retry_max": 2,
        "runtime_repair_max": 2,
        "runtime_redecide_max": 2,
    }
    attrs.update(overrides)
    return type("Config", (), attrs)()


class _ScriptedLLM:
    """伪 LLM：决策提示词消费脚本队列，其余按提示词类型返回固定 JSON。"""

    def __init__(self, decisions: list[str], select_response: str = '{"selected_ids": ["b", "c"]}'):
        self._decisions = list(decisions)
        self._select_response = select_response
        self.decide_prompts: list[str] = []

    def invoke(self, messages):
        text = "".join(str(getattr(m, "content", m)) for m in messages)
        if "执行规划器" in text:
            self.decide_prompts.append(text)
            content = self._decisions.pop(0) if self._decisions else "{}"
        else:
            content = self._select_response
        resp = unittest.mock.MagicMock()
        resp.content = content
        return resp


def _happy_patches(llm):
    photos = [
        {"id": "a", "filename": "a.jpg", "description": "寺庙", "burst_group_id": "g1"},
        {"id": "b", "filename": "b.jpg", "description": "面馆", "burst_group_id": "g1",
         "is_burst_cover": True},
        {"id": "c", "filename": "c.jpg", "description": "山景"},
    ]
    return [
        unittest.mock.patch.object(rt_graph.llm_factory, "create_llm", return_value=llm),
        unittest.mock.patch.object(text_to_sql,
                                  "generate_filter_sql", return_value="SELECT id FROM photos"),
        unittest.mock.patch.object(text_to_sql,
                                  "execute_sql_for_ids", return_value=["a", "b", "c"]),
        unittest.mock.patch.object(caps_common, "fetch_photos_batch",
                                  side_effect=lambda cfg, ids: [
                                      p for p in photos if p.get("id") in ids
                                  ]),
        unittest.mock.patch.object(post_studio, "generate_post",
                                  return_value=("山西第一天", "正文内容", [])),
    ]


def _completed_social_post_state() -> rt_state.TaskState:
    """构造一个已完成选片与文案的发帖任务（多轮续跑的先前状态）。"""
    state = rt_state.new_task(
        rt_state.GOAL_SOCIAL_POST, "找山西旅游第一天的照片并生成发布文案",
        {"question": "找山西旅游第一天的照片并生成发布文案"},
    )
    scope_obs = rt_state.Observation(
        rt_state.OBS_SCOPE, "范围已物化",
        {"restricted": True, "conditions": {"timeline": "山西旅游", "day": "first"},
         "condition_summary": "山西旅游第一天", "ids": ["a", "b", "c"]},
    )
    state = rt_state.reduce_observation(state, scope_obs, step_no=1, action="resolve_trip")
    ids_obs = rt_state.Observation(
        rt_state.OBS_PHOTO_IDS, "检索完成", {"ids": ["a", "b", "c"]},
    )
    state = rt_state.reduce_observation(state, ids_obs, step_no=2, action="sql_search")
    select_obs = rt_state.Observation(
        rt_state.OBS_PHOTOS_SELECTED, "已挑选", {"ids": ["b", "c"],
        "photos": [{"id": "b", "filename": "b.jpg"}, {"id": "c", "filename": "c.jpg"}]},
    )
    state = rt_state.reduce_observation(state, select_obs, step_no=3, action="select_photos")
    copy_obs = rt_state.Observation(
        rt_state.OBS_COPY_DRAFTED, "文案完成", {"title": "山西第一天", "content": "正文"},
    )
    return rt_state.reduce_observation(state, copy_obs, step_no=4, action="write_post")


class TaskDumpTest(unittest.TestCase):
    """任务快照序列化往返（AR4-3）。"""

    def test_dump_load_roundtrip_preserves_state(self):
        prior = _completed_social_post_state()
        restored = rt_state.load_task(json.loads(json.dumps(rt_state.dump_task(prior))))
        self.assertEqual(restored.goal.goal_type, prior.goal.goal_type)
        self.assertEqual(restored.goal.description, prior.goal.description)
        self.assertEqual(restored.goal.allowed_capabilities, prior.goal.allowed_capabilities)
        self.assertEqual(restored.constraints, prior.constraints)
        self.assertEqual(restored.resolved_facts, prior.resolved_facts)
        self.assertEqual(restored.scope.photo_ids, prior.scope.photo_ids)
        self.assertEqual(restored.scope.condition_summary, prior.scope.condition_summary)
        self.assertEqual(restored.artifacts.candidate_ids, prior.artifacts.candidate_ids)
        self.assertEqual(restored.artifacts.selected_ids, prior.artifacts.selected_ids)
        self.assertEqual(restored.artifacts.copy_draft, prior.artifacts.copy_draft)
        self.assertEqual(restored.progress.todo, prior.progress.todo)
        self.assertEqual(restored.progress.history, prior.progress.history)

    def test_load_rejects_unknown_goal_type(self):
        with self.assertRaises(ValueError):
            rt_state.load_task({"goal_type": "no_such_goal", "description": "x"})

    def test_load_rejects_malformed_payload(self):
        with self.assertRaises(ValueError):
            rt_state.load_task({"goal_type": "social_post", "description": "x",
                                "resolved_facts": "not-a-dict"})


class ResumeTaskTest(unittest.TestCase):
    """局部失效语义（V4 多轮修改：保留有效产物，只失效受影响部分）。"""

    def test_copy_affected_keeps_selection_and_scope(self):
        prior = _completed_social_post_state()
        resumed = rt_state.resume_task(prior, "改写为平实风格", [rt_state.AFFECT_COPY])
        self.assertEqual(resumed.progress.todo, ["copy"])
        self.assertEqual(resumed.artifacts.selected_ids, ["b", "c"])
        self.assertEqual(resumed.artifacts.candidate_ids, ["a", "b", "c"])
        self.assertTrue(resumed.scope.established)
        self.assertEqual(resumed.artifacts.copy_draft, {})
        self.assertEqual(resumed.goal.description, "改写为平实风格")

    def test_selection_affected_reopens_select_and_copy(self):
        prior = _completed_social_post_state()
        resumed = rt_state.resume_task(
            prior, "换一批照片重新挑", [rt_state.AFFECT_SELECTION],
        )
        self.assertEqual(resumed.progress.todo, ["select", "copy"])
        # 重选不设程序性保留：已选照片仅在决策摘要中可见，新选片观察整体替换
        self.assertEqual(resumed.artifacts.selected_ids, ["b", "c"])
        self.assertEqual(resumed.artifacts.preserved_selected_ids, [])
        self.assertEqual(resumed.artifacts.copy_draft, {})
        self.assertTrue(resumed.scope.established)

    def test_selection_add_affected_preserves_selection(self):
        """补选声明（AR4-7）：当前入选记入保留集，里程碑重开与重选一致。"""
        prior = _completed_social_post_state()
        resumed = rt_state.resume_task(
            prior, "再补两个不同场景", [rt_state.AFFECT_SELECTION_ADD],
        )
        self.assertEqual(resumed.progress.todo, ["select", "copy"])
        self.assertEqual(resumed.artifacts.selected_ids, ["b", "c"])
        self.assertEqual(resumed.artifacts.preserved_selected_ids, ["b", "c"])
        self.assertEqual(resumed.artifacts.copy_draft, {})
        self.assertTrue(resumed.scope.established)

    def test_selection_add_with_scope_resets_everything(self):
        """范围失效优先：即使同时声明补选，旧入选也不保留（新范围下已失效）。"""
        prior = _completed_social_post_state()
        resumed = rt_state.resume_task(
            prior, "换成第二天再多挑几张", [rt_state.AFFECT_SCOPE, rt_state.AFFECT_SELECTION_ADD],
        )
        self.assertEqual(resumed.progress.todo, ["locate", "candidates", "select", "copy"])
        self.assertEqual(resumed.artifacts.selected_ids, [])
        self.assertEqual(resumed.artifacts.preserved_selected_ids, [])

    def test_copy_affected_clears_stale_preserved(self):
        """保留集每次续跑重算：仅改文案的续跑不携带陈旧保留集。"""
        prior = _completed_social_post_state()
        first = rt_state.resume_task(prior, "再补两张", [rt_state.AFFECT_SELECTION_ADD])
        second = rt_state.resume_task(first, "文案再平实一点", [rt_state.AFFECT_COPY])
        self.assertEqual(second.artifacts.preserved_selected_ids, [])

    def test_scope_affected_resets_downstream_artifacts(self):
        prior = _completed_social_post_state()
        prior.artifacts.photo_cache["b"] = {"id": "b", "filename": "b.jpg"}
        resumed = rt_state.resume_task(prior, "换成第二天", [rt_state.AFFECT_SCOPE])
        self.assertEqual(resumed.progress.todo, ["locate", "candidates", "select", "copy"])
        self.assertFalse(resumed.scope.established)
        self.assertEqual(resumed.artifacts.candidate_ids, [])
        self.assertEqual(resumed.artifacts.selected_ids, [])
        self.assertEqual(resumed.artifacts.copy_draft, {})
        self.assertEqual(resumed.resolved_facts, {})
        # 照片缓存保留，避免续跑重复拉取详情
        self.assertEqual(resumed.artifacts.photo_cache["b"]["filename"], "b.jpg")

    def test_constraints_merge_current_wins(self):
        prior = _completed_social_post_state()
        prior.constraints["style"] = "文艺"
        resumed = rt_state.resume_task(prior, "不要那么文艺", [rt_state.AFFECT_COPY])
        self.assertEqual(resumed.constraints["question"], "不要那么文艺")
        # 先前约束保留（可追溯），同名冲突由当前消息覆盖
        self.assertEqual(resumed.constraints["style"], "文艺")

    def test_stale_clarification_cleared_on_resume(self):
        prior = _completed_social_post_state()
        clarify_obs = rt_state.Observation(
            rt_state.OBS_NEEDS_CLARIFICATION, "需要确认日期", {"message": "哪一天？"},
        )
        prior = rt_state.reduce_observation(prior, clarify_obs, step_no=5, action="resolve_trip")
        resumed = rt_state.resume_task(prior, "继续", [])
        self.assertNotIn("clarification", resumed.resolved_facts)
        self.assertEqual(resumed.progress.terminal_reason, "")

    def test_unknown_affect_values_are_ignored(self):
        prior = _completed_social_post_state()
        resumed = rt_state.resume_task(prior, "继续", ["no_such_part"])
        self.assertEqual(resumed.progress.todo, [])

    def test_comparison_report_affected(self):
        state = rt_state.new_task(rt_state.GOAL_PHOTO_COMPARISON, "对比两年春天", {})
        for period, pid in (("earlier", "a"), ("later", "b")):
            scope_obs = rt_state.Observation(
                rt_state.OBS_SCOPE, f"{period} 范围已物化",
                {"restricted": True, "period": period,
                 "condition_summary": f"{period} 期", "ids": [pid]},
            )
            state = rt_state.reduce_observation(state, scope_obs, step_no=1, action="resolve_trip")
            ids_obs = rt_state.Observation(
                rt_state.OBS_PHOTO_IDS, f"{period} 检索完成", {"ids": [pid], "period": period},
            )
            state = rt_state.reduce_observation(state, ids_obs, step_no=2, action="sql_search")
        report_obs = rt_state.Observation(
            rt_state.OBS_COMPARISON_REPORTED, "对比完成",
            {"report": {"summary": "进步明显", "periods": {"earlier": ["a"], "later": ["b"]},
                        "photo_ids": ["a", "b"]}},
        )
        state = rt_state.reduce_observation(state, report_obs, step_no=3, action="compare_photo_periods")
        self.assertEqual(state.progress.todo, [])

        resumed = rt_state.resume_task(state, "重写结论", [rt_state.AFFECT_REPORT])
        self.assertEqual(resumed.progress.todo, ["compare"])
        self.assertEqual(resumed.artifacts.comparison_report, {})
        # 两期证据组保留，重写结论不必重新检索
        self.assertEqual(resumed.artifacts.comparison_photo_ids, {"earlier": ["a"], "later": ["b"]})
        self.assertTrue(resumed.artifacts.comparison_scopes["earlier"].established)


class SelectionPreservationReduceTest(unittest.TestCase):
    """补选保留的归约保障（AR4-7）：旧照片保留不依赖选片模型遵循指令。"""

    def _resumed(self, affected: list[str]) -> rt_state.TaskState:
        return rt_state.resume_task(_completed_social_post_state(), "再补两个不同场景", affected)

    def _select_obs(self, ids: list[str]) -> rt_state.Observation:
        return rt_state.Observation(
            rt_state.OBS_PHOTOS_SELECTED, "已挑选",
            {"ids": ids, "photos": [{"id": pid, "filename": f"{pid}.jpg"} for pid in ids]},
        )

    def test_merge_keeps_preserved_when_model_drops_them(self):
        state = self._resumed([rt_state.AFFECT_SELECTION_ADD])
        # 选片模型只返回新照片、遗漏旧入选：归约仍程序性保留旧照片
        state = rt_state.reduce_observation(state, self._select_obs(["a"]), step_no=1, action="select_photos")
        self.assertEqual(state.artifacts.selected_ids, ["b", "c", "a"])
        self.assertNotIn("select", state.progress.todo)

    def test_merge_dedups_and_idempotent_for_repair_loop(self):
        state = self._resumed([rt_state.AFFECT_SELECTION_ADD])
        state = rt_state.reduce_observation(state, self._select_obs(["b", "c", "a"]), step_no=1, action="select_photos")
        self.assertEqual(state.artifacts.selected_ids, ["b", "c", "a"])
        # 修复环带反馈重执行选片：保留语义不丢失，重复入选去重
        state = rt_state.reduce_observation(state, self._select_obs(["c", "a"]), step_no=2, action="select_photos")
        self.assertEqual(state.artifacts.selected_ids, ["b", "c", "a"])

    def test_reselect_replaces_wholesale(self):
        state = self._resumed([rt_state.AFFECT_SELECTION])
        state = rt_state.reduce_observation(state, self._select_obs(["a"]), step_no=1, action="select_photos")
        self.assertEqual(state.artifacts.selected_ids, ["a"])

    def test_preserved_visible_in_decision_summary(self):
        state = self._resumed([rt_state.AFFECT_SELECTION_ADD])
        summary = rt_state.summarize_state(state)
        self.assertIn("补选保留", summary)
        # 重选续跑的摘要不出现保留提示
        self.assertNotIn("补选保留", rt_state.summarize_state(self._resumed([rt_state.AFFECT_SELECTION])))

    def test_affect_vocabulary_includes_selection_add(self):
        self.assertIn(rt_state.AFFECT_SELECTION_ADD, rt_state.affect_vocabulary())

    def test_snapshot_roundtrip_carries_preserved(self):
        state = self._resumed([rt_state.AFFECT_SELECTION_ADD])
        restored = rt_state.load_task(json.loads(json.dumps(rt_state.dump_task(state))))
        self.assertEqual(restored.artifacts.preserved_selected_ids, ["b", "c"])

    def test_legacy_snapshot_without_preserved_loads_empty(self):
        data = json.loads(json.dumps(rt_state.dump_task(_completed_social_post_state())))
        del data["artifacts"]["preserved_selected_ids"]
        restored = rt_state.load_task(data)
        self.assertEqual(restored.artifacts.preserved_selected_ids, [])


class RuntimeResumeGraphTest(unittest.TestCase):
    """图级续跑：run_runtime 从先前任务继续，金用例覆盖多轮修改主线（AR4-4）。"""

    def test_resume_rewrite_copy_only(self):
        """金用例第二轮「不要那么文艺」：只重开文案，不重跑范围/检索/选片。"""
        prior = _completed_social_post_state()
        llm = _ScriptedLLM([
            '{"action": "write_post", "params": {}, "reason": "按新风格重写文案"}',
        ])
        patches = _happy_patches(llm)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = rt_graph.run_runtime(
                _cfg(), "找山西旅游第一天的照片并生成发布文案，文案风格平实不要文艺",
                prior_task=prior, affected=[rt_state.AFFECT_COPY],
            )
        self.assertIn("# 山西第一天", result["answer"])
        # 只发生一次决策（直接写文案），选片与范围未被重跑
        self.assertEqual(len(llm.decide_prompts), 1)
        self.assertIn("已选照片", llm.decide_prompts[0])
        self.assertIn("待办里程碑: 创作文案", llm.decide_prompts[0])
        # 先前约束保留，当前消息优先
        self.assertIn("山西旅游第一天的照片", llm.decide_prompts[0])

    def test_resume_add_photos_reselects_and_rewrites(self):
        """金用例第三轮「再补两个不同场景」：补选重开选片与文案，范围与已选保留（AR4-7）。"""
        prior = _completed_social_post_state()
        llm = _ScriptedLLM([
            '{"action": "select_photos", "params": {}, "reason": "在已选基础上补选"}',
            '{"action": "write_post", "params": {}, "reason": "重写文案"}',
        ])
        patches = _happy_patches(llm)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = rt_graph.run_runtime(
                _cfg(), "在已选照片外再补两个不同场景并重新生成文案",
                prior_task=prior, affected=[rt_state.AFFECT_SELECTION_ADD],
            )
        self.assertIn("# 山西第一天", result["answer"])
        # 第一步决策可见先前选片与补选保留标记（可扩展而非从零挑选）
        self.assertIn("已选照片", llm.decide_prompts[0])
        self.assertIn("补选保留", llm.decide_prompts[0])
        self.assertIn("待办里程碑: 挑选发布照片、创作文案", llm.decide_prompts[0])
        self.assertEqual(len(llm.decide_prompts), 2)

    def test_selection_add_cannot_finish_after_model_skips_select(self):
        """模型先写文案时，完成检查仍强制补选后才可交付（AR4-8）。"""
        prior = _completed_social_post_state()
        llm = _ScriptedLLM(
            [
                '{"action": "write_post", "params": {}, "reason": "误判照片已选齐"}',
                '{"action": "select_photos", "params": {}, "reason": "按缺口补选"}',
            ],
            select_response='{"selected_ids": ["a"]}',
        )
        patches = _happy_patches(llm)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = rt_graph.run_runtime(
                _cfg(), "再补一张不同场景的照片并重新生成文案",
                prior_task=prior, affected=[rt_state.AFFECT_SELECTION_ADD],
            )
        task = rt_state.load_task(result["task_dump"])
        self.assertEqual(task.artifacts.selected_ids, ["b", "c", "a"])
        self.assertEqual(task.progress.todo, [])
        self.assertTrue(rt_completion.check_completion(task).complete)
        self.assertIn("# 山西第一天", result["answer"])
        self.assertEqual(len(llm.decide_prompts), 2)
        self.assertIn("完成要件缺口: selected_photos", llm.decide_prompts[1])

    def test_resume_selection_add_merges_even_when_model_drops_old(self):
        """补选图级保障：选片模型只返回新照片时，旧入选仍被程序性保留。"""
        prior = _completed_social_post_state()
        llm = _ScriptedLLM(
            [
                '{"action": "select_photos", "params": {}, "reason": "补选新场景"}',
                '{"action": "write_post", "params": {}, "reason": "重写文案"}',
            ],
            select_response='{"selected_ids": ["c"]}',
        )
        patches = _happy_patches(llm)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = rt_graph.run_runtime(
                _cfg(), "再补一张不同场景的照片",
                prior_task=prior, affected=[rt_state.AFFECT_SELECTION_ADD],
            )
        # 模型漏掉 b，归约合并后 b、c 均保留（不因模型输出丢用户已确认照片）
        self.assertEqual(result["task_dump"]["artifacts"]["selected_ids"], ["b", "c"])
        self.assertIn("# 山西第一天", result["answer"])

    def test_full_multiturn_flow_through_dump_and_load(self):
        """金用例主线：首轮完成 → dump 存快照 → load 后按 copy 失效续跑完成。"""
        llm1 = _ScriptedLLM([
            '{"action": "sql_search", "params": {"query": "山西旅游 第一天"}, "reason": "检索"}',
            '{"action": "select_photos", "params": {}, "reason": "挑选"}',
            '{"action": "write_post", "params": {}, "reason": "文案"}',
        ])
        patches1 = _happy_patches(llm1)
        with patches1[0], patches1[1], patches1[2], patches1[3], patches1[4]:
            first = rt_graph.run_runtime(_cfg(), "找山西旅游第一天的照片并生成发布文案")
        self.assertIn("# 山西第一天", first["answer"])

        # 会话层只持久化 JSON：快照经 JSON 往返后续跑
        snapshot_json = json.dumps(first["task_dump"], ensure_ascii=False)
        prior = rt_state.load_task(json.loads(snapshot_json))
        self.assertEqual(prior.artifacts.selected_ids, ["b", "c"])

        llm2 = _ScriptedLLM([
            '{"action": "write_post", "params": {}, "reason": "重写文案"}',
        ])
        patches2 = _happy_patches(llm2)
        with patches2[0], patches2[1], patches2[2], patches2[3], patches2[4]:
            second = rt_graph.run_runtime(
                _cfg(), "文案风格平实不要文艺",
                prior_task=prior, affected=[rt_state.AFFECT_COPY],
            )
        self.assertIn("# 山西第一天", second["answer"])
        self.assertEqual(second["goal_type"], rt_state.GOAL_SOCIAL_POST)
        self.assertEqual(len(llm2.decide_prompts), 1)

    def test_resume_scope_change_reruns_whole_pipeline(self):
        """范围失效：全链路重跑，先前候选与选片不泄漏进新范围。"""
        prior = _completed_social_post_state()
        llm = _ScriptedLLM([
            '{"action": "sql_search", "params": {"query": "山西旅游 第二天"}, "reason": "重新检索"}',
            '{"action": "select_photos", "params": {}, "reason": "重新挑选"}',
            '{"action": "write_post", "params": {}, "reason": "文案"}',
        ])
        patches = _happy_patches(llm)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = rt_graph.run_runtime(
                _cfg(), "换成山西旅游第二天并生成发布文案",
                prior_task=prior, affected=[rt_state.AFFECT_SCOPE],
            )
        self.assertIn("# 山西第一天", result["answer"])
        self.assertIn("待办里程碑: 确认候选范围、检索候选照片、挑选发布照片、创作文案",
                      llm.decide_prompts[0])


if __name__ == "__main__":
    unittest.main()
