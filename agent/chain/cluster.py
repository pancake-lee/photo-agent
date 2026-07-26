"""
    照片向量聚类模块。

    基于 ChromaDB 中已有照片向量，通过 UMAP 降维 + HDBSCAN 聚类，
    发现视觉相似的照片分组。结果以 JSON 文件存储。

    用法:
        import chain.cluster as cluster_mod

        result = cluster_mod.run_clustering(
            chroma_store,
            min_cluster_size=5,
            min_samples=3,
            umap_n_neighbors=15,
            umap_min_dist=0.1,
            umap_n_components=5,
            umap_metric="cosine",
        )
"""

import sys
import pathlib


import time
import json
import uuid
import logging
import datetime
import dataclasses
import typing

import numpy as np

import vectorstore.chroma_client as chroma_client
import chain.tracer as tracer_mod

logger = logging.getLogger(__name__)


# ── 聚类结果存储 ──────────────────────────────────────────────
# 注意: 聚类存储路径通过函数参数传入，不再使用模块级全局变量。
# server.py 中通过 app.state.cluster_dir 管理，CLI 模式直接传入路径。


def _ensure_cluster_dir(dir_path: pathlib.Path) -> None:
    """确保聚类存储目录存在。"""
    dir_path.mkdir(parents=True, exist_ok=True)


# ── 结果数据结构 ──────────────────────────────────────────────

@dataclasses.dataclass
class ClusterPhoto:
    photo_id: str
    filename: str
    distance_to_centroid: float


@dataclasses.dataclass
class ClusterInfo:
    cluster_id: int
    label: str
    theme_description: str = ""
    size: int = 0
    coherence_score: float = 0.0
    photos: list[ClusterPhoto] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class ClusterStats:
    total_photos: int
    clustered_photos: int
    noise_photos: int
    num_clusters: int
    duration_seconds: float


@dataclasses.dataclass
class ClusterResult:
    id: str
    created_at: str
    params: dict
    stats: ClusterStats
    clusters: list[ClusterInfo]


# ── 内部：向量获取 ────────────────────────────────────────────

def _fetch_photo_vectors(
    chroma: chroma_client.ChromaPhotoStore,
) -> tuple[list[str], list[str], np.ndarray]:
    """
    从 ChromaDB 获取全部照片向量。

    多 chunk 的照片取各 chunk embedding 的平均值。

    返回:
        photo_ids:  照片 ID 列表（与向量矩阵行对应）
        filenames:  文件名列表（从 metadata 提取，兜底用 photo_id）
        matrix:      N × D 的 numpy 数组
    """
    raw = chroma.collection.get(include=["embeddings", "metadatas"])
    all_ids = raw.get("ids", [])
    embeddings_all = raw.get("embeddings", [])
    metadatas_all = raw.get("metadatas", [])

    if not all_ids or len(embeddings_all) == 0:
        raise ValueError("ChromaDB 中无嵌入数据，请先运行 embedding")

    # 按 photo_id 分组求平均
    groups: dict[str, list[np.ndarray]] = {}
    filenames: dict[str, str] = {}

    for i, chunk_id in enumerate(all_ids):
        emb = embeddings_all[i]
        meta = metadatas_all[i] if i < len(metadatas_all) else {}
        pid = (meta or {}).get("photo_id", chunk_id)
        groups.setdefault(pid, []).append(np.array(emb, dtype=np.float32))
        # 优先使用 metadata 中的文件名，兜底用 photo_id
        if pid not in filenames:
            fn = (meta or {}).get("filename", "")
            if not fn:
                fn = (meta or {}).get("file_path", "")
                if fn:
                    fn = pathlib.Path(fn).name
            filenames[pid] = fn if fn else pid

    photo_ids: list[str] = []
    vectors: list[np.ndarray] = []
    for pid, emb_list in groups.items():
        photo_ids.append(pid)
        avg = np.mean(emb_list, axis=0)
        vectors.append(avg)

    matrix = np.stack(vectors, axis=0)
    logger.info(
        "从 ChromaDB 获取 %d 个 photo_id（%d 个 chunk），向量矩阵 shape=%s",
        len(photo_ids), len(all_ids), matrix.shape,
    )
    return photo_ids, [filenames.get(pid, pid) for pid in photo_ids], matrix


# ── 内部：聚类核心逻辑 ────────────────────────────────────────

