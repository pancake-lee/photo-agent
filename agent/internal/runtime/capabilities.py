"""
    Agent Runtime 能力层：把现有检索/工具/创作实现封装为可注册能力。

    分三类:
        - 检索类: sql_search / rag_search / hybrid_search（封装现有实现）
        - 工具类: resolve_trip / fetch_photo_details（Go 后端 OpenAPI 工具）
        - 创作类: select_photos / write_post（临时能力，CQ4 迁移 + 图文工坊复用）

    每个能力返回结构化 Observation（成功 + 数据或引用，失败为 OBS_ERROR），
    参数声明与校验由 registry 承担，能力自身不修改 TaskState。
"""

import functools
import json
import logging
import types
import typing
from concurrent.futures import ThreadPoolExecutor, as_completed

import langchain_core.messages as lc_messages

import internal.chat.photo_rag as photo_rag
import internal.posts.post_studio as post_studio
import internal.chat.text_to_sql as text_to_sql
import internal.runtime.registry as rt_registry
import internal.runtime.state as rt_state
import infra.http_client as http_utils
import infra.llm_factory as llm_factory

logger = logging.getLogger(__name__)

Observation = rt_state.Observation


# ============================================================================
# 迁移自 CQ4 compose 管线的挑选辅助（连拍折叠 / 两级收缩 / 超限令牌）
# ============================================================================

def fetch_photos_batch(cfg, photo_ids: list[str]) -> list[dict]:
    """批量获取照片详情（并行请求 Go 后端，按传入顺序返回）。"""
    if not photo_ids:
        return []

    results: list[dict] = []

    def _fetch(pid: str) -> dict | None:
        try:
            with http_utils.create_client(timeout=5.0) as client:
                resp = client.get(f"{cfg.go_backend_url}/api/v1/photos/{pid}")
                resp.raise_for_status()
                return resp.json()
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_fetch, pid): pid for pid in photo_ids}
        for future in as_completed(futures):
            data = future.result()
            if data:
                results.append(data)

    id_order = {pid: i for i, pid in enumerate(photo_ids)}
    results.sort(key=lambda x: id_order.get(x.get("id", ""), 999))
    return results


def collapse_burst_candidates(photos: list[dict], include_group_members: bool = True) -> list[dict]:
    """按连拍组折叠候选项，优先采用标记的封面。"""
    collapsed: dict[str, dict] = {}
    for photo in photos:
        group_id = photo.get("burst_group_id") or photo.get("burst_group_coarse_id") or ""
        key = f"group:{group_id}" if group_id else f"photo:{photo.get('id', '')}"
        current = collapsed.get(key)
        if current is None or photo.get("is_burst_cover"):
            item = dict(photo)
            item["_group_count"] = current.get("_group_count", 0) if current else 0
            collapsed[key] = item
        collapsed[key]["_group_count"] += 1
    result = list(collapsed.values())
    if not include_group_members:
        for item in result:
            item.pop("_group_count", None)
    return result


def prepare_select_candidates(
    photos: list[dict], group_limit: int, cover_limit: int,
) -> tuple[str, list[dict]]:
    """按两级阈值准备挑选候选：组信息、仅封面或图文工坊兜底。"""
    collapsed = collapse_burst_candidates(photos)
    if len(collapsed) <= group_limit:
        return "groups", collapsed
    if len(collapsed) <= cover_limit:
        return "covers", collapse_burst_candidates(photos, include_group_members=False)
    return "overflow", collapsed


def select_token(photo: dict) -> str:
    """生成图文工坊深链里的照片令牌（带连拍组前缀）。"""
    group_id = photo.get("burst_group_id") or photo.get("burst_group_coarse_id") or ""
    photo_id = photo.get("id", "")
    return f"g:{group_id}:{photo_id}" if group_id else photo_id


# ============================================================================
# 通用辅助
# ============================================================================

def _capability_run(fn: typing.Callable[[dict, rt_registry.RunContext], Observation]):
    """能力执行护栏：异常转为结构化失败观察，不让单次能力失败炸掉整个循环。"""

    @functools.wraps(fn)
    def wrapped(params: dict, ctx: rt_registry.RunContext) -> Observation:
        try:
            return fn(params or {}, ctx)
        except Exception as exc:
            logger.exception("[runtime] 能力 %s 执行失败", fn.__name__)
            return rt_state.Observation(rt_state.OBS_ERROR, f"{fn.__name__} 执行失败: {exc}")

    return wrapped


