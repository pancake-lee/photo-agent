"""程序工具类能力：直接调用 Go 后端的 HTTP 工具，全程无 LLM。"""

import internal.runtime.capabilities.common as common
import internal.runtime.registry as rt_registry
import internal.runtime.state as rt_state


# --------------------------------------------------
# fetch_photo_details — 确认照片信息（Go 后端详情查询，无 LLM）
# --------------------------------------------------

@common.capability_run
def _fetch_photo_details(params: dict, ctx: rt_registry.RunContext) -> rt_state.Observation:
    """获取指定照片的详情（文件名、拍摄时间、描述、连拍组）。"""
    ids = [str(pid) for pid in params.get("ids") or []]
    if not ids:
        return rt_state.Observation(
            rt_state.OBS_ERROR, "未指定要获取详情的照片 ID",
            status=rt_state.STATUS_INVALID_INPUT,
        )
    photos = common.cached_photos(ctx, ids)
    if not photos:
        return rt_state.Observation(
            rt_state.OBS_ERROR,
            f"无法获取候选照片详情（0/{len(ids)} 张），无法继续挑选",
            {"terminal_reason": "photo_details_unavailable", "ids": ids},
            # 详情拉取失败以 Go 后端不可达/超时为主，按瞬时故障归类（有界重试后停止）
            status=rt_state.STATUS_TEMPORARY_ERROR,
        )
    return rt_state.Observation(
        rt_state.OBS_PHOTO_DETAILS,
        f"获取 {len(photos)}/{len(ids)} 张照片详情",
        {"photos": photos},
    )


FETCH_PHOTO_DETAILS = rt_registry.Capability(
    name="fetch_photo_details",
    title="确认照片信息",
    description="获取指定照片的详情（文件名、拍摄时间、描述、连拍组），用于确认候选内容。",
    parameters={
        "ids": {"type": "list", "description": "照片 ID 列表", "required": True},
    },
    run=_fetch_photo_details,
)

# --------------------------------------------------
