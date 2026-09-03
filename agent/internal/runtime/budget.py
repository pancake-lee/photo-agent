"""
    Agent Runtime 预算（框架无关纯 Python）。

    预算是停止条件（Stop），与完成判定（Completion）分离：
    完成看目标要件是否齐备，停止看步数/时长/成本是否耗尽。

    恢复预算（RecoveryBudget）独立于步数：guardrail 内的重试/修复/再决策
    不消耗外层步数，但各自有界计数，且仍计入时长与成本。
"""

import dataclasses
import time


@dataclasses.dataclass
class Budget:
    """预算上限。cost_limit 小于等于 0 表示不设成本上限。"""

    max_steps: int = 12
    timeout_seconds: float = 300.0
    cost_limit: float = 2.0


@dataclasses.dataclass
class RecoveryBudget:
    """恢复动作上限：瞬时重试 / 带反馈修复 / 再决策，0 表示关闭该恢复动作。

    重试与修复按能力独立计数（同能力多次故障不共享额度），
    再决策是决策侧通道，全局计数。
    """

    retry_max: int = 2
    repair_max: int = 2
    redecide_max: int = 2


@dataclasses.dataclass
class BudgetState:
    """预算消耗记录，由编排外壳在每步迭代后更新。"""

    steps_used: int = 0
    started_monotonic: float = dataclasses.field(default_factory=time.monotonic)
    cost_used: float = 0.0
    # 恢复动作计数：键形如 "retry:sql_search" / "repair:select_photos" / "redecide"
    recovery_used: dict[str, int] = dataclasses.field(default_factory=dict)

    def consume_step(self) -> None:
        self.steps_used += 1

    def add_cost(self, amount: float) -> None:
        if amount > 0:
            self.cost_used += amount

    def consume_recovery(self, key: str) -> None:
        self.recovery_used[key] = self.recovery_used.get(key, 0) + 1

    def recovery_used_count(self, key: str) -> int:
        return self.recovery_used.get(key, 0)

    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.started_monotonic


def check_stop(state: BudgetState, budget: Budget) -> str:
    """检查预算是否耗尽，返回停止原因（空串表示可继续）。

    检查顺序：步数 → 时长 → 成本。
    """
    if state.steps_used >= budget.max_steps:
        return "max_steps"
    if state.elapsed_seconds() >= budget.timeout_seconds:
        return "timeout"
    if budget.cost_limit > 0 and state.cost_used >= budget.cost_limit:
        return "cost"
    return ""
