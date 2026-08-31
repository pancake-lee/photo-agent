"""
    Agent Runtime 任务状态与归约规则（框架无关纯 Python）。

    TaskState 是开放目标任务的唯一事实源，区别于聊天记录：
        - 生产者：入口构造 new_task + 显式归约 reduce_observation
        - 消费者：完成检查（completion）、决策摘要（summarize_state）、
          最终输出组装（build_final_output）
    不允许绕过归约函数整体覆盖状态；每个字段有明确的生产者和消费者。
"""

import copy
import dataclasses
import json
import typing


# ============================================================================
# 常量
# ============================================================================

GOAL_SOCIAL_POST = "social_post"

# goal_type → 预设（完成要件 + 初始待办里程碑）
_GOAL_PRESETS: dict[str, dict] = {
    GOAL_SOCIAL_POST: {
        "requirements": ("selected_photos", "copy_draft"),
        "milestones": ("locate", "candidates", "select", "copy"),
    },
}

_REQUIREMENT_LABELS = {
    "selected_photos": "入选照片",
    "copy_draft": "发布文案",
}

_MILESTONE_LABELS = {
    "locate": "定位旅行与日期",
    "candidates": "检索候选照片",
    "select": "挑选发布照片",
    "copy": "创作文案",
}

# Observation 归约分派键
OBS_PHOTO_IDS = "photo_ids"
OBS_FACTS = "facts_resolved"
OBS_PHOTO_DETAILS = "photo_details"
OBS_PHOTOS_SELECTED = "photos_selected"
OBS_SELECTION_OVERFLOW = "selection_overflow"
OBS_COPY_DRAFTED = "copy_drafted"
OBS_ERROR = "error"

# 有界集合上限，防止状态无限膨胀
_HISTORY_MAX = 50
_ERRORS_MAX = 10
_PHOTO_CACHE_MAX = 200
_SUMMARY_ID_PREVIEW = 10


# ============================================================================
# 状态结构
# ============================================================================

@dataclasses.dataclass
class Goal:
    """目标：类型 + 完成要件。完成要件由程序确定性检查，不信任模型自述。"""

    goal_type: str
    description: str
    requirements: tuple[str, ...]


@dataclasses.dataclass
class Artifacts:
    """产物引用。大对象只存引用或摘要，按需读取。"""

    candidate_ids: list[str] = dataclasses.field(default_factory=list)
    selected_ids: list[str] = dataclasses.field(default_factory=list)
    copy_draft: dict = dataclasses.field(default_factory=dict)     # {"title", "content"}
    photo_cache: dict[str, dict] = dataclasses.field(default_factory=dict)
    handoff_url: str = ""


@dataclasses.dataclass
class Progress:
    """执行进度：待办里程碑 + 有界历史。"""

    todo: list[str] = dataclasses.field(default_factory=list)
    history: list[dict] = dataclasses.field(default_factory=list)  # {step, action, kind, summary}
    errors: list[str] = dataclasses.field(default_factory=list)
    terminal_reason: str = ""   # 非空表示任务以兜底形态终止（如候选超限深链）


@dataclasses.dataclass
class TaskState:
    """Runtime 任务状态，字段语义见模块 docstring。"""

    goal: Goal
    constraints: dict = dataclasses.field(default_factory=dict)    # 用户原始约束，入口原样带入
    resolved_facts: dict = dataclasses.field(default_factory=dict)  # 执行中推断出的事实
    artifacts: Artifacts = dataclasses.field(default_factory=Artifacts)
    progress: Progress = dataclasses.field(default_factory=Progress)


@dataclasses.dataclass
class Observation:
    """能力执行的结构化观察，归约的唯一输入。

    kind    归约分派键（OBS_* 常量）
    summary 给决策与轨迹的一句话摘要
    payload 归约所需的数据
    """

    kind: str
    summary: str
    payload: dict = dataclasses.field(default_factory=dict)


def new_goal(goal_type: str, description: str) -> Goal:
    """按预设构造目标，未知目标类型直接报错（编程错误而非运行时分支）。"""
    preset = _GOAL_PRESETS.get(goal_type)
    if preset is None:
        raise ValueError(f"未知的目标类型: {goal_type!r}，可用: {sorted(_GOAL_PRESETS)}")
    return Goal(
        goal_type=goal_type,
        description=description,
        requirements=preset["requirements"],
    )


