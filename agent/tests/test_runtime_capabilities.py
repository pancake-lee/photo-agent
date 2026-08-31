import unittest
import unittest.mock

import internal.runtime.capabilities as rt_caps
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
        result = rt_caps.collapse_burst_candidates([
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
        mode, covers = rt_caps.prepare_select_candidates(photos, group_limit=2, cover_limit=3)
        self.assertEqual(mode, "covers")
        self.assertNotIn("_group_count", covers[0])
        overflow_mode, overflow = rt_caps.prepare_select_candidates(
            photos, group_limit=1, cover_limit=2,
        )
        self.assertEqual(overflow_mode, "overflow")
        self.assertEqual(rt_caps.select_token(overflow[0]), "g:g0:0")


class SelectPhotosCapabilityTest(unittest.TestCase):
    """迁移自 CQ4 test_overflow_returns_existing_post_studio_deep_link。"""

    def test_overflow_returns_existing_post_studio_deep_link(self):
        cfg = _cfg(compose_group_limit=1, compose_cover_limit=2)
        task = rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "写文案", {"question": "写文案"})
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_PHOTO_IDS, "检索", {"ids": ["a", "b", "c"]},
        ), step_no=1, action="sql_search")
        with unittest.mock.patch.object(rt_caps, "fetch_photos_batch",
                                        return_value=[{"id": "a"}, {"id": "b"}, {"id": "c"}]):
            obs = rt_caps._select_photos({}, _ctx(cfg, task))
        self.assertEqual(obs.kind, rt_state.OBS_SELECTION_OVERFLOW)
        self.assertEqual(obs.payload["url"], "#/post-studio?photo_ids=a,b,c")

    def test_select_without_candidates_returns_error(self):
        task = rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "写文案", {"question": "q"})
        obs = rt_caps._select_photos({}, _ctx(_cfg(), task))
        self.assertEqual(obs.kind, rt_state.OBS_ERROR)

    def test_select_happy_path_filters_invalid_ids(self):
        cfg = _cfg(compose_group_limit=20, compose_cover_limit=40)
        task = rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "挑照片", {"question": "挑照片"})
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_PHOTO_IDS, "检索", {"ids": ["a", "b", "c"]},
        ), step_no=1, action="sql_search")
        fake_llm = unittest.mock.MagicMock()
        fake_llm.invoke.return_value.content = '{"selected_ids": ["b", "ghost", "a"]}'
        with unittest.mock.patch.object(rt_caps, "fetch_photos_batch", return_value=[
            {"id": "a", "filename": "a.jpg"}, {"id": "b", "filename": "b.jpg"},
            {"id": "c", "filename": "c.jpg"},
        ]), unittest.mock.patch.object(rt_caps.llm_factory, "create_llm", return_value=fake_llm):
            obs = rt_caps._select_photos({}, _ctx(_cfg(), task))
        self.assertEqual(obs.kind, rt_state.OBS_PHOTOS_SELECTED)
        self.assertEqual(obs.payload["ids"], ["b", "a"])

    def test_select_respects_max_photos(self):
        task = rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "挑照片", {"question": "q"})
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_PHOTO_IDS, "检索", {"ids": ["a", "b", "c"]},
        ), step_no=1, action="sql_search")
        fake_llm = unittest.mock.MagicMock()
        fake_llm.invoke.return_value.content = '{"selected_ids": ["a", "b", "c"]}'
        with unittest.mock.patch.object(rt_caps, "fetch_photos_batch", return_value=[
            {"id": "a"}, {"id": "b"}, {"id": "c"},
        ]), unittest.mock.patch.object(rt_caps.llm_factory, "create_llm", return_value=fake_llm):
            obs = rt_caps._select_photos({"max_photos": 2}, _ctx(_cfg(), task))
        self.assertEqual(obs.payload["ids"], ["a", "b"])

    def test_select_empty_pick_returns_error(self):
        task = rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "挑照片", {"question": "q"})
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_PHOTO_IDS, "检索", {"ids": ["a"]},
        ), step_no=1, action="sql_search")
        fake_llm = unittest.mock.MagicMock()
        fake_llm.invoke.return_value.content = "模型罢工了，没有 JSON"
        with unittest.mock.patch.object(rt_caps, "fetch_photos_batch", return_value=[{"id": "a"}]), \
             unittest.mock.patch.object(rt_caps.llm_factory, "create_llm", return_value=fake_llm):
            obs = rt_caps._select_photos({}, _ctx(_cfg(), task))
        self.assertEqual(obs.kind, rt_state.OBS_ERROR)
        self.assertEqual(obs.payload["terminal_reason"], "photo_selection_failed")

    def test_select_without_photo_details_stops_deterministically(self):
        task = rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "挑照片", {"question": "q"})
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_PHOTO_IDS, "检索", {"ids": ["a"]},
        ), step_no=1, action="sql_search")
        with unittest.mock.patch.object(rt_caps, "fetch_photos_batch", return_value=[]):
            obs = rt_caps._select_photos({}, _ctx(_cfg(), task))
        self.assertEqual(obs.kind, rt_state.OBS_ERROR)
        self.assertEqual(obs.payload["terminal_reason"], "photo_details_unavailable")


