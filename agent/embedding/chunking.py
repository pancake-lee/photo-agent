"""
    文本分片模块。

    针对不同结构的描述文本提供多种分片策略，支持按字数、按段落等方式拆分。
    每种策略作为独立函数注册，通过统一的 `chunk_text` 入口分发。

    用法：
        from embedding.chunking import chunk_text, Strategy

        chunks = chunk_text(long_description, strategy=Strategy.CHARS, max_chars=500)
"""

import enum


class Strategy(enum.Enum):
    """分片策略枚举。"""

    NONE = "none"       # 不分片，直接返回整段
    CHARS = "chars"     # 按字数分片
    # TODO: 后续可扩展
    # TOKENS = "tokens"   # 按 Token 数量分片
    # RECURSIVE = "recursive"  # 递归分片（按段落 → 句子 → 字数）


def chunk_by_none(text: str) -> list[str]:
    """
    不分片策略：直接返回单元素列表。

    适用于短文本（< 500 字）或不需要拆分的场景。
    """
    return [text] if text.strip() else []


def chunk_by_chars(text: str, max_chars: int = 500, overlap: int = 50) -> list[str]:
    """
    按字数分片：将长文本按固定字数切分，相邻片段可重叠。

    参数:
        text:      原始文本
        max_chars: 每片最大字符数
        overlap:   相邻片段重叠字符数（保证语义连贯）

    返回:
        分片后的文本列表
    """
    if not text.strip():
        return []

    text = text.strip()
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    step = max_chars - overlap

    while start < len(text):
        end = min(start + max_chars, len(text))
        chunk = text[start:end]
        chunks.append(chunk)
        start += step

    return chunks


def chunk_text(
    text: str,
    strategy: Strategy = Strategy.CHARS,
    **kwargs,
) -> list[str]:
    """
    统一分片入口，根据策略分发到对应的分片函数。

    参数:
        text:     原始文本
        strategy: 分片策略
        **kwargs: 各策略所需的额外参数（如 max_chars、overlap）

    返回:
        分片后的文本列表
    """
    if not text or not text.strip():
        return []

    dispatch = {
        Strategy.NONE: chunk_by_none,
        Strategy.CHARS: chunk_by_chars,
    }

    handler = dispatch.get(strategy)
    if handler is None:
        raise ValueError(f"未知的分片策略: {strategy.value}")

    return handler(text, **kwargs)
