"""
    Agent Runtime 护栏与恢复策略（AR2-3，框架无关纯 Python）。

    guardrail 是 execute 与 reduce 之间的纯程序节点：
        1. 确定性验证：按观察 status 查「状态 → 策略」映射表
        2. 语义评估：确定性状态为 success 且能力声明 evaluator 时触发（AR2-5）
        3. 恢复动作有界执行：重试/修复/再决策各自计数，超限转为正确停止

    四种恢复策略（04 文档定义，V2 实现前三种加再决策）：
        - 重试     目标、能力、参数不变，适用于瞬时故障，按能力独立计数
        - 修复     能力不变，携带失败反馈重新执行，适用于模型输出缺陷
        - 换策略   以建议形式注入决策上下文（fallback），由 decide 采纳，不强制改写
        - 再决策   invalid 类错误的摘要反馈给 decide 修正参数重新选择，有界

    AR7 时代的终态模型在此降级为默认行：空范围、超限、澄清、旅行未匹配等
    已验证终态直接接受（观察自身携带 terminal_reason，归约后正确停止）。

    预算语义：guardrail 内恢复不消耗外层步数（一次决策仍算一步），
    但计入恢复计数、总时长与总成本；恢复前检查预算，防止重试绕过预算。
"""

import dataclasses
import typing

import internal.runtime.budget as rt_budget
import internal.runtime.registry as rt_registry
import internal.runtime.state as rt_state

# 恢复动作
ACTION_ACCEPT = "accept"          # 接受观察，进入归约
ACTION_RETRY = "retry"            # 瞬时故障：同能力同参数有界重试
ACTION_REPAIR = "repair"          # 模型输出缺陷：带失败反馈修复重执行
ACTION_REDECIDE = "redecide"      # 决策侧契约违规：错误摘要反馈 decide 再决策
ACTION_FALLBACK = "fallback"      # 换策略建议注入决策上下文（低置信/空结果无兜底）
ACTION_STOP = "stop"              # 恢复耗尽：以可行动文案正确停止（替换终态观察）
ACTION_BUDGET_STOP = "budget_stop"  # 恢复前预算已耗尽：交给预算停止语义收尾


@dataclasses.dataclass
class GuardrailVerdict:
    """护栏结论：action 驱动编排外壳的路由，其余字段按动作类型携带。"""

    action: str
    reason: str                                    # 一句话策略依据（过程面板/trace 用）
    feedback: str = ""                             # 修复/再决策/换策略建议携带的反馈
    replacement: rt_state.Observation | None = None  # stop 动作替换的终态观察
    stop_reason: str = ""                          # budget_stop 动作的预算停止原因


def recovery_budget_from_config(cfg: typing.Any) -> rt_budget.RecoveryBudget:
    """从配置对象读取恢复预算（配置键见 configs/config.yaml Agent 段）。"""
    return rt_budget.RecoveryBudget(
        retry_max=cfg.runtime_retry_max,
        repair_max=cfg.runtime_repair_max,
        redecide_max=cfg.runtime_redecide_max,
    )


def run_guardrail(
    observation: rt_state.Observation,
    capability: rt_registry.Capability | None,
    ctx: rt_registry.RunContext,
    budget_state: rt_budget.BudgetState,
    recovery: rt_budget.RecoveryBudget,
    budget: rt_budget.Budget,
) -> GuardrailVerdict:
    """对一次能力观察做验证与恢复决策，返回驱动编排路由的护栏结论。"""
    if (
        observation.status == rt_state.STATUS_SUCCESS
        and capability is not None
        and capability.evaluator is not None
    ):
        quality = capability.evaluator(ctx, observation)
        if not quality.passed:
            return _bounded_recovery(
                ACTION_REPAIR, f"repair:{capability.name}", recovery.repair_max,
                budget_state, budget,
                feedback=f"质量评估未通过：{quality.feedback}",
                exhausted_reason="quality_gate_failed",
                exhausted_summary=(
                    f"{capability.title}多次修复后仍未通过质量检查"
                    f"（{quality.feedback}），可以调整要求（如明确风格或数量）后重试"
                ),
            )
    return _status_strategy(observation, capability, budget_state, recovery, budget)


