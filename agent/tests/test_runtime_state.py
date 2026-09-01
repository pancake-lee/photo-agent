import unittest

import internal.runtime.state as rt_state


class NewTaskTest(unittest.TestCase):
    def test_builds_goal_and_todo_from_preset(self):
        task = rt_state.new_task(
            rt_state.GOAL_SOCIAL_POST, "找山西旅游第一天的照片并生成发布文案",
            constraints={"question": "找山西旅游第一天的照片并生成发布文案"},
        )
        self.assertEqual(task.goal.requirements, ("selected_photos", "copy_draft"))
        self.assertEqual(task.progress.todo, ["locate", "candidates", "select", "copy"])
        self.assertEqual(task.constraints["question"], "找山西旅游第一天的照片并生成发布文案")

    def test_unknown_goal_type_raises(self):
        with self.assertRaises(ValueError):
            rt_state.new_task("unknown_goal", "描述")


class ReduceObservationTest(unittest.TestCase):
    def _task(self) -> rt_state.TaskState:
        return rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "发帖", {"question": "发帖"})

    def test_photo_ids_replaces_candidates_dedup_and_finishes_milestone(self):
        task = self._task()
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_PHOTO_IDS, "SQL 返回 3 个候选",
            {"ids": ["a", "b", "a", "c"], "source": "sql"},
        ), step_no=1, action="sql_search")
        self.assertEqual(task.artifacts.candidate_ids, ["a", "b", "c"])
        self.assertNotIn("candidates", task.progress.todo)
        self.assertEqual(task.progress.history[-1]["action"], "sql_search")

    def test_facts_merge_and_finishes_locate(self):
        task = self._task()
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_FACTS, "匹配时间线", {"facts": {"timeline": "山西旅游"}},
        ), step_no=1, action="resolve_trip")
        self.assertEqual(task.resolved_facts["timeline"], "山西旅游")
        self.assertNotIn("locate", task.progress.todo)

    def test_facts_without_location_keys_keeps_locate(self):
        task = self._task()
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_FACTS, "部分事实", {"facts": {"day_hint": "第一天"}},
        ), step_no=1, action="resolve_trip")
        self.assertIn("locate", task.progress.todo)


def _scope_obs(ids: list[str], restricted: bool = True,
               conditions: dict | None = None, label: str = "山西旅游第一天傍晚",
               soft_hints: list[str] | None = None) -> rt_state.Observation:
    return rt_state.Observation(rt_state.OBS_SCOPE, "范围已确认", {
        "conditions": conditions or {"timeline": "山西旅游", "day": "first", "time_of_day": "傍晚"},
        "restricted": restricted,
        "ids": ids,
        "condition_summary": label,
        "sql": "SELECT id FROM photos WHERE timeline = '山西旅游'",
        "soft_hints": soft_hints if soft_hints is not None else ["太原植物园"],
    })


def _search_obs(ids: list[str]) -> rt_state.Observation:
    return rt_state.Observation(
        rt_state.OBS_PHOTO_IDS, "检索", {"ids": ids, "source": "sql"},
    )


