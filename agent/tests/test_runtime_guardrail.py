"""AR2-3/AR2-5 护栏与恢复策略、语义质量门的确定性单测（不依赖真实 LLM）。"""

import time
import unittest
import unittest.mock

import internal.runtime.budget as rt_budget
import internal.runtime.evaluators as rt_evaluators
import internal.runtime.guardrail as rt_guardrail
import internal.runtime.registry as rt_registry
import internal.runtime.state as rt_state


def _cfg():
    attrs = {
        "runtime_retry_max": 2,
        "runtime_repair_max": 2,
        "runtime_redecide_max": 2,
    }
    return type("Config", (), attrs)()


def _capability(name="sql_search", repairable=(), evaluator=None):
    return rt_registry.Capability(
        name=name, title="查询照片", description="", parameters={},
        run=lambda params, ctx: None,
        repairable_reasons=repairable, evaluator=evaluator,
    )


def _ctx(state=None):
    return rt_registry.RunContext(cfg=_cfg(), question="q", state=state)


def _run(observation, capability=None, budget_state=None, recovery=None, budget=None, ctx=None):
    return rt_guardrail.run_guardrail(
        observation, capability, ctx or _ctx(),
        budget_state or rt_budget.BudgetState(),
        recovery or rt_budget.RecoveryBudget(),
        budget or rt_budget.Budget(max_steps=100, timeout_seconds=60, cost_limit=0),
    )