def _status_strategy(
    observation: rt_state.Observation,
    capability: rt_registry.Capability | None,
    budget_state: rt_budget.BudgetState,
    recovery: rt_budget.RecoveryBudget,
    budget: rt_budget.Budget,
) -> GuardrailVerdict:
    """「状态 → 策略」映射表：恢复动作的触发条件全部是明确状态，不是提示词约定。"""
    status = observation.status
    action_name = capability.name if capability is not None else "decision"

    if status == rt_state.STATUS_SUCCESS:
        return GuardrailVerdict(ACTION_ACCEPT, "成功观察，接受进入归约")

    if status == rt_state.STATUS_EMPTY:
        # 检索空结果由权威范围兜底（AR9），范围空是确定性终态，均直接接受
        return GuardrailVerdict(ACTION_ACCEPT, "空结果由权威范围兜底或为确定性终态，接受")

    if status == rt_state.STATUS_TEMPORARY_ERROR:
        return _bounded_recovery(
            ACTION_RETRY, f"retry:{action_name}", recovery.retry_max,
            budget_state, budget,
            feedback="",
            exhausted_reason="retry_exhausted",
            exhausted_summary=(
                f"{observation.summary}（已重试 {budget_state.recovery_used_count(f'retry:{action_name}')} 次"
                "仍失败，多为服务暂时不可用，建议确认相关服务已启动后重新发起）"
            ),
        )

    if status == rt_state.STATUS_INVALID_INPUT:
        if _is_repairable(capability, observation):
            return _bounded_recovery(
                ACTION_REPAIR, f"repair:{action_name}", recovery.repair_max,
                budget_state, budget,
                feedback=f"上次执行失败：{observation.summary}，请修正后重新执行",
                exhausted_reason="repair_exhausted",
                exhausted_summary=(
                    f"{observation.summary}（已带反馈修复 "
                    f"{budget_state.recovery_used_count(f'repair:{action_name}')} 次仍失败，"
                    "建议更换说法或调整要求后重新发起）"
                ),
            )
        # 决策侧契约违规（未知能力、参数不合法、决策顺序错误）：摘要反馈给 decide
        return _bounded_recovery(
            ACTION_REDECIDE, "redecide", recovery.redecide_max,
            budget_state, budget,
            feedback=f"上一决策无效：{observation.summary}。请修正 action 或参数重新选择",
            exhausted_reason="redecide_exhausted",
            exhausted_summary=(
                f"连续多次决策无效（{observation.summary}），"
                "建议更换说法（如明确日期、地点或数量）后重新发起"
            ),
        )

    if status == rt_state.STATUS_PERMANENT_ERROR:
        # 永久性失败是确定性终态（观察自带 terminal_reason），接受并正确停止
        return GuardrailVerdict(ACTION_ACCEPT, "永久性失败为确定性终态，接受并正确停止")

    # low_confidence：有结果但证据不足，换策略建议注入决策上下文，不强制改写
    return GuardrailVerdict(
        ACTION_FALLBACK,
        "低置信结果，建议更换策略",
        feedback=f"上一结果证据不足（{observation.summary}），建议更换检索方式或调整条件",
    )


def _is_repairable(
    capability: rt_registry.Capability | None, observation: rt_state.Observation,
) -> bool:
    """能力侧输出缺陷（能力声明可修复）才走修复环，其余 invalid 反馈给决策。"""
    if capability is None:
        return False
    return observation.payload.get("terminal_reason") in capability.repairable_reasons


def _bounded_recovery(
    action: str,
    key: str,
    limit: int,
    budget_state: rt_budget.BudgetState,
    budget: rt_budget.Budget,
    feedback: str,
    exhausted_reason: str,
    exhausted_summary: str,
) -> GuardrailVerdict:
    """有界恢复的公共骨架：预算先行 → 计数判限 → 消耗计数并给出恢复结论。

    重试/修复/再决策不消耗外层步数，但计入时长与成本（预算先行检查），
    超限后以可行动文案正确停止，不无限重试也不伪装完成。
    """
    stop = rt_budget.check_stop(budget_state, budget)
    if stop:
        return GuardrailVerdict(
            ACTION_BUDGET_STOP,
            f"预算已耗尽（{stop}），不再执行恢复动作",
            stop_reason=stop,
        )
    if budget_state.recovery_used_count(key) >= limit:
        return GuardrailVerdict(
            ACTION_STOP,
            f"恢复预算耗尽（{key} 已用 {budget_state.recovery_used_count(key)} 次），正确停止",
            replacement=rt_state.Observation(
                rt_state.OBS_ERROR,
                exhausted_summary,
                {"terminal_reason": exhausted_reason},
                status=rt_state.STATUS_PERMANENT_ERROR,
            ),
        )
    budget_state.consume_recovery(key)
    reason = {
        ACTION_RETRY: f"瞬时故障，同能力同参数重试（第 {budget_state.recovery_used_count(key)} 次）",
        ACTION_REPAIR: f"输出缺陷，带失败反馈修复重执行（第 {budget_state.recovery_used_count(key)} 次）",
        ACTION_REDECIDE: f"决策无效，错误摘要反馈重新决策（第 {budget_state.recovery_used_count(key)} 次）",
    }[action]
    return GuardrailVerdict(action, reason, feedback=feedback)
