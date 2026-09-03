"""
    创作类能力：select_photos / write_post（能力内 LLM，提示词驱动）。

    含迁移自 CQ4 compose 管线的挑选辅助（连拍折叠 / 两级收缩 / 超限令牌）。
"""

import logging
import types

import internal.posts.post_studio as post_studio
import internal.runtime.capabilities.common as common
import internal.runtime.registry as rt_registry
import internal.runtime.state as rt_state

logger = logging.getLogger(__name__)


# --------------------------------------------------
# select_photos — 挑选代表照片（能力内 LLM 挑选 + 程序折叠收缩）
# --------------------------------------------------

_SELECT_SYSTEM_PROMPT = (
    "你是摄影编辑。从候选照片中挑选最适合发布的一组照片，兼顾画面质量与叙事连贯。\n"
    "候选已按连拍组折叠（组内封面代表整组），同组照片不要再重复入选。\n"
    "只输出 JSON: {\"selected_ids\": [\"照片id\", ...]}，入选数量通常 4 到 9 张。"
)


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


@common.capability_run
def _select_photos(params: dict, ctx: rt_registry.RunContext) -> rt_state.Observation:
    """从候选照片挑选发布照片：连拍折叠、两级收缩、超限转图文工坊深链。"""
    state = ctx.state
    candidates = list(state.artifacts.candidate_ids) if state is not None else []
    if not candidates:
        return rt_state.Observation(
            rt_state.OBS_ERROR, "没有候选照片，请先用检索能力获取候选",
            status=rt_state.STATUS_INVALID_INPUT,
        )

    photos = common.cached_photos(ctx, candidates)
    if not photos:
        return rt_state.Observation(
            rt_state.OBS_ERROR,
            f"无法获取候选照片详情（0/{len(candidates)} 张），无法继续挑选",
            {"terminal_reason": "photo_details_unavailable", "ids": candidates},
            # 详情拉取失败以 Go 后端不可达/超时为主，按瞬时故障归类（有界重试后停止）
            status=rt_state.STATUS_TEMPORARY_ERROR,
        )
    mode, collapsed = prepare_select_candidates(
        photos, ctx.cfg.compose_group_limit, ctx.cfg.compose_cover_limit,
    )
    logger.info(
        "[runtime] select_photos 候选=%d，折叠=%d，收缩模式=%s",
        len(candidates), len(collapsed), mode,
    )
    if state is not None and state.goal.delivery_mode == "candidate":
        # 二次挑选交付不经代表性选片 LLM，完整保留连拍折叠后的候选。
        if mode == "overflow":
            tokens = ",".join(select_token(item) for item in collapsed)
            return rt_state.Observation(
                rt_state.OBS_SELECTION_OVERFLOW,
                f"候选照片过多（折叠后 {len(collapsed)} 项），转图文工坊自选",
                {"url": f"#/post-studio?photo_ids={tokens}", "candidate_count": len(collapsed)},
            )
        selected_ids = [str(photo.get("id") or "") for photo in collapsed if photo.get("id")]
        return rt_state.Observation(
            rt_state.OBS_PHOTOS_SELECTED,
            f"已保留 {len(selected_ids)} 张连拍折叠后的候选照片，供二次挑选",
            {"ids": selected_ids, "photos": [dict(photo) for photo in collapsed]},
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
    response_text = common.invoke_structured_llm(
        ctx, _SELECT_SYSTEM_PROMPT,
        f"用户请求: {ctx.question}\n{note}\n\n候选:\n{context}",
        temperature=0.3,
    )
    data = common.extract_json_dict(response_text) or {}
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
                # 模型输出越界属能力侧输出缺陷，带失败反馈修复重执行（AR2-3）
                status=rt_state.STATUS_INVALID_INPUT,
            )
    if not valid_ids:
        return rt_state.Observation(
            rt_state.OBS_ERROR,
            "挑选结果为空或均不在候选内，无法继续生成文案",
            {"terminal_reason": "photo_selection_failed"},
            # 挑选空结果是最高频的模型输出缺陷，带失败反馈修复重执行（AR2-3）
            status=rt_state.STATUS_INVALID_INPUT,
        )
    photo_by_id = {p.get("id"): p for p in photos}
    selected_details = [dict(photo_by_id[pid]) for pid in valid_ids]
    # 数量类可回退歧义：未指定张数时沿用默认档位并记录假设，不询问用户（Ask vs Act）
    payload = {"ids": valid_ids, "photos": selected_details}
    if not isinstance(params.get("max_photos"), int):
        payload["assumption"] = "未指定入选数量，按默认 4-9 张挑选"
    return rt_state.Observation(
        rt_state.OBS_PHOTOS_SELECTED,
        f"已挑选 {len(valid_ids)} 张发布照片",
        payload,
    )


