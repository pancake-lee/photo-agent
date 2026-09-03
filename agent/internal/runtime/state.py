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
    "locate": "确认候选范围",
    "candidates": "检索候选照片",
    "select": "挑选发布照片",
    "copy": "创作文案",
}

# Observation 归约分派键
OBS_PHOTO_IDS = "photo_ids"
OBS_SCOPE = "scope_materialized"
OBS_FACTS = "facts_resolved"
OBS_PHOTO_DETAILS = "photo_details"
OBS_PHOTOS_SELECTED = "photos_selected"
OBS_SELECTION_OVERFLOW = "selection_overflow"
OBS_COPY_DRAFTED = "copy_drafted"
OBS_NEEDS_CLARIFICATION = "needs_clarification"
OBS_ERROR = "error"

# Observation 恢复状态（六态）：kind 回答「观察对任务状态意味着什么」（归约分派），
# status 回答「系统应如何反应」（接受/重试/修复/换策略/再决策/停止）。
# 语义性结果（空结果、契约违规、低置信）由能力作者显式声明，
# 能力异常在执行护栏处按异常类型归类（网络超时类 → temporary，其余默认 permanent）。
STATUS_SUCCESS = "success"                  # 接受，进入归约
STATUS_EMPTY = "empty"                      # 语义空结果：有兜底时是合法观察，无兜底给换策略建议
STATUS_INVALID_INPUT = "invalid_input"      # 参数或输出不符合契约：决策侧反馈 decide，能力侧带反馈修复
STATUS_TEMPORARY_ERROR = "temporary_error"  # 瞬时故障（网络、超时、限流）：同能力同参数有界重试
STATUS_PERMANENT_ERROR = "permanent_error"  # 前置不满足或确定性失败：正确停止，文案可行动
STATUS_LOW_CONFIDENCE = "low_confidence"    # 有结果但证据不足：触发语义评估或补充检索（AR2-5 接入）

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
    delivery_mode: str = "editorial"


@dataclasses.dataclass
class Artifacts:
    """产物引用。大对象只存引用或摘要，按需读取。"""

    candidate_ids: list[str] = dataclasses.field(default_factory=list)
    selected_ids: list[str] = dataclasses.field(default_factory=list)
    copy_draft: dict = dataclasses.field(default_factory=dict)     # {"title", "content"}
    photo_cache: dict[str, dict] = dataclasses.field(default_factory=dict)
    handoff_url: str = ""


@dataclasses.dataclass
class Scope:
    """权威候选范围：硬约束（时间线/天序/时段）经程序物化后的候选全集。

    restricted 为 True 时候选类观察一律与 photo_ids 求交集，
    软提示检索零命中的时候选保留整个范围；范围只能由 OBS_SCOPE 归约建立。
    """

    established: bool = False       # 是否已解析（区分"未建立"与"不受限"）
    restricted: bool = False        # True = 受硬约束限制；False = 不受限（全库）
    conditions: dict = dataclasses.field(default_factory=dict)   # {"timeline","day","time_of_day"}
    condition_summary: str = ""     # 用户可读的范围条件（如"山西旅游第一天傍晚"）
    photo_ids: list[str] = dataclasses.field(default_factory=list)
    sql: str = ""                   # 物化范围时执行的 SQL（程序拼装，trace 用）


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
    scope: Scope = dataclasses.field(default_factory=Scope)        # 权威候选范围（硬约束物化）
    artifacts: Artifacts = dataclasses.field(default_factory=Artifacts)
    progress: Progress = dataclasses.field(default_factory=Progress)


@dataclasses.dataclass
class Observation:
    """能力执行的结构化观察，归约的唯一输入。

    kind    归约分派键（OBS_* 常量）：观察对任务状态意味着什么
    summary 给决策与轨迹的一句话摘要
    payload 归约所需的数据
    status  恢复状态（STATUS_* 常量）：系统应如何反应，恢复策略的唯一触发输入
    """

    kind: str
    summary: str
    payload: dict = dataclasses.field(default_factory=dict)
    status: str = STATUS_SUCCESS

    def __post_init__(self) -> None:
        # 错误观察不允许默认 success：失败必须显式归类，否则恢复层会误按「接受」处理
        if self.kind == OBS_ERROR and self.status == STATUS_SUCCESS:
            raise ValueError("OBS_ERROR 观察必须显式携带非 success 的 status（STATUS_* 常量）")


