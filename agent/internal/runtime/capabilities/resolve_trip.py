"""约束解析能力：resolve_trip（能力内 LLM 抽取硬约束，程序物化权威范围）。"""

import datetime
import logging
import re

import infra.http_client as http_utils
import internal.chat.text_to_sql as text_to_sql
import internal.runtime.capabilities.common as common
import internal.runtime.registry as rt_registry
import internal.runtime.state as rt_state

logger = logging.getLogger(__name__)


# --------------------------------------------------
# resolve_trip — 确认候选范围
# 能力内 LLM 只负责抽取硬约束（提示词驱动），时间线沿用确定性名称匹配，
# 时段查固定映射表，范围 SQL 由程序按硬约束拼装（不经 LLM），软提示只保留供检索排序。
# --------------------------------------------------

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
_MONTH_DAY_RE = re.compile(r"(?<!\d)(\d{1,2})月(\d{1,2})日")

# 范围物化与软提示的规模上限
_SCOPE_SQL_LIMIT = 500
_SOFT_HINTS_MAX = 8

_CONSTRAINT_SYSTEM_PROMPT = (
    "你是照片库检索助手。从用户目标中抽取可验证的硬约束与软提示。\n"
    '只输出 JSON: {"timeline": "", "day": "", "time_of_day": "", "soft_hints": []}\n'
    "字段规则:\n"
    "- timeline: 目标提到的旅行或活动名称，从时间线列表中选最接近的；完全没提到则为空串\n"
    '- day: 第一天用 "first"，最后一天用 "last"，第N天用 "relative:N"，明确日期用 "YYYY-MM-DD"，没提到则为空串\n'
    "- time_of_day: 拍摄时段，只能是 清晨/上午/中午/下午/傍晚/夜晚 之一，没明确则为空串\n"
    "- soft_hints: 其余的地点、景物、氛围等描述（字符串数组），只用于排序，不构成硬性筛选"
)


def _validate_day(raw: str) -> str:
    """校验 LLM 抽取的天序：first/last/合法日期，非法值按"无该约束"处理。"""
    value = (raw or "").strip()
    if value in ("first", "last"):
        return value
    if value.startswith("relative:"):
        try:
            number = int(value.removeprefix("relative:"))
        except ValueError:
            return ""
        return f"relative:{number}" if number > 0 else ""
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
    elif day.startswith("relative:"):
        parts.append(f"第{day.removeprefix('relative:')}天")
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
    # NEF 是与 JPG 同目录的原始附件，不是可检索照片。历史残留记录清理前也
    # 必须从 Runtime 的权威范围中排除，避免进入选片和文案上下文。
    conds.insert(0, "LOWER(file_type) != 'nef'")
    where = " AND ".join(conds)
    return f"SELECT id FROM photos WHERE {where} ORDER BY shot_at ASC LIMIT {_SCOPE_SQL_LIMIT}"


def _fetch_timelines(cfg) -> list[str]:
    """获取照片库时间线列表。"""
    with http_utils.create_client(timeout=5.0) as client:
        resp = client.get(f"{cfg.go_backend_url}/api/v1/timelines")
        resp.raise_for_status()
        timelines = resp.json().get("timelines") or []
    return [str(name) for name in timelines if name]


def _fetch_timeline_event_date(cfg, timeline: str) -> str:
    """读取时间线事件的行程首日；缺失事件时返回空串。"""
    with http_utils.create_client(timeout=5.0) as client:
        resp = client.get(f"{cfg.go_backend_url}/api/v1/timeline-events")
        resp.raise_for_status()
        events = resp.json().get("timelineEventList") or []
    for item in events:
        if str(item.get("event") or "") != timeline:
            continue
        value = int(item.get("eventDate") or 0)
        if value > 10_000_000_000:
            value //= 1000
        if value:
            return datetime.datetime.fromtimestamp(value, tz=datetime.timezone.utc).date().isoformat()
    return ""


def _fetch_first_photo_day(cfg, timeline: str) -> str:
    """读取时间线内首个拍摄日，统一使用本地日期口径。"""
    escaped = timeline.replace("'", "''")
    rows = text_to_sql.execute_sql(
        cfg.go_backend_url,
        "SELECT MIN(DATE(shot_at, 'localtime')) AS day FROM photos "
        f"WHERE timeline = '{escaped}'",
        limit=1,
    )
    return str(rows[0].get("day") or "") if rows else ""


def _relative_day_dates(event_day: str, photo_day: str, relative_day: str) -> tuple[str, str]:
    """返回行程首日与首拍日两种口径各自对应的日期。"""
    offset = int(relative_day.removeprefix("relative:")) - 1
    event_date = datetime.date.fromisoformat(event_day) if event_day else None
    photo_date = datetime.date.fromisoformat(photo_day) if photo_day else None
    return (
        (event_date + datetime.timedelta(days=offset)).isoformat() if event_date else "",
        (photo_date + datetime.timedelta(days=offset)).isoformat() if photo_date else "",
    )


