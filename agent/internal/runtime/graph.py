"""
    Agent Runtime 编排外壳（LangGraph）。

    LangGraph 只承担编排：decide → execute → guardrail → reduce → check 循环图
    与条件回环，换取节点执行、条件路由与 checkpoint 就绪能力。业务语义全部在
    框架无关的 runtime 核心模块中（state / budget / completion / registry /
    capabilities / guardrail / evaluators）。

    节点与流转按「是否需要 LLM」分类：
        - decide    LLM 决策点（唯一）：模型在能力清单中选择下一动作和参数，
                    能力清单与各能力的选择规则以提示词提供（registry.specs + decide_hint）
        - execute   程序节点：参数校验 + 能力调用（能力内是否用 LLM 见 capabilities/ 分类）
        - guardrail 程序节点：确定性验证 + 按能力声明语义评估 + 状态到策略映射，
                    恢复动作（重试/修复）回 execute、再决策回 decide、接受进 reduce；
                    语义评估的能力内 LLM 评委在能力声明中（evaluators）
        - reduce    程序节点：把观察按显式规则归约进 TaskState
        - check     程序节点：预算消耗、无进展检测与完成/停止判定
        - finish    程序节点：最终输出组装
        - 节点间流转全部是程序行为：固定边 decide→execute→guardrail→reduce→check，
          条件路由 _route_after_guardrail / _route_after_check 决定回环或收尾，不经 LLM
"""

import json
import logging
import time
import typing

import langchain_core.callbacks as lc_callbacks
import langchain_core.messages as lc_messages
import langchain_core.runnables as lc_runnables
import langgraph.graph as lg_graph

import internal.runtime.budget as rt_budget
import internal.runtime.capabilities as rt_capabilities
import internal.runtime.capabilities.common as caps_common
import internal.runtime.completion as rt_completion
import internal.runtime.guardrail as rt_guardrail
import internal.runtime.progress as rt_progress
import internal.runtime.registry as rt_registry
import internal.runtime.state as rt_state
import infra.llm_factory as llm_factory

logger = logging.getLogger(__name__)


class RuntimeGraphState(typing.TypedDict):
    """Runtime 循环图的共享 State。"""

    question: str
    granularity: str
    task: rt_state.TaskState
    decision: dict             # {action, params, reason}
    observation: rt_state.Observation
    budget_state: rt_budget.BudgetState   # 就地消耗（步数/成本/恢复计数累加），不整体替换
    step_no: int
    stop_reason: str           # 停止原因（check 填写：预算/无进展；guardrail 可直填预算）
    answer: str
    photos: list[dict]
    compose_url: str
    decision_feedback: str     # 决策反馈通道：guardrail（再决策/换策略）与 check（无进展）写入，decide 消费后清空
    guardrail_action: str      # 最近一次护栏结论动作，驱动 _route_after_guardrail
    guardrail_ordinal: int     # 恢复事件序号（过程面板区分同一步内的多次恢复条目）
    signatures: list[str]      # 最近若干步的状态签名（无进展检测窗口）
    no_progress_hinted: bool   # 无进展已提示过换策略（第二次检出即停止）


# --------------------------------------------------
# 注册表与运行配置（程序辅助，无 LLM）
# --------------------------------------------------

# 能力注册表单例（能力是无状态函数，进程内共享）
_registry: rt_registry.CapabilityRegistry | None = None


def _get_registry() -> rt_registry.CapabilityRegistry:
    global _registry
    if _registry is None:
        _registry = rt_capabilities.build_registry()
    return _registry


def _get_runtime_config(config: dict) -> tuple[typing.Any, list, typing.Any, bool, typing.Callable | None]:
    """从 LangGraph configurable 中取配置、LLM 回调与 tracer。"""
    configurable = config.get("configurable", {})
    cfg = configurable.get("cfg")
    if cfg is None:
        raise RuntimeError("Config 未注入到 configurable 中")
    return (
        cfg,
        list(configurable.get("llm_callbacks") or []),
        configurable.get("tracer"),
        bool(configurable.get("pricing_available", True)),
        configurable.get("progress_callback"),
    )


def _emit(tracer, progress_callback, event: str, data: dict) -> None:
    """写入 runtime 步骤事件（tracer 缺失时静默跳过，如 CLI 直跑）。"""
    if tracer is not None:
        tracer.emit(event, data, module="runtime")
    if progress_callback is not None:
        progress_callback(event, data)


