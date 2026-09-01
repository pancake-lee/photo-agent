"""
    Agent Runtime 能力层：把现有检索/工具/创作实现封装为可注册能力。

    分三类:
        - 检索类: sql_search / rag_search / hybrid_search（封装现有实现）
        - 工具类: resolve_trip / fetch_photo_details（Go 后端 OpenAPI 工具）
        - 创作类: select_photos / write_post（临时能力，CQ4 迁移 + 图文工坊复用）

    每个能力返回结构化 Observation（成功 + 数据或引用，失败为 OBS_ERROR），
    参数声明与校验由 registry 承担，能力自身不修改 TaskState。
"""

import datetime
import functools
import json
import logging
import re
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
                payload = resp.json()
                photo = payload.get("photo") if isinstance(payload, dict) else None
                if not isinstance(photo, dict) or not photo.get("id"):
                    logger.warning("[runtime] 照片详情响应缺少 photo.id: id=%s", pid)
                    return None
                return photo
        except Exception as exc:
            logger.warning("[runtime] 获取照片详情失败: id=%s, error=%s", pid, exc)
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
            return rt_state.Observation(
                rt_state.OBS_ERROR,
                f"{fn.__name__} 执行失败: {exc}",
                {"terminal_reason": "capability_execution_failed"},
            )

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


@_capability_run
def _hybrid_search(params: dict, ctx: rt_registry.RunContext) -> Observation:
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


# ============================================================================
# 工具类能力
# ============================================================================

# 时段词 → 拍摄小时窗（本地时区，与库内 shot_at 偏移一致），程序内固定映射
_TIME_OF_DAY_WINDOWS: dict[str, tuple[int, int]] = {
    "清晨": (5, 8),
    "上午": (8, 11),
    "中午": (11, 13),
    "下午": (13, 17),
    "傍晚": (17, 19),
    "夜晚": (19, 23),
}

_DAY_LABELS = {"first": "第一天", "last": "最后一天"}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 范围物化与软提示的规模上限
_SCOPE_SQL_LIMIT = 500
_SOFT_HINTS_MAX = 8

_CONSTRAINT_SYSTEM_PROMPT = (
    "你是照片库检索助手。从用户目标中抽取可验证的硬约束与软提示。\n"
    '只输出 JSON: {"timeline": "", "day": "", "time_of_day": "", "soft_hints": []}\n'
    "字段规则:\n"
    "- timeline: 目标提到的旅行或活动名称，从时间线列表中选最接近的；完全没提到则为空串\n"
    '- day: 第一天用 "first"，最后一天用 "last"，明确日期用 "YYYY-MM-DD"，没提到则为空串\n'
    "- time_of_day: 拍摄时段，只能是 清晨/上午/中午/下午/傍晚/夜晚 之一，没明确则为空串\n"
    "- soft_hints: 其余的地点、景物、氛围等描述（字符串数组），只用于排序，不构成硬性筛选"
)


def _validate_day(raw: str) -> str:
    """校验 LLM 抽取的天序：first/last/合法日期，非法值按"无该约束"处理。"""
    value = (raw or "").strip()
    if value in ("first", "last"):
        return value
    if _DATE_RE.match(value):
        try:
            datetime.date.fromisoformat(value)
            return value
        except ValueError:
            return ""
    return ""


def _validate_time_of_day(raw: str) -> str:
    """时段词按固定映射表校验，不在表内的一律视为无该约束（不终止）。"""
    value = (raw or "").strip()
    return value if value in _TIME_OF_DAY_WINDOWS else ""


def _describe_scope(timeline: str, day: str, time_of_day: str) -> str:
    """拼出用户可读的范围条件，如"山西旅游第一天傍晚"。"""
    parts = [timeline] if timeline else []
    if day in _DAY_LABELS:
        parts.append(_DAY_LABELS[day])
    elif day:
        parts.append(day)
    if time_of_day:
        parts.append(time_of_day)
    return "".join(parts)