class ScopeReductionTest(unittest.TestCase):
    """权威范围归约：范围物化、统一交集、软提示零命中兜底与空范围终态。"""

    def _task(self) -> rt_state.TaskState:
        return rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "发帖", {"question": "发帖"})

    def test_scope_materializes_range_facts_and_finishes_locate(self):
        task = rt_state.reduce_observation(self._task(), _scope_obs(["a", "b", "c"]),
                                           step_no=1, action="resolve_trip")
        self.assertTrue(task.scope.established)
        self.assertTrue(task.scope.restricted)
        self.assertEqual(task.scope.photo_ids, ["a", "b", "c"])
        self.assertEqual(task.scope.condition_summary, "山西旅游第一天傍晚")
        self.assertEqual(task.resolved_facts["timeline"], "山西旅游")
        self.assertEqual(task.resolved_facts["soft_hints"], ["太原植物园"])
        self.assertNotIn("locate", task.progress.todo)

    def test_candidate_search_intersected_with_scope(self):
        """检索返回范围外结果时被交集过滤（RAG/SQL 一视同仁）。"""
        task = rt_state.reduce_observation(self._task(), _scope_obs(["a", "b"]),
                                           step_no=1, action="resolve_trip")
        task = rt_state.reduce_observation(task, _search_obs(["x", "a", "y", "b"]),
                                           step_no=2, action="rag_search")
        self.assertEqual(task.artifacts.candidate_ids, ["a", "b"])

    def test_soft_hint_zero_hits_fall_back_to_whole_scope(self):
        """软提示零命中不能清空候选：保留整个权威范围（只影响排序）。"""
        task = rt_state.reduce_observation(self._task(), _scope_obs(["a", "b"]),
                                           step_no=1, action="resolve_trip")
        task = rt_state.reduce_observation(task, _search_obs(["x", "y"]),
                                           step_no=2, action="sql_search")
        self.assertEqual(task.artifacts.candidate_ids, ["a", "b"])
        self.assertNotIn("candidates", task.progress.todo)

    def test_scope_after_search_reintersects_existing_candidates(self):
        """范围晚于检索建立时，既有候选同样回到范围内。"""
        task = rt_state.reduce_observation(self._task(), _search_obs(["x", "a"]),
                                           step_no=1, action="sql_search")
        task = rt_state.reduce_observation(task, _scope_obs(["a", "b"]),
                                           step_no=2, action="resolve_trip")
        self.assertEqual(task.artifacts.candidate_ids, ["a"])

    def test_unrestricted_scope_keeps_candidates_as_is(self):
        """无硬约束不受限：不做交集强制，全库检索结果直接成为候选。"""
        task = rt_state.reduce_observation(
            self._task(), _scope_obs([], restricted=False, conditions={}, label="",
                                     soft_hints=[]),
            step_no=1, action="resolve_trip",
        )
        self.assertTrue(task.scope.established)
        self.assertFalse(task.scope.restricted)
        task = rt_state.reduce_observation(task, _search_obs(["x", "a"]),
                                           step_no=2, action="rag_search")
        self.assertEqual(task.artifacts.candidate_ids, ["x", "a"])

    def test_restricted_empty_scope_sets_terminal(self):
        """受限但 0 张是确定性终态，禁止后续选片与文案。"""
        task = rt_state.reduce_observation(self._task(), _scope_obs([]),
                                           step_no=1, action="resolve_trip")
        self.assertEqual(task.progress.terminal_reason, "empty_scope")
        output = rt_state.build_final_output(task)
        self.assertIn("未找到符合条件的照片（山西旅游第一天傍晚）", output["answer"])
        self.assertIn("放宽条件", output["answer"])

    def test_summary_includes_scope_line(self):
        task = rt_state.reduce_observation(self._task(), _scope_obs(["a", "b"]),
                                           step_no=1, action="resolve_trip")
        summary = rt_state.summarize_state(task)
        self.assertIn("候选范围: 山西旅游第一天傍晚（硬约束，共 2 张）", summary)
        unrestricted = rt_state.reduce_observation(
            self._task(), _scope_obs([], restricted=False, conditions={}, label="",
                                     soft_hints=[]),
            step_no=1, action="resolve_trip",
        )
        self.assertIn("候选范围: 不受限（全库）", rt_state.summarize_state(unrestricted))
        self.assertIn("候选范围: 尚未确认", rt_state.summarize_state(self._task()))

    def test_photo_details_merge_into_bounded_cache(self):
        task = self._task()
        photos = [{"id": str(i), "filename": f"{i}.jpg"} for i in range(rt_state._PHOTO_CACHE_MAX + 5)]
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_PHOTO_DETAILS, "详情", {"photos": photos},
        ), step_no=1, action="fetch_photo_details")
        self.assertEqual(len(task.artifacts.photo_cache), rt_state._PHOTO_CACHE_MAX)
        self.assertNotIn("0", task.artifacts.photo_cache)
        self.assertIn(str(rt_state._PHOTO_CACHE_MAX + 4), task.artifacts.photo_cache)

    def test_selection_and_copy_finish_milestones(self):
        task = self._task()
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_PHOTOS_SELECTED, "选中 3 张", {"ids": ["a", "b", "c"]},
        ), step_no=2, action="select_photos")
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_COPY_DRAFTED, "文案完成", {"title": "山西行记", "content": "正文"},
        ), step_no=3, action="write_post")
        self.assertEqual(task.artifacts.selected_ids, ["a", "b", "c"])
        self.assertEqual(task.artifacts.copy_draft["title"], "山西行记")
        self.assertEqual(task.progress.todo, ["locate", "candidates"])

    def test_selection_overflow_sets_terminal_and_handoff(self):
        task = self._task()
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_SELECTION_OVERFLOW, "候选过多",
            {"url": "#/post-studio?photo_ids=a,b", "candidate_count": 60},
        ), step_no=2, action="select_photos")
        self.assertEqual(task.progress.terminal_reason, "candidate_overflow")
        self.assertEqual(task.artifacts.handoff_url, "#/post-studio?photo_ids=a,b")

    def test_error_observation_appends_bounded_errors(self):
        task = self._task()
        for i in range(rt_state._ERRORS_MAX + 3):
            task = rt_state.reduce_observation(task, rt_state.Observation(
                rt_state.OBS_ERROR, f"失败{i}", {"action": "sql_search"},
            ), step_no=i + 1, action="sql_search")
        self.assertEqual(len(task.progress.errors), rt_state._ERRORS_MAX)
        self.assertEqual(task.progress.errors[-1], f"失败{rt_state._ERRORS_MAX + 2}")
        self.assertEqual(task.progress.terminal_reason, "capability_failed")

    def test_terminal_error_stops_runtime_with_reason(self):
        task = self._task()
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_ERROR, "无法获取候选照片详情", 
            {"terminal_reason": "photo_details_unavailable"},
        ), step_no=1, action="fetch_photo_details")
        self.assertEqual(task.progress.terminal_reason, "photo_details_unavailable")

    def test_unknown_kind_raises(self):
        task = self._task()
        with self.assertRaises(KeyError):
            rt_state.reduce_observation(task, rt_state.Observation("mystery", "?"), step_no=1)

    def test_reduce_does_not_mutate_input_state(self):
        task = self._task()
        rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_PHOTO_IDS, "检索", {"ids": ["a"]},
        ), step_no=1, action="sql_search")
        self.assertEqual(task.artifacts.candidate_ids, [])
        self.assertEqual(task.progress.history, [])
        self.assertIn("candidates", task.progress.todo)


