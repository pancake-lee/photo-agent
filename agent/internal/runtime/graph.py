"""
    Agent Runtime 编排外壳（LangGraph）。

    LangGraph 只承担编排：decide → execute → reduce → check 循环图与条件回环，
    换取节点执行、条件路由与 checkpoint 就绪能力。业务语义全部在框架无关的
    runtime 核心模块中（state / budget / completion / registry / capabilities）。

    节点与流转按「是否需要 LLM」分类：
        - decide   LLM 决策点（唯一）：模型在能力清单中选择下一动作和参数，
                   能力清单与各能力的选择规则以提示词提供（registry.specs + decide_hint）
        - execute  程序节点：参数校验 + 能力调用（能力内是否用 LLM 见 capabilities/ 分类）
        - reduce   程序节点：把观察按显式规则归约进 TaskState
        - check    程序节点：预算消耗与完成/停止判定
        - finish   程序节点：最终输出组装
        - 节点间流转全部是程序行为：固定边 decide→execute→reduce→check，
          条件路由 _route_after_check 决定回环或收尾，不经 LLM
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
    budget_state: rt_budget.BudgetState   # 就地消耗（步数/成本累加），不整体替换
    step_no: int
    stop_reason: str           # 预算停止原因（check 填写）
    answer: str
    photos: list[dict]
    compose_url: str


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

    missing = rt_completion.check_completion(task).missing
    llm = llm_factory.create_llm(cfg, temperature=0.0, callbacks=callbacks or None)
    started_at = time.perf_counter()
    response = llm.invoke([
        lc_messages.SystemMessage(content=_decide_system_prompt(registry)),
        lc_messages.HumanMessage(content=(
            f"能力列表:\n{json.dumps(registry.specs(), ensure_ascii=False)}\n\n"
            f"当前任务状态:\n{rt_state.summarize_state(task)}\n\n"
            f"完成要件缺口: {'、'.join(missing) if missing else '无'}\n\n"
            "选择下一步动作。"
        )),
    ])
    duration_ms = round((time.perf_counter() - started_at) * 1000)
    parsed = caps_common.extract_json_dict(str(response.content)) or {}
    decision = {
        "action": str(parsed.get("action") or ""),
        "params": parsed.get("params") if isinstance(parsed.get("params"), dict) else {},
        "reason": str(parsed.get("reason") or ""),
    }
    logger.info(
        "[runtime] 第 %d 步决策: action=%s, params=%s",
        state["step_no"] + 1, decision["action"], decision["params"],
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
    return {"decision": decision, "step_no": state["step_no"] + 1}


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
        )
    else:
        capability = registry.get(action)
        ctx = rt_registry.RunContext(
            cfg=cfg,
            granularity=state.get("granularity", "photo"),
            question=state["question"],
            state=state["task"],
            llm_callbacks=callbacks,
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
    }
    _emit(tracer, progress_callback, "runtime.observe", event_data)
    return {"task": task}


def _check_node(state: RuntimeGraphState, config: lc_runnables.RunnableConfig) -> dict:
    """检查节点：程序消耗一步预算并判定完成/停止。"""
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
    if stop_reason:
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
        "terminal_reason": state["task"].progress.terminal_reason,
        "stop_reason": stop_reason,
        "elapsed_ms": round(budget_state.elapsed_seconds() * 1000),
        "cost": round(budget_state.cost_used, 6),
        "cost_budget_enabled": pricing_available,
    }
    _emit(tracer, progress_callback, "runtime.check", event_data)
    return {"stop_reason": stop_reason}


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

def _route_after_check(state: RuntimeGraphState) -> str:
    """条件回环：完成 / 兜底终止 / 预算停止 → finish，否则 → decide。"""
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
        g.add_node("reduce", _reduce_node)
        g.add_node("check", _check_node)
        g.add_node("finish", _finish_node)
        g.add_edge(lg_graph.START, "decide")
        g.add_edge("decide", "execute")
        g.add_edge("execute", "reduce")
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
    }
    # 每步迭代消耗 4 个图节点，递归上限按预算步数放大并留出收尾余量
    runtime_config = {
        "configurable": {
            "cfg": cfg,
            "llm_callbacks": callbacks,
            "pricing_available": pricing_available,
            "tracer": tracer,
            "progress_callback": emit_progress,
        },
        "recursion_limit": max(50, cfg.runtime_max_steps * 5),
    }
    result = _get_runtime_graph().invoke(initial, runtime_config)
    return {
        "answer": result.get("answer", ""),
        "photos": result.get("photos", []),
        "compose_url": result.get("compose_url", ""),
    }
