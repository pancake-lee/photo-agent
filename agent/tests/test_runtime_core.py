import time
import unittest

import runtime.budget as rt_budget
import runtime.completion as rt_completion
import runtime.registry as rt_registry
import runtime.state as rt_state


class BudgetTest(unittest.TestCase):
    def test_step_budget_stops_at_limit(self):
        state = rt_budget.BudgetState()
        budget = rt_budget.Budget(max_steps=3, timeout_seconds=60, cost_limit=0)
        for _ in range(3):
            self.assertEqual(rt_budget.check_stop(state, budget), "")
            state.consume_step()
        self.assertEqual(rt_budget.check_stop(state, budget), "max_steps")

    def test_timeout_detected_via_elapsed_time(self):
        state = rt_budget.BudgetState(started_monotonic=time.monotonic() - 61)
        budget = rt_budget.Budget(max_steps=10, timeout_seconds=60, cost_limit=0)
        self.assertEqual(rt_budget.check_stop(state, budget), "timeout")

    def test_cost_limit_and_zero_disables(self):
        state = rt_budget.BudgetState()
        budget = rt_budget.Budget(max_steps=10, timeout_seconds=60, cost_limit=1.5)
        self.assertEqual(rt_budget.check_stop(state, budget), "")
        state.add_cost(1.5)
        self.assertEqual(rt_budget.check_stop(state, budget), "cost")

        state_zero = rt_budget.BudgetState()
        state_zero.add_cost(100)
        budget_zero = rt_budget.Budget(max_steps=10, timeout_seconds=60, cost_limit=0)
        self.assertEqual(rt_budget.check_stop(state_zero, budget_zero), "")

    def test_negative_cost_ignored(self):
        state = rt_budget.BudgetState()
        state.add_cost(-5)
        self.assertEqual(state.cost_used, 0.0)

    def test_step_check_takes_priority(self):
        state = rt_budget.BudgetState(started_monotonic=time.monotonic() - 61)
        state.consume_step()
        state.consume_step()
        state.add_cost(99)
        budget = rt_budget.Budget(max_steps=2, timeout_seconds=60, cost_limit=1)
        self.assertEqual(rt_budget.check_stop(state, budget), "max_steps")


class CompletionTest(unittest.TestCase):
    def test_empty_state_misses_all_requirements(self):
        task = rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "发帖", {"question": "q"})
        result = rt_completion.check_completion(task)
        self.assertFalse(result.complete)
        self.assertEqual(result.missing, ["selected_photos", "copy_draft"])

    def test_selected_only_still_misses_copy(self):
        task = rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "发帖", {"question": "q"})
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_PHOTOS_SELECTED, "选中", {"ids": ["a"]},
        ), step_no=1, action="select_photos")
        result = rt_completion.check_completion(task)
        self.assertFalse(result.complete)
        self.assertEqual(result.missing, ["copy_draft"])

    def test_copy_without_title_not_complete(self):
        task = rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "发帖", {"question": "q"})
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_PHOTOS_SELECTED, "选中", {"ids": ["a"]},
        ), step_no=1, action="select_photos")
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_COPY_DRAFTED, "半成品", {"title": "", "content": "正文"},
        ), step_no=2, action="write_post")
        result = rt_completion.check_completion(task)
        self.assertEqual(result.missing, ["copy_draft"])

    def test_all_requirements_present_completes(self):
        task = rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "发帖", {"question": "q"})
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_PHOTOS_SELECTED, "选中", {"ids": ["a"]},
        ), step_no=1, action="select_photos")
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_COPY_DRAFTED, "完成", {"title": "标题", "content": "正文"},
        ), step_no=2, action="write_post")
        result = rt_completion.check_completion(task)
        self.assertTrue(result.complete)
        self.assertEqual(result.missing, [])


class CapabilityRegistryTest(unittest.TestCase):
    def _registry(self) -> rt_registry.CapabilityRegistry:
        registry = rt_registry.CapabilityRegistry()
        registry.register(rt_registry.Capability(
            name="sql_search",
            description="结构化条件检索照片",
            parameters={
                "query": {"type": "str", "description": "检索条件描述", "required": True},
                "limit": {"type": "int", "description": "数量上限", "required": False},
            },
            run=lambda params, ctx: rt_state.Observation(rt_state.OBS_PHOTO_IDS, "ok", {}),
        ))
        return registry

    def test_register_and_lookup(self):
        registry = self._registry()
        self.assertEqual(registry.names(), ["sql_search"])
        self.assertIsNotNone(registry.get("sql_search"))
        self.assertIsNone(registry.get("nope"))

    def test_duplicate_register_raises(self):
        registry = self._registry()
        with self.assertRaises(ValueError):
            registry.register(rt_registry.Capability(
                name="sql_search", description="", parameters={}, run=lambda p, c: None,
            ))

    def test_invalid_param_type_declaration_raises(self):
        registry = rt_registry.CapabilityRegistry()
        with self.assertRaises(ValueError):
            registry.register(rt_registry.Capability(
                name="bad", description="",
                parameters={"x": {"type": "map", "description": "", "required": True}},
                run=lambda p, c: None,
            ))

    def test_validate_params_passes_valid(self):
        registry = self._registry()
        self.assertEqual(registry.validate_params("sql_search", {"query": "山西"}), [])
        self.assertEqual(registry.validate_params("sql_search", {"query": "山西", "limit": 5}), [])
        self.assertEqual(registry.validate_params("sql_search", {"query": "山西", "limit": None}), [])

    def test_validate_params_catches_errors(self):
        registry = self._registry()
        self.assertEqual(
            registry.validate_params("sql_search", {}),
            ["缺少必填参数: query"],
        )
        self.assertTrue(registry.validate_params("sql_search", {"query": 123}))
        self.assertTrue(registry.validate_params("sql_search", {"query": "q", "limit": "5"}))
        self.assertTrue(registry.validate_params("sql_search", {"query": "q", "extra": 1}))
        self.assertTrue(registry.validate_params("sql_search", "not-a-dict"))
        self.assertTrue(registry.validate_params("unknown_cap", {}))

    def test_bool_not_accepted_as_int(self):
        registry = self._registry()
        self.assertTrue(registry.validate_params("sql_search", {"query": "q", "limit": True}))

    def test_specs_shape(self):
        registry = self._registry()
        specs = registry.specs()
        self.assertEqual(specs[0]["name"], "sql_search")
        self.assertIn("query", specs[0]["parameters"])


if __name__ == "__main__":
    unittest.main()