def extract_json_dict(text: str) -> dict | None:
    """从模型输出中提取首个 JSON 对象，失败返回 None。"""
    text = (text or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _cached_photos(ctx: rt_registry.RunContext, photo_ids: list[str]) -> list[dict]:
    """按 photo_ids 顺序取详情：优先状态缓存，缺失部分批量补拉。"""
    state = ctx.state
    cache: dict[str, dict] = state.artifacts.photo_cache if state is not None else {}
    missing = [pid for pid in photo_ids if pid not in cache]
    fetched = {p.get("id"): p for p in fetch_photos_batch(ctx.cfg, missing)}
    photos = []
    for pid in photo_ids:
        if pid in cache:
            photos.append(cache[pid])
        elif pid in fetched:
            photos.append(fetched[pid])
    return photos


# ============================================================================
# 检索类能力
# ============================================================================

@_capability_run
def _sql_search(params: dict, ctx: rt_registry.RunContext) -> Observation:
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


@_capability_run
def _rag_search(params: dict, ctx: rt_registry.RunContext) -> Observation:
    """语义检索：向量检索 → 候选照片 ID（按相似度排序）。"""
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


@_capability_run
def _hybrid_search(params: dict, ctx: rt_registry.RunContext) -> Observation:
    """混合检索：结构化过滤 ∩ 语义检索，交集为空或过滤过宽时回退语义结果。"""
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

    if not sql_ids or len(sql_ids) > 50:
        logger.info(
            "[runtime] hybrid_search 结构化过滤为空或过宽（%d），回退语义结果", len(sql_ids),
        )
        return rt_state.Observation(
            rt_state.OBS_PHOTO_IDS,
            f"结构化过滤为空或过宽（{len(sql_ids)} 条），采用语义检索的 {len(rag_ids)} 个候选",
            {"ids": rag_ids, "source": "hybrid_fallback_rag", "sql": filter_sql},
        )

    sql_set = set(sql_ids)
    intersection = [pid for pid in rag_ids if pid in sql_set]
    if not intersection:
        return rt_state.Observation(
            rt_state.OBS_PHOTO_IDS,
            f"结构化与语义交集为空，采用语义检索的 {len(rag_ids)} 个候选",
            {"ids": rag_ids, "source": "hybrid_fallback_rag", "sql": filter_sql},
        )
    return rt_state.Observation(
        rt_state.OBS_PHOTO_IDS,
        f"混合检索返回 {len(intersection)} 个候选照片（结构化 {len(sql_ids)} ∩ 语义 {len(rag_ids)}）",
        {"ids": intersection, "source": "hybrid", "sql": filter_sql},
    )


# ============================================================================
# 工具类能力
# ============================================================================

def _fetch_timelines(cfg) -> list[str]:
    """获取照片库时间线列表。"""
    with http_utils.create_client(timeout=5.0) as client:
        resp = client.get(f"{cfg.go_backend_url}/api/v1/timelines")
        resp.raise_for_status()
        timelines = resp.json().get("timelines") or []
    return [str(name) for name in timelines if name]


def _match_timeline_name(candidate: str, timelines: list[str]) -> str:
    """确定性名称匹配：精确 → 去空白等价 → 包含。"""
    candidate = (candidate or "").strip()
    if not candidate:
        return ""
    for name in timelines:
        if name == candidate:
            return name
    compact = candidate.replace(" ", "")
    for name in timelines:
        if name.replace(" ", "") == compact:
            return name
    for name in timelines:
        if candidate in name or name in candidate:
            return name
    return ""


@_capability_run
def _resolve_trip(params: dict, ctx: rt_registry.RunContext) -> Observation:
    """把目标中的旅行/活动名称匹配到照片库时间线，产出事实。"""
    timelines = _fetch_timelines(ctx.cfg)
    if not timelines:
        return rt_state.Observation(
            rt_state.OBS_FACTS, "照片库暂无时间线，无法定位旅行", {"facts": {}},
        )

    hint = str(params.get("hint") or ctx.question or "")
    llm = llm_factory.create_llm(
        ctx.cfg, temperature=0.0, callbacks=ctx.llm_callbacks or None,
    )
    response = llm.invoke([
        lc_messages.SystemMessage(content=(
            "你是照片库检索助手。把用户目标中提到的旅行或活动匹配到时间线列表。\n"
            '只输出 JSON: {"timeline": "匹配的时间线全名"}，无匹配时 timeline 为空串。'
        )),
        lc_messages.HumanMessage(content=f"用户目标: {hint}\n\n时间线列表: {'、'.join(timelines)}"),
    ])
    data = extract_json_dict(str(response.content)) or {}
    matched = _match_timeline_name(str(data.get("timeline") or ""), timelines)
    if not matched:
        return rt_state.Observation(
            rt_state.OBS_FACTS,
            f"未在 {len(timelines)} 条时间线中匹配到目标（模型原始输出: {data.get('timeline')!r}）",
            {"facts": {}},
        )
    logger.info("[runtime] resolve_trip 匹配时间线: %s", matched)
    return rt_state.Observation(
        rt_state.OBS_FACTS,
        f"目标匹配到时间线「{matched}」",
        {"facts": {"timeline": matched}},
    )


@_capability_run
def _fetch_photo_details(params: dict, ctx: rt_registry.RunContext) -> Observation:
    """获取指定照片的详情（文件名、拍摄时间、描述、连拍组）。"""
    ids = [str(pid) for pid in params.get("ids") or []]
    if not ids:
        return rt_state.Observation(rt_state.OBS_ERROR, "未指定要获取详情的照片 ID")
    photos = _cached_photos(ctx, ids)
    return rt_state.Observation(
        rt_state.OBS_PHOTO_DETAILS,
        f"获取 {len(photos)}/{len(ids)} 张照片详情",
        {"photos": photos},
    )


# ============================================================================
# 创作类临时能力
# ============================================================================

_SELECT_SYSTEM_PROMPT = (
    "你是摄影编辑。从候选照片中挑选最适合发布的一组照片，兼顾画面质量与叙事连贯。\n"
    "候选已按连拍组折叠（组内封面代表整组），同组照片不要再重复入选。\n"
    "只输出 JSON: {\"selected_ids\": [\"照片id\", ...]}，入选数量通常 4 到 9 张。"
)


@_capability_run
def _select_photos(params: dict, ctx: rt_registry.RunContext) -> Observation:
    """从候选照片挑选发布照片：连拍折叠、两级收缩、超限转图文工坊深链。"""
    state = ctx.state
    candidates = list(state.artifacts.candidate_ids) if state is not None else []
    if not candidates:
        return rt_state.Observation(
            rt_state.OBS_ERROR, "没有候选照片，请先用检索能力获取候选",
        )

    photos = _cached_photos(ctx, candidates)
    mode, collapsed = prepare_select_candidates(
        photos, ctx.cfg.compose_group_limit, ctx.cfg.compose_cover_limit,
    )
    logger.info(
        "[runtime] select_photos 候选=%d，折叠=%d，收缩模式=%s",
        len(candidates), len(collapsed), mode,
    )
    if mode == "overflow":
        tokens = ",".join(select_token(item) for item in collapsed)
        return rt_state.Observation(
            rt_state.OBS_SELECTION_OVERFLOW,
            f"候选照片过多（折叠后 {len(collapsed)} 项），转图文工坊自选",
            {"url": f"#/post-studio?photo_ids={tokens}", "candidate_count": len(collapsed)},
        )

    context = "\n\n".join(
        f"[{i}] id={p.get('id')} 文件={p.get('filename')} 时间={p.get('shot_at')} "
        f"连拍数={p.get('_group_count', 1)}\n描述：{p.get('description') or '无描述'}"
        for i, p in enumerate(collapsed, 1)
    )
    note = str(params.get("note") or "")
    llm = llm_factory.create_llm(
        ctx.cfg, temperature=0.3, callbacks=ctx.llm_callbacks or None,
    )
    response = llm.invoke([
        lc_messages.SystemMessage(content=_SELECT_SYSTEM_PROMPT),
        lc_messages.HumanMessage(content=f"用户请求: {ctx.question}\n{note}\n\n候选:\n{context}"),
    ])
    data = extract_json_dict(str(response.content)) or {}
    collapsed_ids = [p.get("id") for p in collapsed]
    valid_ids = [pid for pid in data.get("selected_ids") or [] if pid in collapsed_ids]
    max_photos = params.get("max_photos")
    if isinstance(max_photos, int) and max_photos > 0:
        valid_ids = valid_ids[:max_photos]
    if not valid_ids:
        return rt_state.Observation(
            rt_state.OBS_ERROR, "挑选结果为空或均不在候选内，请重试或调整候选",
        )
    return rt_state.Observation(
        rt_state.OBS_PHOTOS_SELECTED,
        f"已挑选 {len(valid_ids)} 张发布照片",
        {"ids": valid_ids},
    )


@_capability_run
def _write_post(params: dict, ctx: rt_registry.RunContext) -> Observation:
    """基于已选照片生成标题与发布文案（复用图文工坊提示词栈）。"""
    state = ctx.state
    selected = list(state.artifacts.selected_ids) if state is not None else []
    if not selected:
        return rt_state.Observation(
            rt_state.OBS_ERROR, "尚未挑选照片，请先执行 select_photos",
        )

    photos = [types.SimpleNamespace(**p) for p in _cached_photos(ctx, selected)]
    style = str(params.get("style") or "自由")
    note = str(params.get("note") or "")
    user_prompt = ctx.question + (f"\n备注：{note}" if note else "")
    title, content, warnings = post_studio.generate_post(ctx.cfg, photos, style, user_prompt)
    summary = f"文案已生成（标题「{title}」）"
    if warnings:
        summary += "；" + "；".join(warnings)
    logger.info("[runtime] write_post 完成: 标题=%r, 正文 %d 字", title, len(content))
    return rt_state.Observation(
        rt_state.OBS_COPY_DRAFTED, summary, {"title": title, "content": content},
    )


# ============================================================================
# 注册表
# ============================================================================

def build_registry() -> rt_registry.CapabilityRegistry:
    """登记 Runtime V1 的全部能力。"""
    registry = rt_registry.CapabilityRegistry()
    specs: list[tuple[str, str, dict, typing.Callable]] = [
        (
            "sql_search",
            "按结构化条件（时间线、日期、地点、EXIF 参数）检索照片，返回候选照片 ID 列表。"
            "需要精确定位某次旅行、某天、某类器材照片时使用。",
            {"query": {"type": "str", "description": "结构化检索条件描述", "required": True}},
            _sql_search,
        ),
        (
            "rag_search",
            "按画面内容语义（场景、物体、氛围）检索照片，返回候选照片 ID 列表。",
            {"query": {"type": "str", "description": "语义检索描述", "required": True}},
            _rag_search,
        ),
        (
            "hybrid_search",
            "同时包含结构化条件与画面语义时使用，返回两者交集的候选照片 ID 列表。",
            {"query": {"type": "str", "description": "组合检索描述", "required": True}},
            _hybrid_search,
        ),
        (
            "resolve_trip",
            "把用户目标中的旅行/活动名称匹配到照片库时间线，产出已确认事实。"
            "目标涉及某次旅行或活动时先执行。",
            {"hint": {"type": "str", "description": "匹配提示，缺省用原始请求", "required": False}},
            _resolve_trip,
        ),
        (
            "fetch_photo_details",
            "获取指定照片的详情（文件名、拍摄时间、描述、连拍组），用于确认候选内容。",
            {"ids": {"type": "list", "description": "照片 ID 列表", "required": True}},
            _fetch_photo_details,
        ),
        (
            "select_photos",
            "从候选照片中挑选适合发布的照片（自动折叠连拍组并按阈值收缩；"
            "候选过多时返回图文工坊自选链接）。候选就绪后使用。",
            {
                "max_photos": {"type": "int", "description": "入选数量上限", "required": False},
                "note": {"type": "str", "description": "挑选偏好说明", "required": False},
            },
            _select_photos,
        ),
        (
            "write_post",
            "基于已选照片生成标题与发布文案。已选照片就绪后使用，是发帖目标的最后一步。",
            {
                "style": {"type": "str", "description": "文案风格（自由/文艺/纪实/轻松/攻略）", "required": False},
                "note": {"type": "str", "description": "文案额外要求", "required": False},
            },
            _write_post,
        ),
    ]
    for name, description, parameters, run in specs:
        registry.register(rt_registry.Capability(
            name=name, description=description, parameters=parameters, run=run,
        ))
    return registry