class GuardrailStrategyTest(unittest.TestCase):
    """「状态 → 策略」映射表：恢复动作的触发条件全部是明确状态。"""

    def test_success_observation_accepted(self):
        verdict = _run(rt_state.Observation(rt_state.OBS_PHOTO_IDS, "检索成功", {"ids": ["a"]}))
        self.assertEqual(verdict.action, rt_guardrail.ACTION_ACCEPT)

    def test_empty_observation_accepted_with_scope_fallback(self):
        """检索空结果由权威范围兜底（AR9），是合法观察直接接受。"""
        observation = rt_state.Observation(
            rt_state.OBS_PHOTO_IDS, "检索为空", {"ids": []},
            status=rt_state.STATUS_EMPTY,
        )
        verdict = _run(observation)
        self.assertEqual(verdict.action, rt_guardrail.ACTION_ACCEPT)

    def test_permanent_error_accepted_as_deterministic_terminal(self):
        """AR7 终态模型降级为默认行：永久性失败观察自带 terminal_reason，接受即停止。"""
        observation = rt_state.Observation(
            rt_state.OBS_ERROR, "时间线未匹配", {"terminal_reason": "trip_unresolved"},
            status=rt_state.STATUS_PERMANENT_ERROR,
        )
        verdict = _run(observation)
        self.assertEqual(verdict.action, rt_guardrail.ACTION_ACCEPT)

    def test_temporary_error_retries_same_capability(self):
        observation = rt_state.Observation(
            rt_state.OBS_ERROR, "后端连接失败", {"terminal_reason": "capability_execution_failed"},
            status=rt_state.STATUS_TEMPORARY_ERROR,
        )
        budget_state = rt_budget.BudgetState()
        verdict = _run(observation, _capability("sql_search"), budget_state)
        self.assertEqual(verdict.action, rt_guardrail.ACTION_RETRY)
        self.assertEqual(budget_state.recovery_used_count("retry:sql_search"), 1)

    def test_temporary_error_exhausts_into_actionable_stop(self):
        """重试耗尽转为正确停止：终态观察携带可行动建议，不无限重试。"""
        observation = rt_state.Observation(
            rt_state.OBS_ERROR, "后端连接失败", {"terminal_reason": "capability_execution_failed"},
            status=rt_state.STATUS_TEMPORARY_ERROR,
        )
        budget_state = rt_budget.BudgetState()
        budget_state.consume_recovery("retry:sql_search")
        budget_state.consume_recovery("retry:sql_search")
        verdict = _run(observation, _capability("sql_search"), budget_state)
        self.assertEqual(verdict.action, rt_guardrail.ACTION_STOP)
        self.assertEqual(verdict.replacement.payload["terminal_reason"], "retry_exhausted")
        self.assertEqual(verdict.replacement.status, rt_state.STATUS_PERMANENT_ERROR)
        self.assertIn("已重试 2 次", verdict.replacement.summary)
        self.assertIn("确认相关服务", verdict.replacement.summary)

    def test_recovery_does_not_bypass_time_budget(self):
        """恢复动作预算先行：时长/成本已耗尽时不再重试，交给预算停止语义。"""
        observation = rt_state.Observation(
            rt_state.OBS_ERROR, "后端连接失败", {}, status=rt_state.STATUS_TEMPORARY_ERROR,
        )
        budget_state = rt_budget.BudgetState(started_monotonic=time.monotonic() - 61)
        budget = rt_budget.Budget(max_steps=100, timeout_seconds=60, cost_limit=0)
        verdict = _run(observation, _capability("sql_search"), budget_state, budget=budget)
        self.assertEqual(verdict.action, rt_guardrail.ACTION_BUDGET_STOP)
        self.assertEqual(verdict.stop_reason, "timeout")

    def test_retry_counts_are_per_capability(self):
        """重试按能力独立计数：一个能力耗尽不影响另一个能力重试。"""
        failed = rt_state.Observation(
            rt_state.OBS_ERROR, "失败", {}, status=rt_state.STATUS_TEMPORARY_ERROR,
        )
        budget_state = rt_budget.BudgetState()
        budget_state.consume_recovery("retry:rag_search")
        budget_state.consume_recovery("retry:rag_search")
        verdict = _run(failed, _capability("sql_search"), budget_state)
        self.assertEqual(verdict.action, rt_guardrail.ACTION_RETRY)

    def test_repairable_defect_returns_repair_with_feedback(self):
        """能力声明的输出缺陷（如挑选空结果）走带反馈修复环。"""
        observation = rt_state.Observation(
            rt_state.OBS_ERROR, "挑选结果为空", {"terminal_reason": "photo_selection_failed"},
            status=rt_state.STATUS_INVALID_INPUT,
        )
        capability = _capability("select_photos", repairable=("photo_selection_failed",))
        verdict = _run(observation, capability)
        self.assertEqual(verdict.action, rt_guardrail.ACTION_REPAIR)
        self.assertIn("挑选结果为空", verdict.feedback)
        self.assertIn("修正", verdict.feedback)

    def test_repair_exhausts_into_actionable_stop(self):
        observation = rt_state.Observation(
            rt_state.OBS_ERROR, "挑选结果为空", {"terminal_reason": "photo_selection_failed"},
            status=rt_state.STATUS_INVALID_INPUT,
        )
        capability = _capability("select_photos", repairable=("photo_selection_failed",))
        budget_state = rt_budget.BudgetState()
        budget_state.consume_recovery("repair:select_photos")
        budget_state.consume_recovery("repair:select_photos")
        verdict = _run(observation, capability, budget_state)
        self.assertEqual(verdict.action, rt_guardrail.ACTION_STOP)
        self.assertEqual(verdict.replacement.payload["terminal_reason"], "repair_exhausted")
        self.assertIn("更换说法", verdict.replacement.summary)

    def test_decision_side_invalid_returns_redecide(self):
        """决策侧契约违规（未知能力/参数不合法/顺序错误）反馈给 decide 再决策。"""
        observation = rt_state.Observation(
            rt_state.OBS_ERROR, "决策无效（no_such）: 未知能力", {"terminal_reason": "invalid_decision"},
            status=rt_state.STATUS_INVALID_INPUT,
        )
        verdict = _run(observation, capability=None)
        self.assertEqual(verdict.action, rt_guardrail.ACTION_REDECIDE)
        self.assertIn("上一决策无效", verdict.feedback)

    def test_capability_side_order_error_returns_redecide(self):
        """未声明可修复的能力侧违规（如选片前无候选）同样反馈决策侧。"""
        observation = rt_state.Observation(
            rt_state.OBS_ERROR, "没有候选照片，请先检索", status=rt_state.STATUS_INVALID_INPUT,
        )
        verdict = _run(observation, _capability("select_photos"))
        self.assertEqual(verdict.action, rt_guardrail.ACTION_REDECIDE)

    def test_redecide_exhausts_into_actionable_stop(self):
        observation = rt_state.Observation(
            rt_state.OBS_ERROR, "决策无效", {"terminal_reason": "invalid_decision"},
            status=rt_state.STATUS_INVALID_INPUT,
        )
        budget_state = rt_budget.BudgetState()
        budget_state.consume_recovery("redecide")
        budget_state.consume_recovery("redecide")
        verdict = _run(observation, capability=None, budget_state=budget_state)
        self.assertEqual(verdict.action, rt_guardrail.ACTION_STOP)
        self.assertEqual(verdict.replacement.payload["terminal_reason"], "redecide_exhausted")

    def test_low_confidence_returns_fallback_suggestion(self):
        """低置信结果换策略建议注入决策上下文，由 decide 采纳，不强制改写。"""
        observation = rt_state.Observation(
            rt_state.OBS_PHOTO_IDS, "挑选可信度低", status=rt_state.STATUS_LOW_CONFIDENCE,
        )
        verdict = _run(observation, _capability("select_photos"))
        self.assertEqual(verdict.action, rt_guardrail.ACTION_FALLBACK)
        self.assertIn("更换", verdict.feedback)


