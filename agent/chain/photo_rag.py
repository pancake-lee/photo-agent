"""
    完整链路：用户问题 → Embedding → Chroma 纯向量检索 Top-K → 拼接上下文 → LLM 生成

    ChromaDB 仅做语义相似度检索，结构化过滤由 Text-to-SQL 路径完成。
    设计决策见 docs/chroma-metadata-design.md。

    核心功能供 photo_agent 复用，独立演示见 demo/photo_rag_demo.py。
"""

import sys
import pathlib
import requests
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import langchain_core.prompts as lc_prompts

import utils.llm_factory as llm_factory

import config
import embedding.embedder as embedder
import utils.streaming_printer as streaming_printer
import vectorstore.chroma_client as chroma_client

logger = logging.getLogger(__name__)

RAG_SYSTEM_PROMPT = (
    "你是一位摄影档案助手，专门帮助用户从照片库中查找和回顾照片。"
    "你会根据下面提供的照片描述信息回答用户的问题。"
    "如果上下文中有相关照片，请使用 Markdown 图片语法在回答中展示照片：\n"
    "    ![照片描述](图片URL)\n"
    "每个回答最多展示 3 张照片。"
    "如果没有找到相关照片，请诚实告知。"
    "回答简洁，控制在 200 字以内。"
)

CONTEXT_PROMPT = (
    "以下是从照片库中检索到的相关照片描述，请基于这些信息回答问题。\n\n"
    "{context}\n\n"
    "用户问题：{question}"
)

# 检索粒度 → Chroma Collection
# photo:  全量照片，每张独立参与检索（默认，行为与改造前一致）
# fine:   精细连拍组，仅组封面参与检索，一组只出一个结果
# coarse: 模糊连拍组，同上但分组更宽松
GRANULARITY_COLLECTIONS = {
    "photo": chroma_client.COLLECTION_PHOTOS,
    "fine": chroma_client.COLLECTION_BURST_FINE,
    "coarse": chroma_client.COLLECTION_BURST_COARSE,
}


def resolve_collection(granularity: str) -> str:
    """把检索粒度映射为 Collection 名，未知粒度回落到全量照片集合。"""
    return GRANULARITY_COLLECTIONS.get(
        granularity or "photo", chroma_client.COLLECTION_PHOTOS,
    )


def _build_context(results: list[dict], cfg: config.Config) -> tuple[str, list[dict]]:
    """
    将 Chroma 检索结果格式化为上下文文本，并提取结构化照片引用。

    参数:
        results: ChromaPhotoStore.query 返回的扁平结果列表
        cfg:     配置对象（用于构造图片 URL）

    返回:
        (上下文字符串, 结构化照片引用列表)
    """
    if not results:
        return "未找到相关照片。", []

    lines: list[str] = []
    for i, r in enumerate(results, 1):
        meta = r.get("metadata") or {}
        photo_id = meta.get("photo_id", "unknown")
        doc = r.get("document") or ""
        distance = r.get("distance")
        dist_str = f" (相似度距离: {distance:.4f})" if distance is not None else ""
        image_url = f"{cfg.go_backend_url}/api/v1/photos/{photo_id}/image"
        lines.append(
            f"[{i}] 照片 {photo_id}{dist_str}\n"
            f"描述: {doc}\n"
            f"图片: ![{doc[:30] if doc else photo_id}]({image_url})"
        )

    photo_refs = _extract_photo_refs(results, cfg)
    return "\n\n".join(lines), photo_refs


