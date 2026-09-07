"""
    PhotoAgent — 照片库 AI 助手统一入口。

    整合能力:
        - LangGraph 查询路由（SQL / RAG 自动分发）
        - AI 工程保障：tenacity 重试、模型降级、Token 成本追踪
        - 全链路 CLI：聊天 / 评估 / 用量统计 / 场景演示

    用法:
        cd agent
        python cli/photo_agent.py -c ../.local/my-config.yaml          # 聊天模式 (CLI)
        python cli/photo_agent.py -c ../.local/my-config.yaml --serve  # API 服务（使用 Agent.Addr）
        python cli/photo_agent.py -c ../.local/my-config.yaml --serve 9999  # API 自定义端口
        python cli/photo_agent.py -c ../.local/my-config.yaml --eval   # 评估模式
        python cli/photo_agent.py -c ../.local/my-config.yaml --usage  # 用量统计
        python cli/photo_agent.py -c ../.local/my-config.yaml --demo   # 场景演示
        python cli/photo_agent.py -c ../.local/my-config.yaml --suggest # 选题建议
        python cli/photo_agent.py -c ../.local/my-config.yaml sessions list         # 列出会话
        python cli/photo_agent.py -c ../.local/my-config.yaml sessions resume <id>  # 恢复会话
"""

import argparse
import json
import logging
import pathlib
import sys
import time
import typing


import langchain_core.callbacks as lc_callbacks
import langchain_core.messages as lc_messages
import langchain_core.prompts as lc_prompts
import langchain_core.runnables as lc_runnables
import langgraph.graph as lg_graph
import yaml

# 允许从任意目录直接运行 `python cli/photo_agent.py`。
_AGENT_DIR = pathlib.Path(__file__).resolve().parents[1]
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

import cli.demo as demo
import internal.evals.evaluation as evaluation
import internal.chat.photo_rag as photo_rag
import internal.context.builder as ctx_builder
import internal.topics.suggest as suggest_mod
import internal.chat.text_to_sql as text_to_sql
import infra.config as config
import internal.runtime.capabilities.common as caps_common
import internal.runtime.graph as rt_graph
import internal.runtime.state as rt_state
import infra.openapi_client as openapi_client
import infra.llm_factory as llm_factory
import infra.request_metrics as request_metrics
import infra.token_tracker as token_tracker


# ============================================================================
# LangGraph 查询路由
# ============================================================================

class RouterState(typing.TypedDict):
    """查询路由的共享 State。"""
    question: str
    history_block: str              # 会话紧凑历史块（V4 Context Builder 产物，首条消息为空）
    effective_question: str         # 下游实际消费的问题：跟进消息为指代消解后的独立完整请求
    followup: bool                  # 是否为跟进消息（引用/修改此前会话结果）
    granularity: str                # 检索粒度 photo/fine/coarse，见 photo_rag.GRANULARITY_COLLECTIONS
    query_type: str
    sql_result: dict
    rag_answer: str
    tool_answer: str
    combined_result: dict           # {sql_ids, rag_ids, intersection_ids, answer}
    answer: str
    photos: list[dict]
    compose_url: str                # Runtime 兜底深链（候选超限时引导进图文工坊）
    runtime_terminal_reason: str
    runtime_clarification: dict
    runtime_goal_type: str
    runtime_affected: list[str]     # 跟进消解声明的受影响部分（resume_task 词汇表）
    runtime_goal_declared: bool     # 跟进消解是否显式声明了目标类型（区分分类默认值）
    runtime_prior_task_json: str    # 会话层传入的 Runtime 任务快照（空串表示无）
    runtime_task_dump: str          # 本次 Runtime 运行的任务快照（JSON，会话层保存）
    execution_status: str           # completed / partial / failed，供请求级汇总
    request_usage: dict             # 当前请求累计的 LLM 用量


# 分类规则主体；无历史时直接拼问题，有历史时插入 followup 标签与历史块（V4）
_CLASSIFY_RULES = (
    "你是一个查询分类器。判断用户对照片库的提问属于哪种类型，只回答 sql、rag、tool、combined、runtime_post、runtime_comparison 或 runtime_topics，不要解释。\n\n"
    "runtime_post: 用户提出开放目标，需要挑选照片并生成标题、发布文案等创作内容的多步任务；"
    "runtime_comparison: 用户要求比较两个时期/年份的照片，并基于两组照片总结变化、进步或差异；"
    "runtime_topics: 用户要求在明确照片范围内发现选题、主题候选或发布角度。"
    "以上三类即使同时有时间线或日期条件也优先进入对应 runtime。\n"
    "sql: 涉及统计计数、EXIF 参数筛选（品牌/型号/镜头/焦距/光圈/ISO/日期/GPS）、"
    "数量聚合的结构化查询\n"
    "rag: 涉及照片内容描述、场景、物体、颜色、情感、构图、风格、氛围的纯语义检索\n"
    "tool: 涉及照片列表、时间线查看、标签筛选、单张照片详情、归档操作等"
    "需要调用 API 的查询\n"
    "combined: 同时包含结构化维度筛选 + 语义内容检索的查询。"
    "即用户既指定了光线/色调/情绪/场景等可枚举维度，又描述了画面内容\n\n"
    "示例:\n"
    "- \"我有多少张照片？\" → sql\n"
    "- \"用 Nikon 拍的照片有哪些？\" → sql\n"
    "- \"2024 年 3 月拍了几张？\" → sql\n"
    "- \"找一下日落时分的照片\" → rag\n"
    "- \"有猫咪的照片吗？\" → rag\n"
    "- \"ISO 大于 1600 的照片\" → sql\n"
    "- \"红墙前的照片\" → rag\n"
    "- \"湖边的风景照\" → rag\n"
    "- \"列出所有时间线\" → tool\n"
    "- \"查看某张照片详情\" → tool\n"
    "- \"按标签筛选照片\" → tool\n"
    "- \"蓝调时刻的街拍\" → combined\n"
    "- \"暖色调的人像\" → combined\n"
    "- \"逆光的雪山照片\" → combined\n"
    "- \"黑白高对比度的建筑\" → combined\n"
    "- \"宁静氛围的水边照片\" → combined\n\n"
    "- \"找山西旅游第一天的照片并生成发布文案\" → runtime\n\n"
)

CLASSIFY_SYSTEM = _CLASSIFY_RULES + (
    "用户问题: {question}\n"
    "分类:"
)

