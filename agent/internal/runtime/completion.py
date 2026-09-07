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

def _selected_photos_ready(s: rt_state.TaskState) -> bool:
    """入选照片要件：有入选，且范围受限时全部属于权威范围（范围外交付被阻断）。

    补选续跑（AR4-8）：保留集非空且 select 里程碑尚未重执行时判缺口，
    程序性强制重跑选片，「新增」侧不依赖决策模型自觉；重执行后待办清除，
    即使模型只返回保留照片也不会死循环。
    """
    if not s.artifacts.selected_ids:
        return False
    if s.artifacts.preserved_selected_ids and "select" in s.progress.todo:
        return False
    if not s.scope.restricted:
        return True
    scope_set = set(s.scope.photo_ids)
    return all(pid in scope_set for pid in s.artifacts.selected_ids)


def _comparison_report_ready(s: rt_state.TaskState) -> bool:
    report = s.artifacts.comparison_report
    return bool(report.get("summary") and report.get("periods") and report.get("photo_ids"))


def _topic_candidates_ready(s: rt_state.TaskState) -> bool:
    return bool(s.artifacts.topic_candidates)


# 社交媒体帖子 的任务完成条件由 选好图片 和 文案草稿 两个要件组成。
# _REQUIREMENT_CHECKS 的意义就是把两个条件最终封装成统一的调用流程
# _REQUIREMENT_CHECKS.get(name)(state) 直接返回 True/False，方便 check_completion 统一处理。
_REQUIREMENT_CHECKS: dict[str, typing.Callable[[rt_state.TaskState], bool]] = {
    "selected_photos": _selected_photos_ready,
    "copy_draft": lambda s: bool(s.artifacts.copy_draft.get("title"))
    and bool(s.artifacts.copy_draft.get("content")),
    "comparison_report": _comparison_report_ready,
    "topic_candidates": _topic_candidates_ready,
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
