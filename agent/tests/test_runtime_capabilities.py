import datetime
import unittest
import unittest.mock

import internal.runtime.capabilities as rt_caps
import internal.runtime.capabilities.common as caps_common
import internal.runtime.capabilities.creation as caps_creation
import internal.runtime.capabilities.photo_tools as caps_photo_tools
import internal.runtime.capabilities.resolve_trip as caps_resolve_trip
import internal.runtime.capabilities.retrieval as caps_retrieval
import internal.runtime.registry as rt_registry
import internal.runtime.state as rt_state


def _cfg(**overrides):
    attrs = {
        "go_backend_url": "http://backend",
        "compose_group_limit": 20,
        "compose_cover_limit": 40,
        "rag_distance_threshold": None,
        "rag_auto_distance_ratio": 1.8,
    }
    attrs.update(overrides)
    return type("Config", (), attrs)()


def _ctx(cfg, state=None, question="写文案"):
    return rt_registry.RunContext(cfg=cfg, granularity="photo", question=question, state=state)


class CollapseBurstCandidatesTest(unittest.TestCase):
    """迁移自 CQ4 test_collapses_burst_group_to_cover。"""

    def test_collapses_burst_group_to_cover(self):
        result = caps_creation.collapse_burst_candidates([
            {"id": "a", "burst_group_id": "g"},
            {"id": "b", "burst_group_id": "g", "is_burst_cover": True},
            {"id": "c"},
        ])
        self.assertEqual([item["id"] for item in result], ["b", "c"])
        self.assertEqual(result[0]["_group_count"], 2)


class PrepareSelectCandidatesTest(unittest.TestCase):
    """迁移自 CQ4 test_two_level_shrink_and_overflow_tokens。"""

    def test_two_level_shrink_and_overflow_tokens(self):
        photos = [{"id": str(index), "burst_group_id": f"g{index}"} for index in range(3)]
        mode, covers = caps_creation.prepare_select_candidates(photos, group_limit=2, cover_limit=3)
        self.assertEqual(mode, "covers")
        self.assertNotIn("_group_count", covers[0])
        overflow_mode, overflow = caps_creation.prepare_select_candidates(
            photos, group_limit=1, cover_limit=2,
        )
        self.assertEqual(overflow_mode, "overflow")
        self.assertEqual(caps_creation.select_token(overflow[0]), "g:g0:0")


