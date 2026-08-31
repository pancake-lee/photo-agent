"""
    Agent Runtime 完成检查（框架无关纯 Python）。

    完成判定全部由程序确定性执行，逐项检查目标要件，不信任「模型说完成了」。
    语义质量（如文案是否有叙事感）不作为硬性要件。
"""

import dataclasses
import typing

import runtime.state as rt_state


@dataclasses.dataclass
class CompletionResult:
    """完成检查结论：complete 为真表示全部要件齐备，missing 列出缺口。"""

    complete: bool
    missing: list[str]


# 要件名 → 确定性判定函数（消费 TaskState 的具体字段）
_REQUIREMENT_CHECKS: dict[str, typing.Callable[[rt_state.TaskState], bool]] = {
    "selected_photos": lambda s: bool(s.artifacts.selected_ids),
    "copy_draft": lambda s: bool(s.artifacts.copy_draft.get("title"))
    and bool(s.artifacts.copy_draft.get("content")),
}


def check_completion(state: rt_state.TaskState) -> CompletionResult:
    """逐项检查目标完成要件，未知要件名直接报错（预设与检查表不一致是代码 bug）。"""
    missing = []
    for name in state.goal.requirements:
        check = _REQUIREMENT_CHECKS.get(name)
        if check is None:
            raise ValueError(f"完成要件缺少判定函数: {name!r}")
        if not check(state):
            missing.append(name)
    return CompletionResult(complete=not missing, missing=missing)
