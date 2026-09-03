"""
    Agent Runtime 语义质量门（AR2-5，框架无关纯 Python + 能力内 LLM 评委）。

    评估接口输入产物观察与评价维度，输出「通过 / 不通过 + 具体反馈」：
        - evaluate_selection  选片代表性：入选是否覆盖候选的场景与时段、
                              是否存在连拍折叠之外的近重复
        - evaluate_copy       文案事实依据：文案中的事实性断言是否有照片证据，
                              不虚构照片中不存在的内容

    由 guardrail 在确定性检查通过后按能力声明触发；不通过时反馈进入带反馈
    修复环（有界），修复耗尽以质量未达标终态停止。evaluator 是接受前的质量门，
    不改变完成要件（selected_photos + copy_draft）。
"""

import dataclasses
import logging

import internal.runtime.capabilities.common as caps_common
import internal.runtime.registry as rt_registry
import internal.runtime.state as rt_state

logger = logging.getLogger(__name__)

# 评委输出的反馈进入修复提示词，截断防止长反馈放大提示词
_FEEDBACK_MAX_CHARS = 200


@dataclasses.dataclass
class QualityVerdict:
    """质量门结论：passed 为真表示通过，feedback 携带具体改进反馈。"""

    passed: bool
    feedback: str = ""


def _parse_verdict(response_text: str) -> QualityVerdict:
    """解析评委 JSON 输出；输出不含 passed 字段时按通过处理（不误杀正常产物）。"""
    data = caps_common.extract_json_dict(response_text) or {}
    if "passed" not in data:
        logger.warning("[runtime] 质量门评委输出缺少 passed 字段，按通过处理: %s", response_text[:200])
        return QualityVerdict(True)
    feedback = str(data.get("feedback") or "")[:_FEEDBACK_MAX_CHARS]
    return QualityVerdict(bool(data.get("passed")), feedback)


# --------------------------------------------------
# 选片代表性
# --------------------------------------------------

_SELECTION_JUDGE_SYSTEM_PROMPT = (
    "你是摄影编辑评委。评估一组入选发布照片的代表性：\n"
    "1. 入选照片之间是否存在近重复（同一时段且画面内容高度相似，连拍折叠之外的重复）\n"
    "2. 场景与拍摄时段是否过于单一，以致无法代表候选集合的多样性\n"
    "只输出 JSON: {\"passed\": true, \"feedback\": \"\"}。\n"
    "通过时 feedback 留空；不通过时用一句话指出具体问题（哪几张重复、缺什么）。"
)


def _time_bucket(shot_at: str) -> str:
    """从拍摄时间提取本地小时，供时段多样性判断。"""
    hour_str = ""
    if isinstance(shot_at, str) and "T" in shot_at:
        hour_str = shot_at.split("T", 1)[1][:2]
    return f"{hour_str}时" if hour_str.isdigit() else "未知时段"


def _photo_line(photo: dict) -> str:
    return (
        f"- {photo.get('filename') or photo.get('id')}"
        f"（{_time_bucket(str(photo.get('shot_at') or ''))}）："
        f"{str(photo.get('description') or '无描述')[:60]}"
    )


def evaluate_selection(
    ctx: rt_registry.RunContext, observation: rt_state.Observation,
) -> QualityVerdict:
    """选片代表性质量门：只评估成功入选的观察，终态路径（超限深链等）直接通过。"""
    if observation.kind != rt_state.OBS_PHOTOS_SELECTED:
        return QualityVerdict(True)
    # 候选交付模式不经代表性选片（完整保留折叠候选），无代表性语义可评
    if ctx.state is not None and ctx.state.goal.delivery_mode == "candidate":
        return QualityVerdict(True)
    selected = [p for p in observation.payload.get("photos") or [] if isinstance(p, dict)]
    if not selected:
        return QualityVerdict(True)
    candidate_count = len(ctx.state.artifacts.candidate_ids) if ctx.state is not None else 0
    lines = "\n".join(_photo_line(photo) for photo in selected)
    user_prompt = (
        f"候选集合共 {candidate_count} 张（已按连拍组折叠），入选 {len(selected)} 张：\n"
        f"{lines}\n\n"
        "评估这组入选照片的代表性。"
    )
    response = caps_common.invoke_structured_llm(
        ctx, _SELECTION_JUDGE_SYSTEM_PROMPT, user_prompt, temperature=0.0,
    )
    return _parse_verdict(response)


# --------------------------------------------------
# 文案事实依据
# --------------------------------------------------

_COPY_JUDGE_SYSTEM_PROMPT = (
    "你是事实核查评委。给你一组照片的客观描述（来自视觉模型，是唯一事实来源）"
    "和一篇发布文案。逐条核对文案中的事实性断言（地点、景物、人物、事件、时间）：\n"
    "- 照片描述中有依据的断言视为成立\n"
    "- 描述中不存在的具体事实（编造的地名、店名、日期、事件）视为无依据\n"
    "- 合理的抒情、感叹、模糊表述不算事实断言\n"
    "只输出 JSON: {\"passed\": true, \"feedback\": \"\"}。\n"
    "通过时 feedback 留空；不通过时指出哪句断言没有照片证据。"
)


def evaluate_copy(
    ctx: rt_registry.RunContext, observation: rt_state.Observation,
) -> QualityVerdict:
    """文案事实依据质量门：只评估成功文案观察，证据来自入选照片的缓存详情。"""
    if observation.kind != rt_state.OBS_COPY_DRAFTED:
        return QualityVerdict(True)
    title = str(observation.payload.get("title") or "")
    content = str(observation.payload.get("content") or "")
    evidence: list[str] = []
    if ctx.state is not None:
        cache = ctx.state.artifacts.photo_cache
        for pid in ctx.state.artifacts.selected_ids:
            if pid in cache:
                evidence.append(_photo_line(cache[pid]))
    if not evidence:
        return QualityVerdict(True)
    user_prompt = (
        "照片证据：\n" + "\n".join(evidence) + "\n\n"
        f"待核查文案：\n标题：{title}\n正文：{content}\n\n"
        "核查这篇文案的事实依据。"
    )
    response = caps_common.invoke_structured_llm(
        ctx, _COPY_JUDGE_SYSTEM_PROMPT, user_prompt, temperature=0.0,
    )
    return _parse_verdict(response)
