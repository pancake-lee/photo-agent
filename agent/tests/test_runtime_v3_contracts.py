"""AR3：目标契约、能力层级和第二目标的离线回归。"""

import unittest
import unittest.mock

import internal.runtime.capabilities.comparison as comparison
import internal.runtime.capabilities.common as caps_common
import internal.runtime.capabilities.resolve_trip as resolve_trip
import internal.runtime.capabilities.retrieval as retrieval
import internal.runtime.capabilities.workflows as workflows
import internal.runtime.completion as completion
import internal.runtime.graph as graph
import internal.runtime.registry as registry_mod
import internal.runtime.state as state
import internal.topics.suggest as suggest_mod


def _ctx(task, question="对比 2025 和 2026 春天的洱海照片"):
    cfg = type("Config", (), {"go_backend_url": "http://backend"})()
    return registry_mod.RunContext(cfg=cfg, state=task, question=question)


class GoalContractTest(unittest.TestCase):
    def test_delivery_variant_is_explicit_not_inferred_from_words(self):
        task = state.new_task(state.GOAL_SOCIAL_POST, "尽可能多给我照片，我会二次挑选")
        self.assertEqual(task.goal.delivery_mode, "editorial")
        candidate = state.new_task(state.GOAL_SOCIAL_POST, "同一请求", delivery_mode="candidate")
        self.assertEqual(candidate.goal.delivery_mode, "candidate")

    def test_comparison_contract_rejects_post_only_capability(self):
        task = state.new_task(state.GOAL_PHOTO_COMPARISON, "比较两期照片")
        self.assertNotIn("write_post", task.goal.allowed_capabilities)
        with self.assertRaises(ValueError):
            state.reduce_observation(task, state.Observation(
                state.OBS_COPY_DRAFTED, "文案", {"title": "x", "content": "y"},
            ))

    def test_every_registered_capability_has_complete_machine_contract(self):
        from internal.runtime import capabilities
        registry = capabilities.build_registry()
        levels = set()
        for spec in registry.specs():
            levels.add(spec["level"])
            self.assertTrue(spec["applicable_when"])
            self.assertTrue(spec["not_applicable_when"])
            self.assertTrue(spec["output"])
            self.assertTrue(spec["errors"])
        self.assertEqual(levels, {"tool", "skill", "workflow"})


class ComparisonCapabilityTest(unittest.TestCase):
    def test_two_period_evidence_builds_traceable_report(self):
        task = state.new_task(state.GOAL_PHOTO_COMPARISON, "比较两期照片")
        for period, photo_id in (("earlier", "old"), ("later", "new")):
            task = state.reduce_observation(task, state.Observation(
                state.OBS_SCOPE, f"{period} 范围", {
                    "period": period, "restricted": True, "ids": [photo_id],
                    "condition_summary": period, "conditions": {},
                },
            ), action="resolve_trip")
            task = state.reduce_observation(task, state.Observation(
                state.OBS_PHOTO_IDS, f"{period} 候选", {"period": period, "ids": [photo_id]},
            ), action="sql_search")
        fake_llm = unittest.mock.MagicMock()
        fake_llm.invoke.return_value.content = '{"summary":"近期构图更稳定","strengths":["取景更克制"],"next_steps":["继续练习光线"]}'
        photos = [
            {"id": "old", "shot_at": "2025-04-01", "description": "湖面"},
            {"id": "new", "shot_at": "2026-04-01", "description": "湖边人物"},
        ]
        with unittest.mock.patch.object(caps_common, "fetch_photos_batch", return_value=photos), \
             unittest.mock.patch.object(caps_common.llm_factory, "create_llm", return_value=fake_llm):
            obs = comparison._compare_photo_periods({}, _ctx(task))
        task = state.reduce_observation(task, obs, action="compare_photo_periods")
        self.assertTrue(completion.check_completion(task).complete)
        self.assertIn("old", state.build_final_output(task)["answer"])
        self.assertIn("new", state.build_final_output(task)["answer"])

    def test_report_cannot_bypass_verified_period_evidence(self):
        task = state.new_task(state.GOAL_PHOTO_COMPARISON, "比较两期照片")
        with self.assertRaises(ValueError):
            state.reduce_observation(task, state.Observation(
                state.OBS_PHOTO_IDS, "缺少期别", {"ids": ["old"]},
            ), action="sql_search")

    def test_runtime_collects_two_scoped_groups_before_comparison(self):
        class ScriptedLLM:
            def __init__(self):
                self.decisions = iter([
                    '{"action":"resolve_trip","params":{"hint":"2025年春天","period":"earlier"},"reason":"早期范围"}',
                    '{"action":"sql_search","params":{"query":"洱海","period":"earlier"},"reason":"早期检索"}',
                    '{"action":"resolve_trip","params":{"hint":"2026年春天","period":"later"},"reason":"近期范围"}',
                    '{"action":"sql_search","params":{"query":"洱海","period":"later"},"reason":"近期检索"}',
                    '{"action":"compare_photo_periods","params":{},"reason":"形成结论"}',
                ])

            def invoke(self, messages):
                text = "".join(str(getattr(message, "content", message)) for message in messages)
                if "执行规划器" in text:
                    content = next(self.decisions)
                elif "时间线列表" in text:
                    content = (
                        '{"timeline":"","day":"","date_range":{"start":"2025-03-01","end":"2025-05-31"},"time_of_day":"","soft_hints":["洱海"]}'
                        if "2025年春天" in text else
                        '{"timeline":"","day":"","date_range":{"start":"2026-03-01","end":"2026-05-31"},"time_of_day":"","soft_hints":["洱海"]}'
                    )
                else:
                    content = '{"summary":"近期构图更稳定","strengths":["取景更克制"],"next_steps":["继续练习光线"]}'
                response = unittest.mock.MagicMock()
                response.content = content
                return response

        cfg = type("Config", (), {
            "go_backend_url": "http://backend", "runtime_max_steps": 6,
            "runtime_timeout_seconds": 300.0, "runtime_cost_limit": 0,
            "runtime_retry_max": 1, "runtime_repair_max": 1, "runtime_redecide_max": 1,
            "rag_distance_threshold": None, "rag_auto_distance_ratio": 1.8,
        })()
        llm = ScriptedLLM()
        calls = iter([["old"], ["old"], ["new"], ["new"]])
        photos = {
            "old": {"id": "old", "shot_at": "2025-04-01", "description": "湖面"},
            "new": {"id": "new", "shot_at": "2026-04-01", "description": "湖边人物"},
        }
        with unittest.mock.patch.object(caps_common.llm_factory, "create_llm", return_value=llm), \
             unittest.mock.patch.object(resolve_trip, "_fetch_timelines", return_value=[]), \
             unittest.mock.patch.object(retrieval.text_to_sql, "generate_filter_sql", return_value="SELECT id FROM photos"), \
             unittest.mock.patch.object(retrieval.text_to_sql, "execute_sql_for_ids", side_effect=lambda *args, **kwargs: next(calls)), \
             unittest.mock.patch.object(caps_common, "fetch_photos_batch", side_effect=lambda _ctx, ids: [photos[pid] for pid in ids]):
            result = graph.run_runtime(cfg, "对比 2025 和 2026 春天的洱海照片", goal_type=state.GOAL_PHOTO_COMPARISON)
        self.assertEqual(result["terminal_reason"], "")
        self.assertEqual(result["stop_reason"], "")
        self.assertIn("old", result["answer"])
        self.assertIn("new", result["answer"])


