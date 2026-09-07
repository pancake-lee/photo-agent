"""固定控制流的 Workflow Capability 适配层。"""

import internal.runtime.registry as rt_registry
import internal.runtime.state as rt_state
import internal.topics.suggest as suggest_mod


def _discover_topics(params: dict, ctx: rt_registry.RunContext) -> rt_state.Observation:
    """复用既有三阶段选题管线，并把结果规整为一条 Runtime Observation。"""
    # 照片范围是 resolve_trip 物化的权威状态，不能让决策 LLM 再传一份可漂移的 ID 列表。
    # 这也让模型在范围已就绪后只需选择动作，不会因构造长参数而重复 resolve_trip。
    scope_ids = [str(pid) for pid in ctx.state.scope.photo_ids]
    if not scope_ids:
        return rt_state.Observation(
            rt_state.OBS_ERROR, "主题发现 Workflow 需要明确的照片范围",
            {"terminal_reason": "topic_scope_missing"}, status=rt_state.STATUS_INVALID_INPUT,
        )
    suggestions, meta = suggest_mod.run_suggest(
        ctx.cfg, ctx.cfg.go_backend_url, tracer=ctx.tracer, scope_photo_ids=scope_ids,
    )
    scope_set = set(scope_ids)
    topics = []
    for item in suggestions:
        evidence_ids = [str(pid) for pid in item.photo_ids]
        if evidence_ids and set(evidence_ids).issubset(scope_set):
            topics.append({"title": item.title, "reason": item.rationale, "photo_ids": evidence_ids})
    if not topics:
        return rt_state.Observation(
            rt_state.OBS_ERROR,
            "主题发现未在指定范围内产出带完整照片证据的候选",
            {"terminal_reason": "topic_discovery_empty", "meta": meta}, status=rt_state.STATUS_EMPTY,
        )
    return rt_state.Observation(
        rt_state.OBS_TOPICS_DISCOVERED,
        f"主题发现已在指定范围内产出 {len(topics)} 个候选",
        {"topics": topics, "meta": meta},
    )


DISCOVER_TOPICS = rt_registry.Capability(
    name="discover_topics",
    title="发现主题候选",
    description="在明确照片范围内运行既有稳定三阶段主题发现 Workflow，返回主题候选及照片证据。",
    parameters={},
    run=_discover_topics,
    level="workflow",
    applicable_when="目标明确需要基于一个照片范围发现选题时",
    not_applicable_when="只需检索、选片或发帖文案，或范围尚未明确时",
    output_description="主题候选、理由与范围内照片证据",
    error_semantics="范围缺失为 invalid_input；无范围内证据的候选为 empty；不改变历史记录",
    side_effects="none",
    decide_hint="主题发现目标：范围未建立时执行 resolve_trip；范围已建立后立即执行 discover_topics，后者不传照片参数且不得重复 resolve_trip。",
)
