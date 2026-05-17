"""
    RAG 检索评估：Precision@K / Recall@K / MRR。

    用法:
        from chain.evaluation import run_evaluation
        result = run_evaluation(cfg, test_queries=[...], k=5)

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

import config
import embedding.embedder as embedder
import vectorstore.chroma_client as chroma_client
import chain.photo_rag as photo_rag


# 黄金评估集模板 — 你需要手动标注 relevant_photos
# 初次运行时保持 relevant_photos 为空，根据检索结果挑出正确项填入
DEFAULT_EVAL_QUERIES: list[dict] = [
    {"question": "有猫咪的照片吗？", "relevant_photos": []},
    {"question": "日落时分的风景照", "relevant_photos": []},
    {"question": "我有哪些用 Nikon 拍的照片？", "relevant_photos": []},
    {"question": "红墙前的照片", "relevant_photos": []},
    {"question": "湖边的照片", "relevant_photos": []},
    {"question": "夜景照片", "relevant_photos": []},
    {"question": "有人物的照片", "relevant_photos": []},
    {"question": "花卉的照片", "relevant_photos": []},
    {"question": "有建筑的照片", "relevant_photos": []},
    {"question": "黑白照片", "relevant_photos": []},
]


def precision_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    if k <= 0 or not retrieved_ids[:k]:
        return 0.0
    hits = sum(1 for pid in retrieved_ids[:k] if pid in relevant_ids)
    return hits / k


def recall_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    if not relevant_ids:
        return 1.0
    if k <= 0:
        return 0.0
    hits = sum(1 for pid in retrieved_ids[:k] if pid in relevant_ids)
    return hits / len(relevant_ids)


def mrr(retrieved_ids: list[str], relevant_ids: set[str]) -> float:
    if not relevant_ids:
        return 1.0
    for i, pid in enumerate(retrieved_ids, 1):
        if pid in relevant_ids:
            return 1.0 / i
    return 0.0


def run_evaluation(
    cfg: config.Config,
    test_queries: list[dict] | None = None,
    k: int = 5,
    verbose: bool = True,
) -> dict:
    """运行 RAG 检索评估，返回 Precision@K / Recall@K / MRR 等指标。

    参数:
        cfg:          配置对象
        test_queries: 测试查询列表 [{"question": ..., "relevant_photos": [...]}, ...]
        k:            计算 Precision/Recall 时的 K 值
        verbose:      是否打印每条评估详情

    返回:
        {"precision@k": ..., "recall@k": ..., "mrr": ..., "total": ..., "details": [...]}
    """
    queries = test_queries or DEFAULT_EVAL_QUERIES
    if not queries:
        raise ValueError("未提供测试查询，且无内置评估集")

    emb = embedder.Embedder(
        base_url=cfg.go_backend_url,
        model=cfg.embedding_model,
    )
    store = chroma_client.ChromaPhotoStore(
        persist_dir=str(cfg.resolve_path("./data/chroma")),
        collection_name="photos",
    )

    precisions: list[float] = []
    recalls: list[float] = []
    mrrs: list[float] = []
    details: list[dict] = []

    for i, q in enumerate(queries):
        question = q["question"]
        relevant_ids = set(q.get("relevant_photos", []))

        try:
            vectors = emb.embed_texts([question])
            results = store.query(
                query_embeddings=[vectors[0].tolist()],
                n_results=k * 3,
            )
            aggregated = photo_rag._aggregate_by_photo(results, top_n=k)
            retrieved_ids = [
                (r.get("metadata") or {}).get("photo_id", "")
                for r in aggregated
            ]
            retrieved_ids = [pid for pid in retrieved_ids if pid]
        except Exception as exc:
            if verbose:
                print(f"[{i+1}/{len(queries)}] err 检索失败: {question[:40]}... — {exc}")
            details.append({
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

        p = precision_at_k(retrieved_ids, relevant_ids, k)
        r = recall_at_k(retrieved_ids, relevant_ids, k)
        m = mrr(retrieved_ids, relevant_ids)

        precisions.append(p)
        recalls.append(r)
        mrrs.append(m)
        details.append({
            "question": question,
            "relevant_ids": sorted(relevant_ids),
            "retrieved_ids": retrieved_ids,
            "precision": p,
            "recall": r,
            "mrr": m,
        })

        if verbose:
            rel_str = f"相关={sorted(relevant_ids)}" if relevant_ids else "相关=未标注"
            print(f"[{i+1}/{len(queries)}] P@{k}={p:.2f} R@{k}={r:.2f} MRR={m:.2f} "
                  f"| {question[:50]}... ({rel_str})")

    total = len(queries)
    result = {
        "precision@k": sum(precisions) / total if total else 0.0,
        "recall@k": sum(recalls) / total if total else 0.0,
        "mrr": sum(mrrs) / total if total else 0.0,
        "total": total,
        "k": k,
        "details": details,
    }

    if verbose:
        print()
        print(f"评估结果（共 {total} 条）:")
        print(f"   Precision@{k}: {result['precision@k']:.4f}")
        print(f"   Recall@{k}:    {result['recall@k']:.4f}")
        print(f"   MRR:           {result['mrr']:.4f}")

    return result