class SelectPhotosCapabilityTest(unittest.TestCase):
    """迁移自 CQ4 test_overflow_returns_existing_post_studio_deep_link。"""

    def test_overflow_returns_existing_post_studio_deep_link(self):
        cfg = _cfg(compose_group_limit=1, compose_cover_limit=2)
        task = rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "写文案", {"question": "写文案"})
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_PHOTO_IDS, "检索", {"ids": ["a", "b", "c"]},
        ), step_no=1, action="sql_search")
        with unittest.mock.patch.object(caps_common, "fetch_photos_batch",
                                        return_value=[{"id": "a"}, {"id": "b"}, {"id": "c"}]):
            obs = caps_creation._select_photos({}, _ctx(cfg, task))
        self.assertEqual(obs.kind, rt_state.OBS_SELECTION_OVERFLOW)
        # 超限转图文工坊是设计内终态，不是失败
        self.assertEqual(obs.status, rt_state.STATUS_SUCCESS)
        self.assertEqual(obs.payload["url"], "#/post-studio?photo_ids=a,b,c")

    def test_select_without_candidates_returns_error(self):
        task = rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "写文案", {"question": "q"})
        obs = caps_creation._select_photos({}, _ctx(_cfg(), task))
        self.assertEqual(obs.kind, rt_state.OBS_ERROR)
        # 先选片后挑选属决策侧顺序问题（invalid_input）
        self.assertEqual(obs.status, rt_state.STATUS_INVALID_INPUT)

    def test_select_happy_path_filters_invalid_ids(self):
        cfg = _cfg(compose_group_limit=20, compose_cover_limit=40)
        task = rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "挑照片", {"question": "挑照片"})
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_PHOTO_IDS, "检索", {"ids": ["a", "b", "c"]},
        ), step_no=1, action="sql_search")
        fake_llm = unittest.mock.MagicMock()
        fake_llm.invoke.return_value.content = '{"selected_ids": ["b", "ghost", "a"]}'
        fetched = [
            {"id": "a", "filename": "a.jpg", "description": "草坡黄昏"},
            {"id": "b", "filename": "b.jpg", "description": "湖面飞鸟"},
            {"id": "c", "filename": "c.jpg", "description": "岸边剪影"},
        ]
        with unittest.mock.patch.object(caps_common, "fetch_photos_batch", return_value=fetched), \
             unittest.mock.patch.object(caps_common.llm_factory, "create_llm", return_value=fake_llm):
            obs = caps_creation._select_photos({}, _ctx(cfg, task))
        self.assertEqual(obs.kind, rt_state.OBS_PHOTOS_SELECTED)
        self.assertEqual(obs.payload["ids"], ["b", "a"])
        # 挑选观察必须携带完整详情（含 description），归约写入缓存后 write_post 直接可用
        self.assertEqual(obs.payload["photos"], [fetched[1], fetched[0]])
        # 未指定数量时沿用默认档位并记录假设（AR2-6 可回退歧义不询问）
        self.assertEqual(obs.payload["assumption"], "未指定入选数量，按默认 4-9 张挑选")

    def test_select_respects_max_photos(self):
        task = rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "挑照片", {"question": "q"})
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_PHOTO_IDS, "检索", {"ids": ["a", "b", "c"]},
        ), step_no=1, action="sql_search")
        fake_llm = unittest.mock.MagicMock()
        fake_llm.invoke.return_value.content = '{"selected_ids": ["a", "b", "c"]}'
        with unittest.mock.patch.object(caps_common, "fetch_photos_batch", return_value=[
            {"id": "a"}, {"id": "b"}, {"id": "c"},
        ]), unittest.mock.patch.object(caps_common.llm_factory, "create_llm", return_value=fake_llm):
            obs = caps_creation._select_photos({"max_photos": 2}, _ctx(_cfg(), task))
        self.assertEqual(obs.payload["ids"], ["a", "b"])
        # 显式指定数量时不产生假设
        self.assertNotIn("assumption", obs.payload)

    def test_candidate_delivery_keeps_collapsed_candidates_without_llm_selection(self):
        task = rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "尽可能多给我照片，我会二次挑选")
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_PHOTO_IDS, "检索", {"ids": ["a", "b", "c"]},
        ), step_no=1, action="sql_search")
        with unittest.mock.patch.object(caps_common, "fetch_photos_batch", return_value=[
            {"id": "a", "burst_group_id": "g"},
            {"id": "b", "burst_group_id": "g", "is_burst_cover": True},
            {"id": "c"},
        ]), unittest.mock.patch.object(caps_common.llm_factory, "create_llm") as create_llm:
            obs = caps_creation._select_photos({}, _ctx(_cfg(), task))
        self.assertEqual(obs.kind, rt_state.OBS_PHOTOS_SELECTED)
        self.assertEqual(obs.payload["ids"], ["b", "c"])
        create_llm.assert_not_called()

    def test_select_empty_pick_returns_error(self):
        task = rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "挑照片", {"question": "q"})
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_PHOTO_IDS, "检索", {"ids": ["a"]},
        ), step_no=1, action="sql_search")
        fake_llm = unittest.mock.MagicMock()
        fake_llm.invoke.return_value.content = "模型罢工了，没有 JSON"
        with unittest.mock.patch.object(caps_common, "fetch_photos_batch", return_value=[{"id": "a"}]), \
             unittest.mock.patch.object(caps_common.llm_factory, "create_llm", return_value=fake_llm):
            obs = caps_creation._select_photos({}, _ctx(_cfg(), task))
        self.assertEqual(obs.kind, rt_state.OBS_ERROR)
        # 挑选空结果是模型输出缺陷（invalid_input），AR2-3 带反馈修复
        self.assertEqual(obs.status, rt_state.STATUS_INVALID_INPUT)
        self.assertEqual(obs.payload["terminal_reason"], "photo_selection_failed")

    def test_select_without_photo_details_stops_deterministically(self):
        task = rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "挑照片", {"question": "q"})
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_PHOTO_IDS, "检索", {"ids": ["a"]},
        ), step_no=1, action="sql_search")
        with unittest.mock.patch.object(caps_common, "fetch_photos_batch", return_value=[]):
            obs = caps_creation._select_photos({}, _ctx(_cfg(), task))
        self.assertEqual(obs.kind, rt_state.OBS_ERROR)
        # 详情拉取失败以网络/后端不可达为主，按瞬时故障归类
        self.assertEqual(obs.status, rt_state.STATUS_TEMPORARY_ERROR)
        self.assertEqual(obs.payload["terminal_reason"], "photo_details_unavailable")

    def test_select_out_of_scope_pick_is_blocked(self):
        """范围外入选被阻断：进入可解释失败，不允许继续生成文案。"""
        cfg = _cfg()
        task = rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "挑照片", {"question": "q"})
        # 构造不变量被破坏的状态：候选含范围外照片 x，权威范围只有 a
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_SCOPE, "范围",
            {"conditions": {"timeline": "山西旅游", "day": "first", "time_of_day": "傍晚"},
             "restricted": True, "ids": ["a"], "condition_summary": "山西旅游第一天傍晚"},
        ), step_no=1, action="resolve_trip")
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_PHOTO_IDS, "检索", {"ids": ["a", "x"]},
        ), step_no=2, action="sql_search")
        # 绕过归约交集，直接模拟候选未受限的历史状态
        task.artifacts.candidate_ids = ["a", "x"]
        fake_llm = unittest.mock.MagicMock()
        fake_llm.invoke.return_value.content = '{"selected_ids": ["x"]}'
        with unittest.mock.patch.object(caps_common, "fetch_photos_batch", return_value=[
            {"id": "a", "description": "寺庙"}, {"id": "x", "description": "外地图"},
        ]), unittest.mock.patch.object(caps_common.llm_factory, "create_llm",
                                        return_value=fake_llm):
            obs = caps_creation._select_photos({}, _ctx(cfg, task))
        self.assertEqual(obs.kind, rt_state.OBS_ERROR)
        # 越界入选是模型输出缺陷（invalid_input），AR2-3 带反馈修复
        self.assertEqual(obs.status, rt_state.STATUS_INVALID_INPUT)
        self.assertEqual(obs.payload["terminal_reason"], "selection_out_of_scope")
        self.assertEqual(obs.payload["ids"], ["x"])