def _extract_photo_refs(results: list[dict], cfg: config.Config) -> list[dict]:
    """
    从检索结果提取去重的结构化照片引用，并行获取原始文件名。

    命中来自连拍组集合时，metadata 带 group_id/photo_count，
    此时额外附上 burst_group_id 与 burst_count，供前端渲染组卡片。

    参数:
        results: Chroma 检索结果列表
        cfg:     配置对象

    返回:
        [{photo_id, filename, image_url, burst_group_id?, burst_count?}, ...]
    """
    if not results:
        return []

    # 去重提取 photo_id，同时记录其所属连拍组（组集合检索时才有）
    seen: set[str] = set()
    photo_ids: list[str] = []
    group_info: dict[str, tuple[str, int]] = {}
    for r in results:
        meta = r.get("metadata") or {}
        pid = meta.get("photo_id", "")
        if pid and pid not in seen:
            seen.add(pid)
            photo_ids.append(pid)
            gid = meta.get("group_id", "")
            if gid:
                group_info[pid] = (gid, int(meta.get("photo_count") or 0))

    import utils.backend_sdk as bksdk
    photo_api = bksdk.get_photo_api(cfg.go_backend_url)

    # 并行获取原始文件名
    filename_map: dict[str, str] = {}

    def _fetch_filename(pid: str) -> tuple[str, str]:
        try:
            resp = photo_api.photo_service_get_photo_detail(pid)
            photo = resp.photo
            filename = photo.filename if photo and photo.filename else pid
            return pid, filename
        except Exception:
            logger.debug("获取照片文件名失败: %s", pid)
            return pid, pid

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(_fetch_filename, pid): pid
            for pid in photo_ids
        }
        for future in as_completed(futures):
            try:
                pid, filename = future.result()
                filename_map[pid] = filename
            except Exception:
                pass

    # 构建引用列表（保持去重顺序）
    refs: list[dict] = []
    for pid in photo_ids:
        ref = {
            "photo_id": pid,
            "filename": filename_map.get(pid, pid),
            "image_url": f"{cfg.go_backend_url}/api/v1/photos/{pid}/image",
        }
        if pid in group_info:
            gid, count = group_info[pid]
            ref["burst_group_id"] = gid
            ref["burst_count"] = count
        refs.append(ref)

    return refs


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
    granularity: str = "photo",
) -> list[dict]:
    """
    对用户问题进行 Embedding 并在 Chroma 中检索 Top-K 结果（纯向量相似度）。

    参数:
        cfg:         配置对象
        question:    用户问题
        n_results:   返回的最相似结果数量
        granularity: 检索粒度 photo/fine/coarse，决定查询哪个 Collection

    返回:
        扁平化的检索结果列表
    """
    emb = embedder.Embedder(
        base_url=cfg.go_backend_url,
        model=cfg.embedding_model,
    )

    collection_name = resolve_collection(granularity)
    store = chroma_client.ChromaPhotoStore(
        persist_dir=str(cfg.resolve_path("./data/chroma")),
        collection_name=collection_name,
    )
    logger.info(
        "[检索] 粒度=%s → collection=%s, 集合文档数=%d, n_results=%d",
        granularity, collection_name, store.count(), n_results,
    )

    vectors = emb.embed_texts([question])
    query_embedding = vectors[0].tolist()
    logger.info("[检索] query embedding 维度=%d", len(query_embedding))

    results = store.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
    )
    results = _filter_healthy_results(results, cfg)
    logger.info("[检索] 原始返回 %d 条（chunk 级）", len(results))

    return results


def _filter_healthy_results(results: list[dict], cfg: config.Config) -> list[dict]:
    """统一排除未达到 AI 健康准入条件的照片及组封面。"""
    if not results:
        return []
    cache: dict[str, bool] = {}
    filtered: list[dict] = []
    for result in results:
        photo_id = (result.get("metadata") or {}).get("photo_id", "")
        if not photo_id:
            continue
        if photo_id not in cache:
            try:
                payload = requests.get(
                    f"{cfg.go_backend_url.rstrip('/')}/api/v1/photos/{photo_id}",
                    timeout=10,
                ).json().get("photo") or {}
                health = payload.get("aiHealthStatus") or payload.get("ai_health_status")
                embedding = payload.get("embeddingStatus") or payload.get("embedding_status")
                cache[photo_id] = health == "healthy" and embedding == "healthy"
            except requests.RequestException:
                cache[photo_id] = False
        if cache[photo_id]:
            filtered.append(result)
    return filtered