class WritePostCapabilityTest(unittest.TestCase):
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
        with unittest.mock.patch.object(rt_caps, "fetch_photos_batch",
                                        return_value=[{"id": "a", "description": "面馆"}]) as fetch, \
             unittest.mock.patch.object(rt_caps.post_studio, "generate_post",
                                        return_value=("山西行记", "正文", ["1 张照片缺少描述"])) as gen:
            obs = rt_caps._write_post({"style": "文艺"}, _ctx(cfg, task))
        self.assertEqual(obs.kind, rt_state.OBS_COPY_DRAFTED)
        self.assertEqual(obs.payload["title"], "山西行记")
        self.assertIn("1 张照片缺少描述", obs.summary)
        fetch.assert_called_once_with(cfg, ["a"])
        photos_arg = gen.call_args[0][1]
        self.assertEqual([p.id for p in photos_arg], ["b", "a"])
        self.assertEqual(gen.call_args[0][2], "文艺")

    def test_write_post_without_selection_returns_error(self):
        task = rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "发帖", {"question": "q"})
        obs = rt_caps._write_post({}, _ctx(_cfg(), task))
        self.assertEqual(obs.kind, rt_state.OBS_ERROR)


class ResolveTripCapabilityTest(unittest.TestCase):
    def _mock_http(self, timelines):
        mock_client = unittest.mock.MagicMock()
        mock_resp = unittest.mock.MagicMock()
        mock_resp.json.return_value = {"timelines": timelines}
        mock_client.__enter__.return_value.get.return_value = mock_resp
        return mock_client

    def test_matched_timeline_produces_fact(self):
        fake_llm = unittest.mock.MagicMock()
        fake_llm.invoke.return_value.content = '{"timeline": "山西旅游"}'
        with unittest.mock.patch.object(rt_caps, "_fetch_timelines",
                                        return_value=["山西旅游", "北京街拍"]), \
             unittest.mock.patch.object(rt_caps.llm_factory, "create_llm", return_value=fake_llm):
            obs = rt_caps._resolve_trip({}, _ctx(_cfg(), question="找山西旅游第一天的照片"))
        self.assertEqual(obs.kind, rt_state.OBS_FACTS)
        self.assertEqual(obs.payload["facts"], {"timeline": "山西旅游"})

    def test_unmatched_stops_with_trip_reason(self):
        fake_llm = unittest.mock.MagicMock()
        fake_llm.invoke.return_value.content = '{"timeline": "不存在的旅行"}'
        with unittest.mock.patch.object(rt_caps, "_fetch_timelines",
                                        return_value=["山西旅游", "北京街拍"]), \
             unittest.mock.patch.object(rt_caps.llm_factory, "create_llm", return_value=fake_llm):
            obs = rt_caps._resolve_trip({}, _ctx(_cfg(), question="随便"))
        self.assertEqual(obs.kind, rt_state.OBS_ERROR)
        self.assertEqual(obs.payload["terminal_reason"], "trip_unresolved")

    def test_match_timeline_name_fuzzy_variants(self):
        self.assertEqual(rt_caps._match_timeline_name("山西旅游 ", ["山西旅游"]), "山西旅游")
        self.assertEqual(rt_caps._match_timeline_name("山西", ["山西旅游", "北京"]), "山西旅游")
        self.assertEqual(rt_caps._match_timeline_name("都不是", ["山西旅游"]), "")


