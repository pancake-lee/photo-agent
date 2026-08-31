"""
    Agent Runtime 预算（框架无关纯 Python）。

    预算是停止条件（Stop），与完成判定（Completion）分离：
    完成看目标要件是否齐备，停止看步数/时长/成本是否耗尽。
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
class BudgetState:
    """预算消耗记录，由编排外壳在每步迭代后更新。"""

    steps_used: int = 0
    started_monotonic: float = dataclasses.field(default_factory=time.monotonic)
    cost_used: float = 0.0

    def consume_step(self) -> None:
        self.steps_used += 1

    def add_cost(self, amount: float) -> None:
        if amount > 0:
            self.cost_used += amount

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