class WritePostCapabilityTest(unittest.TestCase):
    def test_write_post_after_selection_uses_cached_full_details(self):
        """回归：挑选归约写入缓存的必须是完整详情，write_post 不得误判"都还没有 AI 描述"。

        走真实 generate_post（只 mock LLM），否则 _split_described 的缺描述判定不会被执行。
        """
        cfg = _cfg()
        task = rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "发帖", {"question": "q"})
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_PHOTOS_SELECTED, "选中",
            {"ids": ["a"], "photos": [
                {"id": "a", "filename": "a.jpg", "description": "暮色湖面"},
            ]},
        ), step_no=1, action="select_photos")

        def fetch_spy(_cfg_arg, ids):
            # 缓存命中完整详情时，补拉列表必须为空（空列表不会发起任何请求）
            self.assertEqual(ids, [], "缓存命中完整详情时不应再补拉详情")
            return []

        fake_llm = unittest.mock.MagicMock()
        fake_llm.invoke.return_value.content = '{"title": "标题", "content": "正文"}'
        with unittest.mock.patch.object(caps_common, "fetch_photos_batch", side_effect=fetch_spy), \
             unittest.mock.patch.object(caps_creation.post_studio.llm_factory, "create_llm",
                                        return_value=fake_llm):
            obs = caps_creation._write_post({}, _ctx(cfg, task))
        self.assertEqual(obs.kind, rt_state.OBS_COPY_DRAFTED)
        self.assertEqual(obs.payload["title"], "标题")
        # 未指定风格时沿用默认「自由」并记录假设（AR2-6 可回退歧义不询问）
        self.assertEqual(obs.payload["assumption"], "未指定文案风格，默认「自由」")

    def test_write_post_uses_selected_photos_and_post_studio(self):
        cfg = _cfg()
        task = rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "发帖", {"question": "发帖"})
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_PHOTO_IDS, "检索", {"ids": ["a", "b"]},
        ), step_no=1, action="sql_search")
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_PHOTOS_SELECTED, "选中", {"ids": ["b", "a"]},
        ), step_no=2, action="select_photos")
        # 缓存里有 b 无 a，验证按已选顺序取用并补拉缺失
        task.artifacts.photo_cache["b"] = {
            "id": "b", "filename": "b.jpg", "description": "寺庙",
        }
        with unittest.mock.patch.object(caps_common, "fetch_photos_batch",
                                        return_value=[{"id": "a", "description": "面馆"}]) as fetch, \
             unittest.mock.patch.object(caps_creation.post_studio, "generate_post",
                                        return_value=("山西行记", "正文", ["1 张照片缺少描述"])) as gen:
            obs = caps_creation._write_post({"style": "文艺"}, _ctx(cfg, task))
        self.assertEqual(obs.kind, rt_state.OBS_COPY_DRAFTED)
        self.assertEqual(obs.payload["title"], "山西行记")
        # 显式指定风格时不产生假设
        self.assertNotIn("assumption", obs.payload)
        self.assertIn("1 张照片缺少描述", obs.summary)
        fetch.assert_called_once_with(cfg, ["a"])
        photos_arg = gen.call_args[0][1]
        self.assertEqual([p.id for p in photos_arg], ["b", "a"])
        self.assertEqual(gen.call_args[0][2], "文艺")

    def test_write_post_without_selection_returns_error(self):
        task = rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "发帖", {"question": "q"})
        obs = caps_creation._write_post({}, _ctx(_cfg(), task))
        self.assertEqual(obs.kind, rt_state.OBS_ERROR)
        # 先文案后选片属决策侧顺序问题（invalid_input）
        self.assertEqual(obs.status, rt_state.STATUS_INVALID_INPUT)