def _capability_title(action: str) -> str:
    """能力自带的用户过程标题（registry.Capability.title），未登记能力回退通用标题。"""
    capability = _get_registry().get(action)
    return capability.title if capability is not None else "处理任务"


def _progress_details(action: str, params: dict, observation: rt_state.Observation | None = None) -> dict:
    """挑出允许进入用户过程面板的受控细节，绝不传递 ID、提示词或异常栈。

    能力相关的细节由各能力的 progress_details 提供（聚合在能力定义处）；
    观察携带的 SQL 是跨能力的程序产物，在此统一截断放行。
    """
    details: dict = {}
    capability = _get_registry().get(action)
    if capability is not None and capability.progress_details is not None:
        details.update(capability.progress_details(params or {}))
    if observation is not None and observation.payload.get("sql"):
        details["SQL"] = str(observation.payload["sql"])[:1000]
    return details


# --------------------------------------------------
# decide 节点 — LLM 决策点（能力清单与选择规则以提示词提供）
# --------------------------------------------------

# 编排层的通用选择规则；各能力自带的规则经 registry.decide_hints() 注入
_RUNTIME_DECIDE_RULES = (
    "- 优先选择能推进「待办里程碑」的能力，不要重复已完成的里程碑\n"
    "- 检索到候选后先挑选照片，挑选完成后再创作文案\n"
    "- params 必须符合能力声明，不要编造参数名"
)


def _decide_system_prompt(registry: rt_registry.CapabilityRegistry) -> str:
    """组装决策系统提示词：通用规则 + 各能力自带的选择规则。"""
    rules = _RUNTIME_DECIDE_RULES
    hints = registry.decide_hints()
    if hints:
        rules += "\n" + "\n".join(f"- {hint}" for hint in hints)
    return (
        "你是照片任务的执行规划器。根据当前任务状态，从能力列表中选择下一步动作。\n"
        '只输出 JSON: {"action": "能力名", "params": {...}, "reason": "一句话理由"}。\n'
        f"选择规则:\n{rules}"
    )


def _decide_node(state: RuntimeGraphState, config: lc_runnables.RunnableConfig) -> dict:
    """决策节点：LLM 在能力列表中选择下一动作（程序负责解析与校验）。"""
    cfg, callbacks, tracer, _, progress_callback = _get_runtime_config(config)
    registry = _get_registry()
    task = state["task"]

    # 决策反馈通道（guardrail 再决策/换策略建议、无进展换策略提示），消费即清空
    feedback = str(state.get("decision_feedback") or "")
    missing = rt_completion.check_completion(task).missing
    llm = llm_factory.create_llm(cfg, temperature=0.0, callbacks=callbacks or None)
    started_at = time.perf_counter()
    human_content = (
        f"能力列表:\n{json.dumps(registry.specs(), ensure_ascii=False)}\n\n"
        f"当前任务状态:\n{rt_state.summarize_state(task)}\n\n"
        f"完成要件缺口: {'、'.join(missing) if missing else '无'}\n\n"
    )
    if feedback:
        human_content += f"上一决策反馈: {feedback}\n\n"
    human_content += "选择下一步动作。"
    response = llm.invoke([
        lc_messages.SystemMessage(content=_decide_system_prompt(registry)),
        lc_messages.HumanMessage(content=human_content),
    ])
    duration_ms = round((time.perf_counter() - started_at) * 1000)
    parsed = caps_common.extract_json_dict(str(response.content)) or {}
    decision = {
        "action": str(parsed.get("action") or ""),
        "params": parsed.get("params") if isinstance(parsed.get("params"), dict) else {},
        "reason": str(parsed.get("reason") or ""),
    }
    logger.info(
        "[runtime] 第 %d 步决策: action=%s, params=%s%s",
        state["step_no"] + 1, decision["action"], decision["params"],
        f"（反馈: {feedback}）" if feedback else "",
    )
    event_data = {
        "step": state["step_no"] + 1,
        "action": decision["action"],
        "title": _capability_title(decision["action"]),
        "params": decision["params"],
        "reason": decision["reason"],
        "duration_ms": duration_ms,
    }
    _emit(tracer, progress_callback, "runtime.decide", event_data)
    return {"decision": decision, "step_no": state["step_no"] + 1, "decision_feedback": ""}


# --------------------------------------------------
# execute / reduce / check / finish — 程序节点（无 LLM）
# --------------------------------------------------