# 有会话历史时的分类提示词：增加 followup 标签，跟进消息不走七类（AR18 最小切片）
CLASSIFY_SYSTEM_WITH_HISTORY = _CLASSIFY_RULES + (
    "followup: 用户消息引用、修改或追问此前会话的结果（如「刚才那组」「不要那么文艺」"
    "「第二组再补两张不同场景」），需要结合会话历史才能理解，不是新的独立请求；"
    "会话存在时此类消息优先判为 followup\n\n"
    "会话历史（更早摘要与最近原文，仅供理解指代）:\n{history}\n\n"
    "用户问题: {question}\n"
    "分类:"
)

# 跟进消解：把跟进消息改写为独立完整请求，并声明处理路径与受影响部分。
# 模板内 JSON 示例的花括号一律双写转义（ChatPromptTemplate 变量语法）。
FOLLOWUP_RESOLVE_SYSTEM = (
    "你是会话跟进消息消解器。用户在已有会话中发来一条消息，把它改写为不依赖会话"
    "也能理解的独立完整请求，并给出处理路径与受影响部分。\n"
    '只输出 JSON: {{"rewritten": "改写后的独立完整请求", '
    '"target": "sql|rag|tool|combined|runtime", '
    '"affected": ["scope"|"selection"|"selection_add"|"copy"|"report"|"topics"], '
    '"goal_type": "social_post|photo_comparison|topic_discovery"}}\n'
    "target 规则: 修改或追加此前开放目标（选片发帖/跨期对比/主题发现）的填 runtime；"
    "普通检索、统计、工具操作按 sql/rag/tool/combined 选择。\n"
    "affected 仅在 target=runtime 时填写，可多选: 照片范围变动填 scope，"
    "在已选照片基础上追加或补充填 selection_add（已选照片会被保留），"
    "整体换一批或重新挑选填 selection（已选照片不保留），"
    "仅改文案或风格填 copy，重写对比结论填 report，"
    "重新发现主题填 topics；补选还是重选不确定时填 selection_add。\n"
    "goal_type 仅在 target=runtime 时填写，沿用会话中此前开放目标的类型。\n"
    "改写要求: 保留用户此前的有效约束（日期、范围、数量），合并本次的新要求；"
    "指代（如「刚才那组」「第二组」）必须展开为具体所指。\n"
    "示例:\n"
    "历史最近一轮: 用户「找山西旅游第一天的照片并生成发布文案」，助手交付了 8 张照片和文案；"
    "用户说「不要那么文艺」→ "
    '{{"rewritten": "找山西旅游第一天的照片并生成发布文案，文案风格平实不要文艺", '
    '"target": "runtime", "affected": ["copy"], "goal_type": "social_post"}}\n'
    "用户说「再补两个不同场景」→ "
    '{{"rewritten": "找山西旅游第一天的照片并生成发布文案，在已选照片外再补两个不同场景", '
    '"target": "runtime", "affected": ["selection_add", "copy"], "goal_type": "social_post"}}\n\n'
    "会话历史（更早摘要与最近原文）:\n{history}\n\n"
    "用户消息: {question}\n"
    "输出:"
)


def _get_cfg(config: lc_runnables.RunnableConfig) -> config.Config:
    cfg = config.get("configurable", {}).get("cfg")
    if cfg is None:
        raise RuntimeError("Config 未注入到 configurable 中")
    return cfg


def _classify_node(state: RouterState, config: lc_runnables.RunnableConfig) -> dict:
    cfg = _get_cfg(config)
    llm = llm_factory.create_llm(cfg, temperature=0.0, callbacks=_get_callbacks())
    history_block = state.get("history_block", "")
    template = CLASSIFY_SYSTEM_WITH_HISTORY if history_block else CLASSIFY_SYSTEM
    prompt = lc_prompts.ChatPromptTemplate.from_messages([("system", template)])
    chain = prompt | llm
    invoke_vars = {"question": state["question"]}
    if history_block:
        invoke_vars["history"] = history_block
    response = chain.invoke(invoke_vars)
    raw = str(response.content).strip().lower()
    goal_type = rt_state.GOAL_SOCIAL_POST
    if "followup" in raw and history_block:
        query_type = "followup"
    elif "runtime_comparison" in raw:
        query_type = "runtime"
        goal_type = rt_state.GOAL_PHOTO_COMPARISON
    elif "runtime_topics" in raw:
        query_type = "runtime"
        goal_type = rt_state.GOAL_TOPIC_DISCOVERY
    elif "runtime" in raw or "compose" in raw:
        query_type = "runtime"
    elif "combined" in raw:
        query_type = "combined"
    elif "sql" in raw:
        query_type = "sql"
    elif "tool" in raw:
        query_type = "tool"
    else:
        query_type = "rag"
    logging.getLogger(__name__).info(
        "[路由] 「%s」 → %s（模型原始分类=%r）", state["question"], query_type, raw,
    )
    tracer = config.get("configurable", {}).get("tracer")
    if tracer is not None:
        tracer.emit("chat.route_decision", {
            "classifier_output": raw,
            "query_type": query_type,
            "runtime_goal_type": goal_type,
            "has_history": bool(history_block),
        }, module="chat")
    return {"query_type": query_type, "runtime_goal_type": goal_type}


# 跟进消解的合法输出取值（超出词表的值按兜底处理并告警）
_FOLLOWUP_TARGETS = ("sql", "rag", "tool", "combined", "runtime")
_FOLLOWUP_GOALS = (rt_state.GOAL_SOCIAL_POST, rt_state.GOAL_PHOTO_COMPARISON, rt_state.GOAL_TOPIC_DISCOVERY)


def _followup_resolve_node(state: RouterState, config: lc_runnables.RunnableConfig) -> dict:
    """跟进消解节点：改写为独立完整请求 + 处理路径 + 受影响部分（LLM 输出程序校验）。"""
    cfg = _get_cfg(config)
    _log = logging.getLogger(__name__)
    llm = llm_factory.create_llm(cfg, temperature=0.0, callbacks=_get_callbacks())
    prompt = lc_prompts.ChatPromptTemplate.from_messages([("system", FOLLOWUP_RESOLVE_SYSTEM)])
    chain = prompt | llm
    response = chain.invoke({
        "history": state.get("history_block", ""),
        "question": state["question"],
    })
    parsed = caps_common.extract_json_dict(str(response.content)) or {}
    target = str(parsed.get("target") or "").strip()
    if target not in _FOLLOWUP_TARGETS:
        _log.warning("[跟进消解] 非法 target=%r，按 rag 兜底", target)
        target = "rag"
    rewritten = str(parsed.get("rewritten") or "").strip() or state["question"]
    affected = [
        str(item) for item in (parsed.get("affected") or [])
        if str(item) in rt_state.affect_vocabulary()
    ]
    update: dict = {
        "query_type": target,
        "effective_question": rewritten,
        "followup": True,
        "runtime_affected": affected,
        "runtime_goal_declared": False,
    }
    goal_type = str(parsed.get("goal_type") or "").strip()
    if target == "runtime" and goal_type in _FOLLOWUP_GOALS:
        update["runtime_goal_type"] = goal_type
        update["runtime_goal_declared"] = True
    _log.info(
        "[跟进消解] 「%s」 → target=%s, affected=%s, 改写=「%s」",
        state["question"], target, affected, rewritten,
    )
    return update


