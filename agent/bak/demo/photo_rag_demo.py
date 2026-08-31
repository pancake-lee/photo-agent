"""
    RAG 问答交互式演示（独立入口）。

    用法：
        cd agent
        python demo/photo_rag_demo.py -c ../.local/my-config.yaml
"""

import sys
import pathlib


import chain.photo_rag as photo_rag
import config
import utils.streaming_printer as streaming_printer


def chat_loop(cfg: config.Config) -> None:
    """RAG 问答交互式主循环。"""

    print("=" * 50)
    print("📷 照片库 RAG 问答已启动")
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

        print("🔍 检索相关照片...")
        results = photo_rag._retrieve(cfg, user_input, n_results=15)
        aggregated = photo_rag._aggregate_by_photo(results, top_n=5)
        context = photo_rag._build_context(aggregated)

        chain = photo_rag._build_rag_chain(cfg)
        reply_parts: list[str] = []
        with streaming_printer.StreamingPrinter() as printer:
            for chunk in chain.stream({"context": context, "question": user_input}):
                text = str(chunk.content)
                if text:
                    printer.feed(text)
                    reply_parts.append(text)
        reply = "".join(reply_parts)
        print()
        print()

        if aggregated:
            print("📎 参考照片:")
            for r in aggregated:
                meta = r.get("metadata") or {}
                photo_id = meta.get("photo_id", "unknown")
                distance = r.get("distance")
                dist_str = f" (距离: {distance:.4f})" if distance is not None else ""
                print(f"   - {photo_id}{dist_str}")
            print()


if __name__ == "__main__":
    cfg = config.load_config()
    chat_loop(cfg)
    print("👋 再见！")