def _execute_node(state: RuntimeGraphState, config: lc_runnables.RunnableConfig) -> dict:
    """执行节点：程序校验参数并调用能力，异常与无效决策都转为失败观察。"""
    cfg, callbacks, tracer, _, progress_callback = _get_runtime_config(config)
    registry = _get_registry()
    decision = state["decision"]
    action = decision.get("action", "")

    errors = registry.validate_params(action, decision.get("params"))
    started_at = time.perf_counter()
    if errors:
        observation = rt_state.Observation(
            rt_state.OBS_ERROR,
            f"决策无效（{action or '空 action'}）: {'; '.join(errors)}",
            {"terminal_reason": "invalid_decision"},
            # 决策侧契约违规：错误摘要反馈给 decide 再决策（AR2-3 接入）
            status=rt_state.STATUS_INVALID_INPUT,
        )
    else:
        capability = registry.get(action)
        ctx = rt_registry.RunContext(
            cfg=cfg,
            granularity=state.get("granularity", "photo"),
            question=state["question"],
            state=state["task"],
            llm_callbacks=callbacks,
            tracer=tracer,
        )
        observation = capability.run(decision.get("params"), ctx)
    duration_ms = round((time.perf_counter() - started_at) * 1000)
    logger.info(
        "[runtime] 第 %d 步执行: %s → %s（%s）",
        state["step_no"], action, observation.kind, observation.summary,
    )
    event_data = {
        "step": state["step_no"],
        "action": action,
        "title": _capability_title(action),
        "duration_ms": duration_ms,
        "details": _progress_details(action, decision.get("params") or {}),
    }
    _emit(tracer, progress_callback, "runtime.execute", event_data)
    return {"observation": observation}


# --------------------------------------------------
# guardrail 节点 — 程序节点（确定性验证 + 按能力声明语义评估 + 恢复决策）
# --------------------------------------------------

# 恢复动作 → 过程面板条目标题前缀（沿用 AR8 过程面板机制，前端无新交互）
_RECOVERY_TITLES = {
    rt_guardrail.ACTION_RETRY: "重试",
    rt_guardrail.ACTION_REPAIR: "修复重试",
    rt_guardrail.ACTION_REDECIDE: "重新决策",
    rt_guardrail.ACTION_FALLBACK: "调整策略",
    rt_guardrail.ACTION_STOP: "停止",
    rt_guardrail.ACTION_BUDGET_STOP: "停止",
}


def _guardrail_node(state: RuntimeGraphState, config: lc_runnables.RunnableConfig) -> dict:
    """护栏节点：验证观察并决定接受/重试/修复/再决策/停止（策略表驱动，无提示词约定）。"""
    cfg, callbacks, tracer, pricing_available, progress_callback = _get_runtime_config(config)
    registry = _get_registry()
    observation = state["observation"]
    decision = state["decision"]
    action = decision.get("action", "")
    capability = registry.get(action)
    budget_state = state["budget_state"]
    budget = rt_budget.Budget(
        max_steps=cfg.runtime_max_steps,
        timeout_seconds=cfg.runtime_timeout_seconds,
        cost_limit=cfg.runtime_cost_limit if pricing_available else 0,
    )
    ctx = rt_registry.RunContext(
        cfg=cfg,
        granularity=state.get("granularity", "photo"),
        question=state["question"],
        state=state["task"],
        llm_callbacks=callbacks,
        tracer=tracer,
    )
    verdict = rt_guardrail.run_guardrail(
        observation, capability, ctx, budget_state,
        rt_guardrail.recovery_budget_from_config(cfg), budget,
    )
    logger.info(
        "[runtime] 第 %d 步护栏: %s → %s（%s）",
        state["step_no"], observation.status, verdict.action, verdict.reason,
    )

    update: dict = {"guardrail_action": verdict.action}
    if verdict.action != rt_guardrail.ACTION_ACCEPT:
        ordinal = state.get("guardrail_ordinal", 0) + 1
        update["guardrail_ordinal"] = ordinal
        _emit(tracer, progress_callback, "runtime.guardrail", {
            "step": state["step_no"],
            "ordinal": ordinal,
            "action": action,
            "recovery": verdict.action,
            "title": f"{_RECOVERY_TITLES[verdict.action]}：{_capability_title(action)}",
            "reason": verdict.reason,
            "feedback": verdict.feedback,
        })

    if verdict.action == rt_guardrail.ACTION_ACCEPT:
        return update
    if verdict.action == rt_guardrail.ACTION_FALLBACK:
        # 换策略建议注入决策上下文，由 decide 采纳，不强制改写；观察本身接受
        update["decision_feedback"] = verdict.feedback
        return update
    if verdict.action == rt_guardrail.ACTION_RETRY:
        return update  # 决策不变，回 execute 同能力同参数重试
    if verdict.action == rt_guardrail.ACTION_REPAIR:
        params = dict(decision.get("params") or {})
        params["feedback"] = verdict.feedback
        update["decision"] = {**decision, "params": params}
        return update
    if verdict.action == rt_guardrail.ACTION_REDECIDE:
        update["decision_feedback"] = verdict.feedback
        update["decision"] = {}
        return update
    if verdict.action == rt_guardrail.ACTION_BUDGET_STOP:
        update["stop_reason"] = verdict.stop_reason
        return update
    # ACTION_STOP：以可行动文案的终态观察替换原观察，归约后正确停止
    update["observation"] = verdict.replacement
    return update