def _effective_question(state: RouterState) -> str:
    """下游统一入口：跟进消息消费消解后的独立完整请求，其余等于原始问题。"""
    return state.get("effective_question") or state["question"]


def _sql_node(state: RouterState, config: lc_runnables.RunnableConfig) -> dict:
    cfg = _get_cfg(config)
    _log = logging.getLogger(__name__)
    try:
        result = text_to_sql.answer_with_sql(cfg, _effective_question(state))
        _log.info(
            "[sql] 查询完成: rows=%d, answer_chars=%d",
            len(result.get("results") or []),
            len(result.get("answer") or ""),
        )
    except Exception as exc:
        _log.exception("[sql] 查询异常")
        result = {
            "question": state["question"],
            "sql": "",
            "results": [],
            "answer": f"SQL 查询失败: {exc}",
        }
    return {"sql_result": result, "execution_status": "completed" if result.get("sql") else "failed"}


def _rag_node(state: RouterState, config: lc_runnables.RunnableConfig) -> dict:
    cfg = _get_cfg(config)
    granularity = state.get("granularity", "photo")
    _log = logging.getLogger(__name__)
    try:
        answer_text, photo_refs = photo_rag.answer_question(
            cfg, _effective_question(state),
            distance_threshold=cfg.rag_distance_threshold,
            auto_distance_ratio=cfg.rag_auto_distance_ratio,
            granularity=granularity,
        )
        _log.info("[RAG] 粒度=%s, 返回 %d 个照片引用", granularity, len(photo_refs))
    except Exception as exc:
        _log.exception("[RAG] 检索异常: %s", exc)
        answer_text = f"RAG 检索失败: {exc}"
        photo_refs = []
    return {"rag_answer": answer_text, "photos": photo_refs, "execution_status": "completed" if photo_refs else "partial"}


# 单次工具结果的截断长度，避免超出上下文
_TOOL_RESULT_MAX_LEN = 4000


def _tool_node(state: RouterState, config: lc_runnables.RunnableConfig) -> dict:
    """工具调用节点：使用 llm.bind_tools() 让 LLM 自主调用 Go API。

    支持多轮工具调用：模型每轮返回 tool_calls 就全部执行并继续下一轮，
    返回纯文本则作为最终答案；达到配置的最大轮数（llm.tool_max_rounds）后
    以不带工具的调用强制模型基于已收集信息做总结，避免任务静默中断。
    """
    cfg = _get_cfg(config)
    max_rounds = cfg.tool_max_rounds
    _log = logging.getLogger(__name__)

    try:
        # 获取或创建工具客户端（可能因 Go 后端不可达而失败）
        tool_client = _get_tool_client(cfg.go_backend_url)
        tools = tool_client.get_tools()
        tool_names = [tool.get("function", {}).get("name", "") for tool in tools]
        _log.info(
            "[tool] 工具已加载: count=%d, names=%s", len(tools), tool_names,
        )

        llm_with_tools = llm_factory.create_llm(
            cfg, temperature=0.3, callbacks=_get_callbacks(), tools=tools
        )
        # 兜底总结用：不绑定工具，模型只能输出文本
        llm_plain = llm_factory.create_llm(
            cfg, temperature=0.3, callbacks=_get_callbacks()
        )

        messages: list[lc_messages.BaseMessage] = [
            lc_messages.SystemMessage(content=_TOOL_SYSTEM_PROMPT),
            lc_messages.HumanMessage(content=_effective_question(state)),
        ]

        for round_no in range(1, max_rounds + 1):
            _log.info("[tool] 第 %d/%d 轮模型调用开始", round_no, max_rounds)
            started_at = time.perf_counter()
            response = llm_with_tools.invoke(messages)
            elapsed_ms = round((time.perf_counter() - started_at) * 1000)
            tool_calls = getattr(response, "tool_calls", None) or []
            _log.info(
                "[tool] 第 %d/%d 轮模型调用完成: duration_ms=%d, tool_call_count=%d, content_chars=%d",
                round_no, max_rounds, elapsed_ms,
                len(tool_calls), len(str(response.content)),
            )

            if not tool_calls:
                if round_no == 1:
                    _log.warning(
                        "[tool] 第 1 轮模型未发起工具调用，直接返回文本: content=%r",
                        str(response.content)[:500],
                    )
                return {"tool_answer": str(response.content)}

            # 执行本轮全部工具调用，结果以 ToolMessage 追加到对话后继续下一轮
            messages.append(response)
            for index, tc in enumerate(tool_calls, 1):
                tool_name = tc.get("name", "")
                tool_args = tc.get("args", {})
                _log.info(
                    "[tool] 执行调用 %d/%d: name=%s, arg_keys=%s",
                    index, len(tool_calls), tool_name, sorted(tool_args.keys()),
                )
                started_at = time.perf_counter()
                result = tool_client.execute(tool_name, tool_args)
                _log.info(
                    "[tool] 调用完成 %d/%d: name=%s, duration_ms=%d, result_chars=%d",
                    index, len(tool_calls), tool_name,
                    round((time.perf_counter() - started_at) * 1000), len(result),
                )
                if len(result) > _TOOL_RESULT_MAX_LEN:
                    result = (
                        result[:_TOOL_RESULT_MAX_LEN]
                        + f"\n...（结果已截断，原始长度 {len(result)}）"
                    )
                messages.append(
                    lc_messages.ToolMessage(
                        content=result,
                        tool_call_id=tc.get("id", ""),
                    )
                )

        # 达到最大轮数仍在发起工具调用：强制总结，避免静默截断
        _log.warning(
            "[tool] 达到最大轮数 %d 仍未收敛，追加无工具调用强制总结",
            max_rounds,
        )
        started_at = time.perf_counter()
        final_response = llm_plain.invoke(
            messages + [lc_messages.HumanMessage(
                content="已达到工具调用轮数上限，不要再调用工具。"
                "请基于以上已收集的信息，直接给出对用户问题的总结性回答。"
            )]
        )
        _log.info(
            "[tool] 兜底总结调用完成: duration_ms=%d, content_chars=%d",
            round((time.perf_counter() - started_at) * 1000),
            len(str(final_response.content)),
        )
        return {"tool_answer": str(final_response.content)}
    except Exception as exc:
        logging.getLogger(__name__).exception("_tool_node 执行失败")
        return {"tool_answer": f"工具调用失败: {exc}"}


