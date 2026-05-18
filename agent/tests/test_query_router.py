"""
    LangGraph 查询路由单元测试。

    覆盖：
    - StateGraph 结构正确性（节点、边、条件分支）
    - 路由函数 _route_by_type
    - answer 汇聚节点
    - classify 分类节点
    - 完整 graph invoke（mock LLM）
"""

import sys
import pathlib
import unittest.mock

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import demo.query_router as router


# ------------------------------------------------------------------ #
# 1. Graph 结构
# ------------------------------------------------------------------ #

def test_graph_nodes():
    """验证 StateGraph 包含全部 4 个节点。"""
    graph = router._build_graph()
    node_names = list(graph.nodes.keys())
    assert "classify" in node_names, f"缺少 classify 节点: {node_names}"
    assert "sql_query" in node_names, f"缺少 sql_query 节点: {node_names}"
    assert "rag_query" in node_names, f"缺少 rag_query 节点: {node_names}"
    assert "answer" in node_names, f"缺少 answer 节点: {node_names}"
    assert len(node_names) == 4, f"预期 4 个节点，实际 {len(node_names)}: {node_names}"


def test_graph_has_start_and_end():
    """验证 graph 有 START 和 END 边。"""
    # compile 后检查连通性
    app = router._build_graph().compile()
    # 能成功 compile 说明 START/END 连通
    assert app is not None


def test_graph_can_compile():
    """验证 graph.compile() 成功且返回编译后的图。"""
    app = router._build_graph().compile()
    assert hasattr(app, "invoke"), "编译后的 graph 应该有 invoke 方法"


# ------------------------------------------------------------------ #
# 2. 路由函数
# ------------------------------------------------------------------ #

def test_route_by_type_sql():
    """query_type="sql" 时路由到 sql_query。"""
    state: router.RouterState = {
        "question": "test",
        "query_type": "sql",
        "sql_result": {},
        "rag_answer": "",
        "answer": "",
    }
    assert router._route_by_type(state) == "sql"


def test_route_by_type_rag():
    """query_type="rag" 时路由到 rag_query。"""
    state: router.RouterState = {
        "question": "test",
        "query_type": "rag",
        "sql_result": {},
        "rag_answer": "",
        "answer": "",
    }
    assert router._route_by_type(state) == "rag"


# ------------------------------------------------------------------ #
# 3. answer 汇聚节点
# ------------------------------------------------------------------ #

def test_answer_node_sql():
    """SQL 分支的 answer 取 sql_result.answer。"""
    state: router.RouterState = {
        "question": "how many photos",
        "query_type": "sql",
        "sql_result": {
            "question": "how many photos",
            "sql": "SELECT COUNT(*) FROM photos",
            "results": [{"count": 42}],
            "answer": "共 42 张照片。",
        },
        "rag_answer": "",
        "answer": "",
    }
    result = router.answer(state)
    assert result["answer"] == "共 42 张照片。"


def test_answer_node_rag():
    """RAG 分支的 answer 取 rag_answer。"""
    state: router.RouterState = {
        "question": "find sunset photos",
        "query_type": "rag",
        "sql_result": {},
        "rag_answer": "找到了 3 张日落照片。",
        "answer": "",
    }
    result = router.answer(state)
    assert result["answer"] == "找到了 3 张日落照片。"


def test_answer_node_sql_empty():
    """SQL 结果为空时给出兜底回答。"""
    state: router.RouterState = {
        "question": "test",
        "query_type": "sql",
        "sql_result": {},
        "rag_answer": "",
        "answer": "",
    }
    result = router.answer(state)
    assert "SQL" in result["answer"]


def test_answer_node_rag_empty():
    """RAG 结果为空时给出兜底回答。"""
    state: router.RouterState = {
        "question": "test",
        "query_type": "rag",
        "sql_result": {},
        "rag_answer": "",
        "answer": "",
    }
    result = router.answer(state)
    assert "RAG" in result["answer"]


# ------------------------------------------------------------------ #
# 4. classify 分类节点
# ------------------------------------------------------------------ #

class _FakeLLM:
    """模拟 LLM，可被 LangChain 的 | 管道符串联。"""

    def __init__(self, return_text: str):
        self._return = return_text

    def __call__(self, *args, **kwargs):
        """coerce_to_runnable 会包装 callable，invoke 时调用此方法。"""
        return unittest.mock.MagicMock(content=self._return)


def _make_classify_state(question: str) -> router.RouterState:
    return {
        "question": question,
        "query_type": "",
        "sql_result": {},
        "rag_answer": "",
        "answer": "",
    }


