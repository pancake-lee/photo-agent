"""
    检索类能力：sql_search / rag_search / hybrid_search。

    能力自身代码不直接调用 LLM：sql/hybrid 的自然语言转 SQL 封装在
    text_to_sql 模块内部，rag 是纯向量检索；三者都输出 OBS_PHOTO_IDS，
    候选最终由归约层限制在权威范围内。
"""

import logging

import internal.chat.photo_rag as photo_rag
import internal.chat.text_to_sql as text_to_sql
import internal.runtime.capabilities.common as common
import internal.runtime.registry as rt_registry
import internal.runtime.state as rt_state

logger = logging.getLogger(__name__)

# 三个检索能力共享的决策规则：硬约束已由权威范围物化，query 只写软提示
_SEARCH_DECIDE_HINT = (
    "权威范围（时间线/天数/时段等硬约束）已由程序物化并自动生效，"
    "检索 query 只写软提示（地点、景物、氛围等排序偏好），"
    "不要把时间线名、第一天、傍晚等硬约束或已确认事实写进 query"
)


def _search_progress_details(params: dict) -> dict:
    """过程面板受控细节：只暴露检索条件，不暴露内部 SQL 参数。"""
    return {"查询条件": str(params["query"])} if params.get("query") else {}


# --------------------------------------------------
# sql_search — 查询照片（结构化条件检索）
# --------------------------------------------------

@common.capability_run
def _sql_search(params: dict, ctx: rt_registry.RunContext) -> rt_state.Observation:
    """结构化条件检索：生成过滤 SQL → Go 执行 → 候选照片 ID。"""
    query = str(params.get("query") or "")
    sql = text_to_sql.generate_filter_sql(ctx.cfg, query)
    ids = text_to_sql.execute_sql_for_ids(ctx.cfg.go_backend_url, sql)
    logger.info("[runtime] sql_search 返回 %d 个候选 | SQL: %s", len(ids), sql)
    return rt_state.Observation(
        rt_state.OBS_PHOTO_IDS,
        f"结构化检索（SQL）返回 {len(ids)} 个候选照片",
        {"ids": ids, "source": "sql", "sql": sql},
    )


SQL_SEARCH = rt_registry.Capability(
    name="sql_search",
    title="查询照片",
    description=(
        "按结构化软条件（地点、景物、场景、EXIF 参数）检索照片，返回候选照片 ID 列表。"
        "query 只写软提示（排序偏好），时间线/天数/时段等硬约束已由权威范围限定，"
        "候选会被自动限制在范围内。"
    ),
    parameters={
        "query": {"type": "str", "description": "结构化检索条件描述", "required": True},
    },
    run=_sql_search,
    decide_hint=_SEARCH_DECIDE_HINT,
    progress_details=_search_progress_details,
)

# --------------------------------------------------
# rag_search — 查找相似照片（语义检索，纯向量无 LLM）
# --------------------------------------------------

@common.capability_run
def _rag_search(params: dict, ctx: rt_registry.RunContext) -> rt_state.Observation:
    """语义检索：向量检索 → 候选照片 ID（按相似度排序，归约层负责与权威范围求交集）。"""
    query = str(params.get("query") or "")
    ids = photo_rag.retrieve_photo_ids(
        ctx.cfg, query,
        n_results=20,
        distance_threshold=ctx.cfg.rag_distance_threshold,
        auto_distance_ratio=ctx.cfg.rag_auto_distance_ratio,
        granularity=ctx.granularity,
    )
    if isinstance(ids, tuple):
        ids = ids[0]
    logger.info("[runtime] rag_search 返回 %d 个候选", len(ids))
    return rt_state.Observation(
        rt_state.OBS_PHOTO_IDS,
        f"语义检索（RAG）返回 {len(ids)} 个候选照片",
        {"ids": ids, "source": "rag"},
    )


RAG_SEARCH = rt_registry.Capability(
    name="rag_search",
    title="查找相似照片",
    description=(
        "按画面内容语义（场景、物体、氛围）在权威候选范围内排序照片，返回候选照片 ID 列表。"
        "query 只写软提示。"
    ),
    parameters={
        "query": {"type": "str", "description": "语义检索描述", "required": True},
    },
    run=_rag_search,
    decide_hint=_SEARCH_DECIDE_HINT,
    progress_details=_search_progress_details,
)

# --------------------------------------------------
# hybrid_search — 综合查询照片（结构化 ∩ 语义）
# --------------------------------------------------

@common.capability_run
def _hybrid_search(params: dict, ctx: rt_registry.RunContext) -> rt_state.Observation:
    """混合检索：结构化软条件 ∩ 语义检索，按语义顺序返回交集候选。

    不做"空结果/过宽 → 全库 RAG"的替代：候选最终会被归约层限制在权威范围内，
    交集为空时交由权威范围兜底，软提示检索永远不能清空或替换范围。
    """
    query = str(params.get("query") or "")
    filter_sql = text_to_sql.generate_filter_sql(ctx.cfg, query)
    sql_ids = text_to_sql.execute_sql_for_ids(ctx.cfg.go_backend_url, filter_sql)
    rag_ids = photo_rag.retrieve_photo_ids(
        ctx.cfg, query,
        n_results=20,
        distance_threshold=ctx.cfg.rag_distance_threshold,
        auto_distance_ratio=ctx.cfg.rag_auto_distance_ratio,
        granularity=ctx.granularity,
    )
    if isinstance(rag_ids, tuple):
        rag_ids = rag_ids[0]

    sql_set = set(sql_ids)
    intersection = [pid for pid in rag_ids if pid in sql_set]
    if not intersection:
        return rt_state.Observation(
            rt_state.OBS_PHOTO_IDS,
            f"结构化与语义交集为空（结构化 {len(sql_ids)} ∩ 语义 {len(rag_ids)}），"
            "候选交由权威范围兜底",
            {"ids": [], "source": "hybrid", "sql": filter_sql},
        )
    return rt_state.Observation(
        rt_state.OBS_PHOTO_IDS,
        f"混合检索返回 {len(intersection)} 个候选照片（结构化 {len(sql_ids)} ∩ 语义 {len(rag_ids)}）",
        {"ids": intersection, "source": "hybrid", "sql": filter_sql},
    )


HYBRID_SEARCH = rt_registry.Capability(
    name="hybrid_search",
    title="综合查询照片",
    description=(
        "同时需要结构化软条件与画面语义时使用，返回两者交集的候选照片 ID 列表；"
        "交集为空时候选交由权威范围兜底，不会用全库结果替换范围。"
    ),
    parameters={
        "query": {"type": "str", "description": "组合检索描述", "required": True},
    },
    run=_hybrid_search,
    decide_hint=_SEARCH_DECIDE_HINT,
    progress_details=_search_progress_details,
)

# --------------------------------------------------