_TOOL_SYSTEM_PROMPT = (
    "你是一位摄影档案助手，可以调用后端 API 帮助用户管理照片库。\n"
    "你可以分多轮调用工具：先规划步骤，逐步收集信息，信息不完整时继续调用工具，"
    "不要输出“我来查看”“接下来我会”这类中断性的中间表态。\n"
    "收集到足够信息后，一次性给出完整结果。回答简洁，控制在 300 字以内。"
)


def _combined_node(state: RouterState, config: lc_runnables.RunnableConfig) -> dict:
    """组合查询节点：SQL 结构化过滤 + RAG 语义检索 → 取交集。

    流程:
        1. Text-to-SQL 生成结构化过滤 → 执行 → sql_ids
        2. RAG 语义检索 → rag_ids（按相似度排序）
        3. 取交集（保持 RAG 相似度顺序）
        4. 交集非空 → 获取照片详情 → LLM 生成回答
        5. 交集为空 → 降级为纯 RAG
    """
    cfg = _get_cfg(config)
    question = _effective_question(state)
    granularity = state.get("granularity", "photo")
    _log = logging.getLogger(__name__)

    try:
        # Step 1: SQL 结构化过滤
        filter_sql = text_to_sql.generate_filter_sql(cfg, question)
        sql_ids = text_to_sql.execute_sql_for_ids(cfg.go_backend_url, filter_sql)
        _log.info(
            "[combined] SQL 过滤返回 %d 个 photo_id | SQL: %s",
            len(sql_ids), filter_sql,
        )

        # SQL 结果过多说明过滤太宽泛，降级为纯 RAG
        if len(sql_ids) > 50:
            _log.info("[combined] SQL 结果过多(%d > 50)，过滤太宽泛，降级为纯 RAG", len(sql_ids))
            answer_text, photo_refs = photo_rag.answer_question(
                cfg, question,
                distance_threshold=cfg.rag_distance_threshold,
                auto_distance_ratio=cfg.rag_auto_distance_ratio,
                granularity=granularity,
            )
            return {
                "combined_result": {
                    "sql_ids": sql_ids,
                    "rag_ids": [],
                    "intersection_ids": [],
                    "fallback": True,
                    "fallback_reason": "sql_too_broad",
                },
                "rag_answer": answer_text,
                "photos": photo_refs,
                "execution_status": "completed",
            }

        # SQL 无结果 → 降级
        if not sql_ids:
            _log.info("[combined] SQL 无结果，降级为纯 RAG")
            answer_text, photo_refs = photo_rag.answer_question(
                cfg, question,
                distance_threshold=cfg.rag_distance_threshold,
                auto_distance_ratio=cfg.rag_auto_distance_ratio,
                granularity=granularity,
            )
            return {
                "combined_result": {
                    "sql_ids": [],
                    "rag_ids": [],
                    "intersection_ids": [],
                    "fallback": True,
                    "fallback_reason": "sql_empty",
                },
                "rag_answer": answer_text,
                "photos": photo_refs,
                "execution_status": "completed",
            }

        # Step 2: RAG 语义检索（组粒度下命中的是连拍组封面）
        rag_ids, rag_results = photo_rag.retrieve_photo_ids(
            cfg, question,
            n_results=20,
            distance_threshold=cfg.rag_distance_threshold,
            auto_distance_ratio=cfg.rag_auto_distance_ratio,
            with_details=True,
            granularity=granularity,
        )
        _log.info("[combined] RAG 检索返回 %d 个 photo_id", len(rag_ids))

        # 封面 photo_id -> (group_id, photo_count)，用于给最终结果补组信息
        group_info: dict[str, tuple[str, int]] = {}
        for r in rag_results:
            meta = r.get("metadata") or {}
            gid = meta.get("group_id", "")
            pid = meta.get("photo_id", "")
            if gid and pid:
                group_info[pid] = (gid, int(meta.get("photo_count") or 0))

        # Step 3: 取交集（保持 RAG 相似度排序）
        sql_set = set(sql_ids)
        intersection_ids = [pid for pid in rag_ids if pid in sql_set]
        _log.info(
            "[combined] 交集: %d 个 photo_id (SQL %d ∩ RAG %d)",
            len(intersection_ids), len(sql_ids), len(rag_ids),
        )

        # Step 4: 交集为空 → 降级为纯 RAG
        if not intersection_ids:
            _log.info("[combined] 交集为空，降级为纯 RAG")
            answer_text, photo_refs = photo_rag.answer_question(
                cfg, question,
                distance_threshold=cfg.rag_distance_threshold,
                auto_distance_ratio=cfg.rag_auto_distance_ratio,
                granularity=granularity,
            )
            return {
                "combined_result": {
                    "sql_ids": sql_ids,
                    "rag_ids": rag_ids,
                    "intersection_ids": [],
                    "fallback": True,
                    "fallback_reason": "intersection_empty",
                },
                "rag_answer": answer_text,
                "photos": photo_refs,
                "execution_status": "completed",
            }

        # Step 5: 交集非空 → 获取照片详情并生成回答
        top_ids = intersection_ids[:5]  # 最多展示 5 张
        photo_details = caps_common.fetch_photos_batch(cfg, top_ids)

        # 构建上下文
        context_lines: list[str] = []
        photo_refs: list[dict] = []
        for i, pd in enumerate(photo_details, 1):
            pid = pd.get("id", "")
            desc = pd.get("description", "") or "无描述"
            context_lines.append(f"[{i}] 照片 {pid}\n描述: {desc}")
            ref = {
                "photo_id": pid,
                "filename": pd.get("filename", pid),
                "image_url": f"{cfg.go_backend_url}/api/v1/photos/{pid}/image",
            }
            if pid in group_info:
                gid, count = group_info[pid]
                ref["burst_group_id"] = gid
                ref["burst_count"] = count
            photo_refs.append(ref)

        context = "\n\n".join(context_lines)

        # LLM 生成回答
        llm = llm_factory.create_llm(
            cfg, temperature=0.5, callbacks=_get_callbacks(),
        )
        answer_prompt = lc_prompts.ChatPromptTemplate.from_messages([
            ("system",
             "你是一位摄影档案助手。根据下面经过结构化过滤的照片回答用户问题。"
             "使用 Markdown 图片语法展示照片: ![描述](图片URL)。"
             "回答简洁，控制在 200 字以内。"),
            ("human",
             "以下是通过光线/色调/场景/情绪等结构化维度 + 语义内容双重过滤后的照片:\n\n"
             "{context}\n\n"
             "用户问题: {question}"),
        ])
        chain = answer_prompt | llm
        response = chain.invoke({"context": context, "question": question})
        answer_text = str(response.content)

        _log.info("[combined] 最终回答基于 %d 张照片", len(photo_refs))

        return {
            "combined_result": {
                "sql_ids": sql_ids,
                "rag_ids": rag_ids,
                "intersection_ids": intersection_ids,
                "fallback": False,
            },
            "answer": answer_text,
            "photos": photo_refs,
            "execution_status": "completed",
        }
    except Exception as exc:
        _log.exception("[combined] 组合查询异常，降级为纯 RAG")
        try:
            answer_text, photo_refs = photo_rag.answer_question(
                cfg, question,
                distance_threshold=cfg.rag_distance_threshold,
                auto_distance_ratio=cfg.rag_auto_distance_ratio,
                granularity=granularity,
            )
        except Exception:
            answer_text = f"组合查询和 RAG 降级均失败: {exc}"
            photo_refs = []
        return {
            "combined_result": {
                "sql_ids": [],
                "rag_ids": [],
                "intersection_ids": [],
                "fallback": True,
                "fallback_reason": f"error: {exc}",
            },
            "rag_answer": answer_text,
            "photos": photo_refs,
            "execution_status": "partial",
        }