def _reduce_node(state: RuntimeGraphState, config: lc_runnables.RunnableConfig) -> dict:
    """归约节点：把观察按显式规则合并进 TaskState。"""
    _, _, tracer, _, progress_callback = _get_runtime_config(config)
    observation = state["observation"]
    action = state["decision"].get("action", "")
    task = rt_state.reduce_observation(
        state["task"], observation, step_no=state["step_no"], action=action,
    )
    facts = []
    if observation.kind == rt_state.OBS_SCOPE and task.scope.established:
        if task.scope.restricted:
            facts.append(
                f"候选范围：{task.scope.condition_summary}（共 {len(task.scope.photo_ids)} 张）"
            )
        else:
            facts.append("候选范围不受限（全库）")
        hints = task.resolved_facts.get("soft_hints") or []
        if hints:
            facts.append(f"软提示（只用于排序）：{'、'.join(str(h) for h in hints)}")
    for key, value in (observation.payload.get("facts") or {}).items():
        facts.append(f"已确认{key}：{value}")
    event_data = {
        "step": state["step_no"],
        "action": action,
        "title": _capability_title(action),
        "kind": observation.kind,
        "summary": observation.summary,
        "candidate_count": len(task.artifacts.candidate_ids),
        "selected_count": len(task.artifacts.selected_ids),
        "facts": facts,
        "details": _progress_details(action, state["decision"].get("params") or {}, observation),
        "observation": observation.payload,
    }
    if tracer is not None:
        event_data["payload_ref"] = tracer.save_payload(
            f"runtime-step-{state['step_no']}-{action}.json",
            json.dumps({"decision": state["decision"], "observation": observation.payload}, ensure_ascii=False, default=str),
        )
    _emit(tracer, progress_callback, "runtime.observe", event_data)
    return {"task": task}


# 无进展检测窗口：连续 _NO_PROGRESS_WINDOW 步状态签名不变视为振荡（AR2-4）。
# 两级响应：首次检出注入换策略反馈继续执行，提示后仍无进展才停止。
_NO_PROGRESS_WINDOW = 3


def _check_node(state: RuntimeGraphState, config: lc_runnables.RunnableConfig) -> dict:
    """检查节点：程序消耗一步预算，做无进展检测并判定完成/停止。"""
    cfg, _, tracer, pricing_available, progress_callback = _get_runtime_config(config)
    budget_state = state["budget_state"]
    budget_state.consume_step()
    budget = rt_budget.Budget(
        max_steps=cfg.runtime_max_steps,
        timeout_seconds=cfg.runtime_timeout_seconds,
        cost_limit=cfg.runtime_cost_limit if pricing_available else 0,
    )
    stop_reason = rt_budget.check_stop(budget_state, budget)
    completion = rt_completion.check_completion(state["task"])

    # 无进展检测（AR2-4）：签名窗口不变说明每步都"成功"但状态不推进
    update: dict = {}
    task = state["task"]
    signature = rt_state.state_signature(task)
    signatures = list(state.get("signatures") or [])
    hinted = bool(state.get("no_progress_hinted"))
    previous = signatures[-1] if signatures else None
    if previous is not None and signature != previous:
        hinted = False  # 状态重新推进，换策略提示标志复位
    signatures.append(signature)
    del signatures[:-_NO_PROGRESS_WINDOW]
    stalled = (
        len(signatures) == _NO_PROGRESS_WINDOW
        and len(set(signatures)) == 1
        and not completion.complete
        and not task.progress.terminal_reason
        and not stop_reason
    )
    if stalled:
        if not hinted:
            hinted = True
            update["decision_feedback"] = (
                f"最近{_NO_PROGRESS_WINDOW}步任务状态没有任何变化，"
                "请更换策略（换一种检索方式或调整参数），不要重复同一动作"
            )
            logger.warning("[runtime] 检测到无进展，注入换策略反馈: signature=%s", signature)
        else:
            stop_reason = "no_progress"
            logger.warning("[runtime] 换策略反馈后仍无进展，停止任务: signature=%s", signature)

    if stop_reason and stop_reason != "no_progress":
        logger.warning(
            "[runtime] 预算耗尽停止: reason=%s, steps=%d, elapsed=%.1fs, cost=%.4f",
            stop_reason, budget_state.steps_used,
            budget_state.elapsed_seconds(), budget_state.cost_used,
        )
    event_data = {
        "step": state["step_no"],
        "steps_used": budget_state.steps_used,
        "complete": completion.complete,
        "missing": completion.missing,
        "terminal_reason": task.progress.terminal_reason,
        "stop_reason": stop_reason,
        "signature": signature,
        "elapsed_ms": round(budget_state.elapsed_seconds() * 1000),
        "cost": round(budget_state.cost_used, 6),
        "cost_budget_enabled": pricing_available,
    }
    _emit(tracer, progress_callback, "runtime.check", event_data)
    update.update({
        "stop_reason": stop_reason,
        "signatures": signatures,
        "no_progress_hinted": hinted,
    })
    return update