def new_task(goal_type: str, description: str, constraints: dict | None = None) -> TaskState:
    """入口构造初始任务状态，待办里程碑来自目标预设。"""
    goal = new_goal(goal_type, description)
    preset = _GOAL_PRESETS[goal_type]
    return TaskState(
        goal=goal,
        constraints=dict(constraints or {}),
        progress=Progress(todo=list(preset["milestones"])),
    )


# ============================================================================
# 显式归约
# ============================================================================

def reduce_observation(
    state: TaskState,
    obs: Observation,
    step_no: int = 0,
    action: str = "",
) -> TaskState:
    """将一次能力观察归约进任务状态，返回新状态，不修改入参。

    归约规则按 obs.kind 显式分派，未知 kind 直接报错。
    """
    next_state = copy.deepcopy(state)
    _APPLY_RULES[obs.kind](next_state, obs)
    next_state.progress.history.append({
        "step": step_no,
        "action": action,
        "kind": obs.kind,
        "summary": obs.summary,
    })
    del next_state.progress.history[:-_HISTORY_MAX]
    return next_state


def _apply_photo_ids(state: TaskState, obs: Observation) -> None:
    """检索类观察：候选集合整体替换（最新一次检索定义候选），去重保序。"""
    ids: list[str] = []
    for pid in obs.payload.get("ids") or []:
        if pid and pid not in ids:
            ids.append(pid)
    state.artifacts.candidate_ids = ids
    _finish_milestone(state, "candidates")


def _apply_facts(state: TaskState, obs: Observation) -> None:
    """事实观察：合并进 resolved_facts；定位到旅行或日期即完成 locate。"""
    facts = obs.payload.get("facts") or {}
    if not isinstance(facts, dict):
        raise ValueError("facts_resolved 观察的 payload.facts 必须是字典")
    state.resolved_facts.update(facts)
    if "timeline" in state.resolved_facts or "date_range" in state.resolved_facts:
        _finish_milestone(state, "locate")


def _apply_photo_details(state: TaskState, obs: Observation) -> None:
    """详情观察：合并进有界缓存，超出上限淘汰最早写入的条目。"""
    for photo in obs.payload.get("photos") or []:
        pid = photo.get("id")
        if not pid:
            continue
        state.artifacts.photo_cache[pid] = photo
    while len(state.artifacts.photo_cache) > _PHOTO_CACHE_MAX:
        oldest = next(iter(state.artifacts.photo_cache))
        del state.artifacts.photo_cache[oldest]


def _apply_photos_selected(state: TaskState, obs: Observation) -> None:
    """挑选观察：写入入选照片引用。"""
    state.artifacts.selected_ids = list(obs.payload.get("ids") or [])
    _finish_milestone(state, "select")


def _apply_selection_overflow(state: TaskState, obs: Observation) -> None:
    """超限观察：任务以图文工坊深链兜底形态终止。"""
    state.artifacts.handoff_url = str(obs.payload.get("url") or "")
    state.progress.terminal_reason = "candidate_overflow"


def _apply_copy_drafted(state: TaskState, obs: Observation) -> None:
    """文案观察：写入文案草稿（title + content）。"""
    state.artifacts.copy_draft = {
        "title": str(obs.payload.get("title") or ""),
        "content": str(obs.payload.get("content") or ""),
    }
    _finish_milestone(state, "copy")


def _apply_error(state: TaskState, obs: Observation) -> None:
    """错误观察：记录有界错误清单，供决策与最终说明使用。"""
    state.progress.errors.append(obs.summary or "未知错误")
    del state.progress.errors[:-_ERRORS_MAX]


_APPLY_RULES: dict[str, typing.Callable[[TaskState, Observation], None]] = {
    OBS_PHOTO_IDS: _apply_photo_ids,
    OBS_FACTS: _apply_facts,
    OBS_PHOTO_DETAILS: _apply_photo_details,
    OBS_PHOTOS_SELECTED: _apply_photos_selected,
    OBS_SELECTION_OVERFLOW: _apply_selection_overflow,
    OBS_COPY_DRAFTED: _apply_copy_drafted,
    OBS_ERROR: _apply_error,
}


