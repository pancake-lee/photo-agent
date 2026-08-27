"""
    RAG 检索评估：Precision@K / Recall@K / MRR。

    用法:
        from chain.evaluation import run_evaluation
        result = run_evaluation(cfg, test_queries=[...], precision_k=10)

    黄金评估集填写指南：
        1. 先运行一次空评估（不填 relevant_photos），看看每条查询检索到哪些 photo_id
        2. 在返回结果中挑出你认为是正确答案的 photo_id，填入 relevant_photos
        3. 建议 20~50 条查询，覆盖不同语义场景（物体/颜色/场景/情感/时间）
        4. 填充后重新运行，得到基线指标
        5. 可切换分块策略对比效果

    正确填写示例：
        {
            "question": "有猫咪的照片吗？",
            "relevant_photos": ["photo_001", "photo_042", "photo_108"],
        },
"""

import datetime
import hashlib
import json
import os
import pathlib
import uuid

import utils.http_client as http_utils

import config
import embedding.embedder as embedder
import vectorstore.chroma_client as chroma_client
import chain.photo_rag as photo_rag

GRANULARITIES = ("photo", "fine", "coarse")


def _normalize_id(photo_id: str) -> str:
    """去除文件扩展名，兼容用户标注时只写文件名不写后缀的场景。"""
    if not photo_id:
        return ""
    return os.path.splitext(photo_id)[0]


def _build_id_to_filename(go_backend_url: str) -> dict[str, str]:
    """从 Go 后端获取全部照片，构建 UUID → 文件名(去后缀) 映射。

    ChromaDB 中 photo_id 存的是 Go 后端的 UUID，评估时需要转回文件名
    才能与黄金用例中的 relevant_photos（文件名）匹配。
    """
    mapping: dict[str, str] = {}
    client = http_utils.create_client(timeout=30.0)
    page = 1
    try:
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
                fname = p.get("filename", "")
                if pid and fname:
                    mapping[pid] = _normalize_id(fname)
            page += 1
    finally:
        client.close()
    return mapping


def _build_photo_records(go_backend_url: str) -> dict[str, dict]:
    """读取当前图库，用于评估时的实时资产准入和证据快照。"""
    records: dict[str, dict] = {}
    client = http_utils.create_client(timeout=30.0)
    page = 1
    try:
        while True:
            resp = client.get(f"{go_backend_url}/api/v1/photos", params={"page": page, "page_size": 500})
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items", data if isinstance(data, list) else [])
            if not items:
                break
            for photo in items:
                if photo.get("id"):
                    records[photo["id"]] = photo
            page += 1
    finally:
        client.close()
    return records


def _photo_is_healthy(photo: dict, version_map: dict[str, set[str]]) -> tuple[bool, dict]:
    """按当前描述和 Chroma 版本生成可解释的资产健康结论。"""
    photo_id = photo.get("id", "")
    description = photo.get("description") or ""
    vlm_status = photo.get("vlmStatus") or photo.get("vlm_status") or "pending"
    current_version = hashlib.sha256(description.encode("utf-8")).hexdigest() if description else ""
    vector_versions = version_map.get(photo_id, set())
    vector_current = bool(current_version) and (current_version in vector_versions or "" in vector_versions)
    healthy = vlm_status == "healthy" and vector_current
    if vlm_status != "healthy":
        reason = photo.get("vlmReason") or photo.get("vlm_reason") or "AI 描述不可用"
    elif not vector_current:
        reason = "当前描述没有一致的 Embedding"
    else:
        reason = ""
    return healthy, {
        "photo_id": photo_id, "filename": _normalize_id(photo.get("filename", "")),
        "vlm_status": vlm_status, "description_version": current_version,
        "vector_versions": sorted(vector_versions), "healthy": healthy, "reason": reason,
    }


