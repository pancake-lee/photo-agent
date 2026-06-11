"""
    完整链路：用户问题 → Embedding → Chroma 检索 Top-K → 拼接上下文 → LLM 生成

    核心功能供 photo_agent 复用，独立演示见 demo/photo_rag_demo.py。
"""

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import langchain_core.prompts as lc_prompts
import langchain_openai as lc_openai

import config
import embedding.embedder as embedder
import utils.streaming_printer as streaming_printer
import vectorstore.chroma_client as chroma_client


# 元数据过滤支持的维度及允许值（与 extract_attributes.py 保持一致）
METADATA_SCHEMA: dict[str, list[str]] = {
    "scene": ["indoor", "outdoor", "urban", "nature", "water", "mountain", "street", "night", "studio"],
    "lighting": ["bright", "dim", "soft", "harsh", "golden_hour", "backlit", "artificial"],
    "mood": ["warm", "calm", "dramatic", "melancholy", "joyful", "serious", "mysterious"],
}

FILTER_PROMPT = (
    "你是一位查询分析专家。请从用户的照片库检索问题中，提取可用于元数据过滤的结构化条件。\n\n"
    "支持过滤的维度及允许值（必须严格匹配以下值之一，不能自创）：\n"
    "- scene（场景）: indoor, outdoor, urban, nature, water, mountain, street, night, studio\n"
    "- lighting（光线）: bright, dim, soft, harsh, golden_hour, backlit, artificial\n"
    "- mood（情绪）: warm, calm, dramatic, melancholy, joyful, serious, mysterious\n\n"
    "规则：\n"
    "1. 仅当用户问题中明确包含某维度的信息时才提取\n"
    "2. 将用户的自然语言映射为上述允许值之一，映射示例：\n"
    "   - 蓝调时刻/夜景/夜晚 → dim\n"
    "   - 街拍/街头 → street\n"
    "   - 日落/黄昏/夕阳 → golden_hour\n"
    "   - 室内/屋里 → indoor\n"
    "   - 室外/户外 → outdoor\n"
    "   - 城市/都市 → urban\n"
    "   - 自然/风景 → nature\n"
    "   - 水面/湖边/海边 → water\n"
    "   - 雪山/山峰 → mountain\n"
    "   - 温暖/温馨 → warm\n"
    "   - 宁静/平和 → calm\n"
    "3. 如果无法匹配到允许值，不要包含该维度\n"
    "4. 输出严格 JSON 对象，不要包含任何额外文字\n"
    "5. 没有任何匹配时输出空对象 {{}}\n\n"
    "示例：\n"
    '- 输入: "找蓝色调、室外、有人物的照片" → 输出: {"scene": "outdoor"}\n'
    '- 输入: "蓝调时刻的街拍" → 输出: {"lighting": "dim", "scene": "street"}\n'
    '- 输入: "有猫咪的照片吗？" → 输出: {}\n'
    '- 输入: "日落时分的风景照" → 输出: {"lighting": "golden_hour", "scene": "nature"}\n'
    '- 输入: "室内温馨的家庭照" → 输出: {"scene": "indoor", "mood": "warm"}\n\n'
    "用户问题: {question}\n\n"
    "JSON:"
)

RAG_SYSTEM_PROMPT = (
    "你是一位摄影档案助手，专门帮助用户从照片库中查找和回顾照片。"
    "你会根据下面提供的照片描述信息回答用户的问题。"
    "如果上下文中有相关照片，请简要描述它们的内容并提及文件名；"
    "如果没有找到相关照片，请诚实告知。"
    "回答简洁，控制在 150 字以内。"
)

CONTEXT_PROMPT = (
    "以下是从照片库中检索到的相关照片描述，请基于这些信息回答问题。\n\n"
    "{context}\n\n"
    "用户问题：{question}"
)


def extract_filters_from_question(
    cfg: config.Config,
    question: str,
) -> dict:
    """从用户问题中提取 Chroma metadata 过滤条件。

    使用 LLM 将自然语言映射为预定义的结构化维度（scene/lighting/mood），
    仅返回能匹配到允许值的字段，无匹配时返回空 dict。

    参数:
        cfg:      配置对象
        question: 用户问题

    返回:
        Chroma where 过滤条件字典，如 {"scene": "street", "lighting": "dim"}
    """
    import json as _json
    import re as _re

    llm = lc_openai.ChatOpenAI(
        model=cfg.llm_model,
        api_key=cfg.llm_api_key,  # type: ignore[arg-type]
        base_url=cfg.llm_base_url,
        temperature=0.0,
        streaming=False,
    )

    prompt = lc_prompts.ChatPromptTemplate.from_messages([
        ("human", FILTER_PROMPT),
    ])
    chain = prompt | llm

    try:
        response = chain.invoke({"question": question})
        raw = str(response.content).strip()
    except Exception:
        return {}

    # 清理 markdown 代码块
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:])
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

    # 解析 JSON
    try:
        filters = _json.loads(raw)
    except _json.JSONDecodeError:
        match = _re.search(r'\{[^}]*\}', raw)
        if match:
            try:
                filters = _json.loads(match.group())
            except _json.JSONDecodeError:
                return {}
        else:
            return {}

    if not isinstance(filters, dict):
        return {}

    # 校验：只保留 schema 中定义的 key，且值必须在允许值列表中
    validated: dict = {}
    for key, allowed_values in METADATA_SCHEMA.items():
        val = filters.get(key)
        if val and isinstance(val, str) and val.lower() in [v.lower() for v in allowed_values]:
            # 使用标准大小写（与 index_photos.py 写入的一致）
            validated[key] = val.lower()

    return validated


