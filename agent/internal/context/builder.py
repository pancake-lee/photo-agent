"""
    会话上下文构建器（框架无关纯 Python）。

    Context 不是对话日志的全量搬运，而是一次决策所需的最小充分输入（V4）。
    build_session_context 把会话历史整理为紧凑的历史块，供入口分类与跟进消解消费：
        - 选择：最近若干组问答保留原文（单条截断），更早轮次只留摘要
        - 压缩：更早轮次每轮压成一行，用户问题原样保留（硬约束不因压缩丢失）
        - 引用：照片只保留 ID 引用与数量，详情不进入上下文，按需另行加载
        - 优先级：当前用户消息由调用方独立传入，历史块只承载指代与约束线索，
          不与当前要求竞争优先级
    输入是纯消息字典列表（session_store.get_messages 的产物），不依赖存储实现。
"""

import dataclasses


# 近窗口原文保留的最近问答组数
_RECENT_TURNS = 2
# 更早轮次的摘要行上限（超出时丢弃最早的，标记 truncated）
_OLDER_TURNS_MAX = 6
# 近窗口单条消息截断长度
_USER_TEXT_MAX = 300
_ASSISTANT_TEXT_MAX = 400
# 摘要行内用户问题与回答的截断长度
_OLDER_USER_MAX = 80
_OLDER_ANSWER_MAX = 60
# 照片 ID 引用上限（近窗口原文行）
_PHOTO_REF_MAX = 12
# 更早轮次摘要行的照片 ID 引用上限（更小，长会话指代仍可展开为具体所选，AR4-6）
_OLDER_PHOTO_REF_MAX = 6


@dataclasses.dataclass
class SessionContext:
    """一次决策可用的会话上下文。

    history_block  注入提示词的紧凑历史块（空会话为空串）
    has_history    会话是否存在历史消息
    turn_count     历史中的问答组数
    truncated      摘要行或总长度是否发生丢弃
    """

    history_block: str
    has_history: bool
    turn_count: int
    truncated: bool


def _clip(text: str, limit: int) -> str:
    """单条文本截断，超长时标注原始长度。"""
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + f"…（已截断，原长 {len(text)}）"


def _photo_ref_line(photo_ids: list[str]) -> str:
    """照片引用行：ID 有界列出，数量始终可见。"""
    ids = [str(pid) for pid in photo_ids if pid]
    if not ids:
        return ""
    preview = "、".join(ids[:_PHOTO_REF_MAX])
    if len(ids) > _PHOTO_REF_MAX:
        preview += f"…（共 {len(ids)} 张）"
    return f"照片引用：{preview}"


def _pair_turns(messages: list[dict]) -> list[dict]:
    """把消息序列按「用户消息 + 其后首条助手消息」组织成问答组。

    缺少助手回复的悬空用户消息保留 assistant 为空串；连续助手消息只并入首条。
    """
    turns: list[dict] = []
    pending_user: dict | None = None
    for message in messages or []:
        role = str(message.get("role") or "")
        if role == "user":
            if pending_user is not None:
                turns.append(pending_user)
            pending_user = {
                "user_text": str(message.get("content") or ""),
                "assistant_text": "",
                "photo_ids": [],
            }
        elif role == "assistant" and pending_user is not None:
            pending_user["assistant_text"] = str(message.get("content") or "")
            pending_user["photo_ids"] = [
                str(photo.get("photo_id") or photo.get("id") or "")
                for photo in (message.get("photos") or [])
            ]
            turns.append(pending_user)
            pending_user = None
    if pending_user is not None:
        turns.append(pending_user)
    return turns


def _older_photo_suffix(photo_ids: list[str]) -> str:
    """更早轮次摘要的照片括注：数量 + 有界 ID 引用。

    ID 引用让「用刚才第二组」类长程指代在消解时能展开为具体所选（AR4-6）；
    上限小于近窗口，超限截断，数量始终可见。
    """
    if not photo_ids:
        return ""
    preview = "、".join(photo_ids[:_OLDER_PHOTO_REF_MAX])
    if len(photo_ids) > _OLDER_PHOTO_REF_MAX:
        preview += "…"
    return f"（照片 {len(photo_ids)} 张，引用：{preview}）"


def _older_summary_line(turn_no: int, turn: dict) -> str:
    """更早轮次的单行摘要：用户问题原样（截断），回答只留首行、照片数与有界 ID 引用。"""
    user_text = _clip(turn["user_text"], _OLDER_USER_MAX)
    answer_first_line = turn["assistant_text"].strip().splitlines()[0] if turn["assistant_text"].strip() else ""
    answer_text = _clip(answer_first_line, _OLDER_ANSWER_MAX)
    photo_ids = [pid for pid in turn["photo_ids"] if pid]
    photo_suffix = _older_photo_suffix(photo_ids)
    parts = [f"第{turn_no}轮 用户：{user_text}"]
    if answer_text:
        parts.append(f"回答：{answer_text}{photo_suffix}")
    elif photo_suffix:
        parts.append(photo_suffix)
    return "；".join(parts)


def _recent_block(turn_no: int, turn: dict) -> list[str]:
    """近窗口单组问答的原文行（截断到单条上限，照片只留引用）。"""
    lines = [f"用户：{_clip(turn['user_text'], _USER_TEXT_MAX)}"]
    if turn["assistant_text"]:
        lines.append(f"助手：{_clip(turn['assistant_text'], _ASSISTANT_TEXT_MAX)}")
    ref = _photo_ref_line(turn["photo_ids"])
    if ref:
        lines.append(ref)
    return lines


def build_session_context(messages: list[dict]) -> SessionContext:
    """把会话历史整理为紧凑历史块。

    输出长度由逐项截断约束（轮数上限 + 单条文本上限 + 照片引用上限）自然有界，
    无需额外的总长截断分支。
    """
    turns = _pair_turns(messages)
    if not turns:
        return SessionContext(history_block="", has_history=False, turn_count=0, truncated=False)

    truncated = False
    first_retained_turn_no = 1
    older_count = max(len(turns) - _RECENT_TURNS, 0)
    if older_count > _OLDER_TURNS_MAX:
        discarded_turn_count = older_count - _OLDER_TURNS_MAX
        turns = turns[discarded_turn_count:]
        first_retained_turn_no += discarded_turn_count
        older_count = _OLDER_TURNS_MAX
        truncated = True
    older_turns = turns[:older_count]
    recent_turns = turns[older_count:]

    sections: list[str] = []
    if older_turns:
        summary_lines = [
            _older_summary_line(first_retained_turn_no + index, turn)
            for index, turn in enumerate(older_turns)
        ]
        sections.append("[更早会话摘要]\n" + "\n".join(summary_lines))
    if recent_turns:
        recent_lines: list[str] = ["[最近会话]"]
        base_no = first_retained_turn_no + older_count - 1
        for index, turn in enumerate(recent_turns):
            recent_lines.append(f"— 第{base_no + index + 1}轮 —")
            recent_lines.extend(_recent_block(base_no + index + 1, turn))
        sections.append("\n".join(recent_lines))

    return SessionContext(
        history_block="\n\n".join(sections),
        has_history=True,
        turn_count=len(turns),
        truncated=truncated,
    )