def _select_progress_details(params: dict) -> dict:
    """过程面板受控细节：只暴露入选数量上限。"""
    if isinstance(params.get("max_photos"), int):
        return {"最多入选": params["max_photos"]}
    return {}


SELECT_PHOTOS = rt_registry.Capability(
    name="select_photos",
    title="挑选代表照片",
    description=(
        "从候选照片中挑选适合发布的照片（候选交付模式下保留折叠候选，不调用选片模型；自动折叠连拍组并按阈值收缩；"
        "候选过多时返回图文工坊自选链接）。候选就绪后使用。"
    ),
    parameters={
        "max_photos": {"type": "int", "description": "入选数量上限", "required": False},
        "note": {"type": "str", "description": "挑选偏好说明", "required": False},
    },
    run=_select_photos,
    progress_details=_select_progress_details,
)

# --------------------------------------------------
# write_post — 生成发布文案（复用图文工坊提示词栈）
# --------------------------------------------------

@common.capability_run
def _write_post(params: dict, ctx: rt_registry.RunContext) -> rt_state.Observation:
    """基于已选照片生成标题与发布文案（复用图文工坊提示词栈）。"""
    state = ctx.state
    selected = list(state.artifacts.selected_ids) if state is not None else []
    if not selected:
        return rt_state.Observation(
            rt_state.OBS_ERROR, "尚未挑选照片，请先执行 select_photos",
            status=rt_state.STATUS_INVALID_INPUT,
        )

    photos = [types.SimpleNamespace(**p) for p in common.cached_photos(ctx, selected)]
    style = str(params.get("style") or "自由")
    note = str(params.get("note") or "")
    user_prompt = ctx.question + (f"\n备注：{note}" if note else "")
    title, content, warnings = post_studio.generate_post(ctx.cfg, photos, style, user_prompt)
    summary = f"文案已生成（标题「{title}」）"
    if warnings:
        summary += "；" + "；".join(warnings)
    logger.info("[runtime] write_post 完成: 标题=%r, 正文 %d 字", title, len(content))
    payload = {"title": title, "content": content}
    # 风格类可回退歧义：未指定风格时沿用默认并记录假设，不询问用户（Ask vs Act）
    if not params.get("style"):
        payload["assumption"] = "未指定文案风格，默认「自由」"
    return rt_state.Observation(
        rt_state.OBS_COPY_DRAFTED, summary, payload,
    )


def _write_post_progress_details(params: dict) -> dict:
    """过程面板受控细节：只暴露文案风格。"""
    return {"文案风格": str(params["style"])} if params.get("style") else {}


WRITE_POST = rt_registry.Capability(
    name="write_post",
    title="生成发布文案",
    description="基于已选照片生成标题与发布文案。已选照片就绪后使用，是发帖目标的最后一步。",
    parameters={
        "style": {"type": "str", "description": "文案风格（自由/文艺/纪实/轻松/攻略）", "required": False},
        "note": {"type": "str", "description": "文案额外要求", "required": False},
    },
    run=_write_post,
    progress_details=_write_post_progress_details,
)

# --------------------------------------------------
