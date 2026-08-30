import unittest
import unittest.mock

from chain import photo_agent


class ComposeQueryTest(unittest.TestCase):
    def test_collapses_burst_group_to_cover(self):
        result = photo_agent._collapse_compose_candidates([
            {"id": "a", "burst_group_id": "g"},
            {"id": "b", "burst_group_id": "g", "is_burst_cover": True},
            {"id": "c"},
        ])
        self.assertEqual([item["id"] for item in result], ["b", "c"])
        self.assertEqual(result[0]["_group_count"], 2)


    def test_two_level_shrink_and_overflow_tokens(self):
        photos = [{"id": str(index), "burst_group_id": f"g{index}"} for index in range(3)]
        mode, covers = photo_agent._prepare_compose_candidates(photos, group_limit=2, cover_limit=3)
        self.assertEqual(mode, "covers")
        self.assertNotIn("_group_count", covers[0])
        overflow_mode, overflow = photo_agent._prepare_compose_candidates(photos, group_limit=1, cover_limit=2)
        self.assertEqual(overflow_mode, "overflow")
        self.assertEqual(photo_agent._compose_photo_token(overflow[0]), "g:g0:0")

    def test_overflow_returns_existing_post_studio_deep_link(self):
        cfg = type("Config", (), {"go_backend_url": "http://backend", "compose_group_limit": 1, "compose_cover_limit": 2})()
        with unittest.mock.patch.object(photo_agent.text_to_sql, "generate_filter_sql", return_value="SELECT id FROM photos"), \
             unittest.mock.patch.object(photo_agent.text_to_sql, "execute_sql_for_ids", return_value=["a", "b", "c"]), \
             unittest.mock.patch.object(photo_agent, "_fetch_photos_batch", return_value=[{"id": "a"}, {"id": "b"}, {"id": "c"}]):
            result = photo_agent._compose_node({"question": "写文案"}, {"configurable": {"cfg": cfg}})
        self.assertEqual(result["compose_url"], "#/post-studio?photo_ids=a,b,c")
