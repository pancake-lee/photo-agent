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
) -> list[dict]:
    """
    对用户问题进行 Embedding 并在 Chroma 中检索 Top-K 结果。

    参数:
        cfg:        配置对象
        question:   用户问题
        n_results:  返回的最相似结果数量

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
) -> str:
    """
    执行完整 RAG 链路，返回答案字符串。

    参数:
        cfg:        配置对象
        question:   用户问题
        n_results:  检索结果数量（聚合模式下为返回的照片数）
        aggregate:  是否按照片聚合（默认 True），避免同一照片多 chunk 重复

    返回:
        LLM 生成的回答文本
    """
    # 聚合模式下先检索更多 chunk，再聚合到照片级别
    retrieve_n = n_results * 3 if aggregate else n_results
    results = _retrieve(cfg, question, n_results=retrieve_n)

    if aggregate:
        results = _aggregate_by_photo(results, top_n=n_results)

    context = _build_context(results)

    chain = _build_rag_chain(cfg)
    response = chain.invoke({"context": context, "question": question})

    return str(response.content)


