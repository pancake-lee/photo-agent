"""
    LangGraph 查询路由：根据用户问题自动路由到 SQL 或 RAG 分支。

    架构:
        START → classify → [条件分支] → sql_query / rag_query → answer → END

    用法:
        cd agent
        python chain/query_router.py -c ../.local/my-config.yaml
"""

import pathlib
import sys
import typing

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import langchain_core.prompts as lc_prompts
import langchain_openai as lc_openai
import langgraph.graph as lg_graph
import langgraph.types as lg_types

import chain.photo_rag as photo_rag
import chain.text_to_sql as text_to_sql
import config


# --------------------------------------------------------------------------- #
# State 定义
# --------------------------------------------------------------------------- #

class RouterState(typing.TypedDict):
    """查询路由的共享 State。

    字段说明:
        question:   用户原始问题
        query_type: 分类结果，"sql" 或 "rag"
        sql_result: text_to_sql.answer_with_sql 返回的完整结果
        rag_answer: photo_rag.answer_question 返回的文本
        answer:     汇聚节点产出的最终回答
    """
    question: str
    query_type: str
    sql_result: dict
    rag_answer: str
    answer: str


# --------------------------------------------------------------------------- #
# 分类 Prompt
# --------------------------------------------------------------------------- #

CLASSIFY_SYSTEM = (
    "你是一个查询分类器。判断用户对照片库的提问属于哪种类型，只回答 sql 或 rag，不要解释。\n\n"
    "sql: 涉及统计计数、EXIF 参数筛选（品牌/型号/镜头/焦距/光圈/ISO/日期/GPS）、数量聚合的结构化查询\n"
    "rag: 涉及照片内容描述、场景、物体、颜色、情感、构图、风格、氛围的语义检索\n\n"
    "示例:\n"
    "- \"我有多少张照片？\" → sql\n"
    "- \"用 Nikon 拍的照片有哪些？\" → sql\n"
    "- \"2024 年 3 月拍了几张？\" → sql\n"
    "- \"找一下日落时分的照片\" → rag\n"
    "- \"有猫咪的照片吗？\" → rag\n"
    "- \"ISO 大于 1600 的照片\" → sql\n"
    "- \"红墙前的照片\" → rag\n"
    "- \"湖边的风景照\" → rag\n\n"
    "用户问题: {question}\n"
    "分类:"
)


# --------------------------------------------------------------------------- #
# Node 函数
# --------------------------------------------------------------------------- #

def _get_cfg(config: lg_types.RunnableConfig) -> config.Config:  # type: ignore
    """从 RunnableConfig 中提取 Config 对象。"""
    cfg = config.get("configurable", {}).get("cfg")
    if cfg is None:
        raise RuntimeError("Config 未注入到 configurable 中")
    return cfg


def classify(state: RouterState, config: lg_types.RunnableConfig) -> dict:  # type: ignore
    """分类节点：用 LLM 判断问题是 SQL 型还是 RAG 型。"""
    cfg = _get_cfg(config)

    llm = lc_openai.ChatOpenAI(
        model=cfg.llm_model,
        api_key=cfg.llm_api_key,  # type: ignore[arg-type]
        base_url=cfg.llm_base_url,
        temperature=0.0,
    )

    prompt = lc_prompts.ChatPromptTemplate.from_messages([
        ("system", CLASSIFY_SYSTEM),
    ])
    chain = prompt | llm
    response = chain.invoke({"question": state["question"]})
    raw = str(response.content).strip().lower()

    query_type = "rag"  # 默认走 RAG
    if "sql" in raw:
        query_type = "sql"

    return {"query_type": query_type}


def sql_query(state: RouterState, config: lg_types.RunnableConfig) -> dict:  # type: ignore
    """SQL 节点：调用 Text-to-SQL 链路生成并执行查询。"""
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