def _resolve_date_in_hint(ctx: rt_registry.RunContext, timeline: str, hint: str) -> tuple[str, list[str]]:
    """确定性解析用户写出的日期；无年份只从已知行程/拍摄年份推断。"""
    matched = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", hint)
    if matched:
        return _validate_day(matched.group(1)), []
    matched = _MONTH_DAY_RE.search(hint)
    if not matched or not timeline:
        return "", []
    month, day = (int(value) for value in matched.groups())
    event_day = _fetch_timeline_event_date(ctx.cfg, timeline)
    photo_day = _fetch_first_photo_day(ctx.cfg, timeline)
    candidates = []
    for source_day in (event_day, photo_day):
        if not source_day:
            continue
        try:
            candidate = datetime.date(datetime.date.fromisoformat(source_day).year, month, day).isoformat()
        except ValueError:
            continue
        if candidate not in candidates:
            candidates.append(candidate)
    return (candidates[0], []) if len(candidates) == 1 else ("", candidates)


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


@common.capability_run
def _resolve_trip(params: dict, ctx: rt_registry.RunContext) -> rt_state.Observation:
    """约束解析：抽取硬约束（时间线/天序/时段）与软提示，物化权威候选范围。"""
    timelines = _fetch_timelines(ctx.cfg)
    hint = str(params.get("hint") or ctx.question or "")
    response_text = common.invoke_structured_llm(
        ctx, _CONSTRAINT_SYSTEM_PROMPT,
        f"用户目标: {hint}\n\n时间线列表: {'、'.join(timelines) or '（空）'}",
        temperature=0.0,
    )
    data = common.extract_json_dict(response_text) or {}
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

    explicit_day, date_options = _resolve_date_in_hint(ctx, matched, hint)
    if explicit_day:
        day = explicit_day
        conditions["day"] = day
    elif date_options:
        message = f"“{_MONTH_DAY_RE.search(hint).group(0)}”可能是 {' 或 '.join(date_options)}，请回复完整日期。"
        return rt_state.Observation(
            rt_state.OBS_NEEDS_CLARIFICATION, message,
            {"message": message, "options": date_options, "timeline": matched},
        )

    if day.startswith("relative:"):
        event_day = _fetch_timeline_event_date(ctx.cfg, matched) if matched else ""
        photo_day = _fetch_first_photo_day(ctx.cfg, matched) if matched else ""
        event_date, photo_date = _relative_day_dates(event_day, photo_day, day)
        if event_date and photo_date and event_date != photo_date:
            message = (
                f"{event_day} 为行程首日，{photo_day} 为首个拍摄日；"
                f"第{day.removeprefix('relative:')}天指 {event_date} 还是 {photo_date}？"
            )
            return rt_state.Observation(
                rt_state.OBS_NEEDS_CLARIFICATION, message,
                {"message": message, "options": [event_date, photo_date], "timeline": matched},
            )
        resolved_date = event_date or photo_date
        if not resolved_date:
            return rt_state.Observation(
                rt_state.OBS_NEEDS_CLARIFICATION, "无法确定这次旅行的起始日期，请直接回复完整日期。",
                {"message": "无法确定这次旅行的起始日期，请直接回复完整日期。", "options": [], "timeline": matched},
            )
        day = resolved_date
        conditions["day"] = day

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
    scope_payload = {
        "conditions": conditions,
        "restricted": True,
        "ids": ids,
        "sql": sql,
        "condition_summary": scope_label,
        "soft_hints": soft_hints,
    }
    return rt_state.Observation(
        rt_state.OBS_SCOPE,
        f"已确认候选范围「{scope_label}」，共 {len(ids)} 张",
        scope_payload,
    )


def _progress_details(params: dict) -> dict:
    """过程面板受控细节：只暴露用户可读的解析提示。"""
    return {"解析提示": str(params["hint"])} if params.get("hint") else {}


RESOLVE_TRIP = rt_registry.Capability(
    name="resolve_trip",
    title="确认候选范围",
    description=(
        "解析用户目标中的硬约束（时间线、第一天/最后一天/具体日期、拍摄时段）与软提示，"
        "物化为权威候选范围。目标涉及旅行、日期或时段时必须最先执行。"
    ),
    parameters={
        "hint": {"type": "str", "description": "解析提示，缺省用原始请求", "required": False},
    },
    run=_resolve_trip,
    decide_hint=(
        "目标涉及旅行、日期或时段时，先执行 resolve_trip 确认权威候选范围，未确认前不要检索"
    ),
    progress_details=_progress_details,
)

# --------------------------------------------------