class QualityGateTest(unittest.TestCase):
    """AR2-5 语义质量门：确定性检查通过后按能力声明触发，不通过进修复环。"""

    def _obs(self, kind):
        return rt_state.Observation(kind, "产物", {})

    def test_evaluator_reject_triggers_repair_with_feedback(self):
        judge = lambda ctx, obs: rt_evaluators.QualityVerdict(False, "入选三张同一场景近重复")
        verdict = _run(self._obs(rt_state.OBS_COPY_DRAFTED), _capability(evaluator=judge))
        self.assertEqual(verdict.action, rt_guardrail.ACTION_REPAIR)
        self.assertIn("入选三张同一场景近重复", verdict.feedback)

    def test_evaluator_pass_accepts(self):
        judge = lambda ctx, obs: rt_evaluators.QualityVerdict(True)
        verdict = _run(self._obs(rt_state.OBS_COPY_DRAFTED), _capability(evaluator=judge))
        self.assertEqual(verdict.action, rt_guardrail.ACTION_ACCEPT)

    def test_quality_repair_exhausts_into_quality_terminal(self):
        """修复环耗尽以质量未达标终态停止，不伪装完成。"""
        judge = lambda ctx, obs: rt_evaluators.QualityVerdict(False, "文案提到未拍摄的地名")
        capability = _capability("write_post", evaluator=judge)
        budget_state = rt_budget.BudgetState()
        budget_state.consume_recovery("repair:write_post")
        budget_state.consume_recovery("repair:write_post")
        verdict = _run(self._obs(rt_state.OBS_COPY_DRAFTED), capability, budget_state)
        self.assertEqual(verdict.action, rt_guardrail.ACTION_STOP)
        self.assertEqual(verdict.replacement.payload["terminal_reason"], "quality_gate_failed")
        self.assertIn("未拍摄的地名", verdict.replacement.summary)

    def test_evaluator_not_declared_accepts_without_semantic_check(self):
        verdict = _run(self._obs(rt_state.OBS_COPY_DRAFTED), _capability())
        self.assertEqual(verdict.action, rt_guardrail.ACTION_ACCEPT)