class RetrievalCapabilityTest(unittest.TestCase):
    def test_fetch_photos_batch_unwraps_photo_response(self):
        response = unittest.mock.MagicMock()
        response.json.return_value = {"photo": {"id": "a", "filename": "a.jpg"}}
        client = unittest.mock.MagicMock()
        client.__enter__.return_value.get.return_value = response
        with unittest.mock.patch.object(rt_caps.http_utils, "create_client", return_value=client):
            photos = rt_caps.fetch_photos_batch(_cfg(), ["a"])
        self.assertEqual(photos, [{"id": "a", "filename": "a.jpg"}])

    def test_sql_search_returns_photo_ids_observation(self):
        with unittest.mock.patch.object(rt_caps.text_to_sql, "generate_filter_sql",
                                        return_value="SELECT id FROM photos") as gen, \
             unittest.mock.patch.object(rt_caps.text_to_sql, "execute_sql_for_ids",
                                        return_value=["a", "b"]) as exec_ids:
            obs = rt_caps._sql_search({"query": "山西第一天"}, _ctx(_cfg()))
        self.assertEqual(obs.kind, rt_state.OBS_PHOTO_IDS)
        self.assertEqual(obs.payload["ids"], ["a", "b"])
        self.assertEqual(obs.payload["source"], "sql")
        gen.assert_called_once()
        exec_ids.assert_called_once_with("http://backend", "SELECT id FROM photos")

    def test_hybrid_search_intersects_with_rag_order(self):
        with unittest.mock.patch.object(rt_caps.text_to_sql, "generate_filter_sql",
                                        return_value="SQL"), \
             unittest.mock.patch.object(rt_caps.text_to_sql, "execute_sql_for_ids",
                                        return_value=["a", "b", "c"]), \
             unittest.mock.patch.object(rt_caps.photo_rag, "retrieve_photo_ids",
                                        return_value=["c", "a", "d"]):
            obs = rt_caps._hybrid_search({"query": "蓝调街拍"}, _ctx(_cfg()))
        self.assertEqual(obs.payload["ids"], ["c", "a"])
        self.assertEqual(obs.payload["source"], "hybrid")

    def test_hybrid_search_empty_sql_falls_back_to_rag(self):
        with unittest.mock.patch.object(rt_caps.text_to_sql, "generate_filter_sql",
                                        return_value="SQL"), \
             unittest.mock.patch.object(rt_caps.text_to_sql, "execute_sql_for_ids",
                                        return_value=[]), \
             unittest.mock.patch.object(rt_caps.photo_rag, "retrieve_photo_ids",
                                        return_value=["x", "y"]):
            obs = rt_caps._hybrid_search({"query": "q"}, _ctx(_cfg()))
        self.assertEqual(obs.payload["ids"], ["x", "y"])
        self.assertEqual(obs.payload["source"], "hybrid_fallback_rag")

    def test_fetch_photo_details_requires_ids(self):
        obs = rt_caps._fetch_photo_details({}, _ctx(_cfg()))
        self.assertEqual(obs.kind, rt_state.OBS_ERROR)

    def test_fetch_photo_details_stops_when_all_details_missing(self):
        with unittest.mock.patch.object(rt_caps, "fetch_photos_batch", return_value=[]):
            obs = rt_caps._fetch_photo_details({"ids": ["a"]}, _ctx(_cfg()))
        self.assertEqual(obs.kind, rt_state.OBS_ERROR)
        self.assertEqual(obs.payload["terminal_reason"], "photo_details_unavailable")

    def test_capability_exception_becomes_error_observation(self):
        with unittest.mock.patch.object(rt_caps.text_to_sql, "generate_filter_sql",
                                        side_effect=RuntimeError("后端挂了")):
            obs = rt_caps._sql_search({"query": "q"}, _ctx(_cfg()))
        self.assertEqual(obs.kind, rt_state.OBS_ERROR)
        self.assertIn("后端挂了", obs.summary)
        self.assertEqual(obs.payload["terminal_reason"], "capability_execution_failed")


class BuildRegistryTest(unittest.TestCase):
    def test_registers_all_capabilities_with_valid_params(self):
        registry = rt_caps.build_registry()
        self.assertEqual(registry.names(), [
            "sql_search", "rag_search", "hybrid_search", "resolve_trip",
            "fetch_photo_details", "select_photos", "write_post",
        ])
        self.assertEqual(registry.validate_params("sql_search", {"query": "q"}), [])
        self.assertTrue(registry.validate_params("sql_search", {}))


if __name__ == "__main__":
    unittest.main()