def build_scope_sql(
    timeline: str, day: str,
    hour_start: int | None, hour_end: int | None,
) -> str:
    """按校验后的硬约束拼装权威范围 SQL（只含时间线/天序/小时窗，程序拼装不经 LLM）。

    库内 shot_at 混合 UTC(+00:00) 与本地(+08:00) 偏移，天序与小时窗一律经
    'localtime' 修饰符换算到本地时区再比较，避免两种格式语义漂移。
    """
    local_day = "DATE(shot_at, 'localtime')"
    conds: list[str] = []
    if timeline:
        esc = timeline.replace("'", "''")
        conds.append(f"timeline = '{esc}'")
    if day in _DAY_LABELS:
        agg = "MIN" if day == "first" else "MAX"
        scoped = f" WHERE timeline = '{esc}'" if timeline else ""
        conds.append(f"{local_day} = (SELECT {agg}({local_day}) FROM photos{scoped})")
    elif day:
        conds.append(f"{local_day} = '{day}'")
    if hour_start is not None and hour_end is not None:
        conds.append(
            f"CAST(strftime('%H', shot_at, 'localtime') AS INTEGER) "
            f"BETWEEN {int(hour_start)} AND {int(hour_end)}"
        )
    where = " AND ".join(conds) if conds else "1=1"
    return f"SELECT id FROM photos WHERE {where} ORDER BY shot_at ASC LIMIT {_SCOPE_SQL_LIMIT}"


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
    """约束解析：抽取硬约束（时间线/天序/时段）与软提示，物化权威候选范围。

    一次 LLM 调用只负责抽取；时间线沿用确定性名称匹配，时段查固定映射表，
    范围 SQL 由程序按硬约束拼装（不经 LLM），软提示只保留供检索排序。
    """
    timelines = _fetch_timelines(ctx.cfg)
    hint = str(params.get("hint") or ctx.question or "")
    llm = llm_factory.create_llm(
        ctx.cfg, temperature=0.0, callbacks=ctx.llm_callbacks or None,
    )
    response = llm.invoke([
        lc_messages.SystemMessage(content=_CONSTRAINT_SYSTEM_PROMPT),
        lc_messages.HumanMessage(content=(
            f"用户目标: {hint}\n\n时间线列表: {'、'.join(timelines) or '（空）'}"
        )),
    ])
    data = extract_json_dict(str(response.content)) or {}
    raw_timeline = str(data.get("timeline") or "").strip()
    matched = _match_timeline_name(raw_timeline, timelines)
    if raw_timeline and not matched:
        return rt_state.Observation(
            rt_state.OBS_ERROR,
            f"未在 {len(timelines)} 条时间线中匹配到目标（模型原始输出: {raw_timeline!r}）",
            {"terminal_reason": "trip_unresolved"},
        )
    day = _validate_day(str(data.get("day") or ""))
    time_of_day = _validate_time_of_day(str(data.get("time_of_day") or ""))
    soft_hints = [
        str(item).strip() for item in data.get("soft_hints") or []
        if str(item).strip()
    ][:_SOFT_HINTS_MAX]
    conditions = {"timeline": matched, "day": day, "time_of_day": time_of_day}

    if not (matched or day or time_of_day):
        logger.info("[runtime] resolve_trip 无硬约束，范围不受限 | soft_hints=%s", soft_hints)
        return rt_state.Observation(
            rt_state.OBS_SCOPE,
            "目标没有可验证的硬约束，候选范围不受限（全库）",
            {"conditions": conditions, "restricted": False, "ids": [], "soft_hints": soft_hints},
        )

    hour_start, hour_end = _TIME_OF_DAY_WINDOWS[time_of_day] if time_of_day else (None, None)
    sql = build_scope_sql(matched, day, hour_start, hour_end)
    scope_label = _describe_scope(matched, day, time_of_day)
    ids = text_to_sql.execute_sql_for_ids(ctx.cfg.go_backend_url, sql, limit=_SCOPE_SQL_LIMIT)
    logger.info(
        "[runtime] resolve_trip 物化范围: %s → %d 张 | SQL: %s", scope_label, len(ids), sql,
    )
    if not ids:
        return rt_state.Observation(
            rt_state.OBS_ERROR,
            f"未找到符合条件的照片（{scope_label}）",
            {"terminal_reason": "empty_scope", "conditions": conditions, "sql": sql},
        )
    return rt_state.Observation(
        rt_state.OBS_SCOPE,
        f"已确认候选范围「{scope_label}」，共 {len(ids)} 张",
        {
            "conditions": conditions,
            "restricted": True,
            "ids": ids,
            "sql": sql,
            "condition_summary": scope_label,
            "soft_hints": soft_hints,
        },
    )


