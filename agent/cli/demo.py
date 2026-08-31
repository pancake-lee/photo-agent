"""
    全链路场景演示：依次执行 SQL / RAG 覆盖场景。

    用法:
        import cli.demo as demo
        demo.run_demo(cfg)
"""

import typing

import infra.config as config

# LangGraph RouterState 结构（与 photo_agent 保持一致）
RouterState = typing.NewType("RouterState", dict)

DEMO_QUERIES: list[tuple[str, str]] = [
    ("SQL", "我有多少张照片？"),
    ("SQL", "用 Canon 拍的照片有哪些？"),
    ("SQL", "ISO 大于 1600 的高感光度照片"),
    ("RAG", "找一下日落时分的风景照"),
    ("RAG", "有猫咪的照片吗？"),
    ("RAG", "红墙前的照片"),
    ("SQL", "2024 年拍了几张照片？"),
    ("RAG", "夜景照片"),
    ("combined", "蓝调时刻的街拍"),
    ("combined", "暖色调的人像"),
]


def run_demo(cfg: config.Config, graph_app, tracker) -> None:
    """全链路场景演示：依次执行 SQL / RAG 覆盖场景并输出结果。

    参数:
        cfg:       配置对象
        graph_app: LangGraph compiled app
        tracker:   TokenTracker 实例（用于用量汇总）
    """
    print("=" * 60)
    print("全链路场景演示")
    print(f"   模型: {cfg.llm_model}")
    print(f"   Go 后端: {cfg.go_backend_url}")
    print(f"   测试场景: {len(DEMO_QUERIES)} 个")
    print("=" * 60)
    print()

    for i, (expected_type, question) in enumerate(DEMO_QUERIES, 1):
        print(f"--- 场景 {i}/{len(DEMO_QUERIES)} ---")
        print(f"问题: {question}")
        print(f"预期路由: {expected_type}")

        initial = {
            "question": question,
            "query_type": "",
            "sql_result": {},
            "rag_answer": "",
            "tool_answer": "",
            "combined_result": {},
            "answer": "",
            "photos": [],
        }

        try:
            result = graph_app.invoke(initial, {"configurable": {"cfg": cfg}})

            actual_type = result["query_type"]
            match_str = "ok" if actual_type == expected_type.lower() else "mismatch"
            print(f"实际路由: {actual_type} {match_str}")

            if actual_type == "sql":
                sql_result = result.get("sql_result", {})
                print(f"SQL: {sql_result.get('sql', 'N/A')}")
                print(f"结果数: {len(sql_result.get('results') or [])}")
                answer = sql_result.get("answer", "")
            elif actual_type == "combined":
                combined = result.get("combined_result", {})
                if combined.get("fallback"):
                    print(f"(降级: {combined.get('fallback_reason', '')})")
                else:
                    print(f"SQL ∩ RAG: {len(combined.get('intersection_ids', []))} 张")
                answer = result.get("answer", "") or result.get("rag_answer", "")
            elif actual_type == "tool":
                answer = result.get("tool_answer", "") or result.get("answer", "")
            else:
                answer = result.get("rag_answer", "") or result.get("answer", "")

            if len(answer) > 200:
                answer = answer[:200] + "..."
            print(f"回答: {answer}")
        except Exception as exc:
            print(f"err 执行失败: {exc}")

        print()

    # 用量汇总
    usage = tracker.summary(days=1)
    if usage:
        print("--- Token 用量（本次） ---")
        total_cost = 0.0
        for row in usage:
            print(f"  {row['model']}: {row['calls']} 次调用, "
                  f"入 {row['total_input']} / 出 {row['total_output']} tokens, "
                  f"费用 ${row['total_cost']:.6f}")
            total_cost += row["total_cost"]
        print(f"  总费用: ${total_cost:.6f}")

    print()
    print("=" * 60)
    print("场景演示完成")
    print("=" * 60)
