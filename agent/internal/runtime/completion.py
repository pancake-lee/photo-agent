"""
    Agent Runtime 完成检查（框架无关纯 Python）。

    完成判定全部由程序确定性执行，逐项检查目标要件，不信任「模型说完成了」。
    语义质量（如文案是否有叙事感）不作为硬性要件。
"""

import dataclasses
import typing

import internal.runtime.state as rt_state


@dataclasses.dataclass
class CompletionResult:
    """完成检查结论：complete 为真表示全部要件齐备，missing 列出缺口。"""

    complete: bool
    missing: list[str]


# 要件名 → 确定性判定函数（消费 TaskState 的具体字段）
def _selected_photos_ready(s: rt_state.TaskState) -> bool:
    """入选照片要件：有入选，且范围受限时全部属于权威范围（范围外交付被阻断）。"""
    if not s.artifacts.selected_ids:
        return False
    if not s.scope.restricted:
        return True
    scope_set = set(s.scope.photo_ids)
    return all(pid in scope_set for pid in s.artifacts.selected_ids)


_REQUIREMENT_CHECKS: dict[str, typing.Callable[[rt_state.TaskState], bool]] = {
    "selected_photos": _selected_photos_ready,
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