def _run_umap(
    matrix: np.ndarray,
    n_neighbors: int,
    min_dist: float,
    n_components: int,
    metric: str,
) -> np.ndarray:
    """UMAP 降维。"""
    import umap

    # n_neighbors 不能超过样本数
    n = max(2, min(n_neighbors, matrix.shape[0] - 1))
    if n != n_neighbors:
        logger.warning("n_neighbors 从 %d 调整为 %d（样本数=%d）", n_neighbors, n, matrix.shape[0])

    reducer = umap.UMAP(
        n_neighbors=n,
        min_dist=min_dist,
        n_components=n_components,
        metric=metric,
        random_state=42,
        n_jobs=1,
    )
    reduced = reducer.fit_transform(matrix)
    logger.info("UMAP 降维完成: %s → %s", matrix.shape, reduced.shape)
    return reduced


def _run_hdbscan(
    reduced: np.ndarray,
    min_cluster_size: int,
    min_samples: int,
) -> tuple[np.ndarray, np.ndarray]:
    """HDBSCAN 聚类。"""
    import hdbscan

    # min_cluster_size 不能超过样本数
    n = max(2, min(min_cluster_size, reduced.shape[0]))
    s = max(1, min(min_samples, reduced.shape[0]))
    if n != min_cluster_size:
        logger.warning("min_cluster_size 从 %d 调整为 %d", min_cluster_size, n)
    if s != min_samples:
        logger.warning("min_samples 从 %d 调整为 %d", min_samples, s)

    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=n,
        min_samples=s,
        metric="euclidean",
        cluster_selection_method="eom",
    )
    labels = clusterer.fit_predict(reduced)
    probabilities = clusterer.probabilities_
    logger.info(
        "HDBSCAN 完成: %d 个簇, %d 个噪声点",
        len(set(labels)) - (1 if -1 in labels else 0),
        np.sum(labels == -1),
    )
    return labels, probabilities


def _compute_cluster_stats(
    reduced: np.ndarray,
    labels: np.ndarray,
    photo_ids: list[str],
    filenames: list[str],
) -> list[ClusterInfo]:
    """计算每个聚类的统计信息。"""
    unique_labels = sorted(set(labels))
    clusters: list[ClusterInfo] = []

    for label in unique_labels:
        if label == -1:
            continue  # 跳过噪声

        mask = labels == label
        indices = np.where(mask)[0]
        members = reduced[mask]
        centroid = np.mean(members, axis=0)

        # 凝聚度：成员到质心的平均距离（归一化取反，越高越好）
        distances = np.linalg.norm(members - centroid, axis=1)
        mean_dist = float(np.mean(distances))
        # 用 1/(1+mean_dist) 映射到 (0, 1]，距离越小分数越高
        coherence = round(1.0 / (1.0 + mean_dist), 4)

        # 按质心距离排序（距离最近的排前面 → 视觉最连贯）
        sorted_order = np.argsort(distances)

        photos: list[ClusterPhoto] = []
        for idx in sorted_order:
            i = int(indices[idx])
            photos.append(ClusterPhoto(
                photo_id=photo_ids[i],
                filename=filenames[i],
                distance_to_centroid=round(float(distances[idx]), 4),
            ))

        clusters.append(ClusterInfo(
            cluster_id=int(label),
            label=f"聚类 {label}",
            size=len(photos),
            coherence_score=coherence,
            photos=photos,
        ))

    # 按簇大小降序排列
    clusters.sort(key=lambda c: c.size, reverse=True)
    return clusters


# ── 公开接口 ──────────────────────────────────────────────────