def _build_asset_health(queries: list[dict], photo_records: dict[str, dict], version_map: dict[str, set[str]]) -> tuple[dict[str, dict], dict]:
    """返回每条黄金用例的期望资产快照和全局健康汇总。"""
    filename_to_photo = {_normalize_id(photo.get("filename", "")): photo for photo in photo_records.values()}
    by_golden_id: dict[str, dict] = {}
    summary = {"total": 0, "healthy": 0, "unhealthy": 0, "missing": 0}
    for query in queries:
        assets: list[dict] = []
        for ref in query.get("relevant_photos", []):
            ref_id = ref.get("photo_id", "") if isinstance(ref, dict) else ref
            photo = filename_to_photo.get(_normalize_id(ref_id))
            if photo is None:
                asset = {"photo_id": _normalize_id(ref_id), "filename": _normalize_id(ref_id), "healthy": False, "reason": "期望照片不在当前图库", "vlm_status": "missing", "description_version": "", "vector_versions": []}
                summary["missing"] += 1
            else:
                _, asset = _photo_is_healthy(photo, version_map)
            summary["total"] += 1
            if asset["healthy"]:
                summary["healthy"] += 1
            else:
                summary["unhealthy"] += 1
            assets.append(asset)
        by_golden_id[query.get("id", "")] = {"trusted": all(asset["healthy"] for asset in assets), "assets": assets}
    return by_golden_id, summary


def save_evaluation_snapshot(cfg: config.Config, result: dict) -> pathlib.Path:
    """持久化每次黄金评估，便于直接比较修复前后的数据和检索证据。"""
    directory = cfg.resolve_path("./data/eval_reports/golden")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{result['generated_at'][:10]}-{result['report_id']}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _load_golden_queries_from_items(items: list[dict]) -> list[dict]:
    """将 JSON 黄金用例转换为评估输入，并兼容旧格式。"""
    # 适配 JSON 字段名 → evaluation 期望的字段名
    # relevant_photos 可能是新格式 [{photo_id, filename}] 或旧格式 [str]
    result = []
    for it in items:
        raw = it.get("relevant_photos", it.get("relevant_photo_ids", []))
        refs = []
        for photo in raw:
            if isinstance(photo, dict):
                # 黄金用例只记录单张照片；旧数据中的粒度字段忽略，统一按 photo 集合评估。
                refs.append({
                    "photo_id": _normalize_id(photo.get("photo_id", "")),
                    "granularity": "photo",
                })
            else:
                refs.append({"photo_id": _normalize_id(photo), "granularity": "photo"})
        result.append({
            "id": it.get("id", ""),
            "question": it.get("query_text", ""),
            "relevant_photos": refs,
        })
    return result