class TopicWorkflowTest(unittest.TestCase):
    def test_topic_expansion_supplements_sparse_rag_within_scope(self):
        photos = [
            type("Photo", (), {
                "id": f"p{index}", "shot_at": "2026-05-01",
            })()
            for index in range(9)
        ]
        intuition = suggest_mod.TopicIntuition("五月光影", "观察五月光线", "有连续性", [0])
        cfg = type("Config", (), {})()
        with unittest.mock.patch(
            "internal.chat.photo_rag.retrieve_photo_ids", return_value=["p0"],
        ):
            expanded = suggest_mod._stage2_expand_selection(cfg, intuition, photos)
        self.assertGreaterEqual(len(expanded), 6)
        self.assertTrue({photo.id for photo in expanded}.issubset({photo.id for photo in photos}))

    def test_workflow_passes_explicit_scope_without_history_write(self):
        task = state.new_task(state.GOAL_TOPIC_DISCOVERY, "找雨天主题")
        task.scope = state.Scope(established=True, restricted=True, photo_ids=["a", "b"])
        suggestion = type("Suggestion", (), {"title": "雨中城市", "rationale": "光线变化", "photo_ids": ["a", "b"]})()
        with unittest.mock.patch.object(workflows.suggest_mod, "run_suggest", return_value=([suggestion], {})) as run:
            obs = workflows._discover_topics({}, _ctx(task))
        self.assertEqual(obs.kind, state.OBS_TOPICS_DISCOVERED)
        self.assertEqual(run.call_args.kwargs["scope_photo_ids"], ["a", "b"])

    def test_runtime_topic_goal_runs_scoped_workflow(self):
        class ScriptedLLM:
            def __init__(self):
                self.decisions = iter([
                    '{"action":"resolve_trip","params":{"hint":"山西旅游"},"reason":"确认范围"}',
                    '{"action":"discover_topics","params":{},"reason":"发现主题"}',
                ])

            def invoke(self, messages):
                text = "".join(str(getattr(message, "content", message)) for message in messages)
                content = next(self.decisions) if "执行规划器" in text else (
                    '{"timeline":"山西旅游","day":"","date_range":{"start":"","end":""},"time_of_day":"","soft_hints":[]}'
                )
                response = unittest.mock.MagicMock()
                response.content = content
                return response

        cfg = type("Config", (), {
            "go_backend_url": "http://backend", "runtime_max_steps": 4,
            "runtime_timeout_seconds": 300.0, "runtime_cost_limit": 0,
            "runtime_retry_max": 1, "runtime_repair_max": 1, "runtime_redecide_max": 1,
        })()
        suggestion = type("Suggestion", (), {
            "title": "雨中城市", "rationale": "光线变化", "photo_ids": ["a", "b"],
        })()
        with unittest.mock.patch.object(caps_common.llm_factory, "create_llm", return_value=ScriptedLLM()), \
             unittest.mock.patch.object(resolve_trip, "_fetch_timelines", return_value=["山西旅游"]), \
             unittest.mock.patch.object(resolve_trip.text_to_sql, "execute_sql_for_ids", return_value=["a", "b"]), \
             unittest.mock.patch.object(workflows.suggest_mod, "run_suggest", return_value=([suggestion], {})) as run:
            result = graph.run_runtime(cfg, "在山西旅游照片中发现选题", goal_type=state.GOAL_TOPIC_DISCOVERY)
        self.assertEqual(result["terminal_reason"], "")
        self.assertEqual(result["stop_reason"], "")
        self.assertIn("雨中城市", result["answer"])
        self.assertEqual(run.call_args.kwargs["scope_photo_ids"], ["a", "b"])