class RepairFeedbackTest(unittest.TestCase):
    """AR2-3/AR2-5 修复环：护栏注入的失败反馈进入能力重执行提示词。"""

    def _task_with_candidates(self):
        task = rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "发帖", {"question": "发帖"})
        return rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_PHOTO_IDS, "检索", {"ids": ["a", "b"]},
        ), step_no=1, action="sql_search")

    def test_select_photos_feedback_enters_llm_prompt(self):
        task = self._task_with_candidates()
        prompts: list[str] = []

        def fake_invoke(ctx, system_prompt, user_prompt, temperature):
            prompts.append(user_prompt)
            return '{"selected_ids": ["a", "b"]}'

        with unittest.mock.patch.object(caps_common, "fetch_photos_batch",
                                        return_value=[{"id": "a"}, {"id": "b"}]), \
             unittest.mock.patch.object(caps_common, "invoke_structured_llm",
                                        side_effect=fake_invoke):
            obs = caps_creation._select_photos(
                {"feedback": "入选三张同一场景近重复，请覆盖不同时段"}, _ctx(_cfg(), task),
            )
        self.assertEqual(obs.kind, rt_state.OBS_PHOTOS_SELECTED)
        self.assertEqual(len(prompts), 1)
        self.assertIn("上次挑选未通过", prompts[0])
        self.assertIn("近重复", prompts[0])

    def test_select_photos_without_feedback_prompt_unchanged(self):
        task = self._task_with_candidates()
        prompts: list[str] = []

        def fake_invoke(ctx, system_prompt, user_prompt, temperature):
            prompts.append(user_prompt)
            return '{"selected_ids": ["a", "b"]}'

        with unittest.mock.patch.object(caps_common, "fetch_photos_batch",
                                        return_value=[{"id": "a"}, {"id": "b"}]), \
             unittest.mock.patch.object(caps_common, "invoke_structured_llm",
                                        side_effect=fake_invoke):
            caps_creation._select_photos({}, _ctx(_cfg(), task))
        self.assertNotIn("上次挑选未通过", prompts[0])

    def test_write_post_feedback_enters_user_prompt(self):
        task = self._task_with_candidates()
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_PHOTOS_SELECTED, "选中", {"ids": ["a"], "photos": [{"id": "a"}]},
        ), step_no=2, action="select_photos")
        with unittest.mock.patch.object(caps_common, "fetch_photos_batch",
                                        return_value=[]), \
             unittest.mock.patch.object(caps_creation.post_studio, "generate_post",
                                        return_value=("标题", "正文", [])) as gen:
            caps_creation._write_post(
                {"feedback": "提到的大雁塔不在照片中"}, _ctx(_cfg(), task),
            )
        user_prompt = gen.call_args[0][3]
        self.assertIn("上次文案未通过质量检查", user_prompt)
        self.assertIn("大雁塔", user_prompt)