def _load_golden_queries(cfg: config.Config) -> list[dict]:
    """从 agent/data/golden_queries.json 加载黄金用例。"""
    json_path = cfg.resolve_path("./data/golden_queries.json")
    if not json_path.exists():
        return []
    try:
        items = json.loads(json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return _load_golden_queries_from_items(items) if items else []


def _match_ids(
    retrieved_ids: list[str], relevant_ids: set[str], k: int
) -> tuple[list[str], list[str], list[str]]:
    """返回 (hits, misses, remaining)，均使用归一化后的 ID。

    hits:      检索结果中命中相关集合的（只看前 K 个）
    misses:    检索结果中未命中的（只看前 K 个）
    remaining: 相关集合中未被检索到的
    """
    norm_relevant = {_normalize_id(pid) for pid in relevant_ids if pid}
    top_k = [_normalize_id(pid) for pid in retrieved_ids[:k] if pid]

    hits = [pid for pid in top_k if pid in norm_relevant]
    misses = [pid for pid in top_k if pid not in norm_relevant]
    remaining = sorted(norm_relevant - {pid for pid in top_k})

    return hits, misses, remaining




def precision_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    if k <= 0 or not retrieved_ids[:k]:
        return 0.0
    norm_relevant = {_normalize_id(pid) for pid in relevant_ids if pid}
    hits = sum(1 for pid in retrieved_ids[:k] if _normalize_id(pid) in norm_relevant)
    return hits / k


def recall_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    if not relevant_ids:
        return 1.0
    if k <= 0:
        return 0.0
    norm_relevant = {_normalize_id(pid) for pid in relevant_ids if pid}
    hits = sum(1 for pid in retrieved_ids[:k] if _normalize_id(pid) in norm_relevant)
    return hits / len(norm_relevant)


def mrr(retrieved_ids: list[str], relevant_ids: set[str]) -> float:
    if not relevant_ids:
        return 1.0
    norm_relevant = {_normalize_id(pid) for pid in relevant_ids if pid}
    for i, pid in enumerate(retrieved_ids, 1):
        if _normalize_id(pid) in norm_relevant:
            return 1.0 / i
    return 0.0


def run_evaluation(
    cfg: config.Config,
    test_queries: list[dict] | None = None,
    precision_k: int = 10,
    verbose: bool = True,
    tracker=None,
) -> dict:
    """运行 RAG 检索评估，返回 Precision@K / Recall@K / MRR 等指标。

    Precision 使用固定 K=precision_k，Recall 按每条查询的标注总量动态计算。
    tracker 为可选 TokenTracker，用于持久化 embedding token 用量。
    """
    queries = test_queries or _load_golden_queries(cfg)
    if not queries:
        raise ValueError("未提供测试查询，且无内置评估集")

    emb = embedder.Embedder(
        base_url=cfg.go_backend_url,
        model=cfg.embedding_model,
        tracker=tracker,
    )
    stores = {
        "photo": chroma_client.ChromaPhotoStore(
            persist_dir=str(cfg.resolve_path("./data/chroma")),
            collection_name=photo_rag.GRANULARITY_COLLECTIONS["photo"],
        ),
    }

    # 构建 UUID ↔ 文件名双向映射，并在同一份图库快照上判断资产健康。
    photo_records = _build_photo_records(cfg.go_backend_url)
    id_to_file = {photo_id: _normalize_id(photo.get("filename", "")) for photo_id, photo in photo_records.items()}
    file_to_id: dict[str, str] = {}
    for uid, fname in id_to_file.items():
        # 多个 UUID 可能映射到同一文件名（chunk 分块），取第一个即可
        file_to_id.setdefault(fname, uid)
    version_map = stores["photo"].get_photo_embedding_versions()
    asset_health_by_golden, asset_health_summary = _build_asset_health(queries, photo_records, version_map)
    if verbose:
        print(f"已加载 {len(id_to_file)} 条 UUID→文件名 映射")

    precisions: list[float] = []
    recalls: list[float] = []
    mrrs: list[float] = []
    details: list[dict] = []

    for i, q in enumerate(queries):
        question = q["question"]
        raw_relevant = q.get("relevant_photos", [])
        relevant_by_granularity: dict[str, set[str]] = {"photo": set()}
        for ref in raw_relevant:
            if isinstance(ref, dict):
                photo_id = ref.get("photo_id", "")
            else:
                photo_id = ref
            if photo_id:
                relevant_by_granularity["photo"].add(_normalize_id(photo_id))
        relevant_ids = set().union(*relevant_by_granularity.values())
        recall_k = len(relevant_ids)
        fetch_k = max(precision_k, recall_k, 10)

        try:
            vectors = emb.embed_texts([question])
            aggregated = []
            for granularity, granularity_relevant in relevant_by_granularity.items():
                # 没有该粒度标注时不把另一个 Collection 的结果混入指标。
                if not granularity_relevant:
                    continue
                results = stores[granularity].query(
                    query_embeddings=[vectors[0].tolist()],
                    n_results=fetch_k * 3,
                )
                aggregated.extend(
                    photo_rag._aggregate_by_photo(results, top_n=fetch_k)
                )
            aggregated = [
                item for item in aggregated
                if (item.get("metadata") or {}).get("photo_id") in photo_records
                and _photo_is_healthy(photo_records[(item.get("metadata") or {}).get("photo_id")], version_map)[0]
            ]
            aggregated.sort(key=lambda item: item.get("distance", float("inf")))
            retrieved_ids = [
                (r.get("metadata") or {}).get("photo_id", "") for r in aggregated
            ]
            retrieved_ids = [pid for pid in retrieved_ids if pid]

            # 保留原始 UUID 用于构建图片 URL
            retrieved_uuids = list(retrieved_ids)

            # 将 UUID 转为文件名（去后缀）用于匹配
            retrieved_ids = [_normalize_id(id_to_file.get(pid, pid)) for pid in retrieved_ids]

            # debug: 打印 ID 匹配详情
            if verbose:
                norm_rel = sorted({_normalize_id(pid) for pid in relevant_ids if pid})
                norm_ret = [_normalize_id(pid) for pid in retrieved_ids[:10]]
                print(f"  [DEBUG] relevant({len(norm_rel)})[:5]: {norm_rel[:5]}")
                print(f"  [DEBUG] retrieved({len(norm_ret)})[:5]: {norm_ret[:5]}")
                common = set(norm_rel) & set(norm_ret)
                print(f"  [DEBUG] 交集={len(common)}: {sorted(common)[:5]}")
        except Exception as exc:
            if verbose:
                print(f"[{i+1}/{len(queries)}] err 检索失败: {question[:40]}... — {exc}")
            details.append({
                "golden_id": q.get("id", ""),
                "question": question,
                "error": str(exc),
                "precision": 0.0,
                "recall": 0.0,
                "mrr": 0.0,
            })
            precisions.append(0.0)
            recalls.append(0.0)
            mrrs.append(0.0)
            continue

        # 当标注的相关照片数 < precision_k 时，用相关数作为有效的 K
        effective_k = min(precision_k, recall_k) if recall_k > 0 else precision_k
        p = precision_at_k(retrieved_ids, relevant_ids, effective_k)
        r = recall_at_k(retrieved_ids, relevant_ids, recall_k)
        m = mrr(retrieved_ids, relevant_ids)
        hits, misses, remaining = _match_ids(retrieved_ids, relevant_ids, recall_k)

        precisions.append(p)
        recalls.append(r)
        mrrs.append(m)
        # 将 photo_id 列表转为 {filename, uuid} 格式供前端展示
        def _to_photo_list(ids: list[str]) -> list[dict]:
            result = []
            for pid in ids:
                uid = file_to_id.get(pid, "")
                result.append({"photo_id": pid, "filename": pid, "uuid": uid})
            return result

        details.append({
            "golden_id": q.get("id", ""),
            "question": question,
            "relevant_ids": sorted(relevant_ids),
            "retrieved_ids": retrieved_ids,
            "hit_ids": _to_photo_list(hits),
            "miss_ids": _to_photo_list(misses),
            "remaining_ids": _to_photo_list(remaining),
            "hits": hits,
            "misses": misses,
            "remaining": remaining,
            "precision": p,
            "recall": r,
            "mrr": m,
            "effective_k": effective_k,
            "asset_health": asset_health_by_golden.get(q.get("id", ""), {}),
        })

        if verbose:
            print(f"[{i+1}/{len(queries)}] P@{effective_k}={p:.2f} R@{recall_k}={r:.2f} MRR={m:.2f} "
                  f"| {question[:50]}")
            print(f"  命中({len(hits)}): {hits}")
            print(f"  未命中({len(misses)}): {misses}")
            print(f"  遗漏({len(remaining)}): {remaining}")

    total = len(queries)
    result = {
        "report_id": uuid.uuid4().hex[:12],
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "precision@k": sum(precisions) / total if total else 0.0,
        "recall@k": sum(recalls) / total if total else 0.0,
        "mrr": sum(mrrs) / total if total else 0.0,
        "total": total,
        "precision_k": precision_k,
        "details": details,
        "asset_health": asset_health_summary,
        "data_trusted": asset_health_summary["unhealthy"] == 0,
    }

    if verbose:
        print()
        print(f"评估结果（共 {total} 条）:")
        print(f"   Precision@{precision_k}: {result['precision@k']:.4f}")
        print(f"   Recall(动态):           {result['recall@k']:.4f}")
        print(f"   MRR:                    {result['mrr']:.4f}")
        print(f"   Embedding Tokens:       {emb.total_tokens}")

    return result
