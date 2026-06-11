"""
    PhotoAgent — 照片库 AI 助手统一入口。

    整合能力:
        - LangGraph 查询路由（SQL / RAG 自动分发）
        - AI 工程保障：tenacity 重试、模型降级、Token 成本追踪
        - 全链路 CLI：聊天 / 评估 / 用量统计 / 场景演示

    用法:
        cd agent
        python chain/photo_agent.py -c ../.local/my-config.yaml          # 聊天模式
        python chain/photo_agent.py -c ../.local/my-config.yaml --eval   # 评估模式
        python chain/photo_agent.py -c ../.local/my-config.yaml --usage  # 用量统计
        python chain/photo_agent.py -c ../.local/my-config.yaml --demo   # 场景演示
"""

import argparse
import pathlib
import sys
import typing

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import langchain_core.callbacks as lc_callbacks
import langchain_core.messages as lc_messages
import langchain_core.prompts as lc_prompts
import langchain_core.runnables as lc_runnables
import langgraph.graph as lg_graph

import chain.demo as demo
import chain.evaluation as evaluation
import chain.photo_rag as photo_rag
import chain.text_to_sql as text_to_sql
import config
import tools.openapi_client as openapi_client
import utils.llm_factory as llm_factory
import utils.token_tracker as token_tracker


# ============================================================================
# LangGraph 查询路由
# ============================================================================

class RouterState(typing.TypedDict):
    """查询路由的共享 State。"""
    question: str
    query_type: str
    sql_result: dict
    rag_answer: str
    tool_answer: str
    answer: str


CLASSIFY_SYSTEM = (
    "你是一个查询分类器。判断用户对照片库的提问属于哪种类型，只回答 sql、rag 或 tool，不要解释。\n\n"
    "sql: 涉及统计计数、EXIF 参数筛选（品牌/型号/镜头/焦距/光圈/ISO/日期/GPS）、"
    "数量聚合的结构化查询\n"
    "rag: 涉及照片内容描述、场景、物体、颜色、情感、构图、风格、氛围的语义检索\n"
    "tool: 涉及照片列表、时间线查看、标签筛选、单张照片详情、归档操作等"
    "需要调用 API 的查询\n\n"
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
    "- \"按标签筛选照片\" → tool\n\n"
    "用户问题: {question}\n"
    "分类:"
)


def _get_cfg(config: lc_runnables.RunnableConfig) -> config.Config:
    cfg = config.get("configurable", {}).get("cfg")
    if cfg is None:
        raise RuntimeError("Config 未注入到 configurable 中")
    return cfg


def _classify_node(state: RouterState, config: lc_runnables.RunnableConfig) -> dict:
    cfg = _get_cfg(config)
    llm = llm_factory.create_llm(cfg, temperature=0.0, callbacks=_get_callbacks())
    prompt = lc_prompts.ChatPromptTemplate.from_messages([("system", CLASSIFY_SYSTEM)])
    chain = prompt | llm
    response = chain.invoke({"question": state["question"]})
    raw = str(response.content).strip().lower()
    if "sql" in raw:
        query_type = "sql"
    elif "tool" in raw:
        query_type = "tool"
    else:
        query_type = "rag"
    return {"query_type": query_type}


def _sql_node(state: RouterState, config: lc_runnables.RunnableConfig) -> dict:
    cfg = _get_cfg(config)
    try:
        result = text_to_sql.answer_with_sql(cfg, state["question"])
    except Exception as exc:
        result = {
            "question": state["question"],
            "sql": "",
            "results": [],
            "answer": f"SQL 查询失败: {exc}",
        }
    return {"sql_result": result}


def _rag_node(state: RouterState, config: lc_runnables.RunnableConfig) -> dict:
    cfg = _get_cfg(config)
    try:
        # 自动提取结构化过滤条件，显式传入避免 answer_question 内部重复提取
        filters = photo_rag.extract_filters_from_question(cfg, state["question"])
        answer_text = photo_rag.answer_question(
            cfg, state["question"], where=filters
        )
        # 如果有提取到过滤条件，在答案前附加调试信息
        if filters:
            answer_text = f"[过滤条件: {filters}]\n{answer_text}"
    except Exception as exc:
        answer_text = f"RAG 检索失败: {exc}"
    return {"rag_answer": answer_text}


def _tool_node(state: RouterState, config: lc_runnables.RunnableConfig) -> dict:
    """工具调用节点：使用 llm.bind_tools() 让 LLM 自主调用 Go API。"""
    cfg = _get_cfg(config)

    # 获取或创建工具客户端
    tool_client = _get_tool_client(cfg.go_backend_url)
    tools = tool_client.get_tools()

    llm = llm_factory.create_llm(cfg, temperature=0.3, callbacks=_get_callbacks())
    llm_with_tools = llm.bind_tools(tools)

    messages: list[lc_messages.BaseMessage] = [
        lc_messages.SystemMessage(content=_TOOL_SYSTEM_PROMPT),
        lc_messages.HumanMessage(content=state["question"]),
    ]

    try:
        response = llm_with_tools.invoke(messages)

        # 处理工具调用
        if hasattr(response, "tool_calls") and response.tool_calls:
            tool_messages: list[lc_messages.BaseMessage] = []
            for tc in response.tool_calls:
                result = tool_client.execute(
                    tc.get("name", ""), tc.get("args", {})
                )
                # 截断过长结果，避免超出上下文
                max_len = 4000
                if len(result) > max_len:
                    result = result[:max_len] + f"\n...（结果已截断，原始长度 {len(result)}）"
                tool_messages.append(
                    lc_messages.ToolMessage(
                        content=result,
                        tool_call_id=tc.get("id", ""),
                    )
                )

            # 将工具结果再次传给 LLM 生成最终回答
            final_response = llm_with_tools.invoke(messages + [response] + tool_messages)
            return {"tool_answer": str(final_response.content)}

        return {"tool_answer": str(response.content)}
    except Exception as exc:
        return {"tool_answer": f"工具调用失败: {exc}"}