def run_clustering(
    chroma: chroma_client.ChromaPhotoStore,
    min_cluster_size: int = 5,
    min_samples: int = 3,
    umap_n_neighbors: int = 15,
    umap_min_dist: float = 0.1,
    umap_n_components: int = 5,
    umap_metric: str = "cosine",
    tracer: tracer_mod.Tracer | None = None,
) -> ClusterResult:
    """
    执行一次完整的聚类流程。

    参数:
        chroma: ChromaPhotoStore 实例
        tracer: 可选的结构化追踪器
        其他: 聚类参数（见 backlog 说明）
    """
    t0 = time.time()

    # trace: cluster.run.start
    if tracer:
        tracer.emit("cluster.run.start", {
            "params": {
                "min_cluster_size": min_cluster_size,
                "min_samples": min_samples,
                "umap_n_neighbors": umap_n_neighbors,
                "umap_min_dist": umap_min_dist,
                "umap_n_components": umap_n_components,
                "umap_metric": umap_metric,
            },
        }, module="cluster.run")

    # 1. 获取向量
    photo_ids, filenames, matrix = _fetch_photo_vectors(chroma)
    n_total = len(photo_ids)

    # 2. UMAP 降维
    t_umap = time.time()
    reduced = _run_umap(
        matrix,
        n_neighbors=umap_n_neighbors,
        min_dist=umap_min_dist,
        n_components=umap_n_components,
        metric=umap_metric,
    )
    if tracer:
        tracer.emit("umap.reduce", {
            "input_shape": list(matrix.shape),
            "output_shape": list(reduced.shape),
            "duration_ms": int((time.time() - t_umap) * 1000),
        }, module="cluster.umap")

    # 3. HDBSCAN 聚类
    t_hdbscan = time.time()
    labels, _probs = _run_hdbscan(reduced, min_cluster_size, min_samples)
    label_counts: dict[str, int] = {}
    for lb in labels:
        key = str(lb)
        label_counts[key] = label_counts.get(key, 0) + 1
    if tracer:
        tracer.emit("hdbscan.cluster", {
            "duration_ms": int((time.time() - t_hdbscan) * 1000),
            "num_clusters": len(set(labels)) - (1 if -1 in labels else 0),
            "noise_count": int(np.sum(labels == -1)),
            "label_distribution": label_counts,
        }, module="cluster.hdbscan")

    # 4. 计算簇统计
    clusters = _compute_cluster_stats(reduced, labels, photo_ids, filenames)

    noise_count = int(np.sum(labels == -1))
    clustered_count = n_total - noise_count

    stats = ClusterStats(
        total_photos=n_total,
        clustered_photos=clustered_count,
        noise_photos=noise_count,
        num_clusters=len(clusters),
        duration_seconds=round(time.time() - t0, 1),
    )

    result = ClusterResult(
        id=uuid.uuid4().hex[:12],
        created_at=datetime.datetime.now().isoformat(),
        params={
            "min_cluster_size": min_cluster_size,
            "min_samples": min_samples,
            "umap_n_neighbors": umap_n_neighbors,
            "umap_min_dist": umap_min_dist,
            "umap_n_components": umap_n_components,
            "umap_metric": umap_metric,
        },
        stats=stats,
        clusters=clusters,
    )

    # trace: cluster.save + cluster.run.end
    if tracer:
        tracer.emit("cluster.save", {
            "result_id": result.id,
            "num_clusters": stats.num_clusters,
        }, module="cluster.save")
        tracer.emit("cluster.run.end", {
            "result_id": result.id,
            "total_photos": stats.total_photos,
            "clustered_photos": stats.clustered_photos,
            "noise_photos": stats.noise_photos,
            "num_clusters": stats.num_clusters,
            "duration_ms": int((time.time() - t0) * 1000),
        }, module="cluster.run")

    logger.info(
        "聚类完成: %d 张照片 → %d 个簇, %d 噪声, 耗时 %.1fs",
        n_total, stats.num_clusters, stats.noise_photos, stats.duration_seconds,
    )
    return result


# ── 主题标签生成 ──────────────────────────────────────────────

_MAX_REPRESENTATIVE_PHOTOS = 8

_THEME_SYSTEM_PROMPT = (
    "你是一位摄影主题策划专家。用户会提供一组照片聚类中代表性照片的信息，"
    "你需要为这组照片生成一个主题标签和一句话描述。\n\n"
    "规则：\n"
    "- 主题标签 6-12 个字，精炼有记忆点（如\"云南雪山系列\"\"城市蓝调时刻\"\"逆光人像合集\"）\n"
    "- 一句话描述 15-30 字，概括这组照片的核心特征和视觉风格\n"
    "- 优先从「描述」字段理解照片的视觉内容和主题，结构化属性（主体/场景/色调/光线/情绪）作为辅助索引\n\n"
    "你必须严格返回一行合法 JSON，不得包含任何其他文字、注释或 markdown 标记。\n"
    '输出格式：{"label":"主题标签","description":"一句话描述"}'
)