def _build_rag_chain(cfg: config.Config):
    """
    构建 RAG 问答 Chain。

    参数:
        cfg: 配置对象

    返回:
        可 invoke 的 LangChain Chain
    """
    llm = llm_factory.create_llm(cfg, temperature=0.5, streaming=True)

    prompt = lc_prompts.ChatPromptTemplate.from_messages([
        ("system", RAG_SYSTEM_PROMPT),
        ("human", CONTEXT_PROMPT),
    ])

    return prompt | llm


def _filter_by_ratio_gap(results: list[dict], ratio_threshold: float) -> list[dict]:
    """
    最大比值法（Max Ratio Gap）：检测相邻距离的比值，在第一个显著跳跃处截断。

    Top-K 结果按距离升序排列（最相似的在前）。遍历相邻对 dist[i], dist[i+1]，
    若 dist[i+1] / dist[i] >= ratio_threshold，说明第 i+1 个结果的相似度出现
    断崖式下跌，回退到 i 处截断。

    例如 [0.32, 0.38, 0.95, 1.42]，相邻比值 [1.19, 2.50, 1.49]：
    ratio=2.50 >= 1.8 → 在 index 1 处截断，保留前 2 个。

    参数:
        results:         按距离升序排列的检索结果（需含 "distance" 字段）
        ratio_threshold: 相邻距离比值阈值，>= 此值即截断

    返回:
        截断后的结果列表（至少保留 1 条）
    """
    if len(results) < 2:
        return results

    distances = [r.get("distance") for r in results]

    # 打印所有相邻比值
    ratios: list[float] = []
    for i in range(len(distances) - 1):
        d_curr = distances[i]
        d_next = distances[i + 1]
        if d_curr and d_next and d_curr > 0:
            r = d_next / d_curr
            ratios.append(r)
        else:
            ratios.append(float("nan"))
    logger.info("[过滤-阶段1] 相邻比值序列: %s", [f"{r:.2f}" if not (r != r) else "nan" for r in ratios])

    for i in range(len(distances) - 1):
        d_curr = distances[i]
        d_next = distances[i + 1]
        if d_curr is None or d_next is None or d_curr <= 0:
            continue
        ratio = d_next / d_curr
        if ratio >= ratio_threshold:
            cut_at = i + 1  # 保留 [0, cut_at)
            logger.info(
                "[过滤-阶段1] ✅ 触发截断: dist[%d]=%.4f → dist[%d]=%.4f (ratio=%.2f >= %.2f), 保留前 %d 条",
                i, d_curr, i + 1, d_next, ratio, ratio_threshold, cut_at,
            )
            return results[:cut_at]

    max_ratio = max(ratios) if ratios else 0.0
    return results


def retrieve_photo_ids(
    cfg: config.Config,
    question: str,
    n_results: int = 20,
    distance_threshold: float | None = None,
    auto_distance_ratio: float = 1.8,
    with_details: bool = False,
    granularity: str = "photo",
) -> list[str] | tuple[list[str], list[dict]]:
    """
    纯向量语义检索，仅返回 photo_id 列表（按相似度降序）。

    用于组合查询场景（SQL 结构化过滤 + RAG 语义检索取交集）。
    不生成 LLM 回答，只做检索。

    参数:
        cfg:                 配置对象
        question:            用户问题
        n_results:           返回的最大照片数
        distance_threshold:  绝对距离阈值（None 表示不过滤）
        auto_distance_ratio: 自动比值断层阈值（默认 1.8），0 表示关闭
        with_details:        为 True 时返回 (ids, results) 元组，
                            results 含 distance 字段用于 trace
        granularity:         检索粒度 photo/fine/coarse，组粒度下返回的是组封面 ID

    返回:
        按相似度降序排列的 photo_id 列表，或 (ids, results) 元组
    """
    # 检索更多 chunk 再聚合到照片级别
    results = _retrieve(cfg, question, n_results=n_results * 3, granularity=granularity)
    results = _aggregate_by_photo(results, top_n=n_results)
    logger.info("[组合查询] 聚合后 %d 张照片（按距离升序）", len(results))

    # 自动比值断层过滤
    if auto_distance_ratio > 0:
        results = _filter_by_ratio_gap(results, auto_distance_ratio)

    # 绝对距离阈值过滤
    if distance_threshold is not None:
        results = [
            r for r in results
            if r.get("distance") is not None and r["distance"] <= distance_threshold
        ]

    # 提取 photo_id
    ids: list[str] = []
    seen: set[str] = set()
    for r in results:
        meta = r.get("metadata") or {}
        pid = meta.get("photo_id", "")
        if pid and pid not in seen:
            seen.add(pid)
            ids.append(pid)

    logger.info("[组合查询] RAG 检索返回 %d 个 photo_id", len(ids))
    if with_details:
        return ids, results
    return ids


