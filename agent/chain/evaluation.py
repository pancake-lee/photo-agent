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

import os

import config
import embedding.embedder as embedder
import vectorstore.chroma_client as chroma_client
import chain.photo_rag as photo_rag


def _normalize_id(photo_id: str) -> str:
    """去除文件扩展名，兼容用户标注时只写文件名不写后缀的场景。"""
    if not photo_id:
        return ""
    return os.path.splitext(photo_id)[0]


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


# 黄金评估集模板 — 你需要手动标注 relevant_photos
# 初次运行时保持 relevant_photos 为空，根据检索结果挑出正确项填入
DEFAULT_EVAL_QUERIES: list[dict] = [
    {"question": "有猫咪的照片吗？", "relevant_photos": [
        "DSC_7391.JPG", "DSC_7386.JPG", "DSC_7385.JPG","DSC_7368","DSC_7355","DSC_0816","DSC_0745","DSC_9768","DSC_9755","DSC_8878","DSC_8876","DSC_8556","DSC_3134","DSC_2874","DSC_2867","DSC_2865","DSC_2858","DSC_2846","DSC_2837","DSC_1621","DSC_1617","DSC_0959","DSC_0928","DSC_0573","DSC_0563","DSC_1589","DSC_9144"
    ]},
    {"question": "日落时分的风景照", "relevant_photos": [
        "DSC_9396","DSC_9406","DSC_9416","DSC_9443","DSC_9467","DSC_9470","DSC_9483","DSC_9486","DSC_9501","DSC_9502","DSC_9540","DSC_5622","DSC_5599","DSC_5585","DSC_5584","DSC_5582","DSC_5580","DSC_5579","DSC_5551","DSC_5549","DSC_5548","DSC_5533","DSC_6141","DSC_7349","DSC_0136","DSC_0114","DSC_0115","DSC_0116","DSC_0118","DSC_0121","DSC_0122","DSC_0123","DSC_0124","DSC_0129","DSC_0131","DSC_0132","DSC_0133","DSC_9533",
    ]},
    {"question": "湖边的照片", "relevant_photos": [
        "DSC_0551","DSC_3122","DSC_3123","DSC_3124","DSC_3126","DSC_3130","DSC_3134","DSC_3170","DSC_7818","DSC_9678","DSC_9687","DSC_9690","DSC_9730","DSC_9738","DSC_0048","DSC_0051","DSC_0054","DSC_0066","DSC_0072","DSC_0079","DSC_0080","DSC_0081","DSC_0082","DSC_0093","DSC_0097","DSC_158","DSC_1148","DSC_1185","DSC_4317","DSC_5400","DSC_5535","DSC_5708","DSC_6084","DSC_6004","DSC_6001","DSC_5970","DSC_5965","DSC_5961","DSC_5959","DSC_5958","DSC_5953","DSC_5940","DSC_5939","DSC_5938","DSC_5933","DSC_5931","DSC_5916","DSC_5900","DSC_5898","DSC_5878","DSC_5857","DSC_5840","DSC_5833","DSC_5804","DSC_5801","DSC_5793","DSC_5790","DSC_5739","DSC_5734","DSC_5730","DSC_5714","DSC_5709","DSC_3298","DSC_3395","DSC_3401","DSC_3404","DSC_3445","DSC_3446","DSC_3449","DSC_3452","DSC_3478","DSC_3567","DSC_3569","DSC_3596","DSC_3616","DSC_3705","DSC_3710","DSC_3711","DSC_3821","DSC_3825","DSC_3831","DSC_3834","DSC_3836","DSC_3907","DSC_3935","DSC_3940","DSC_3942","DSC_3947","DSC_3949","DSC_3971","DSC_3984","DSC_4032","DSC_4038","DSC_4041","DSC_4044","DSC_4046","DSC_4054","DSC_4065","DSC_4083","DSC_4109"
    ]},
    {"question": "夜景照片", "relevant_photos": [
        "DSC_0048","DSC_0051","DSC_0054","DSC_0066","DSC_0072","DSC_0079","DSC_0080","DSC_0081","DSC_0082","DSC_0093","DSC_0097","DSC_4172","DSC_4162","DSC_7850","DSC_2273","DSC_2271","DSC_2190","DSC_6639","DSC_6641","DSC_6643","DSC_6644","DSC_6645","DSC_6646"
    ]},
    {"question": "花卉的照片", "relevant_photos": [
        "DSC_5402","DSC_5217","DSC_4598","DSC_4329","DSC_4396","DSC_4392","DSC_4377","DSC_4371","DSC_4363","DSC_4358","DSC_4355","DSC_4352","DSC_4349","DSC_4344","DSC_4333","DSC_3141","DSC_1435","DSC_1457","DSC_1453","DSC_1450","DSC_1447","DSC_1445","DSC_1442","DSC_1439","DSC_1123","DSC_1125","DSC_1069","DSC_1102","DSC_1095","DSC_1093","DSC_1092","DSC_1087","DSC_1085","DSC_1084","DSC_1083","DSC_1082","DSC_1077","DSC_1070","DSC_1052","DSC_1054","DSC_1482","DSC_1508","DSC_1505","DSC_1499","DSC_1497","DSC_1492","DSC_1491","DSC_1487","DSC_0575","DSC_0469"]},
    {"question": "有雪山的照片", "relevant_photos": [
        "DSC_6775","IMG_3436","DSC_6773","DSC_6764","DSC_6761","DSC_6759","DSC_6743","DSC_6735","DSC_6716","DSC_6714","DSC_6713","DSC_6710","DSC_6708","DSC_6700","DSC_6697","DSC_6692","DSC_6690","DSC_6678","DSC_6674","DSC_6668","DSC_6667","DSC_6663","DSC_6661","DSC_6658","DSC_6655","DSC_6652","DSC_6646","DSC_6645","IMG_3434","DSC_6644","DSC_6643","DSC_6641","DSC_6639","DSC_6613","DSC_6606","DSC_6604","DSC_6603","DSC_6598","DSC_6584","DSC_6537","DSC_6517","DSC_6506"
    ]},
]


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
) -> dict:
    """运行 RAG 检索评估，返回 Precision@K / Recall@K / MRR 等指标。

    Precision 使用固定 K=precision_k，Recall 按每条查询的标注总量动态计算。
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
        recall_k = len(relevant_ids)
        fetch_k = max(precision_k, recall_k, 10)

        try:
            vectors = emb.embed_texts([question])
            results = store.query(
                query_embeddings=[vectors[0].tolist()],
                n_results=fetch_k * 3,
            )
            aggregated = photo_rag._aggregate_by_photo(results, top_n=fetch_k)
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

        p = precision_at_k(retrieved_ids, relevant_ids, precision_k)
        r = recall_at_k(retrieved_ids, relevant_ids, recall_k)
        m = mrr(retrieved_ids, relevant_ids)
        hits, misses, remaining = _match_ids(retrieved_ids, relevant_ids, recall_k)

        precisions.append(p)
        recalls.append(r)
        mrrs.append(m)
        details.append({
            "question": question,
            "relevant_ids": sorted(relevant_ids),
            "retrieved_ids": retrieved_ids,
            "hits": hits,
            "misses": misses,
            "remaining": remaining,
            "precision": p,
            "recall": r,
            "mrr": m,
        })

        if verbose:
            print(f"[{i+1}/{len(queries)}] P@{precision_k}={p:.2f} R@{recall_k}={r:.2f} MRR={m:.2f} "
                  f"| {question[:50]}")
            print(f"  命中({len(hits)}): {hits}")
            print(f"  未命中({len(misses)}): {misses}")
            print(f"  遗漏({len(remaining)}): {remaining}")

    total = len(queries)
    result = {
        "precision@k": sum(precisions) / total if total else 0.0,
        "recall@k": sum(recalls) / total if total else 0.0,
        "mrr": sum(mrrs) / total if total else 0.0,
        "total": total,
        "precision_k": precision_k,
        "details": details,
    }

    if verbose:
        print()
        print(f"评估结果（共 {total} 条）:")
        print(f"   Precision@{precision_k}: {result['precision@k']:.4f}")
        print(f"   Recall(动态):           {result['recall@k']:.4f}")
        print(f"   MRR:                    {result['mrr']:.4f}")

    return result