_PHOTO_INFO_TEMPLATE = (
    "- {filename}\n"
    "  描述: {description}\n"
    "  属性: 主体={objects} 场景={scene} 色调={colors} 光线={lighting} 情绪={mood}"
)


def _fetch_photo_descriptions(
    go_backend_url: str, photo_ids: list[str]
) -> dict[str, dict]:
    """从 Go 后端批量获取照片描述和结构化属性。"""
    import utils.http_client as http_utils

    result: dict[str, dict] = {}
    if not photo_ids:
        return result

    photo_id_set = set(photo_ids)
    client = http_utils.create_client(timeout=30.0)
    try:
        page = 1
        while True:
            resp = client.get(
                f"{go_backend_url}/api/v1/photos",
                params={"page": page, "page_size": 500},
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items", data if isinstance(data, list) else [])
            if not items:
                break
            for p in items:
                pid = p.get("id", "")
                if pid in photo_id_set:
                    result[pid] = {
                        "filename": p.get("filename", pid),
                        "objects": p.get("objects", "") or "",
                        "scene": p.get("scene", "") or "",
                        "colors": p.get("colors", "") or "",
                        "lighting": p.get("lighting", "") or "",
                        "mood": p.get("mood", "") or "",
                        "description": (p.get("description", "") or "")[:200],
                    }
            page += 1
    finally:
        client.close()

    return result


def _build_photo_info_text(photo: dict) -> str:
    """将单张照片的结构化属性和描述格式化为 LLM 可读的文本块。"""
    desc = (photo.get("description") or "").strip()
    if not desc:
        desc = "无描述"

    return _PHOTO_INFO_TEMPLATE.format(
        filename=photo.get("filename", "未知"),
        description=desc,
        objects=photo.get("objects") or "未识别",
        scene=photo.get("scene") or "未识别",
        colors=photo.get("colors") or "未识别",
        lighting=photo.get("lighting") or "未识别",
        mood=photo.get("mood") or "未识别",
    )


def _parse_llm_theme_response(raw: str) -> tuple[str, str]:
    """从 LLM 响应中提取 label 和 description。

    优先尝试 JSON 解析；失败时用正则从自由文本中提取。
    返回 (label, description)，提取失败时两者均为空字符串。
    """
    import re

    raw = raw.strip()

    # 1. 尝试纯 JSON 解析
    for attempt in (raw,):
        # 去掉可能的 markdown 代码块包裹
        cleaned = attempt
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.startswith("```")]
            cleaned = "\n".join(lines).strip()
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict) and parsed.get("label"):
                return parsed["label"].strip(), parsed.get("description", "").strip()
        except (json.JSONDecodeError, TypeError, KeyError):
            pass

    # 2. Fallback: 从自由文本提取
    # 尝试匹配 {"label":"...","description":"..."} 子串
    m = re.search(r'\{\s*"label"\s*:\s*"([^"]+)"\s*,\s*"description"\s*:\s*"([^"]+)"\s*\}', raw)
    if m:
        return m.group(1).strip(), m.group(2).strip()

    # 3. Fallback: 匹配 "主题标签：xxx" / "标签：xxx" 等中文模式
    label = ""
    desc = ""
    for pattern in [r'主题标签[：:]\s*(.+?)(?:\n|$)', r'标签[：:]\s*(.+?)(?:\n|$)', r'\*\*主题标签[：:]*\*\*\s*(.+?)(?:\n|$)']:
        m = re.search(pattern, raw)
        if m:
            label = m.group(1).strip().lstrip("#").strip()
            break

    for pattern in [r'描述[：:]\s*(.+?)(?:\n|$)', r'\*\*描述[：:]*\*\*\s*(.+?)(?:\n|$)']:
        m = re.search(pattern, raw)
        if m:
            desc = m.group(1).strip()
            break

    # 清理 label 中的 markdown 和多余符号
    label = re.sub(r'[#*_]', '', label).strip()
    # 如果 label 太长（可能是多标签拼接），只取第一个
    if label and len(label) > 16:
        # 尝试按空格或标点拆开取第一部分
        parts = re.split(r'[，,、\s#]', label)
        label = parts[0].strip()

    return label, desc