def rag_query(state: RouterState, config: lg_types.RunnableConfig) -> dict:  # type: ignore
    """RAG 节点：Chroma 向量检索 + LLM 生成回答。"""
    cfg = _get_cfg(config)

    try:
        answer_text = photo_rag.answer_question(cfg, state["question"])
    except Exception as exc:
        answer_text = f"RAG 检索失败: {exc}"

    return {"rag_answer": answer_text}


def answer(state: RouterState) -> dict:
    """汇聚节点：从对应分支提取最终回答文本。"""
    if state["query_type"] == "sql":
        result = state.get("sql_result", {})
        text = result.get("answer") or "SQL 查询未返回结果。"
    else:
        text = state.get("rag_answer") or "RAG 检索未返回结果。"

    return {"answer": text}


# --------------------------------------------------------------------------- #
# 条件路由
# --------------------------------------------------------------------------- #

def _route_by_type(state: RouterState) -> str:
    """根据 query_type 决定下一步：sql_query 或 rag_query。"""
    return state["query_type"]


# --------------------------------------------------------------------------- #
# Graph 构建与编译
# --------------------------------------------------------------------------- #

def _build_graph() -> lg_graph.StateGraph:
    """构建查询路由 StateGraph（不 compile）。"""
    graph = lg_graph.StateGraph(RouterState)

    graph.add_node("classify", classify)
    graph.add_node("sql_query", sql_query)
    graph.add_node("rag_query", rag_query)
    graph.add_node("answer", answer)

    graph.add_edge(lg_graph.START, "classify")
    graph.add_conditional_edges(
        "classify",
        _route_by_type,
        {"sql": "sql_query", "rag": "rag_query"},
    )
    graph.add_edge("sql_query", "answer")
    graph.add_edge("rag_query", "answer")
    graph.add_edge("answer", lg_graph.END)

    return graph


# compile 后的 app 可复用，避免每次查询都重新构建
_compiled_app: typing.Any = None


def _get_app():
    global _compiled_app
    if _compiled_app is None:
        _compiled_app = _build_graph().compile()
    return _compiled_app


# --------------------------------------------------------------------------- #
# 查询入口
# --------------------------------------------------------------------------- #

def route_query(cfg: config.Config, question: str) -> RouterState:
    """路由单次查询到合适的处理分支，返回最终的 RouterState。

    参数:
        cfg:      配置对象
        question: 用户自然语言问题

    返回:
        RouterState，包含 question, query_type, sql_result, rag_answer, answer
    """
    app = _get_app()

    initial: RouterState = {
        "question": question,
        "query_type": "",
        "sql_result": {},
        "rag_answer": "",
        "answer": "",
    }

    result = app.invoke(initial, {"configurable": {"cfg": cfg}})
    return typing.cast(RouterState, result)


# --------------------------------------------------------------------------- #
# 交互式演示
# --------------------------------------------------------------------------- #

def chat_loop(cfg: config.Config) -> None:
    """查询路由交互式演示循环。"""
    print("=" * 50)
    print("🧭 LangGraph 查询路由已启动")
    print(f"   Go 后端: {cfg.go_backend_url}")
    print("   自动判断查询类型: SQL 统计 / RAG 检索")
    print("   输入 exit 或按 Ctrl+C 退出")
    print("=" * 50)
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

        result = route_query(cfg, user_input)

        query_type = result["query_type"]
        print(f"🔀 路由: {'SQL 统计查询' if query_type == 'sql' else 'RAG 语义检索'}")
        print()

        if query_type == "sql":
            sql_result = result.get("sql_result", {})
            print(f"📋 SQL: {sql_result.get('sql', 'N/A')}")
            print(f"📊 结果数: {len(sql_result.get('results', []))}")
            print()
        else:
            print(f"🤖 回答: {result['answer']}")
            print()

        print("=" * 50)
        print()


if __name__ == "__main__":
    cfg = config.load_config()
    chat_loop(cfg)
