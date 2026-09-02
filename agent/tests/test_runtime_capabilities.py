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
        self.assertEqual(obs.payload["url"], "#/post-studio?photo_ids=a,b,c")

    def test_select_without_candidates_returns_error(self):
        task = rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "写文案", {"question": "q"})
        obs = caps_creation._select_photos({}, _ctx(_cfg(), task))
        self.assertEqual(obs.kind, rt_state.OBS_ERROR)

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
        self.assertEqual(obs.payload["terminal_reason"], "photo_selection_failed")

    def test_select_without_photo_details_stops_deterministically(self):
        task = rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "挑照片", {"question": "q"})
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_PHOTO_IDS, "检索", {"ids": ["a"]},
        ), step_no=1, action="sql_search")
        with unittest.mock.patch.object(caps_common, "fetch_photos_batch", return_value=[]):
            obs = caps_creation._select_photos({}, _ctx(_cfg(), task))
        self.assertEqual(obs.kind, rt_state.OBS_ERROR)
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
        self.assertIn("1 张照片缺少描述", obs.summary)
        fetch.assert_called_once_with(cfg, ["a"])
        photos_arg = gen.call_args[0][1]
        self.assertEqual([p.id for p in photos_arg], ["b", "a"])
        self.assertEqual(gen.call_args[0][2], "文艺")

    def test_write_post_without_selection_returns_error(self):
        task = rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "发帖", {"question": "q"})
        obs = caps_creation._write_post({}, _ctx(_cfg(), task))
        self.assertEqual(obs.kind, rt_state.OBS_ERROR)


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
        self.assertEqual(obs.payload["terminal_reason"], "empty_scope")
        self.assertIn("山西旅游第一天夜晚", obs.summary)

    def test_unmatched_stops_with_trip_reason(self):
        obs = self._resolve('{"timeline": "不存在的旅行"}', question="随便")
        self.assertEqual(obs.kind, rt_state.OBS_ERROR)
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
                         "SELECT id FROM photos WHERE DATE(shot_at, 'localtime') = '2026-08-02' "
                         "ORDER BY shot_at ASC LIMIT 500")
        escaped = caps_resolve_trip.build_scope_sql("O'rien't", "", None, None)
        self.assertIn("timeline = 'O''rien''t'", escaped)

    def test_build_scope_sql_day_without_timeline_uses_whole_library(self):
        """天序无时间线时按全库最早/最晚日期取值，不静默丢弃约束。"""
        sql = caps_resolve_trip.build_scope_sql("", "first", None, None)
        self.assertEqual(
            sql,
            "SELECT id FROM photos WHERE DATE(shot_at, 'localtime') = "
            "(SELECT MIN(DATE(shot_at, 'localtime')) FROM photos) "
            "ORDER BY shot_at ASC LIMIT 500",
        )

    def test_match_timeline_name_fuzzy_variants(self):
        self.assertEqual(caps_resolve_trip._match_timeline_name("山西旅游 ", ["山西旅游"]), "山西旅游")
        self.assertEqual(caps_resolve_trip._match_timeline_name("山西", ["山西旅游", "北京"]), "山西旅游")
        self.assertEqual(caps_resolve_trip._match_timeline_name("都不是", ["山西旅游"]), "")


class RetrievalCapabilityTest(unittest.TestCase):
    def test_fetch_photos_batch_unwraps_photo_response(self):
        response = unittest.mock.MagicMock()
        response.json.return_value = {"photo": {"id": "a", "filename": "a.jpg"}}
        client = unittest.mock.MagicMock()
        client.__enter__.return_value.get.return_value = response
        with unittest.mock.patch.object(caps_common.http_utils, "create_client", return_value=client):
            photos = caps_common.fetch_photos_batch(_cfg(), ["a"])
        self.assertEqual(photos, [{"id": "a", "filename": "a.jpg"}])

    def test_sql_search_returns_photo_ids_observation(self):
        with unittest.mock.patch.object(caps_retrieval.text_to_sql, "generate_filter_sql",
                                        return_value="SELECT id FROM photos") as gen, \
             unittest.mock.patch.object(caps_retrieval.text_to_sql, "execute_sql_for_ids",
                                        return_value=["a", "b"]) as exec_ids:
            obs = caps_retrieval._sql_search({"query": "山西第一天"}, _ctx(_cfg()))
        self.assertEqual(obs.kind, rt_state.OBS_PHOTO_IDS)
        self.assertEqual(obs.payload["ids"], ["a", "b"])
        self.assertEqual(obs.payload["source"], "sql")
        gen.assert_called_once()
        exec_ids.assert_called_once_with("http://backend", "SELECT id FROM photos")

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

    def test_fetch_photo_details_requires_ids(self):
        obs = caps_photo_tools._fetch_photo_details({}, _ctx(_cfg()))
        self.assertEqual(obs.kind, rt_state.OBS_ERROR)

    def test_fetch_photo_details_stops_when_all_details_missing(self):
        with unittest.mock.patch.object(caps_common, "fetch_photos_batch", return_value=[]):
            obs = caps_photo_tools._fetch_photo_details({"ids": ["a"]}, _ctx(_cfg()))
        self.assertEqual(obs.kind, rt_state.OBS_ERROR)
        self.assertEqual(obs.payload["terminal_reason"], "photo_details_unavailable")

    def test_capability_exception_becomes_error_observation(self):
        with unittest.mock.patch.object(caps_retrieval.text_to_sql, "generate_filter_sql",
                                        side_effect=RuntimeError("后端挂了")):
            obs = caps_retrieval._sql_search({"query": "q"}, _ctx(_cfg()))
        self.assertEqual(obs.kind, rt_state.OBS_ERROR)
        self.assertIn("后端挂了", obs.summary)
        self.assertEqual(obs.payload["terminal_reason"], "capability_execution_failed")


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
