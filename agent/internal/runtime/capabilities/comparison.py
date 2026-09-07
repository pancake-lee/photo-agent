"""跨期照片对比 Skill：基于两组明确照片证据形成可追溯结论。"""

import internal.runtime.capabilities.common as common
import internal.runtime.registry as rt_registry
import internal.runtime.state as rt_state


_COMPARE_SYSTEM_PROMPT = (
    "你是摄影编辑。比较两组照片的拍摄进步，只能依据给出的照片描述、时间和对象。"
    "不得虚构照片中没有的事实。只输出 JSON："
    '{"summary":"对比结论", "strengths":["…"], "next_steps":["…"]}'
)


@common.capability_run
def _compare_photo_periods(params: dict, ctx: rt_registry.RunContext) -> rt_state.Observation:
    """取两期照片详情后产出带照片引用的对比报告。"""
    groups = ctx.state.artifacts.comparison_photo_ids if ctx.state is not None else {}
    earlier_ids = [str(pid) for pid in groups.get("earlier") or []]
    later_ids = [str(pid) for pid in groups.get("later") or []]
    if not earlier_ids or not later_ids:
        return rt_state.Observation(
            rt_state.OBS_ERROR, "跨期对比需要两组已验证的照片证据",
            {"terminal_reason": "comparison_evidence_missing"},
            status=rt_state.STATUS_INVALID_INPUT,
        )
    photos = common.cached_photos(ctx, list(dict.fromkeys(earlier_ids + later_ids)))
    photo_map = {str(photo.get("id")): photo for photo in photos}
    if any(pid not in photo_map for pid in earlier_ids + later_ids):
        return rt_state.Observation(
            rt_state.OBS_ERROR, "跨期对比所需的照片详情不完整",
            {"terminal_reason": "comparison_evidence_unavailable"},
            status=rt_state.STATUS_TEMPORARY_ERROR,
        )
    def render(label: str, ids: list[str]) -> str:
        return "\n".join(
            f"[{label}] id={pid} 时间={photo_map[pid].get('shot_at')} 描述={photo_map[pid].get('description') or '无'}"
            for pid in ids
        )
    response = common.invoke_structured_llm(
        ctx, _COMPARE_SYSTEM_PROMPT,
        f"用户请求：{ctx.question}\n\n{render('早期', earlier_ids)}\n\n{render('近期', later_ids)}",
        temperature=0.2,
    )
    data = common.extract_json_dict(response) or {}
    summary = str(data.get("summary") or "")
    if not summary:
        return rt_state.Observation(
            rt_state.OBS_ERROR, "对比结论未返回有效摘要",
            {"terminal_reason": "comparison_generation_failed"},
            status=rt_state.STATUS_INVALID_INPUT,
        )
    report = {
        "summary": summary,
        "strengths": list(data.get("strengths") or []),
        "next_steps": list(data.get("next_steps") or []),
        "periods": {"earlier": earlier_ids, "later": later_ids},
        "photo_ids": earlier_ids + later_ids,
    }
    return rt_state.Observation(
        rt_state.OBS_COMPARISON_REPORTED,
        f"已基于两期共 {len(report['photo_ids'])} 张照片形成对比结论",
        {"report": report, "photos": [photo_map[pid] for pid in report["photo_ids"]]},
    )


COMPARE_PHOTO_PERIODS = rt_registry.Capability(
    name="compare_photo_periods",
    title="形成跨期对比",
    description="基于两组已明确的照片证据总结拍摄进步；不选片、不生成发布草稿、不写入任何数据。",
    parameters={
    },
    run=_compare_photo_periods,
    level="skill",
    applicable_when="已收集两组已验证的跨期照片证据，且目标需要综合结论时",
    not_applicable_when="只有一组照片、需要发帖草稿或没有可追溯照片证据时",
    output_description="带两期照片 ID 引用的进步对比报告",
    error_semantics="缺少证据为 invalid_input；详情暂不可得为 temporary_error；不产生写操作",
    side_effects="none",
)