class SummarizeStateTest(unittest.TestCase):
    def test_summary_contains_key_sections(self):
        task = rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "山西第一天发帖", {"question": "山西"})
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_FACTS, "匹配时间线 山西旅游", {"facts": {"timeline": "山西旅游"}},
        ), step_no=1, action="resolve_trip")
        summary = rt_state.summarize_state(task)
        self.assertIn("目标类型: social_post", summary)
        self.assertIn("山西旅游", summary)
        self.assertIn("待办里程碑", summary)
        self.assertIn("最近动作", summary)

    def test_summary_truncates_long_candidate_list(self):
        task = rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "发帖", {"question": "q"})
        ids = [f"p{i}" for i in range(30)]
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_PHOTO_IDS, "检索", {"ids": ids},
        ), step_no=1, action="sql_search")
        summary = rt_state.summarize_state(task)
        self.assertIn("共 30 个", summary)
        self.assertNotIn("p29", summary)


class BuildFinalOutputTest(unittest.TestCase):
    def _completed_task(self) -> rt_state.TaskState:
        task = rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "发帖", {"question": "q"})
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_PHOTOS_SELECTED, "选中", {"ids": ["a", "b"]},
        ), step_no=1, action="select_photos")
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_COPY_DRAFTED, "完成", {"title": "标题", "content": "正文"},
        ), step_no=2, action="write_post")
        return task

    def test_complete_output_contains_title_content_and_ids(self):
        output = rt_state.build_final_output(self._completed_task())
        self.assertIn("# 标题", output["answer"])
        self.assertIn("正文", output["answer"])
        self.assertIn("入选照片：a、b", output["answer"])
        self.assertEqual(output["handoff_url"], "")

    def test_complete_output_prefers_filenames_and_falls_back_to_ids(self):
        task = rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "发帖", {"question": "q"})
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_PHOTOS_SELECTED, "选中",
            {"ids": ["a", "b", "c"], "photos": [
                {"id": "a", "filename": "DSC0001.jpg"},
                {"id": "b", "filename": "DSC0002.jpg"},
            ]},
        ), step_no=1, action="select_photos")
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_COPY_DRAFTED, "完成", {"title": "标题", "content": "正文"},
        ), step_no=2, action="write_post")
        # 挑选观察带入的详情进入缓存，且不覆盖已有完整详情
        self.assertEqual(task.artifacts.photo_cache["a"]["filename"], "DSC0001.jpg")
        output = rt_state.build_final_output(task)
        self.assertIn("入选照片：DSC0001.jpg、DSC0002.jpg、c", output["answer"])

    def test_complete_takes_priority_over_budget_stop(self):
        output = rt_state.build_final_output(self._completed_task(), stop_reason="max_steps")
        self.assertIn("# 标题", output["answer"])
        self.assertNotIn("预算", output["answer"])

    def test_overflow_output_returns_handoff(self):
        task = rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "发帖", {"question": "q"})
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_SELECTION_OVERFLOW, "超限", {"url": "#/post-studio?photo_ids=a"},
        ), step_no=1, action="select_photos")
        output = rt_state.build_final_output(task)
        self.assertEqual(output["handoff_url"], "#/post-studio?photo_ids=a")
        self.assertIn("图文工坊", output["answer"])

    def test_budget_stop_describes_progress_and_missing(self):
        task = rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "发帖", {"question": "q"})
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_FACTS, "匹配时间线", {"facts": {"timeline": "山西旅游"}},
        ), step_no=1, action="resolve_trip")
        output = rt_state.build_final_output(task, stop_reason="max_steps")
        self.assertIn("预算已耗尽（步数）", output["answer"])
        self.assertIn("已完成：确认候选范围", output["answer"])
        self.assertIn("仍缺少：入选照片、发布文案", output["answer"])
        self.assertIn("最后动作：resolve_trip", output["answer"])

    def test_terminal_error_output_does_not_claim_budget_exhaustion(self):
        task = rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "发帖", {"question": "q"})
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_ERROR, "无法获取候选照片详情", 
            {"terminal_reason": "photo_details_unavailable"},
        ), step_no=1, action="fetch_photo_details")
        output = rt_state.build_final_output(task)
        self.assertIn("无法获取候选照片详情", output["answer"])
        self.assertNotIn("预算已耗尽", output["answer"])


if __name__ == "__main__":
    unittest.main()