class ResolveTripCapabilityTest(unittest.TestCase):
    """约束解析能力：抽取 + 程序校验 + 权威范围物化（SQL 不经 LLM）。"""

    def _resolve(self, llm_content: str, question="找山西旅游第一天傍晚的照片",
                 execute_ids=None):
        fake_llm = unittest.mock.MagicMock()
        fake_llm.invoke.return_value.content = llm_content
        patches = [
            unittest.mock.patch.object(caps_resolve_trip, "_fetch_timelines",
                                       return_value=["山西旅游", "北京街拍"]),
            unittest.mock.patch.object(caps_common.llm_factory, "create_llm", return_value=fake_llm),
        ]
        if execute_ids is not None:
            patches.append(unittest.mock.patch.object(
                caps_resolve_trip.text_to_sql, "execute_sql_for_ids", return_value=execute_ids,
            ))
        for patch in patches:
            patch.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(patches)])
        return caps_resolve_trip._resolve_trip({}, _ctx(_cfg(), question=question))

    def test_matched_constraints_materialize_scope_sql(self):
        """山西用例：范围 SQL 只含硬约束（时间线/天序/小时窗），软提示不入 WHERE。"""
        obs = self._resolve(
            '{"timeline": "山西旅游", "day": "first", "time_of_day": "傍晚",'
            ' "soft_hints": ["太原植物园", "植物"]}',
            execute_ids=["a", "b"],
        )
        self.assertEqual(obs.kind, rt_state.OBS_SCOPE)
        self.assertTrue(obs.payload["restricted"])
        self.assertEqual(obs.payload["ids"], ["a", "b"])
        self.assertEqual(obs.payload["condition_summary"], "山西旅游第一天傍晚")
        self.assertEqual(obs.payload["soft_hints"], ["太原植物园", "植物"])
        sql = obs.payload["sql"]
        self.assertIn("timeline = '山西旅游'", sql)
        self.assertIn("MIN(DATE(shot_at, 'localtime'))", sql)
        self.assertIn("BETWEEN 17 AND 19", sql)
        for soft in ("植物园", "植物"):
            self.assertNotIn(soft, sql)

    def test_no_hard_constraints_marks_scope_unrestricted(self):
        """抽不出任何硬约束时范围不受限（全库），不执行范围 SQL。"""
        obs = self._resolve(
            '{"timeline": "", "day": "", "time_of_day": "", "soft_hints": ["黄昏氛围"]}',
            question="挑几张有氛围感的照片发帖",
        )
        self.assertEqual(obs.kind, rt_state.OBS_SCOPE)
        self.assertFalse(obs.payload["restricted"])
        self.assertEqual(obs.payload["ids"], [])
        self.assertEqual(obs.payload["soft_hints"], ["黄昏氛围"])

    def test_empty_scope_returns_deterministic_terminal(self):
        """受限但 0 张时进入 empty_scope 终态，不进入检索/选片。"""
        obs = self._resolve(
            '{"timeline": "山西旅游", "day": "first", "time_of_day": "夜晚", "soft_hints": []}',
            execute_ids=[],
        )
        self.assertEqual(obs.kind, rt_state.OBS_ERROR)
        # 范围物化 0 张是语义空结果（empty），empty_scope 是其确定性终态
        self.assertEqual(obs.status, rt_state.STATUS_EMPTY)
        self.assertEqual(obs.payload["terminal_reason"], "empty_scope")
        self.assertIn("山西旅游第一天夜晚", obs.summary)

    def test_unmatched_stops_with_trip_reason(self):
        obs = self._resolve('{"timeline": "不存在的旅行"}', question="随便")
        self.assertEqual(obs.kind, rt_state.OBS_ERROR)
        # 时间线无法匹配是确定性失败，正确停止并建议换策略
        self.assertEqual(obs.status, rt_state.STATUS_PERMANENT_ERROR)
        self.assertEqual(obs.payload["terminal_reason"], "trip_unresolved")

    def test_illegal_values_treated_as_no_constraint(self):
        """非法天序/时段按"无该约束"处理，不终止。"""
        obs = self._resolve(
            '{"timeline": "山西旅游", "day": "第二天", "time_of_day": "黄昏", "soft_hints": []}',
            execute_ids=["a"],
        )
        self.assertEqual(obs.kind, rt_state.OBS_SCOPE)
        self.assertEqual(obs.payload["conditions"], {
            "timeline": "山西旅游", "day": "", "time_of_day": "",
        })
        # 只剩时间线约束，SQL 不带天序与小时窗
        self.assertNotIn("MIN(DATE", obs.payload["sql"])
        self.assertNotIn("BETWEEN", obs.payload["sql"])

    def test_validate_day_and_time_variants(self):
        self.assertEqual(caps_resolve_trip._validate_day("first"), "first")
        self.assertEqual(caps_resolve_trip._validate_day("2026-08-02"), "2026-08-02")
        self.assertEqual(caps_resolve_trip._validate_day("2026-13-99"), "")
        self.assertEqual(caps_resolve_trip._validate_day("第二天"), "")
        self.assertEqual(caps_resolve_trip._validate_time_of_day("傍晚"), "傍晚")
        self.assertEqual(caps_resolve_trip._validate_time_of_day("黄昏"), "")

    def test_relative_day_with_different_starts_needs_clarification(self):
        fake_llm = unittest.mock.MagicMock()
        fake_llm.invoke.return_value.content = (
            '{"timeline": "山西旅游", "day": "relative:2", "time_of_day": "", "soft_hints": []}'
        )
        with unittest.mock.patch.object(caps_resolve_trip, "_fetch_timelines", return_value=["山西旅游"]), \
             unittest.mock.patch.object(caps_common.llm_factory, "create_llm", return_value=fake_llm), \
             unittest.mock.patch.object(caps_resolve_trip, "_fetch_timeline_event_date", return_value="2026-08-01"), \
             unittest.mock.patch.object(caps_resolve_trip, "_fetch_first_photo_day", return_value="2026-08-02"):
            obs = caps_resolve_trip._resolve_trip({}, _ctx(_cfg(), question="找山西旅游第二天的照片"))
        self.assertEqual(obs.kind, rt_state.OBS_NEEDS_CLARIFICATION)
        # 澄清是设计内确定性停止，不是失败，恢复层不得重试
        self.assertEqual(obs.status, rt_state.STATUS_SUCCESS)
        self.assertEqual(obs.payload["options"], ["2026-08-02", "2026-08-03"])

    def test_month_day_uses_timeline_year_instead_of_model_guess(self):
        fake_llm = unittest.mock.MagicMock()
        fake_llm.invoke.return_value.content = (
            '{"timeline": "山西旅游", "day": "2025-08-03", "time_of_day": "", "soft_hints": []}'
        )
        with unittest.mock.patch.object(caps_resolve_trip, "_fetch_timelines", return_value=["山西旅游"]), \
             unittest.mock.patch.object(caps_common.llm_factory, "create_llm", return_value=fake_llm), \
             unittest.mock.patch.object(caps_resolve_trip, "_fetch_timeline_event_date", return_value="2026-08-01"), \
             unittest.mock.patch.object(caps_resolve_trip, "_fetch_first_photo_day", return_value="2026-08-02"), \
             unittest.mock.patch.object(caps_resolve_trip.text_to_sql, "execute_sql_for_ids", return_value=["a"]):
            obs = caps_resolve_trip._resolve_trip({}, _ctx(_cfg(), question="找山西旅游8月3日的照片"))
        self.assertEqual(obs.payload["conditions"]["day"], "2026-08-03")

    def test_build_scope_sql_combines_only_hard_constraints(self):
        sql = caps_resolve_trip.build_scope_sql("山西旅游", "last", 19, 23)
        self.assertIn("timeline = '山西旅游'", sql)
        self.assertIn(
            "DATE(shot_at, 'localtime') = (SELECT MAX(DATE(shot_at, 'localtime')) "
            "FROM photos WHERE timeline = '山西旅游')",
            sql,
        )
        self.assertIn(
            "CAST(strftime('%H', shot_at, 'localtime') AS INTEGER) BETWEEN 19 AND 23", sql,
        )
        date_sql = caps_resolve_trip.build_scope_sql("", "2026-08-02", None, None)
        self.assertEqual(date_sql,
                         "SELECT id FROM photos WHERE LOWER(file_type) != 'nef' AND DATE(shot_at, 'localtime') = '2026-08-02' "
                         "ORDER BY shot_at ASC LIMIT 500")
        escaped = caps_resolve_trip.build_scope_sql("O'rien't", "", None, None)
        self.assertIn("timeline = 'O''rien''t'", escaped)

    def test_build_scope_sql_day_without_timeline_uses_whole_library(self):
        """天序无时间线时按全库最早/最晚日期取值，不静默丢弃约束。"""
        sql = caps_resolve_trip.build_scope_sql("", "first", None, None)
        self.assertEqual(
            sql,
            "SELECT id FROM photos WHERE LOWER(file_type) != 'nef' AND DATE(shot_at, 'localtime') = "
            "(SELECT MIN(DATE(shot_at, 'localtime')) FROM photos) "
            "ORDER BY shot_at ASC LIMIT 500",
        )

    def test_match_timeline_names_fuzzy_variants(self):
        self.assertEqual(
            caps_resolve_trip._match_timeline_names("山西旅游 ", ["山西旅游"]), ["山西旅游"],
        )
        self.assertEqual(
            caps_resolve_trip._match_timeline_names("山西", ["山西旅游", "北京"]), ["山西旅游"],
        )
        self.assertEqual(caps_resolve_trip._match_timeline_names("都不是", ["山西旅游"]), [])
        self.assertEqual(caps_resolve_trip._match_timeline_names("", ["山西旅游"]), [])

    def test_match_timeline_names_exact_beats_similar_names(self):
        """时间线库里有相似名称时，精确命中仍是唯一确定匹配，不澄清。"""
        matches = caps_resolve_trip._match_timeline_names(
            "山西旅游", ["山西旅游", "山西旅游2025"],
        )
        self.assertEqual(matches, ["山西旅游"])

    def test_match_timeline_names_multi_containment_returns_all(self):
        """包含层级多条命中必须全部返回，供调用方触发澄清。"""
        matches = caps_resolve_trip._match_timeline_names(
            "山西", ["山西旅游", "山西旅拍", "北京街拍"],
        )
        self.assertEqual(matches, ["山西旅游", "山西旅拍"])

    def test_multi_match_timeline_triggers_clarification_not_silent_pick(self):
        """AR2-6：两条相似时间线时走澄清，不静默选第一条。"""
        fake_llm = unittest.mock.MagicMock()
        fake_llm.invoke.return_value.content = (
            '{"timeline": "山西", "day": "", "time_of_day": "", "soft_hints": []}'
        )
        with unittest.mock.patch.object(
            caps_resolve_trip, "_fetch_timelines",
            return_value=["山西旅游", "山西旅拍"],
        ), unittest.mock.patch.object(caps_common.llm_factory, "create_llm",
                                     return_value=fake_llm):
            obs = caps_resolve_trip._resolve_trip(
                {}, _ctx(_cfg(), question="找山西的照片发帖"),
            )
        self.assertEqual(obs.kind, rt_state.OBS_NEEDS_CLARIFICATION)
        self.assertEqual(obs.status, rt_state.STATUS_SUCCESS)
        self.assertEqual(obs.payload["confirm_kind"], "timeline")
        self.assertEqual(obs.payload["options"], ["山西旅游", "山西旅拍"])
        self.assertIn("山西旅游、山西旅拍", obs.payload["message"])

    def test_single_match_timeline_still_resolves_directly(self):
        """单匹配路径不受多匹配澄清影响（确定性自证）。"""
        fake_llm = unittest.mock.MagicMock()
        fake_llm.invoke.return_value.content = (
            '{"timeline": "山西", "day": "", "time_of_day": "", "soft_hints": []}'
        )
        with unittest.mock.patch.object(
            caps_resolve_trip, "_fetch_timelines", return_value=["山西旅游"],
        ), unittest.mock.patch.object(caps_common.llm_factory, "create_llm",
                                     return_value=fake_llm), \
             unittest.mock.patch.object(caps_resolve_trip.text_to_sql, "execute_sql_for_ids",
                                        return_value=["a"]) as exec_ids:
            obs = caps_resolve_trip._resolve_trip(
                {}, _ctx(_cfg(), question="找山西的照片发帖"),
            )
        self.assertEqual(obs.kind, rt_state.OBS_SCOPE)
        self.assertEqual(obs.payload["conditions"]["timeline"], "山西旅游")
        exec_ids.assert_called_once()