def _runtime_node(state: RouterState, config: lc_runnables.RunnableConfig) -> dict:
    """开放目标节点：进入 Runtime 多步执行（decide/execute/reduce/check 循环）。

    跟进消息携带任务快照时从先前任务局部失效后续跑（V4 多轮修改）；
    快照损坏按全新任务执行并告警，不让持久化数据问题打断会话。
    """
    cfg = _get_cfg(config)
    _log = logging.getLogger(__name__)
    configurable = config.get("configurable", {})
    progress_callback = configurable.get("progress_callback")
    if progress_callback is not None:
        progress_callback("runtime.started", {"message": "任务已进入多步处理"})
    prior_task = None
    prior_json = state.get("runtime_prior_task_json") or ""
    if state.get("followup") and prior_json:
        try:
            prior_task = rt_state.load_task(json.loads(prior_json))
        except (ValueError, KeyError, TypeError) as exc:
            _log.warning("[runtime] 任务快照不可用，按全新任务执行: %s", exc)
            prior_task = None
        if prior_task is not None and state.get("runtime_goal_declared"):
            # 消解显式声明的目标与快照目标不一致（如对发帖任务提对比跟进）：
            # 旧任务产物不适用于新目标，按声明的目标全新执行
            if state.get("runtime_goal_type") != prior_task.goal.goal_type:
                _log.info(
                    "[runtime] 跟进目标与快照目标不一致（%s ≠ %s），按全新任务执行",
                    state.get("runtime_goal_type"), prior_task.goal.goal_type,
                )
                prior_task = None
    if prior_task is not None:
        _log.info(
            "[runtime] 跟进续跑: goal=%s, affected=%s",
            prior_task.goal.goal_type, state.get("runtime_affected") or [],
        )
    result = rt_graph.run_runtime(
        cfg, _effective_question(state),
        granularity=state.get("granularity", "photo"),
        llm_callbacks=_get_callbacks(),
        prices=configurable.get("prices"),
        pricing_available=bool(configurable.get("pricing_available", True)),
        tracer=configurable.get("tracer"),
        progress_callback=progress_callback,
        goal_type=state.get("runtime_goal_type", rt_state.GOAL_SOCIAL_POST),
        prior_task=prior_task,
        affected=state.get("runtime_affected") or [],
    )
    return {
        "answer": result["answer"],
        "photos": result["photos"],
        "compose_url": result.get("compose_url", ""),
        "runtime_terminal_reason": result.get("terminal_reason", ""),
        "runtime_clarification": result.get("clarification", {}),
        "runtime_goal_type": result.get("goal_type", state.get("runtime_goal_type", rt_state.GOAL_SOCIAL_POST)),
        "runtime_task_dump": json.dumps(result.get("task_dump") or {}, ensure_ascii=False) if result.get("task_dump") else "",
        "execution_status": "completed" if result.get("completed") else "partial",
    }


def _answer_node(state: RouterState) -> dict:
    query_type = state["query_type"]
    if query_type == "runtime":
        text = state.get("answer") or "任务执行未返回结果。"
        if state.get("compose_url"):
            text += f"\n\n[进入图文工坊]({state['compose_url']})"
        photos = state.get("photos", [])
    elif query_type == "combined":
        combined = state.get("combined_result", {})
        if combined.get("fallback"):
            # 降级为 RAG，使用 rag_answer
            text = state.get("rag_answer") or "RAG 检索未返回结果。"
        else:
            text = state.get("answer") or "组合查询未返回结果。"
        photos = state.get("photos", [])
    elif query_type == "sql":
        result = state.get("sql_result", {})
        text = result.get("answer") or "SQL 查询未返回结果。"
        photos = []
    elif query_type == "tool":
        text = state.get("tool_answer") or "工具调用未返回结果。"
        photos = []
    else:
        text = state.get("rag_answer") or "RAG 检索未返回结果。"
        photos = state.get("photos", [])
    return {"answer": text, "photos": photos}


def _route_by_type(state: RouterState) -> str:
    return state["query_type"]


# 工具客户端单例（按 base_url 缓存）
# 设计说明: 以下模块级单例 (_tool_clients, _graph_app, _tracker, _callbacks)
# 在 PhotoAgent.__init__ 中初始化，进程生命周期内仅创建一次，避免重复创建
# 开销较大的 LangGraph 图和 HTTP 客户端。这是 FastAPI 单进程模式下的务实选择，
# 代价是测试时需手动重置这些状态。如需提升可测试性，可改为依赖注入。
_tool_clients: dict[str, openapi_client.OpenAPIClient] = {}