def answer_question(
    cfg: config.Config,
    question: str,
    n_results: int = 5,
    aggregate: bool = True,
    distance_threshold: float | None = None,
    auto_distance_ratio: float = 1.8,
    granularity: str = "photo",
) -> tuple[str, list[dict]]:
    """
    执行完整 RAG 链路（纯向量语义检索），返回答案和结构化照片引用。

    结构化过滤需求由 Text-to-SQL 路径独立处理，不在 ChromaDB 侧做 where 过滤。
    设计决策见 docs/chroma-metadata-design.md。

    过滤顺序：聚合 → 自动比值断层 → 绝对距离阈值 → 构建上下文。
    两个过滤独立配置，可组合使用。

    参数:
        cfg:                 配置对象
        question:            用户问题
        n_results:           检索结果数量（聚合模式下为返回的照片数）
        aggregate:           是否按照片聚合（默认 True），避免同一照片多 chunk 重复
        distance_threshold:  绝对距离阈值，超过此值的结果被丢弃（None 表示不过滤）
        auto_distance_ratio: 自动比值断层阈值（默认 1.8），0 表示关闭此算法。
                             算法：相邻 dist[i+1]/dist[i] >= ratio 时截断
        granularity:         检索粒度 photo/fine/coarse。组粒度下命中的是连拍组封面，
                             返回的引用会带 burst_group_id/burst_count

    返回:
        (LLM 生成的回答文本, 结构化照片引用列表)
    """
    # 聚合模式下先检索更多 chunk，再聚合到照片级别
    retrieve_n = n_results * 3 if aggregate else n_results
    results = _retrieve(cfg, question, n_results=retrieve_n, granularity=granularity)

    if aggregate:
        results = _aggregate_by_photo(results, top_n=n_results)

    # 打印聚合后的原始结果（诊断用）
    if results:
        dists = [f"{r.get('distance', '?'):.4f}" if r.get('distance') is not None else "?" for r in results]
        pids = [(r.get("metadata") or {}).get("photo_id", "?") for r in results]
        logger.info("[过滤-输入] 聚合后 %d 条: distances=%s, photo_ids=%s", len(results), dists, pids)
    else:
        logger.info("[过滤-输入] 聚合后 0 条（检索阶段即无结果，回答将提示未找到）")

    # 阶段 1: 自动比值断层过滤 — 检测距离序列中的显著跳跃
    if auto_distance_ratio > 0:
        before = len(results)
        results = _filter_by_ratio_gap(results, auto_distance_ratio)
        if before != len(results):
            logger.info(
                "[过滤-阶段1] 自动断层: ratio=%.2f, %d → %d 条",
                auto_distance_ratio, before, len(results),
            )

    # 阶段 2: 绝对距离阈值过滤 — 丢弃相似度不达标的低质量结果
    if distance_threshold is not None:
        before = len(results)
        results = [
            r for r in results
            if r.get("distance") is not None and r["distance"] <= distance_threshold
        ]
        if before != len(results):
            logger.info(
                "[过滤-阶段2] 距离阈值: %.4f, %d → %d 条",
                distance_threshold, before, len(results),
            )

    context, photo_refs = _build_context(results, cfg)

    chain = _build_rag_chain(cfg)
    response = chain.invoke({"context": context, "question": question})

    return str(response.content), photo_refs