def new_goal(goal_type: str, description: str) -> Goal:
    """按预设构造目标，未知目标类型直接报错（编程错误而非运行时分支）。"""
    preset = _GOAL_PRESETS.get(goal_type)
    if preset is None:
        raise ValueError(f"未知的目标类型: {goal_type!r}，可用: {sorted(_GOAL_PRESETS)}")
    candidate_mode = any(term in description for term in ("尽可能多", "二次挑选", "二次选择", "自己再挑"))
    return Goal(
        goal_type=goal_type,
        description=description,
        # 候选交付只是放宽选片（不再由 LLM 精选），不是放弃发布文案。
        # 两种交付都必须经过 write_post，才能保证标题和正文完整返回。
        requirements=preset["requirements"],
        delivery_mode="candidate" if candidate_mode else "editorial",
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
    """检索类观察：候选集合整体替换（最新一次检索定义候选），去重保序后与范围求交集。"""
    ids: list[str] = []
    for pid in obs.payload.get("ids") or []:
        if pid and pid not in ids:
            ids.append(pid)
    state.artifacts.candidate_ids = ids
    _constrain_candidates_to_scope(state)
    _finish_milestone(state, "candidates")


def _constrain_candidates_to_scope(state: TaskState) -> None:
    """范围受限时候选必须落在权威范围内；软提示零命中的时候选保留整个范围。

    软提示（地点/景物/氛围）只影响范围内排序，永远不能清空或替换范围。
    """
    if not state.scope.restricted:
        return
    scope_set = set(state.scope.photo_ids)
    kept = [pid for pid in state.artifacts.candidate_ids if pid in scope_set]
    if kept:
        state.artifacts.candidate_ids = kept
    else:
        state.artifacts.candidate_ids = list(state.scope.photo_ids)


def _apply_scope(state: TaskState, obs: Observation) -> None:
    """范围观察：物化权威候选范围，时间线与软提示并入已确认事实。

    受限但范围为空是确定性终态（empty_scope），禁止后续选片与文案；
    范围晚于检索建立时，既有候选同样要回到范围内。
    """
    restricted = bool(obs.payload.get("restricted"))
    state.scope.established = True
    state.scope.restricted = restricted
    state.scope.conditions = dict(obs.payload.get("conditions") or {})
    state.scope.condition_summary = str(obs.payload.get("condition_summary") or "")
    state.scope.sql = str(obs.payload.get("sql") or "")
    ids: list[str] = []
    for pid in obs.payload.get("ids") or []:
        if pid and pid not in ids:
            ids.append(pid)
    state.scope.photo_ids = ids if restricted else []
    facts: dict = {}
    if state.scope.conditions.get("timeline"):
        facts["timeline"] = state.scope.conditions["timeline"]
    if obs.payload.get("soft_hints"):
        facts["soft_hints"] = [str(h) for h in obs.payload["soft_hints"]]
    if facts:
        state.resolved_facts.update(facts)
    if restricted:
        if not state.scope.photo_ids:
            detail = f"未找到符合条件的照片（{state.scope.condition_summary}）" \
                if state.scope.condition_summary else "权威候选范围为空"
            state.progress.errors.append(detail)
            del state.progress.errors[:-_ERRORS_MAX]
            state.progress.terminal_reason = "empty_scope"
        else:
            _constrain_candidates_to_scope(state)
    _finish_milestone(state, "locate")


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
    _trim_photo_cache(state)


def _trim_photo_cache(state: TaskState) -> None:
    """缓存只保留最近写入的 _PHOTO_CACHE_MAX 条，超出淘汰最早写入的条目。"""
    while len(state.artifacts.photo_cache) > _PHOTO_CACHE_MAX:
        oldest = next(iter(state.artifacts.photo_cache))
        del state.artifacts.photo_cache[oldest]


def _apply_photos_selected(state: TaskState, obs: Observation) -> None:
    """挑选观察：写入入选照片引用，并把入选照片完整详情并入缓存。

    缓存语义是"命中即完整详情"（cached_photos 据此跳过补拉），
    因此 payload.photos 必须携带能力手中的完整详情，不能只带 id/filename 摘要。
    """
    state.artifacts.selected_ids = list(obs.payload.get("ids") or [])
    for photo in obs.payload.get("photos") or []:
        pid = photo.get("id")
        if pid:
            state.artifacts.photo_cache[pid] = photo
    _trim_photo_cache(state)
    _record_assumption(state, obs)
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
    _record_assumption(state, obs)
    _finish_milestone(state, "copy")


# 可回退歧义的默认值假设上限（数量、风格各一条即可覆盖重选/重写场景）
_ASSUMPTIONS_MAX = 5


def _record_assumption(state: TaskState, obs: Observation) -> None:
    """可回退歧义的默认值假设（未指定数量/风格）记入已确认事实，不询问用户。

    假设对决策摘要与最终输出可见，用户事后可要求调整；只记录、不触发任何交互。
    """
    assumption = obs.payload.get("assumption")
    if not assumption:
        return
    assumptions = state.resolved_facts.setdefault("assumptions", [])
    assumptions.append(str(assumption))
    del assumptions[:-_ASSUMPTIONS_MAX]


def _apply_needs_clarification(state: TaskState, obs: Observation) -> None:
    """澄清观察：停止当前运行，等待会话层保存目标并接收用户短回复。"""
    state.resolved_facts["clarification"] = dict(obs.payload)
    state.progress.terminal_reason = "needs_clarification"


def _apply_error(state: TaskState, obs: Observation) -> None:
    """错误观察：记录失败并以确定性终态停止，避免无进展重复决策。"""
    state.progress.errors.append(obs.summary or "未知错误")
    del state.progress.errors[:-_ERRORS_MAX]
    terminal_reason = obs.payload.get("terminal_reason") or "capability_failed"
    state.progress.terminal_reason = str(terminal_reason)


_APPLY_RULES: dict[str, typing.Callable[[TaskState, Observation], None]] = {
    OBS_PHOTO_IDS: _apply_photo_ids,
    OBS_SCOPE: _apply_scope,
    OBS_FACTS: _apply_facts,
    OBS_PHOTO_DETAILS: _apply_photo_details,
    OBS_PHOTOS_SELECTED: _apply_photos_selected,
    OBS_SELECTION_OVERFLOW: _apply_selection_overflow,
    OBS_COPY_DRAFTED: _apply_copy_drafted,
    OBS_NEEDS_CLARIFICATION: _apply_needs_clarification,
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


def _scope_summary(state: TaskState) -> str:
    """决策摘要中的范围行：范围未建立/不受限/受限三种形态。"""
    if not state.scope.established:
        return "候选范围: 尚未确认"
    if not state.scope.restricted:
        return "候选范围: 不受限（全库）"
    return f"候选范围: {state.scope.condition_summary}（硬约束，共 {len(state.scope.photo_ids)} 张）"


def summarize_state(state: TaskState) -> str:
    """把任务状态序列化为决策提示词用的确定性摘要。"""
    done = [milestone_label(m) for m in _MILESTONE_LABELS if m not in state.progress.todo]
    lines = [
        f"目标类型: {state.goal.goal_type}（{state.goal.description}）",
        f"交付模式: {'候选照片供二次挑选' if state.goal.delivery_mode == 'candidate' else '编辑精选发布'}",
        f"已完成里程碑: {'、'.join(done) if done else '无'}",
        f"待办里程碑: {'、'.join(milestone_label(m) for m in state.progress.todo) or '无'}",
        f"用户约束: {_dump(state.constraints)}",
        f"已确认事实: {_dump(state.resolved_facts)}",
        _scope_summary(state),
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


def _selected_photo_labels(state: TaskState) -> list[str]:
    """入选照片展示名：缓存里有文件名用文件名，缺失时回退照片 ID。"""
    labels = []
    for pid in state.artifacts.selected_ids:
        filename = state.artifacts.photo_cache.get(pid, {}).get("filename")
        labels.append(str(filename) if filename else pid)
    return labels


def build_final_output(state: TaskState, stop_reason: str = "") -> dict:
    """组装最终输出（纯函数，确定性）。

    优先级：完成 > 兜底终止 > 预算停止。返回 {"answer", "handoff_url"}。
    """
    import internal.runtime.completion as rt_completion

    completion = rt_completion.check_completion(state)
    if completion.complete:
        if state.goal.delivery_mode == "candidate":
            draft = state.artifacts.copy_draft
            return {
                "answer": f"# {draft.get('title', '')}\n\n{draft.get('content', '')}\n\n"
                f"已保留 {len(state.artifacts.selected_ids)} 张候选照片，供你二次挑选。\n\n"
                f"候选照片：{'、'.join(_selected_photo_labels(state))}",
                "handoff_url": "",
            }
        draft = state.artifacts.copy_draft
        answer = f"# {draft.get('title', '')}\n\n{draft.get('content', '')}"
        if state.artifacts.selected_ids:
            answer += f"\n\n入选照片：{'、'.join(_selected_photo_labels(state))}"
        return {"answer": answer, "handoff_url": ""}

    if state.progress.terminal_reason == "candidate_overflow":
        return {
            "answer": "候选照片过多，请进入图文工坊自选后生成文案。",
            "handoff_url": state.artifacts.handoff_url,
        }

    if state.progress.terminal_reason == "needs_clarification":
        clarification = state.resolved_facts.get("clarification") or {}
        return {
            "answer": str(clarification.get("message") or "需要你确认日期后才能继续。"),
            "handoff_url": "",
        }

    if state.progress.terminal_reason == "empty_scope":
        detail = state.progress.errors[-1] if state.progress.errors else "没有符合条件的照片"
        return {
            "answer": (
                f"{detail}。"
                "可以放宽条件后重试，例如去掉时段或天数限制，或换成更大的日期范围。"
            ),
            "handoff_url": "",
        }

    if state.progress.terminal_reason:
        last_error = state.progress.errors[-1] if state.progress.errors else "关键能力执行失败"
        return {
            "answer": f"任务未能完成：{last_error}。",
            "handoff_url": "",
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