def _get_tool_client(base_url: str) -> openapi_client.OpenAPIClient:
    """获取或创建 OpenAPI 工具客户端（按 base_url 缓存）。"""
    if base_url not in _tool_clients:
        _tool_clients[base_url] = openapi_client.OpenAPIClient(base_url)
    return _tool_clients[base_url]


# LangGraph app 单例
_graph_app: typing.Any = None


def _get_graph():
    global _graph_app
    if _graph_app is None:
        g = lg_graph.StateGraph(RouterState)
        g.add_node("classify", _classify_node)
        g.add_node("followup_resolve", _followup_resolve_node)
        g.add_node("sql_query", _sql_node)
        g.add_node("rag_query", _rag_node)
        g.add_node("tool_query", _tool_node)
        g.add_node("combined_query", _combined_node)
        g.add_node("runtime_query", _runtime_node)
        g.add_node("answer", _answer_node)
        g.add_edge(lg_graph.START, "classify")
        g.add_conditional_edges(
            "classify", _route_by_type,
            {
                "sql": "sql_query",
                "rag": "rag_query",
                "tool": "tool_query",
                "combined": "combined_query",
                "runtime": "runtime_query",
                "followup": "followup_resolve",
            },
        )
        g.add_conditional_edges(
            "followup_resolve", _route_by_type,
            {
                "sql": "sql_query",
                "rag": "rag_query",
                "tool": "tool_query",
                "combined": "combined_query",
                "runtime": "runtime_query",
            },
        )
        g.add_edge("sql_query", "answer")
        g.add_edge("rag_query", "answer")
        g.add_edge("tool_query", "answer")
        g.add_edge("combined_query", "answer")
        g.add_edge("runtime_query", "answer")
        g.add_edge("answer", lg_graph.END)
        _graph_app = g.compile()
    return _graph_app


# Token tracker 全局单例（由 PhotoAgent.__init__ 注入）
_tracker: token_tracker.TokenTracker | None = None
_callbacks: list[lc_callbacks.BaseCallbackHandler] = []


def _get_tracker() -> token_tracker.TokenTracker:
    global _tracker
    if _tracker is None:
        _tracker = token_tracker.TokenTracker(":memory:")
    return _tracker


def _get_callbacks() -> list[lc_callbacks.BaseCallbackHandler]:
    global _callbacks
    return _callbacks


# ============================================================================
# PhotoAgent 主类
# ============================================================================

class PhotoAgent:
    """照片 AI 助手统一入口，整合 LangGraph 路由 + AI 工程保障。

    用法:
        agent = PhotoAgent(cfg)
        result = agent.route("我有多少张照片？")
        print(result["answer"])
    """

    def __init__(self, cfg: config.Config):
        self._cfg = cfg
        self._app = _get_graph()

        # 初始化 Token 追踪
        prices: dict[str, dict[str, float]] | None = None
        pricing_error = ""
        try:
            loaded_prices = token_tracker.load_prices(
                cfg.resolve_path(cfg.prices_path).as_posix()
            )
            token_tracker.validate_model_prices(
                loaded_prices, cfg.llm_model, cfg.llm_fallback_model, cfg.embedding_model
            )
            prices = loaded_prices
        except (OSError, ValueError, yaml.YAMLError) as exc:
            pricing_error = str(exc)
        # 价格表同时供 Runtime 预算的成本累加使用
        self._prices = prices
        self._pricing_error = pricing_error
        db_path = cfg.agent_path("sqlite", "token_usage.db").as_posix()
        db_path = str(pathlib.Path(db_path).resolve())
        pathlib.Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        global _tracker, _callbacks
        _tracker = token_tracker.TokenTracker(db_path, prices)
        _callbacks = [token_tracker.TokenCallback(_tracker)]

        _log = logging.getLogger(__name__)
        _log.info("PhotoAgent 初始化完成")
        _log.info("   主模型: %s", cfg.llm_model)
        if cfg.llm_fallback_model:
            _log.info("   降级模型: %s", cfg.llm_fallback_model)
        _log.info("   重试: %s（最多 %d 次）",
                  "开启" if cfg.retry_enabled else "关闭",
                  cfg.retry_max_attempts)
        if pricing_error:
            _log.warning(
                "价格配置不可用，已降级：Token 成本不追踪，Runtime 成本预算已停用。原因: %s",
                pricing_error,
            )
        else:
            _log.info("   Token 追踪: 已加载 %d 个模型单价（人民币元/百万 Token）", len(prices))

    def route(
        self,
        question: str,
        granularity: str = "photo",
        tracer=None,
        progress_callback=None,
        history: list[dict] | None = None,
        prior_runtime_task_json: str | None = None,
    ) -> RouterState:
        """路由单次查询，自动分发到 SQL / RAG / Tool / Combined / Runtime / 跟进消解分支。

        参数:
            question:    用户问题
            granularity: 检索粒度 photo/fine/coarse。photo 为单张照片检索（默认），
                         fine/coarse 走连拍组封面集合，一组只返回一个结果
            tracer:      可选 Tracer，Runtime 多步执行时输出步骤事件
            history:     会话历史消息（session_store.get_messages 产物）。
                         非空时构建紧凑历史块，分类可识别跟进消息（V4 多轮）
            prior_runtime_task_json: 会话层保存的 Runtime 任务快照（JSON），
                         跟进消息命中 Runtime 时局部失效后续跑
        """
        session_ctx = ctx_builder.build_session_context(history or [])
        initial: RouterState = {
            "question": question,
            "history_block": session_ctx.history_block,
            "effective_question": question,
            "followup": False,
            "granularity": granularity,
            "query_type": "",
            "sql_result": {},
            "rag_answer": "",
            "tool_answer": "",
            "combined_result": {},
            "answer": "",
            "photos": [],
            "compose_url": "",
            "runtime_terminal_reason": "",
            "runtime_clarification": {},
            "runtime_goal_type": rt_state.GOAL_SOCIAL_POST,
            "runtime_affected": [],
            "runtime_goal_declared": False,
            "runtime_prior_task_json": prior_runtime_task_json or "",
            "runtime_task_dump": "",
            "execution_status": "",
            "request_usage": {},
        }
        usage, usage_token = request_metrics.begin_request(self._prices)
        started_at = time.perf_counter()
        try:
            runtime_config = {
                "configurable": {
                    "cfg": self._cfg,
                    "prices": self._prices,
                    "pricing_available": not self._pricing_error,
                    "tracer": tracer,
                    "progress_callback": progress_callback,
                },
            }
            result = self._app.invoke(initial, runtime_config)
            routed = typing.cast(RouterState, result)
            usage_snapshot = usage.snapshot()
            execution_mode = "general_agent" if routed["query_type"] == "runtime" else f"direct_{routed['query_type']}"
            summary = {
                "query_type": routed["query_type"],
                "execution_mode": execution_mode,
                "execution_status": routed.get("execution_status") or "completed",
                "runtime_terminal_reason": routed.get("runtime_terminal_reason", ""),
                "duration_ms": round((time.perf_counter() - started_at) * 1000),
                **usage_snapshot,
            }
            if tracer is not None:
                tracer.emit("chat.execution_summary", summary, module="chat")
            routed["request_usage"] = usage_snapshot
            return routed
        except Exception:
            if tracer is not None:
                tracer.emit("chat.execution_summary", {
                    "query_type": "",
                    "execution_mode": "unknown",
                    "execution_status": "failed",
                    "duration_ms": round((time.perf_counter() - started_at) * 1000),
                    **usage.snapshot(),
                }, module="chat")
            raise
        finally:
            request_metrics.end_request(usage_token)

    @property
    def tracker(self) -> token_tracker.TokenTracker:
        return _get_tracker()

    @property
    def cfg(self) -> config.Config:
        return self._cfg

    @property
    def pricing_status(self) -> dict[str, str | bool]:
        """返回价格配置的当前状态，供服务诊断与健康检查使用。"""
        return {
            "available": not self._pricing_error,
            "error": self._pricing_error,
        }