def _make_runnable_config(cfg):
    """构造模拟的 RunnableConfig。"""
    return {"configurable": {"cfg": cfg}}


def test_classify_returns_sql_when_llm_says_sql():
    """LLM 返回 "sql" 时分类为 sql。"""
    fake_cfg = unittest.mock.MagicMock()
    with unittest.mock.patch(
        "demo.query_router.lc_openai.ChatOpenAI",
        return_value=_FakeLLM("sql"),
    ):
        result = router.classify(
            _make_classify_state("how many photos"),
            _make_runnable_config(fake_cfg),
        )
    assert result["query_type"] == "sql"


def test_classify_returns_rag_when_llm_says_rag():
    """LLM 返回 "rag" 时分类为 rag。"""
    fake_cfg = unittest.mock.MagicMock()
    with unittest.mock.patch(
        "demo.query_router.lc_openai.ChatOpenAI",
        return_value=_FakeLLM("rag"),
    ):
        result = router.classify(
            _make_classify_state("find sunset photos"),
            _make_runnable_config(fake_cfg),
        )
    assert result["query_type"] == "rag"


def test_classify_defaults_to_rag_on_unknown():
    """LLM 返回非预期内容时默认 fallback 到 rag。"""
    fake_cfg = unittest.mock.MagicMock()
    with unittest.mock.patch(
        "demo.query_router.lc_openai.ChatOpenAI",
        return_value=_FakeLLM("something weird"),
    ):
        result = router.classify(
            _make_classify_state("hello world"),
            _make_runnable_config(fake_cfg),
        )
    assert result["query_type"] == "rag"


def test_classify_uses_temperature_zero():
    """classify 节点使用 temperature=0 保证确定性。"""
    fake_cfg = unittest.mock.MagicMock()
    mock_llm_cls = unittest.mock.patch(
        "demo.query_router.lc_openai.ChatOpenAI",
        return_value=_FakeLLM("sql"),
    )
    with mock_llm_cls as mock_cls:
        router.classify(
            _make_classify_state("count"),
            _make_runnable_config(fake_cfg),
        )
    call_kwargs = mock_cls.call_args[1]
    assert call_kwargs["temperature"] == 0.0


# ------------------------------------------------------------------ #
# 5. RouterState 结构
# ------------------------------------------------------------------ #

def test_router_state_has_required_fields():
    """RouterState 必须包含 5 个字段。"""
    fields = router.RouterState.__annotations__
    assert "question" in fields
    assert "query_type" in fields
    assert "sql_result" in fields
    assert "rag_answer" in fields
    assert "answer" in fields


# ------------------------------------------------------------------ #
# 6. Graph invoke（集成风格，mock 所有 LLM/外部调用）
# ------------------------------------------------------------------ #

def test_compile_and_invoke_sql_route():
    """编译 graph 并走通 SQL 路由分支。"""
    fake_cfg = unittest.mock.MagicMock()

    with unittest.mock.patch(
        "demo.query_router.lc_openai.ChatOpenAI",
        return_value=_FakeLLM("sql"),
    ), unittest.mock.patch(
        "demo.query_router.text_to_sql.answer_with_sql",
        return_value={
            "question": "how many",
            "sql": "SELECT COUNT(*) FROM photos",
            "results": [{"c": 3}],
            "answer": "共 3 张。",
        },
    ):
        result = router.route_query(fake_cfg, "how many photos")

    assert result["query_type"] == "sql"
    assert result["answer"] == "共 3 张。"
    assert "sql" in result["sql_result"]


def test_compile_and_invoke_rag_route():
    """编译 graph 并走通 RAG 路由分支。"""
    fake_cfg = unittest.mock.MagicMock()

    with unittest.mock.patch(
        "demo.query_router.lc_openai.ChatOpenAI",
        return_value=_FakeLLM("rag"),
    ), unittest.mock.patch(
        "demo.query_router.photo_rag.answer_question",
        return_value="找到 2 张猫咪照片。",
    ):
        result = router.route_query(fake_cfg, "有猫咪的照片吗")

    assert result["query_type"] == "rag"
    assert result["answer"] == "找到 2 张猫咪照片。"
    assert result["rag_answer"] == "找到 2 张猫咪照片。"


# ------------------------------------------------------------------ #
# 运行
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    import traceback

    tests = [
        fn for name, fn in sorted(globals().items())
        if name.startswith("test_") and callable(fn)
    ]

    passed = 0
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception:
            print(f"  FAIL  {fn.__name__}")
            traceback.print_exc()
            failed += 1

    print(f"\n{'='*40}")
    print(f"通过: {passed}/{len(tests)}, 失败: {failed}")