def _finish_milestone(state: TaskState, milestone: str) -> None:
    if milestone in state.progress.todo:
        state.progress.todo.remove(milestone)


def milestone_label(milestone: str) -> str:
    return _MILESTONE_LABELS.get(milestone, milestone)


def requirement_label(requirement: str) -> str:
    return _REQUIREMENT_LABELS.get(requirement, requirement)


# ============================================================================
# 决策摘要与最终输出
# ============================================================================

def _ids_preview(ids: list[str]) -> str:
    if not ids:
        return "无"
    preview = "、".join(ids[:_SUMMARY_ID_PREVIEW])
    if len(ids) > _SUMMARY_ID_PREVIEW:
        preview += f"…（共 {len(ids)} 个）"
    return preview


def _dump(value: typing.Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def summarize_state(state: TaskState) -> str:
    """把任务状态序列化为决策提示词用的确定性摘要。"""
    done = [milestone_label(m) for m in _MILESTONE_LABELS if m not in state.progress.todo]
    lines = [
        f"目标类型: {state.goal.goal_type}（{state.goal.description}）",
        f"已完成里程碑: {'、'.join(done) if done else '无'}",
        f"待办里程碑: {'、'.join(milestone_label(m) for m in state.progress.todo) or '无'}",
        f"用户约束: {_dump(state.constraints)}",
        f"已确认事实: {_dump(state.resolved_facts)}",
        f"候选照片: {_ids_preview(state.artifacts.candidate_ids)}",
        f"已选照片: {_ids_preview(state.artifacts.selected_ids)}",
        f"文案草稿: "
        + (f"已有（标题「{state.artifacts.copy_draft.get('title', '')}」）"
           if state.artifacts.copy_draft else "无"),
    ]
    if state.progress.terminal_reason:
        lines.append(f"终止形态: {state.progress.terminal_reason}")
    if state.progress.errors:
        lines.append(f"最近错误: {'；'.join(state.progress.errors[-3:])}")
    recent = state.progress.history[-3:]
    if recent:
        lines.append("最近动作:")
        lines.extend(
            f"  第{item['step']}步 {item['action']}（{item['kind']}）: {item['summary']}"
            for item in recent
        )
    return "\n".join(lines)


_STOP_REASON_LABELS = {
    "max_steps": "步数",
    "timeout": "时长",
    "cost": "成本",
}


def build_final_output(state: TaskState, stop_reason: str = "") -> dict:
    """组装最终输出（纯函数，确定性）。

    优先级：完成 > 兜底终止 > 预算停止。返回 {"answer", "handoff_url"}。
    """
    import internal.runtime.completion as rt_completion

    completion = rt_completion.check_completion(state)
    if completion.complete:
        draft = state.artifacts.copy_draft
        answer = f"# {draft.get('title', '')}\n\n{draft.get('content', '')}"
        if state.artifacts.selected_ids:
            answer += f"\n\n入选照片：{'、'.join(state.artifacts.selected_ids)}"
        return {"answer": answer, "handoff_url": ""}

    if state.progress.terminal_reason == "candidate_overflow":
        return {
            "answer": "候选照片过多，请进入图文工坊自选后生成文案。",
            "handoff_url": state.artifacts.handoff_url,
        }

    reason_label = _STOP_REASON_LABELS.get(stop_reason, stop_reason or "未知")
    done = [milestone_label(m) for m in _MILESTONE_LABELS if m not in state.progress.todo]
    missing = "、".join(requirement_label(r) for r in completion.missing) or "无"
    last = state.progress.history[-1]
    last_line = f"（最后动作：{last['action']} — {last['summary']}）" if last else ""
    answer = (
        f"任务未能完成：执行预算已耗尽（{reason_label}）。\n\n"
        f"已完成：{'、'.join(done) if done else '无'}\n"
        f"仍缺少：{missing}\n"
        f"{last_line}"
    )
    return {"answer": answer, "handoff_url": ""}