class RetrievalCapabilityTest(unittest.TestCase):
    def test_fetch_photos_batch_unwraps_photo_response(self):
        response = unittest.mock.MagicMock()
        response.json.return_value = {"photo": {"id": "a", "filename": "a.jpg"}}
        client = unittest.mock.MagicMock()
        client.__enter__.return_value.get.return_value = response
        with unittest.mock.patch.object(caps_common.http_utils, "create_client", return_value=client):
            photos = caps_common.fetch_photos_batch(_cfg(), ["a"])
        self.assertEqual(photos, [{"id": "a", "filename": "a.jpg", "shot_at": ""}])

    def _fetch_with_photo(self, photo: dict) -> dict:
        response = unittest.mock.MagicMock()
        response.json.return_value = {"photo": photo}
        client = unittest.mock.MagicMock()
        client.__enter__.return_value.get.return_value = response
        with unittest.mock.patch.object(caps_common.http_utils, "create_client", return_value=client):
            photos = caps_common.fetch_photos_batch(_cfg(), ["a"])
        return photos[0]

    def test_fetch_photos_batch_normalizes_shotat_unix_seconds(self):
        """后端真实契约：shotAt 是 Unix 秒（字符串或整数），归一化为本地 ISO 的 shot_at。

        回归背景：2026-09-04 山西请求中选片 context 与评委全程读到 shot_at=None
        （时段未知），评委持续拒绝导致修复环耗尽时长预算。
        """
        photo = self._fetch_with_photo({
            "id": "a", "filename": "a.jpg", "shotAt": "1785894484",
        })
        expected = datetime.datetime.fromtimestamp(1785894484).isoformat(timespec="seconds")
        self.assertEqual(photo["shot_at"], expected)
        self.assertEqual(photo["shotAt"], "1785894484")   # 原字段保留，其余字段不动

        photo = self._fetch_with_photo({
            "id": "a", "filename": "a.jpg", "shotAt": 1785894484,
        })
        self.assertEqual(photo["shot_at"], expected)

    def test_fetch_photos_batch_keeps_existing_shot_at(self):
        photo = self._fetch_with_photo({
            "id": "a", "filename": "a.jpg", "shot_at": "2026-08-01T18:00:00+08:00",
        })
        self.assertEqual(photo["shot_at"], "2026-08-01T18:00:00+08:00")

    def test_fetch_photos_batch_marks_missing_or_zero_shotat_unknown(self):
        """拍摄时间缺失或 0（EXIF 无数据）置空串，不伪装成 1970 年。"""
        for raw in ("", "0", 0, None):
            photo = self._fetch_with_photo({"id": "a", "filename": "a.jpg", "shotAt": raw})
            self.assertEqual(photo["shot_at"], "", f"shotAt={raw!r}")

    def test_sql_search_returns_photo_ids_observation(self):
        with unittest.mock.patch.object(caps_retrieval.text_to_sql, "generate_filter_sql",
                                        return_value="SELECT id FROM photos") as gen, \
             unittest.mock.patch.object(caps_retrieval.text_to_sql, "execute_sql_for_ids",
                                        return_value=["a", "b"]) as exec_ids:
            obs = caps_retrieval._sql_search({"query": "山西第一天"}, _ctx(_cfg()))
        self.assertEqual(obs.kind, rt_state.OBS_PHOTO_IDS)
        self.assertEqual(obs.status, rt_state.STATUS_SUCCESS)
        self.assertEqual(obs.payload["ids"], ["a", "b"])
        self.assertEqual(obs.payload["source"], "sql")
        gen.assert_called_once()
        exec_ids.assert_called_once_with("http://backend", "SELECT id FROM photos")

    def test_sql_search_empty_result_declares_empty_status(self):
        """SQL 检索 0 命中是合法空观察（候选由权威范围兜底），不是失败。"""
        with unittest.mock.patch.object(caps_retrieval.text_to_sql, "generate_filter_sql",
                                        return_value="SELECT id FROM photos"), \
             unittest.mock.patch.object(caps_retrieval.text_to_sql, "execute_sql_for_ids",
                                        return_value=[]):
            obs = caps_retrieval._sql_search({"query": "q"}, _ctx(_cfg()))
        self.assertEqual(obs.kind, rt_state.OBS_PHOTO_IDS)
        self.assertEqual(obs.status, rt_state.STATUS_EMPTY)

    def test_rag_search_empty_result_declares_empty_status(self):
        with unittest.mock.patch.object(caps_retrieval.photo_rag, "retrieve_photo_ids",
                                        return_value=[]):
            obs = caps_retrieval._rag_search({"query": "q"}, _ctx(_cfg()))
        self.assertEqual(obs.kind, rt_state.OBS_PHOTO_IDS)
        self.assertEqual(obs.status, rt_state.STATUS_EMPTY)

    def test_hybrid_search_intersects_with_rag_order(self):
        with unittest.mock.patch.object(caps_retrieval.text_to_sql, "generate_filter_sql",
                                        return_value="SQL"), \
             unittest.mock.patch.object(caps_retrieval.text_to_sql, "execute_sql_for_ids",
                                        return_value=["a", "b", "c"]), \
             unittest.mock.patch.object(caps_retrieval.photo_rag, "retrieve_photo_ids",
                                        return_value=["c", "a", "d"]):
            obs = caps_retrieval._hybrid_search({"query": "蓝调街拍"}, _ctx(_cfg()))
        self.assertEqual(obs.payload["ids"], ["c", "a"])
        self.assertEqual(obs.payload["source"], "hybrid")

    def test_hybrid_search_empty_sql_keeps_intersection_only(self):
        """结构化为空时交集为空，不再回退全库 RAG（候选由权威范围兜底）。"""
        with unittest.mock.patch.object(caps_retrieval.text_to_sql, "generate_filter_sql",
                                        return_value="SQL"), \
             unittest.mock.patch.object(caps_retrieval.text_to_sql, "execute_sql_for_ids",
                                        return_value=[]), \
             unittest.mock.patch.object(caps_retrieval.photo_rag, "retrieve_photo_ids",
                                        return_value=["x", "y"]):
            obs = caps_retrieval._hybrid_search({"query": "q"}, _ctx(_cfg()))
        self.assertEqual(obs.payload["ids"], [])
        self.assertEqual(obs.payload["source"], "hybrid")
        self.assertEqual(obs.status, rt_state.STATUS_EMPTY)

    def test_fetch_photo_details_requires_ids(self):
        obs = caps_photo_tools._fetch_photo_details({}, _ctx(_cfg()))
        self.assertEqual(obs.kind, rt_state.OBS_ERROR)
        # 空参数列表是调用契约违规（invalid_input）
        self.assertEqual(obs.status, rt_state.STATUS_INVALID_INPUT)

    def test_fetch_photo_details_stops_when_all_details_missing(self):
        with unittest.mock.patch.object(caps_common, "fetch_photos_batch", return_value=[]):
            obs = caps_photo_tools._fetch_photo_details({"ids": ["a"]}, _ctx(_cfg()))
        self.assertEqual(obs.kind, rt_state.OBS_ERROR)
        # 详情拉取失败以网络/后端不可达为主，按瞬时故障归类
        self.assertEqual(obs.status, rt_state.STATUS_TEMPORARY_ERROR)
        self.assertEqual(obs.payload["terminal_reason"], "photo_details_unavailable")

    def test_capability_exception_becomes_error_observation(self):
        with unittest.mock.patch.object(caps_retrieval.text_to_sql, "generate_filter_sql",
                                        side_effect=RuntimeError("后端挂了")):
            obs = caps_retrieval._sql_search({"query": "q"}, _ctx(_cfg()))
        self.assertEqual(obs.kind, rt_state.OBS_ERROR)
        self.assertIn("后端挂了", obs.summary)
        # 非网络类异常默认按永久失败归类
        self.assertEqual(obs.status, rt_state.STATUS_PERMANENT_ERROR)
        self.assertEqual(obs.payload["terminal_reason"], "capability_execution_failed")