def _build_context(results: list[dict]) -> str:
    """
    将 Chroma 检索结果格式化为上下文文本。

    参数:
        results: ChromaPhotoStore.query 返回的扁平结果列表

    返回:
        拼接后的上下文字符串，每条结果包含文件名、描述和距离
    """
    if not results:
        return "未找到相关照片。"

    lines: list[str] = []
    for i, r in enumerate(results, 1):
        meta = r.get("metadata") or {}
        photo_id = meta.get("photo_id", "unknown")
        doc = r.get("document") or ""
        distance = r.get("distance")
        dist_str = f" (相似度距离: {distance:.4f})" if distance is not None else ""
        lines.append(f"[{i}] 照片: {photo_id}{dist_str}\n描述: {doc}")

    return "\n\n".join(lines)


def _aggregate_by_photo(
    results: list[dict],
    top_n: int = 5,
) -> list[dict]:
    """
    将 chunk 级别的检索结果按照片聚合。

    同一照片的多个 chunk 只保留相似度最高（距离最小）的一条，
    避免同一照片在上下文中重复出现。

    参数:
        results: Chroma 检索结果列表（chunk 级别）
        top_n:   聚合后返回的最大照片数

    返回:
        按 photo_id 聚合后的结果列表，按距离升序排列
    """
    if not results:
        return []

    # photo_id -> 最佳结果（距离最小）
    best_by_photo: dict[str, dict] = {}

    for r in results:
        meta = r.get("metadata") or {}
        photo_id = meta.get("photo_id")
        if not photo_id:
            continue

        distance = r.get("distance")
        if distance is None:
            distance = float("inf")

        existing = best_by_photo.get(photo_id)
        if existing is None or distance < existing.get("distance", float("inf")):
            best_by_photo[photo_id] = r

    # 按距离排序，取 top_n
    aggregated = sorted(
        best_by_photo.values(),
        key=lambda x: x.get("distance") if x.get("distance") is not None else float("inf"), # type: ignore
    ) # type: ignore
    return aggregated[:top_n]


def _retrieve(
    cfg: config.Config,
    question: str,
    n_results: int = 5,
    where: dict | None = None,
) -> list[dict]:
    """
    对用户问题进行 Embedding 并在 Chroma 中检索 Top-K 结果。

    参数:
        cfg:        配置对象
        question:   用户问题
        n_results:  返回的最相似结果数量
        where:      元数据过滤条件，如 {"brand": "Canon"}、
                    {"shot_at": {"$gte": "2024-01-01"}}，支持 Chroma 原生语法

    返回:
        扁平化的检索结果列表
    """
    emb = embedder.Embedder(
        base_url=cfg.go_backend_url,
        model=cfg.embedding_model,
    )

    store = chroma_client.ChromaPhotoStore(
        persist_dir=str(cfg.resolve_path("./data/chroma")),
        collection_name="photos",
    )

    vectors = emb.embed_texts([question])
    query_embedding = vectors[0].tolist()

    results = store.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        where=where,
    )

    return results


def _build_rag_chain(cfg: config.Config):
    """
    构建 RAG 问答 Chain。

    参数:
        cfg: 配置对象

    返回:
        可 invoke 的 LangChain Chain
    """
    llm = lc_openai.ChatOpenAI(
        model=cfg.llm_model,
        api_key=cfg.llm_api_key,  # type: ignore[arg-type]
        base_url=cfg.llm_base_url,
        temperature=0.5,
        streaming=True,
    )

    prompt = lc_prompts.ChatPromptTemplate.from_messages([
        ("system", RAG_SYSTEM_PROMPT),
        ("human", CONTEXT_PROMPT),
    ])

    return prompt | llm


def answer_question(
    cfg: config.Config,
    question: str,
    n_results: int = 5,
    aggregate: bool = True,
    where: dict | None = None,
    auto_filter: bool = False,
) -> str:
    """
    执行完整 RAG 链路，返回答案字符串。

    参数:
        cfg:         配置对象
        question:    用户问题
        n_results:   检索结果数量（聚合模式下为返回的照片数）
        aggregate:   是否按照片聚合（默认 True），避免同一照片多 chunk 重复
        where:       元数据过滤条件，透传给 Chroma 检索（与 auto_filter 二选一）
        auto_filter: 是否自动从问题中提取 where 过滤条件（默认 False）

    返回:
        LLM 生成的回答文本
    """
    # 自动提取过滤条件（仅在未显式传入 where 时生效）
    effective_where = where
    if auto_filter and where is None:
        effective_where = extract_filters_from_question(cfg, question)

    # 聚合模式下先检索更多 chunk，再聚合到照片级别
    retrieve_n = n_results * 3 if aggregate else n_results
    results = _retrieve(cfg, question, n_results=retrieve_n, where=effective_where)

    if aggregate:
        results = _aggregate_by_photo(results, top_n=n_results)

    context = _build_context(results)

    chain = _build_rag_chain(cfg)
    response = chain.invoke({"context": context, "question": question})

    return str(response.content)


