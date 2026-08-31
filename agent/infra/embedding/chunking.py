"""
    文本分片模块。

    针对不同结构的描述文本提供多种分片策略，支持按字数、按 Markdown 标题等方式拆分。
    每种策略作为独立函数注册，通过统一的 `chunk_text` 入口分发。

    用法：
        import infra.embedding.chunking as chunking

        chunks = chunking.chunk_text(text, strategy=chunking.Strategy.FIXED_SIZE, chunk_size=500, chunk_overlap=50)
"""

import enum
import re
import typing


class Strategy(enum.Enum):
    """分片策略枚举。"""

    NONE = "none"                          # 不分片，直接返回整段
    FIXED_SIZE = "fixed_size"              # 按固定字数分片（带重叠窗口）
    MARKDOWN_HEADING = "markdown_heading"  # 按 Markdown 标题分片


def chunk_by_none(text: str) -> list[str]:
    """
    不分片策略：直接返回单元素列表。

    适用于短文本或不需要拆分的场景。
    """
    return [text] if text.strip() else []


def chunk_by_fixed_size(text: str, chunk_size: int = 500, chunk_overlap: int = 50) -> list[str]:
    """
    按固定字数分片：将长文本按固定字数切分，相邻片段可重叠。

    参数:
        text:           原始文本
        chunk_size:     每片目标字符数
        chunk_overlap:  相邻片段重叠字符数（保证语义连贯）

    返回:
        分片后的文本列表
    """
    if not text.strip():
        return []

    text = text.strip()
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    step = chunk_size - chunk_overlap

    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk = text[start:end]
        chunks.append(chunk)
        start += step

    return chunks


def chunk_by_markdown_heading(text: str, level: int = 2) -> list[str]:
    """
    按 Markdown 标题分片：按指定级别的标题将文本切分为多个块。

    每个块以目标级别的标题行开头，包含该标题下的所有内容，直到下一个同级标题。
    如果文本中不包含目标级别的标题，则返回整块文本。

    参数:
        text:   原始 Markdown 文本
        level:  标题级别，1-6，默认为 2（即 ##）

    返回:
        分片后的文本列表
    """
    if not text.strip():
        return []

    if not 1 <= level <= 6:
        raise ValueError(f"heading_level 必须在 1-6 之间，当前为 {level}")

    heading_prefix = '#' * level + ' '
    lines = text.split('\n')

    chunks: list[str] = []
    current_chunk: list[str] = []

    for line in lines:
        # 检测是否是目标级别的标题行
        # 必须精确匹配 level 个 # 后接空格，避免把更高级别（如 ### 当 level=2）误判
        if line.startswith(heading_prefix) and not line.startswith('#' * (level + 1) + ' '):
            if current_chunk:
                chunk_text_content = '\n'.join(current_chunk).strip()
                if chunk_text_content:
                    chunks.append(chunk_text_content)
            current_chunk = [line]
        else:
            current_chunk.append(line)

    if current_chunk:
        chunk_text_content = '\n'.join(current_chunk).strip()
        if chunk_text_content:
            chunks.append(chunk_text_content)

    return chunks


def chunk_text(
    text: str,
    strategy: Strategy = Strategy.NONE,
    **kwargs,
) -> list[str]:
    """
    统一分片入口，根据策略分发到对应的分片函数。

    参数:
        text:     原始文本
        strategy: 分片策略
        **kwargs: 各策略所需的额外参数
            - FIXED_SIZE: chunk_size (int), chunk_overlap (int)
            - MARKDOWN_HEADING: level (int)

    返回:
        分片后的文本列表
    """
    if not text or not text.strip():
        return []

    dispatch = {
        Strategy.NONE: chunk_by_none,
        Strategy.FIXED_SIZE: chunk_by_fixed_size,
        Strategy.MARKDOWN_HEADING: chunk_by_markdown_heading,
    }

    if not isinstance(strategy, Strategy):
        raise ValueError(f"策略必须是 Strategy 枚举类型，当前为: {type(strategy).__name__}")

    handler = dispatch.get(strategy)
    if handler is None:
        raise ValueError(f"未知的分片策略: {strategy.value}")

    return handler(text, **kwargs)


# --------------------------------------------------------------------------- #
# 自动策略选择
# --------------------------------------------------------------------------- #

def _has_markdown_headings(text: str) -> bool:
    """简单检测文本是否包含二级及以上 Markdown 标题行（## 到 ######）。"""
    pattern = re.compile(r'^#{2,6}\s', re.MULTILINE)
    return bool(pattern.search(text))


def _try_markdown_level(text: str, level: int) -> typing.Optional[list[str]]:
    """
    尝试用指定 Markdown 标题级别分块。

    返回:
        分块成功且结果非空则返回 chunks 列表，否则返回 None。
    """
    try:
        chunks = chunk_by_markdown_heading(text, level=level)
        return chunks if chunks else None
    except ValueError:
        return None


def chunk_text_auto(
    text: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
    md_level: int = 0,
) -> list[str]:
    """
    自动选择分片策略。

    策略选择逻辑:
        1. 文本长度 <= chunk_size：不分片，返回整块
        2. 文本包含 Markdown 标题（二级及以上 ##）:
            - md_level = 0（默认）：自动计算合适的标题级别
                - 从 level=2 开始尝试，如果分块后每块都 <= chunk_size，则使用该级别
                - 否则 level+1 继续尝试，直到 level=6
                - 如果 level=6 仍不满足，兜底用 FIXED_SIZE
            - md_level > 0：使用用户指定的级别
                - 分块后验证每块都 <= chunk_size，否则依次降级再试，最终兜底 FIXED_SIZE
        3. 文本不含 Markdown 标题：按 FIXED_SIZE 分块

    参数:
        text:           原始文本
        chunk_size:     每片目标字符数上限
        chunk_overlap:  FIXED_SIZE 策略的相邻片段重叠字符数
        md_level:       Markdown 标题级别，0 表示自动计算（默认），1-6 表示指定级别

    返回:
        分片后的文本列表
    """
    if not text or not text.strip():
        return []

    text = text.strip()
    if len(text) <= chunk_size:
        return [text]

    # 检查是否包含二级及以上 Markdown 标题
    if _has_markdown_headings(text):
        if md_level == 0:
            # 自动计算：从 level=2 开始尝试到 level=6
            levels_to_try = list(range(2, 7))
        else:
            # 用户指定：先尝试指定级别，再依次降级到 level=6
            levels_to_try = list(range(md_level, 7))

        for level in levels_to_try:
            chunks = _try_markdown_level(text, level)
            if chunks is not None and all(len(c) <= chunk_size for c in chunks):
                return chunks

        # Markdown 策略均不满足，兜底用 FIXED_SIZE
        return chunk_by_fixed_size(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    # 不含 Markdown 标题，按 FIXED_SIZE 分块
    return chunk_by_fixed_size(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