class EvaluatorTest(unittest.TestCase):
    """两个语义评委的接口行为（LLM 经 mock，不依赖真实模型）。"""

    def _capture_ctx(self, state=None, responses=None):
        """构造 ctx 并拦截能力内 LLM 调用，记录提示词。"""
        prompts: list[tuple[str, str]] = []

        def fake_invoke(ctx, system_prompt, user_prompt, temperature):
            prompts.append((system_prompt, user_prompt))
            return responses.pop(0) if responses else '{"passed": true, "feedback": ""}'

        ctx = _ctx(state)
        return ctx, prompts, fake_invoke

    def _task_with_selection(self, delivery="editorial"):
        task = rt_state.new_task(rt_state.GOAL_SOCIAL_POST, "找照片发帖", {"question": "找照片发帖"})
        task.goal.delivery_mode = delivery
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_PHOTO_IDS, "检索", {"ids": ["a", "b", "c"]},
        ), step_no=1, action="sql_search")
        return task

    def test_selection_judge_skips_non_selection_kind(self):
        """超限深链等终态路径不做代表性质量门（评委不触发）。"""
        ctx, prompts, fake = self._capture_ctx()
        with unittest.mock.patch.object(rt_evaluators.caps_common, "invoke_structured_llm",
                                        side_effect=fake):
            verdict = rt_evaluators.evaluate_selection(
                ctx, rt_state.Observation(rt_state.OBS_SELECTION_OVERFLOW, "超限", {}),
            )
        self.assertTrue(verdict.passed)
        self.assertEqual(prompts, [])

    def test_selection_judge_skips_candidate_delivery_mode(self):
        """候选交付模式完整保留折叠候选，无代表性语义可评（AR12 不回退）。"""
        task = self._task_with_selection(delivery="candidate")
        ctx, prompts, fake = self._capture_ctx(task)
        observation = rt_state.Observation(
            rt_state.OBS_PHOTOS_SELECTED, "保留候选", {"ids": ["a"], "photos": [{"id": "a"}]},
        )
        with unittest.mock.patch.object(rt_evaluators.caps_common, "invoke_structured_llm",
                                        side_effect=fake):
            verdict = rt_evaluators.evaluate_selection(ctx, observation)
        self.assertTrue(verdict.passed)
        self.assertEqual(prompts, [])

    def test_selection_judge_receives_photos_and_returns_feedback(self):
        task = self._task_with_selection()
        ctx, prompts, fake = self._capture_ctx(
            task, responses=['{"passed": false, "feedback": "两张同时段寺庙近重复"}'],
        )
        observation = rt_state.Observation(
            rt_state.OBS_PHOTOS_SELECTED, "已挑选 2 张",
            {"ids": ["a", "b"], "photos": [
                {"id": "a", "filename": "a.jpg", "shot_at": "2026-08-01T18:00:00+08:00",
                 "description": "寺庙"},
                {"id": "b", "filename": "b.jpg", "shot_at": "2026-08-01T18:30:00+08:00",
                 "description": "寺庙"},
            ]},
        )
        with unittest.mock.patch.object(rt_evaluators.caps_common, "invoke_structured_llm",
                                        side_effect=fake):
            verdict = rt_evaluators.evaluate_selection(ctx, observation)
        self.assertFalse(verdict.passed)
        self.assertIn("近重复", verdict.feedback)
        self.assertEqual(len(prompts), 1)
        system_prompt, user_prompt = prompts[0]
        self.assertIn("摄影编辑评委", system_prompt)
        self.assertIn("a.jpg", user_prompt)
        self.assertIn("寺庙", user_prompt)

    def test_selection_judge_unparseable_output_fails_open(self):
        """评委输出不可解析时按通过处理，不误杀正常产物。"""
        task = self._task_with_selection()
        ctx, _, fake = self._capture_ctx(task, responses=["评委觉得不行"])
        observation = rt_state.Observation(
            rt_state.OBS_PHOTOS_SELECTED, "已挑选",
            {"ids": ["a"], "photos": [{"id": "a", "description": "寺庙"}]},
        )
        with unittest.mock.patch.object(rt_evaluators.caps_common, "invoke_structured_llm",
                                        side_effect=fake):
            verdict = rt_evaluators.evaluate_selection(ctx, observation)
        self.assertTrue(verdict.passed)

    def test_selection_judge_reads_real_backend_contract(self):
        """真实后端契约回归：评委读到结构化摘要与归一化时段，而非 JSON 原文截断。

        回归背景：2026-09-04 山西请求中照片详情携带 JSON description 与
        shotAt，评委拿到「未知时段 + JSON 前缀」信息不足，持续拒绝正常选片。
        """
        task = self._task_with_selection()
        ctx, prompts, fake = self._capture_ctx(task)
        observation = rt_state.Observation(
            rt_state.OBS_PHOTOS_SELECTED, "已挑选 2 张",
            {"ids": ["a", "b"], "photos": [
                {"id": "a", "filename": "DSC_1630.jpg", "shot_at": "2026-08-05T09:48:04",
                 "description": '```json\n{"subject": {"main_objects": ["石雕佛像"]}}\n```',
                 "objects": "石雕佛造像", "scene": "石窟洞窟内部", "mood": "肃穆"},
                {"id": "b", "filename": "DSC_1655.jpg", "shot_at": "2026-08-05T17:20:00",
                 "description": '```json\n{"overall_summary": "傍晚的石窟外景"}\n```',
                 "objects": "", "scene": "", "mood": ""},
            ]},
        )
        with unittest.mock.patch.object(rt_evaluators.caps_common, "invoke_structured_llm",
                                        side_effect=fake):
            rt_evaluators.evaluate_selection(ctx, observation)
        _, user_prompt = prompts[0]
        # 结构化字段优先，未提供时退回 overall_summary；时段来自归一化 shot_at
        self.assertIn("石雕佛造像，石窟洞窟内部，肃穆", user_prompt)
        self.assertIn("傍晚的石窟外景", user_prompt)
        self.assertIn("09时", user_prompt)
        self.assertIn("17时", user_prompt)
        self.assertNotIn("未知时段", user_prompt)
        self.assertNotIn("main_objects", user_prompt)   # JSON 原文不进评委提示词

    def test_copy_judge_skips_non_copy_kind(self):
        ctx, prompts, fake = self._capture_ctx()
        with unittest.mock.patch.object(rt_evaluators.caps_common, "invoke_structured_llm",
                                        side_effect=fake):
            verdict = rt_evaluators.evaluate_copy(
                ctx, rt_state.Observation(rt_state.OBS_PHOTO_IDS, "检索", {}),
            )
        self.assertTrue(verdict.passed)
        self.assertEqual(prompts, [])

    def test_copy_judge_receives_evidence_and_copy(self):
        task = self._task_with_selection()
        task = rt_state.reduce_observation(task, rt_state.Observation(
            rt_state.OBS_PHOTOS_SELECTED, "选中",
            {"ids": ["a", "b"], "photos": [
                {"id": "a", "filename": "a.jpg", "description": "寺庙",
                 "shot_at": "2026-08-01T18:00:00+08:00"},
                {"id": "b", "filename": "b.jpg", "description": "面馆",
                 "shot_at": "2026-08-01T19:00:00+08:00"},
            ]},
        ), step_no=2, action="select_photos")
        ctx, prompts, fake = self._capture_ctx(
            task, responses=['{"passed": false, "feedback": "提到的大雁塔不在照片中"}'],
        )
        observation = rt_state.Observation(
            rt_state.OBS_COPY_DRAFTED, "文案已生成",
            {"title": "山西行", "content": "在大雁塔下吃了一碗面"},
        )
        with unittest.mock.patch.object(rt_evaluators.caps_common, "invoke_structured_llm",
                                        side_effect=fake):
            verdict = rt_evaluators.evaluate_copy(ctx, observation)
        self.assertFalse(verdict.passed)
        self.assertIn("大雁塔", verdict.feedback)
        _, user_prompt = prompts[0]
        self.assertIn("寺庙", user_prompt)       # 照片证据来自入选缓存
        self.assertIn("大雁塔下", user_prompt)    # 待核查文案进入提示词

    def test_copy_judge_passes_without_evidence_cache(self):
        """证据缓存缺失（如异常路径）不阻断，按通过处理。"""
        ctx, prompts, fake = self._capture_ctx(rt_state.new_task(
            rt_state.GOAL_SOCIAL_POST, "发帖", {},
        ))
        observation = rt_state.Observation(
            rt_state.OBS_COPY_DRAFTED, "文案", {"title": "t", "content": "c"},
        )
        with unittest.mock.patch.object(rt_evaluators.caps_common, "invoke_structured_llm",
                                        side_effect=fake):
            verdict = rt_evaluators.evaluate_copy(ctx, observation)
        self.assertTrue(verdict.passed)
        self.assertEqual(prompts, [])


class RecoveryBudgetConfigTest(unittest.TestCase):
    """恢复预算从配置读取，BudgetState 恢复计数独立于步数。"""

    def test_recovery_budget_from_config(self):
        recovery = rt_guardrail.recovery_budget_from_config(_cfg())
        self.assertEqual(
            (recovery.retry_max, recovery.repair_max, recovery.redecide_max), (2, 2, 2),
        )

    def test_recovery_counts_do_not_consume_steps(self):
        budget_state = rt_budget.BudgetState()
        budget_state.consume_recovery("retry:sql_search")
        budget_state.consume_recovery("retry:sql_search")
        self.assertEqual(budget_state.steps_used, 0)
        self.assertEqual(budget_state.recovery_used_count("retry:sql_search"), 2)
        self.assertEqual(budget_state.recovery_used_count("retry:rag_search"), 0)


if __name__ == "__main__":
    unittest.main()