def generate_cluster_theme(
    cfg,
    result: ClusterResult,
    cluster_id: int,
    go_backend_url: str,
    cluster_dir: pathlib.Path,
    tracer: tracer_mod.Tracer | None = None,
) -> ClusterResult:
    """为聚类结果中指定簇生成主题标签和描述。

    通过 LLM 分析该簇的代表性照片，生成有意义的主题标签
    （如"云南雪山系列"）和一句话描述。结果持久化到 JSON 文件。

    参数:
        cfg: 配置对象（需含 LLM 配置）
        result: 聚类结果
        cluster_id: 要生成主题的簇 ID（ClusterInfo.cluster_id）
        go_backend_url: Go 后端地址
        tracer: 可选的结构化追踪器

    返回:
        更新后的 ClusterResult（已持久化）
    """
    import langchain_core.messages as lc_messages
    import utils.llm_factory as llm_factory

    # 找到目标簇
    target: ClusterInfo | None = None
    for c in result.clusters:
        if c.cluster_id == cluster_id:
            target = c
            break
    if target is None:
        raise ValueError(f"簇 {cluster_id} 不存在")

    # trace: cluster.theme.start
    if tracer:
        rep_ids = [p.photo_id for p in target.photos[:_MAX_REPRESENTATIVE_PHOTOS]]
        tracer.emit("cluster.theme.start", {
            "cluster_id": cluster_id,
            "cluster_size": target.size,
            "representative_photo_ids": rep_ids,
        }, module="cluster.generate_theme")

    t_theme_start = time.time()
    llm = llm_factory.create_llm(cfg, temperature=0.7)

    # 1. 获取代表照片的描述
    reps = target.photos[:_MAX_REPRESENTATIVE_PHOTOS]
    rep_ids = [p.photo_id for p in reps]
    photo_map = _fetch_photo_descriptions(go_backend_url, rep_ids)
    logger.info("簇 %d: 获取了 %d/%d 张照片的描述", cluster_id, len(photo_map), len(rep_ids))

    # 2. 构建照片信息文本
    lines: list[str] = []
    for p in reps:
        info = photo_map.get(p.photo_id)
        if info:
            lines.append(_build_photo_info_text(info))
        else:
            lines.append(f"- {p.filename}")

    if not lines:
        raise RuntimeError(f"簇 {cluster_id} 无可用照片信息")

    photo_text = "\n".join(lines)

    # 3. 调用 LLM（使用 SystemMessage + HumanMessage 分离指令和输入）
    messages = [
        lc_messages.SystemMessage(content=_THEME_SYSTEM_PROMPT),
        lc_messages.HumanMessage(
            content=f"以下是一个照片聚类中 {len(lines)} 张代表性照片的信息，"
            f"请为这组照片生成主题标签和描述：\n\n{photo_text}"
        ),
    ]

    # trace: llm.call.start
    if tracer:
        prompt_text = _THEME_SYSTEM_PROMPT + "\n\n" + messages[1].content
        payload_ref = tracer.save_payload(f"llm-req-cluster-{cluster_id}.txt", prompt_text)
        tracer.emit("llm.call.start", {
            "cluster_id": cluster_id,
            "model": cfg.llm_model,
            "temperature": 0.7,
            "prompt_chars": len(prompt_text),
            "payload_ref": payload_ref,
        }, module="cluster.generate_theme")

    t_llm = time.time()
    resp = llm.invoke(messages)
    raw = resp.content if hasattr(resp, "content") else str(resp)
    llm_duration_ms = int((time.time() - t_llm) * 1000)

    # trace: llm.call.end + parse.theme
    token_usage = {}
    if hasattr(resp, "response_metadata"):
        usage = resp.response_metadata.get("token_usage", {})
        token_usage = {
            "prompt": usage.get("prompt_tokens", 0),
            "completion": usage.get("completion_tokens", 0),
        }
    if tracer:
        resp_ref = tracer.save_payload(f"llm-resp-cluster-{cluster_id}.txt", raw)
        tracer.emit("llm.call.end", {
            "cluster_id": cluster_id,
            "duration_ms": llm_duration_ms,
            "token_usage": token_usage,
            "response_chars": len(raw),
            "payload_ref": resp_ref,
        }, module="cluster.generate_theme")

    label, desc = _parse_llm_theme_response(raw)

    # trace: parse.theme
    parse_path = "json_direct"
    if not label:
        # 判断走到了哪个 fallback（简化判定：以 raw 内容特征区分）
        parse_path = "failed"
    elif label and desc:
        parse_path = "json_direct"  # 简化：实际路径可能为 json_direct/regex_extract/fallback
    if tracer:
        tracer.emit("parse.theme", {
            "cluster_id": cluster_id,
            "label": label,
            "description": desc,
            "parse_path": parse_path,
            "raw_preview": raw[:200],
        }, module="cluster.generate_theme")

    if not label:
        raise RuntimeError(
            f"簇 {cluster_id} LLM 未返回有效主题标签（raw={raw[:200]}）"
        )

    target.label = label
    target.theme_description = desc
    logger.info("簇 %d 主题: %s — %s", cluster_id, label, desc)

    # 4. 持久化
    save_result(result, cluster_dir)
    logger.info("主题标签已保存到 %s/%s.json", cluster_dir, result.id)

    # trace: cluster.theme.end
    if tracer:
        tracer.emit("cluster.theme.end", {
            "cluster_id": cluster_id,
            "label": label,
            "description": desc,
            "duration_ms": int((time.time() - t_theme_start) * 1000),
        }, module="cluster.generate_theme")

    return result