# ============================================================================
# 交互式聊天
# ============================================================================

def _chat_loop(agent: PhotoAgent) -> None:
    """交互式聊天循环，LangGraph 自动路由 SQL / RAG / Tool。"""
    print("=" * 60)
    print("PhotoAgent 聊天已启动（LangGraph 路由: SQL / RAG / Tool）")
    print(f"   Go 后端: {agent.cfg.go_backend_url}")
    print("   输入 exit 或按 Ctrl+C 退出")
    print("=" * 60)
    print()

    while True:
        try:
            user_input = input("你: ")
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if user_input.lower() == "exit":
            break
        if not user_input.strip():
            continue

        result = agent.route(user_input)
        query_type = result["query_type"]

        route_name = {
            "sql": "SQL 统计查询",
            "rag": "RAG 语义检索",
            "tool": "Tool API 调用",
            "combined": "Combined 组合查询",
            "runtime": "Runtime 多步执行",
        }.get(query_type, "未知路由")
        print(f"路由: {route_name}")

        if query_type == "combined":
            combined = result.get("combined_result", {})
            if combined.get("fallback"):
                reason = combined.get("fallback_reason", "未知")
                print(f"(组合查询降级: {reason})")
            else:
                print(f"SQL ∩ RAG: {len(combined.get('intersection_ids', []))} 张匹配照片")
        print()

        if query_type == "sql":
            sql_result = result.get("sql_result", {})
            print(f"SQL: {sql_result.get('sql', 'N/A')}")
            print(f"结果数: {len(sql_result.get('results') or [])}")
            print(f"{sql_result.get('answer', '')}")
        else:
            print(f"{result['answer']}")
        print()
        print("=" * 60)
        print()


# ============================================================================
# 用量查看
# ============================================================================

def _print_usage(tracker: token_tracker.TokenTracker, days: int = 7) -> None:
    """打印 Token 用量统计。"""
    print(f"Token 用量统计（最近 {days} 天）")
    print("=" * 60)

    summary = tracker.summary(days=days)
    if not summary:
        print("  暂无数据")
        print()
        return

    total_cost = 0.0
    has_untracked_cost = False
    print()
    print("按模型汇总:")
    for row in summary:
        print(f"  {row['model']}:")
        print(f"    调用次数: {row['calls']}")
        print(f"    Input:  {row['total_input']:,} tokens")
        print(f"    Output: {row['total_output']:,} tokens")
        if row["cost_tracked"]:
            print(f"    费用:   ${row['total_cost']:.6f}")
            total_cost += row["total_cost"]
        else:
            print("    费用:   未追踪（价格配置不可用）")
            has_untracked_cost = True
    print("  ────────────────────")
    if has_untracked_cost:
        print("  总费用: 不完整（存在未追踪成本的调用）")
    else:
        print(f"  总费用: ${total_cost:.6f}")
    print()

    daily = tracker.daily_breakdown(days=days)
    if daily:
        print("按天拆分:")
        current_day = ""
        for row in daily:
            if row["day"] != current_day:
                current_day = row["day"]
                print(f"  {current_day}:")
            cost_text = (
                f"${row['total_cost']:.6f}"
                if row["cost_tracked"]
                else "未追踪"
            )
            print(f"    {row['model']}: {row['calls']} 次 "
                  f"| 入 {row['total_input']:,} / 出 {row['total_output']:,} "
                  f"| {cost_text}")
    print()


# ============================================================================
# CLI 入口
# ============================================================================