def _finish_node(state: RuntimeGraphState, config: lc_runnables.RunnableConfig) -> dict:
    """收尾节点：组装最终输出与照片引用，并输出轨迹摘要。"""
    cfg, _, tracer, _, progress_callback = _get_runtime_config(config)
    output = rt_state.build_final_output(state["task"], stop_reason=state.get("stop_reason", ""))

    photos: list[dict] = []
    for photo in caps_common.fetch_photos_batch(cfg, state["task"].artifacts.selected_ids):
        pid = photo.get("id", "")
        photos.append({
            "photo_id": pid,
            "filename": photo.get("filename", pid),
            "image_url": f"{cfg.go_backend_url}/api/v1/photos/{pid}/image",
        })

    completion = rt_completion.check_completion(state["task"])
    task = state["task"]
    capability_calls: dict[str, int] = {}
    for item in task.progress.history:
        if item.get("action"):
            capability_calls[item["action"]] = capability_calls.get(item["action"], 0) + 1
    logger.info(
        "[runtime] 任务结束: complete=%s, terminal=%s, stop=%s, steps=%d, photos=%d",
        completion.complete, task.progress.terminal_reason,
        state.get("stop_reason", ""), state["budget_state"].steps_used, len(photos),
    )
    event_data = {
        "steps_used": state["budget_state"].steps_used,
        "capability_calls": capability_calls,
        "recovery_used": dict(state["budget_state"].recovery_used),
        "milestones_done": [m for m in ("locate", "candidates", "select", "copy")
                            if m not in task.progress.todo],
        "todo_left": list(task.progress.todo),
        "complete": completion.complete,
        "terminal_reason": task.progress.terminal_reason,
        "stop_reason": state.get("stop_reason", ""),
        "photo_count": len(photos),
        "cost": round(state["budget_state"].cost_used, 6),
    }
    _emit(tracer, progress_callback, "runtime.trace_summary", event_data)
    return {
        "answer": output["answer"],
        "photos": photos,
        "compose_url": output["handoff_url"],
    }


# --------------------------------------------------
# 条件路由 — 程序判定（不经 LLM）
# --------------------------------------------------

def _route_after_guardrail(state: RuntimeGraphState) -> str:
    """护栏结论路由：重试/修复 → execute，再决策 → decide，预算停止 → finish，其余 → reduce。"""
    action = state.get("guardrail_action", rt_guardrail.ACTION_ACCEPT)
    if action in (rt_guardrail.ACTION_RETRY, rt_guardrail.ACTION_REPAIR):
        return "execute"
    if action == rt_guardrail.ACTION_REDECIDE:
        return "decide"
    if action == rt_guardrail.ACTION_BUDGET_STOP:
        return "finish"
    # accept / fallback / stop：观察（或替换后的终态观察）进入归约
    return "reduce"


def _route_after_check(state: RuntimeGraphState) -> str:
    """条件回环：完成 / 兜底终止 / 停止（预算/无进展）→ finish，否则 → decide。"""
    if state.get("stop_reason"):
        return "finish"
    if state["task"].progress.terminal_reason:
        return "finish"
    if rt_completion.check_completion(state["task"]).complete:
        return "finish"
    return "decide"


