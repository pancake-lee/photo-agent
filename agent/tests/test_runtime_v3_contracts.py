"""AR3：目标契约、能力层级和第二目标的离线回归。"""

import unittest
import unittest.mock

import internal.runtime.capabilities.comparison as comparison
import internal.runtime.capabilities.common as caps_common
import internal.runtime.capabilities.workflows as workflows
import internal.runtime.completion as completion
import internal.runtime.registry as registry_mod
import internal.runtime.state as state


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
        fake_llm = unittest.mock.MagicMock()
        fake_llm.invoke.return_value.content = '{"summary":"近期构图更稳定","strengths":["取景更克制"],"next_steps":["继续练习光线"]}'
        photos = [
            {"id": "old", "shot_at": "2025-04-01", "description": "湖面"},
            {"id": "new", "shot_at": "2026-04-01", "description": "湖边人物"},
        ]
        with unittest.mock.patch.object(caps_common, "fetch_photos_batch", return_value=photos), \
             unittest.mock.patch.object(caps_common.llm_factory, "create_llm", return_value=fake_llm):
            obs = comparison._compare_photo_periods({"earlier_ids": ["old"], "later_ids": ["new"]}, _ctx(task))
        task = state.reduce_observation(task, obs, action="compare_photo_periods")
        self.assertTrue(completion.check_completion(task).complete)
        self.assertIn("old", state.build_final_output(task)["answer"])
        self.assertIn("new", state.build_final_output(task)["answer"])


class TopicWorkflowTest(unittest.TestCase):
    def test_workflow_passes_explicit_scope_without_history_write(self):
        task = state.new_task(state.GOAL_TOPIC_DISCOVERY, "找雨天主题")
        suggestion = type("Suggestion", (), {"title": "雨中城市", "rationale": "光线变化", "photo_ids": ["a", "b"]})()
        with unittest.mock.patch.object(workflows.suggest_mod, "run_suggest", return_value=([suggestion], {})) as run:
            obs = workflows._discover_topics({"photo_ids": ["a", "b"]}, _ctx(task))
        self.assertEqual(obs.kind, state.OBS_TOPICS_DISCOVERED)
        self.assertEqual(run.call_args.kwargs["scope_photo_ids"], ["a", "b"])