_TOOL_SYSTEM_PROMPT = (
    "你是一位摄影档案助手，可以调用后端 API 帮助用户管理照片库。"
    "根据用户的需求选择合适的工具，回答简洁，控制在 150 字以内。"
)


def _answer_node(state: RouterState) -> dict:
    query_type = state["query_type"]
    if query_type == "sql":
        result = state.get("sql_result", {})
        text = result.get("answer") or "SQL 查询未返回结果。"
    elif query_type == "tool":
        text = state.get("tool_answer") or "工具调用未返回结果。"
    else:
        text = state.get("rag_answer") or "RAG 检索未返回结果。"
    return {"answer": text}


def _route_by_type(state: RouterState) -> str:
    return state["query_type"]


# 工具客户端单例（按 base_url 缓存）
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
        g.add_node("sql_query", _sql_node)
        g.add_node("rag_query", _rag_node)
        g.add_node("tool_query", _tool_node)
        g.add_node("answer", _answer_node)
        g.add_edge(lg_graph.START, "classify")
        g.add_conditional_edges(
            "classify", _route_by_type,
            {"sql": "sql_query", "rag": "rag_query", "tool": "tool_query"},
        )
        g.add_edge("sql_query", "answer")
        g.add_edge("rag_query", "answer")
        g.add_edge("tool_query", "answer")
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
        prices = {}
        if cfg.prices_path:
            prices = token_tracker.load_prices(
                cfg.resolve_path(cfg.prices_path).as_posix()
            )
        db_path = cfg.resolve_path("./data/token_usage.db").as_posix()
        db_path = str(pathlib.Path(db_path).resolve())
        pathlib.Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        global _tracker, _callbacks
        _tracker = token_tracker.TokenTracker(db_path, prices)
        _callbacks = [token_tracker.TokenCallback(_tracker)]

        print(f"PhotoAgent 初始化完成")
        print(f"   主模型: {cfg.llm_model}")
        if cfg.llm_fallback_model:
            print(f"   降级模型: {cfg.llm_fallback_model}")
        print(f"   重试: {'开启' if cfg.retry_enabled else '关闭'}"
              f"（最多 {cfg.retry_max_attempts} 次）")
        if prices:
            print(f"   Token 追踪: 已加载 {len(prices)} 个模型单价")
        else:
            print(f"   Token 追踪: 已开启（无单价配置，仅记录 token 数）")
        print()

    def route(self, question: str) -> RouterState:
        """路由单次查询，自动分发到 SQL / RAG / Tool 分支。"""
        initial: RouterState = {
            "question": question,
            "query_type": "",
            "sql_result": {},
            "rag_answer": "",
            "tool_answer": "",
            "answer": "",
        }
        result = self._app.invoke(initial, {"configurable": {"cfg": self._cfg}})
        return typing.cast(RouterState, result)

    @property
    def tracker(self) -> token_tracker.TokenTracker:
        return _get_tracker()

    @property
    def cfg(self) -> config.Config:
        return self._cfg


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
        }.get(query_type, "未知路由")
        print(f"路由: {route_name}")
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
    print()
    print("按模型汇总:")
    for row in summary:
        print(f"  {row['model']}:")
        print(f"    调用次数: {row['calls']}")
        print(f"    Input:  {row['total_input']:,} tokens")
        print(f"    Output: {row['total_output']:,} tokens")
        print(f"    费用:   ${row['total_cost']:.6f}")
        total_cost += row["total_cost"]
    print(f"  ────────────────────")
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
            print(f"    {row['model']}: {row['calls']} 次 "
                  f"| 入 {row['total_input']:,} / 出 {row['total_output']:,} "
                  f"| ${row['total_cost']:.6f}")
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
  python chain/photo_agent.py -c config.yaml              # 交互式聊天
  python chain/photo_agent.py -c config.yaml --eval       # 评估模式
  python chain/photo_agent.py -c config.yaml --usage      # 用量统计
  python chain/photo_agent.py -c config.yaml --demo       # 场景演示
  python chain/photo_agent.py -c config.yaml --usage 30   # 最近 30 天用量
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
    return parser


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    if not args.config:
        parser.error("需要 -c/--config 指定配置文件")
    cfg = config.Config(args.config)
    cfg.check_api_key()
    print(f"配置加载成功: {cfg}")
    print()

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