@_capability_run
def _fetch_photo_details(params: dict, ctx: rt_registry.RunContext) -> Observation:
    """获取指定照片的详情（文件名、拍摄时间、描述、连拍组）。"""
    ids = [str(pid) for pid in params.get("ids") or []]
    if not ids:
        return rt_state.Observation(rt_state.OBS_ERROR, "未指定要获取详情的照片 ID")
    photos = _cached_photos(ctx, ids)
    if not photos:
        return rt_state.Observation(
            rt_state.OBS_ERROR,
            f"无法获取候选照片详情（0/{len(ids)} 张），无法继续挑选",
            {"terminal_reason": "photo_details_unavailable", "ids": ids},
        )
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
    if not photos:
        return rt_state.Observation(
            rt_state.OBS_ERROR,
            f"无法获取候选照片详情（0/{len(candidates)} 张），无法继续挑选",
            {"terminal_reason": "photo_details_unavailable", "ids": candidates},
        )
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
    # 范围归属校验：受限范围外的入选一律阻断，不生成带确定性地点/场景断言的文案
    if state is not None and state.scope.restricted:
        scope_set = set(state.scope.photo_ids)
        out_of_scope = [pid for pid in valid_ids if pid not in scope_set]
        if out_of_scope:
            return rt_state.Observation(
                rt_state.OBS_ERROR,
                f"挑选结果中有 {len(out_of_scope)} 张不属于权威候选范围，已阻断交付",
                {"terminal_reason": "selection_out_of_scope", "ids": out_of_scope},
            )
    if not valid_ids:
        return rt_state.Observation(
            rt_state.OBS_ERROR,
            "挑选结果为空或均不在候选内，无法继续生成文案",
            {"terminal_reason": "photo_selection_failed"},
        )
    photo_by_id = {p.get("id"): p for p in photos}
    selected_details = [dict(photo_by_id[pid]) for pid in valid_ids]
    return rt_state.Observation(
        rt_state.OBS_PHOTOS_SELECTED,
        f"已挑选 {len(valid_ids)} 张发布照片",
        {"ids": valid_ids, "photos": selected_details},
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
            "按结构化软条件（地点、景物、场景、EXIF 参数）检索照片，返回候选照片 ID 列表。"
            "query 只写软提示（排序偏好），时间线/天数/时段等硬约束已由权威范围限定，"
            "候选会被自动限制在范围内。",
            {"query": {"type": "str", "description": "结构化检索条件描述", "required": True}},
            _sql_search,
        ),
        (
            "rag_search",
            "按画面内容语义（场景、物体、氛围）在权威候选范围内排序照片，返回候选照片 ID 列表。"
            "query 只写软提示。",
            {"query": {"type": "str", "description": "语义检索描述", "required": True}},
            _rag_search,
        ),
        (
            "hybrid_search",
            "同时需要结构化软条件与画面语义时使用，返回两者交集的候选照片 ID 列表；"
            "交集为空时候选交由权威范围兜底，不会用全库结果替换范围。",
            {"query": {"type": "str", "description": "组合检索描述", "required": True}},
            _hybrid_search,
        ),
        (
            "resolve_trip",
            "解析用户目标中的硬约束（时间线、第一天/最后一天/具体日期、拍摄时段）与软提示，"
            "物化为权威候选范围。目标涉及旅行、日期或时段时必须最先执行。",
            {"hint": {"type": "str", "description": "解析提示，缺省用原始请求", "required": False}},
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