# --------------------------------------------------
# LLM 成本回调与图装配
# --------------------------------------------------

class _CostCallback(lc_callbacks.BaseCallbackHandler):
    """把每次 LLM 调用的估算成本累加进预算（人民币元）。"""

    def __init__(self, prices: dict, budget_state: rt_budget.BudgetState):
        self._prices = prices or {}
        self._budget_state = budget_state

    def on_llm_end(self, response, **kwargs) -> None:
        llm_output = getattr(response, "llm_output", None) or {}
        usage = llm_output.get("token_usage", {})
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        if not (input_tokens or output_tokens):
            return
        model = (llm_output.get("model_name", "") or
                 getattr(response, "model_name", "") or "")
        price = self._prices.get(model) or {}
        cost = (
            input_tokens / 1_000_000.0 * price.get("input", 0.0)
            + output_tokens / 1_000_000.0 * price.get("output", 0.0)
        )
        self._budget_state.add_cost(cost)


# Runtime 循环图单例
_runtime_app: typing.Any = None


def _get_runtime_graph():
    global _runtime_app
    if _runtime_app is None:
        g = lg_graph.StateGraph(RuntimeGraphState)
        g.add_node("decide", _decide_node)
        g.add_node("execute", _execute_node)
        g.add_node("guardrail", _guardrail_node)
        g.add_node("reduce", _reduce_node)
        g.add_node("check", _check_node)
        g.add_node("finish", _finish_node)
        g.add_edge(lg_graph.START, "decide")
        g.add_edge("decide", "execute")
        g.add_edge("execute", "guardrail")
        g.add_conditional_edges(
            "guardrail", _route_after_guardrail,
            {"execute": "execute", "decide": "decide", "reduce": "reduce", "finish": "finish"},
        )
        g.add_edge("reduce", "check")
        g.add_conditional_edges(
            "check", _route_after_check,
            {"decide": "decide", "finish": "finish"},
        )
        g.add_edge("finish", lg_graph.END)
        _runtime_app = g.compile()
    return _runtime_app


def run_runtime(
    cfg,
    question: str,
    granularity: str = "photo",
    llm_callbacks: list | None = None,
    prices: dict | None = None,
    pricing_available: bool = True,
    tracer=None,
    progress_callback: typing.Callable[[str, dict], None] | None = None,
) -> dict:
    """执行一次开放目标任务，返回 {"answer", "photos", "compose_url"}。"""
    budget_state = rt_budget.BudgetState()
    callbacks = [*(llm_callbacks or []), _CostCallback(prices, budget_state)]
    translator = rt_progress.RuntimeProgressTranslator()

    def emit_progress(event: str, data: dict) -> None:
        if progress_callback is not None:
            progress_callback("runtime.step", {"steps": translator.consume(event, data)})

    initial: RuntimeGraphState = {
        "question": question,
        "granularity": granularity,
        "task": rt_state.new_task(
            rt_state.GOAL_SOCIAL_POST, question, {"question": question},
        ),
        "decision": {},
        "observation": rt_state.Observation("", ""),
        "budget_state": budget_state,
        "step_no": 0,
        "stop_reason": "",
        "answer": "",
        "photos": [],
        "compose_url": "",
        "decision_feedback": "",
        "guardrail_action": "reduce",
        "guardrail_ordinal": 0,
        "signatures": [],
        "no_progress_hinted": False,
    }
    # 每步迭代消耗 5 个图节点（decide/execute/guardrail/reduce/check）；
    # 恢复回环（重试/修复每次 2 节点、再决策每次 3 节点）按恢复预算放大上限
    recovery = rt_guardrail.recovery_budget_from_config(cfg)
    runtime_config = {
        "configurable": {
            "cfg": cfg,
            "llm_callbacks": callbacks,
            "pricing_available": pricing_available,
            "tracer": tracer,
            "progress_callback": emit_progress,
        },
        "recursion_limit": max(
            100,
            cfg.runtime_max_steps * (5 + 2 * (recovery.retry_max + recovery.repair_max))
            + 3 * recovery.redecide_max + 10,
        ),
    }
    result = _get_runtime_graph().invoke(initial, runtime_config)
    return {
        "answer": result.get("answer", ""),
        "photos": result.get("photos", []),
        "compose_url": result.get("compose_url", ""),
        "terminal_reason": result["task"].progress.terminal_reason,
        "stop_reason": result.get("stop_reason", ""),
        "recovery_used": dict(result["budget_state"].recovery_used),
        "clarification": result["task"].resolved_facts.get("clarification") or {},
    }