def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="PhotoAgent — 照片库 AI 助手",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python cli/photo_agent.py -c config.yaml              # 交互式聊天 (CLI)
  python cli/photo_agent.py -c config.yaml --serve      # API 服务（使用 Agent.Addr）
  python cli/photo_agent.py -c config.yaml --serve -l   # API 服务，控制台文本日志
  python cli/photo_agent.py -c config.yaml --serve 9999 # API 自定义端口
  python cli/photo_agent.py -c config.yaml --eval       # 评估模式
  python cli/photo_agent.py -c config.yaml --usage      # 用量统计
  python cli/photo_agent.py -c config.yaml --demo       # 场景演示
  python cli/photo_agent.py -c config.yaml --suggest    # 选题建议
  python cli/photo_agent.py -c config.yaml --usage 30   # 最近 30 天用量
  python cli/photo_agent.py -c config.yaml sessions list        # 列出所有会话
  python cli/photo_agent.py -c config.yaml sessions resume <id> # 恢复会话
        """,
    )
    parser.add_argument(
        "-c", "--config", dest="config", required=True,
        help="YAML 配置文件路径",
    )
    parser.add_argument(
        "--eval", dest="eval_mode", action="store_true",
        help="运行 RAG 检索评估",
    )
    parser.add_argument(
        "--demo", dest="demo_mode", action="store_true",
        help="运行全链路场景演示",
    )
    parser.add_argument(
        "--usage", dest="usage_days", nargs="?", const=7, type=int, default=None,
        help="查看 Token 用量统计，可选指定天数（默认 7 天）",
    )
    parser.add_argument(
        "--serve", dest="serve_port", nargs="?", const=0, type=int, default=None,
        metavar="PORT",
        help="启动 HTTP API 服务（默认使用 Agent.Addr，可选覆盖端口）",
    )
    parser.add_argument(
        "-l", dest="console_logging", action="store_true",
        help="服务模式输出人类可读的控制台日志；JSONL 文件日志始终保留",
    )
    parser.add_argument(
        "--suggest", dest="suggest_mode", action="store_true",
        help="运行潜在主题识别，输出选题建议列表",
    )
    parser.add_argument(
        "sessions_command", nargs="*", default=None,
        help="会话管理: sessions list | sessions resume <session_id>",
    )
    return parser


def _handle_sessions(cfg: config.Config, cmd: list[str]) -> None:
    """处理 sessions 子命令。"""
    import internal.chat.session_store as session_store

    db_path = cfg.resolve_path(
        getattr(cfg, "chat_db_path", "") or "./data/agent/sqlite/chat_sessions.db"
    ).as_posix()
    store = session_store.SessionStore(db_path)

    if not cmd or cmd[0] != "sessions":
        print("用法: sessions list | sessions resume <session_id>")
        return

    if len(cmd) < 2:
        print("用法: sessions list | sessions resume <session_id>")
        return

    action = cmd[1]

    if action == "list":
        sessions = store.list_sessions()
        if not sessions:
            print("暂无会话记录")
            return
        print(f"{'Session ID':<14} {'标题':<24} {'消息数':<8} {'更新时间'}")
        print("-" * 78)
        for s in sessions:
            print(
                f"{s['session_id']:<14} {s['title']:<24} {s['message_count']:<8} "
                f"{s['updated_at']}"
            )

    elif action == "resume":
        if len(cmd) < 3:
            print("用法: sessions resume <session_id>")
            return
        session_id = cmd[2]
        session = store.get_session(session_id)
        if session is None:
            print(f"会话不存在: {session_id}")
            return

        print(f"恢复会话: {session['title']} ({session_id})")
        print(f"历史消息数: {len(session['messages'])}")
        print()

        # 打印历史消息
        for msg in session["messages"]:
            role_label = "你" if msg["role"] == "user" else "AI"
            print(f"{role_label}: {msg['content']}")
            print()

        # 启动对话循环（消息追加到此会话）
        print("=" * 60)
        print("继续对话（输入 exit 退出）")
        print("=" * 60)
        print()

        agent = PhotoAgent(cfg)
        try:
            while True:
                try:
                    user_input = input("你: ")
                except (EOFError, KeyboardInterrupt):
                    print()
                    break

                if user_input.lower() == "exit":
                    break
                if not user_input.strip():
                    continue

                # 历史与任务快照在追加当前消息前读取（V4 多轮）
                history = store.get_messages(session_id)
                snapshot = store.get_runtime_snapshot(session_id)
                store.add_message(session_id, "user", user_input)
                result = agent.route(
                    user_input,
                    history=history,
                    prior_runtime_task_json=snapshot.get("task_json") if snapshot else None,
                )
                answer = result.get("answer", "") or "未能获取回答。"
                query_type = result.get("query_type", "")
                if query_type == "runtime" and result.get("runtime_task_dump"):
                    store.save_runtime_snapshot(
                        session_id,
                        result.get("runtime_goal_type") or "social_post",
                        result["runtime_task_dump"],
                    )

                # 首条提问后更新标题
                user_count = sum(
                    1 for m in store.get_messages(session_id)
                    if m["role"] == "user"
                )
                if user_count == 1 and len(session["messages"]) == 0:
                    new_title = session_store._format_question_title(user_input)
                    store.update_title(session_id, new_title)

                store.add_message(session_id, "assistant", answer, query_type=query_type)

                route_label = {
                    "sql": "SQL", "rag": "RAG", "tool": "Tool", "combined": "Combined",
                    "runtime": "Runtime",
                }.get(query_type, query_type)
                print(f"[{route_label}] {answer}")
                print()

        except KeyboardInterrupt:
            print()

    else:
        print(f"未知的 sessions 动作: {action}")
        print("用法: sessions list | sessions resume <session_id>")


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    if not args.config:
        parser.error("需要 -c/--config 指定配置文件")
    cfg = config.Config(args.config)
    cfg.check_api_key()

    # CLI 模式保留控制台输出；服务模式由 server 配置独立 JSONL 应用日志。
    if args.serve_port is None:
        logging.basicConfig(
            level=logging.INFO,
            format="%(message)s",
            stream=sys.stdout,
        )

    # sessions 子命令：无需启动 Agent，直接操作数据库
    if args.sessions_command:
        _handle_sessions(cfg, args.sessions_command)
        return

    print(f"配置加载成功: {cfg}")
    print()

    # --serve 模式：启动 API 服务（Agent 和 Chroma/EmbedQueue 在 server 内部初始化）
    if args.serve_port is not None:
        import cli.server as server
        server.run_server(
            cfg, port=args.serve_port, console_logging=args.console_logging,
        )
        return


    agent = PhotoAgent(cfg)

    try:
        if args.eval_mode:
            print("RAG 检索评估...")
            print()
            evaluation.run_evaluation(cfg, verbose=True, tracker=agent.tracker)

        elif args.demo_mode:
            demo.run_demo(cfg, _get_graph(), agent.tracker)

        elif args.usage_days is not None:
            _print_usage(agent.tracker, days=args.usage_days)

        elif args.suggest_mode:
            print("潜在主题识别（选题建议）...")
            print()
            cluster_dir = cfg.agent_path("topic-discovery", "clusters")
            suggestions, meta = suggest_mod.run_suggest(
                cfg, cfg.go_backend_url, cluster_dir,
            )
            output = suggest_mod.format_suggestions(
                suggestions, meta, go_backend_url=cfg.go_backend_url,
            )
            print(output)

        else:
            _chat_loop(agent)

    except KeyboardInterrupt:
        print()
    finally:
        summary = agent.tracker.summary(days=1)
        if summary:
            total_cost = sum(r["total_cost"] for r in summary)
            total_calls = sum(r["calls"] for r in summary)
            print(f"本次会话: {total_calls} 次 LLM 调用, 费用 ${total_cost:.6f}")

    print("再见！")


if __name__ == "__main__":
    main()