# ── 结果文件读写 ──────────────────────────────────────────────

def _result_to_dict(r: ClusterResult) -> dict:
    """将 ClusterResult 转为可 JSON 序列化的 dict。"""
    return {
        "id": r.id,
        "created_at": r.created_at,
        "params": r.params,
        "stats": dataclasses.asdict(r.stats),
        "clusters": [
            {
                "cluster_id": c.cluster_id,
                "label": c.label,
                "theme_description": c.theme_description,
                "size": c.size,
                "coherence_score": c.coherence_score,
                "photos": [dataclasses.asdict(p) for p in c.photos],
            }
            for c in r.clusters
        ],
    }


def _dict_to_result(d: dict) -> ClusterResult:
    """从 dict 还原 ClusterResult（不含 clusters 详情时 clusters 为空）。"""
    stats_raw = d.get("stats", {})
    return ClusterResult(
        id=d["id"],
        created_at=d["created_at"],
        params=d.get("params", {}),
        stats=ClusterStats(**stats_raw),
        clusters=[
            ClusterInfo(
                cluster_id=c["cluster_id"],
                label=c.get("label", f"聚类 {c['cluster_id']}"),
                theme_description=c.get("theme_description", ""),
                size=c["size"],
                coherence_score=c.get("coherence_score", 0.0),
                photos=[ClusterPhoto(**p) for p in c.get("photos", [])],
            )
            for c in d.get("clusters", [])
        ],
    )


def save_result(result: ClusterResult, cluster_dir: pathlib.Path) -> None:
    """将聚类结果保存为 JSON 文件。"""
    _ensure_cluster_dir(cluster_dir)
    d = _result_to_dict(result)
    fp = cluster_dir / f"{result.id}.json"
    fp.write_text(json.dumps(d, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def load_result(result_id: str, cluster_dir: pathlib.Path) -> ClusterResult | None:
    """加载单个聚类结果。"""
    fp = cluster_dir / f"{result_id}.json"
    if not fp.exists():
        return None
    return _dict_to_result(json.loads(fp.read_text(encoding="utf-8")))


def list_results(cluster_dir: pathlib.Path) -> list[dict]:
    """
    列出所有聚类结果（摘要，不含 clusters 详情）。
    按创建时间倒序。
    """
    results: list[dict] = []
    if not cluster_dir.exists():
        return results
    for fp in sorted(cluster_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            d = json.loads(fp.read_text(encoding="utf-8"))
            # 返回摘要（去掉 clusters 里的 photos 以减少传输量）
            summary = {
                "id": d["id"],
                "created_at": d["created_at"],
                "params": d.get("params", {}),
                "stats": d.get("stats", {}),
                "cluster_labels": [
                    {"cluster_id": c["cluster_id"], "label": c.get("label", ""), "size": c["size"]}
                    for c in d.get("clusters", [])
                ],
            }
            results.append(summary)
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("跳过损坏的聚类结果文件 %s: %s", fp.name, e)
    return results


def delete_result(result_id: str, cluster_dir: pathlib.Path) -> bool:
    """删除一个聚类结果文件。返回 True 表示成功删除。"""
    fp = cluster_dir / f"{result_id}.json"
    if not fp.exists():
        return False
    fp.unlink()
    return True