# --------------------------------------------------------------------------- #
# 异常归类测试 — AR2-2（网络超时类 temporary，其余默认 permanent）
# --------------------------------------------------------------------------- #

class ExceptionClassificationTest(unittest.TestCase):

    def test_network_exceptions_classified_temporary(self):
        import httpx
        self.assertEqual(
            caps_common.classify_exception(httpx.ConnectError("后端不可达")),
            rt_state.STATUS_TEMPORARY_ERROR,
        )
        self.assertEqual(
            caps_common.classify_exception(httpx.ReadTimeout("读取超时")),
            rt_state.STATUS_TEMPORARY_ERROR,
        )
        self.assertEqual(
            caps_common.classify_exception(TimeoutError("超时")),
            rt_state.STATUS_TEMPORARY_ERROR,
        )

    def test_other_exceptions_classified_permanent(self):
        self.assertEqual(
            caps_common.classify_exception(RuntimeError("解析失败")),
            rt_state.STATUS_PERMANENT_ERROR,
        )
        self.assertEqual(
            caps_common.classify_exception(ValueError("输出契约违规")),
            rt_state.STATUS_PERMANENT_ERROR,
        )

    def test_capability_network_exception_carries_temporary_status(self):
        """真实场景：Go 后端断连应归类瞬时故障（AR2-3 有界重试的触发条件）。"""
        import httpx
        with unittest.mock.patch.object(
            caps_retrieval.text_to_sql, "generate_filter_sql",
            side_effect=httpx.ConnectError("后端不可达"),
        ):
            obs = caps_retrieval._sql_search({"query": "q"}, _ctx(_cfg()))
        self.assertEqual(obs.kind, rt_state.OBS_ERROR)
        self.assertEqual(obs.status, rt_state.STATUS_TEMPORARY_ERROR)

    def test_sdk_connection_failure_classified_temporary(self):
        """SDK（swagger/urllib3 栈）连接失败是真实后端断连的异常形态，同样归瞬时。"""
        import urllib3.exceptions
        self.assertEqual(
            caps_common.classify_exception(urllib3.exceptions.MaxRetryError(
                None, "/", None,
            )),
            rt_state.STATUS_TEMPORARY_ERROR,
        )


class BuildRegistryTest(unittest.TestCase):
    def test_registers_all_capabilities_with_valid_params(self):
        registry = rt_caps.build_registry()
        self.assertEqual(registry.names(), [
            "resolve_trip", "sql_search", "rag_search", "hybrid_search",
            "fetch_photo_details", "select_photos", "write_post",
        ])
        self.assertEqual(registry.validate_params("sql_search", {"query": "q"}), [])
        self.assertTrue(registry.validate_params("sql_search", {}))


if __name__ == "__main__":
    unittest.main()
