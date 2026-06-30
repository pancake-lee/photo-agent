"""
    Text-to-SQL 交互式演示（独立入口）。

    用法：
        cd agent
        python demo/text_to_sql_demo.py -c ../.local/my-config.yaml
"""

import sys
import pathlib


import chain.text_to_sql as text_to_sql
import config


def chat_loop(cfg: config.Config) -> None:
    """Text-to-SQL 交互式演示循环。"""
    print("=" * 50)
    print("📊 Text-to-SQL 问答已启动")
    print(f"   Go 后端: {cfg.go_backend_url}")
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

        try:
            print("🧠 生成 SQL...")
            sql = text_to_sql.generate_sql(cfg, user_input)
            print(f"📋 SQL: {sql}")

            print("📊 执行查询...")
            results = text_to_sql.execute_sql(cfg.go_backend_url, sql)
            print(f"✅ 返回 {len(results)} 条结果")

            answer = text_to_sql.format_results(user_input, sql, results)
            print(f"AI: {answer}")
            print()

        except ValueError as e:
            print(f"❌ 错误: {e}")
            print()
        except Exception as e:
            print(f"❌ 执行失败: {e}")
            print()


if __name__ == "__main__":
    cfg = config.load_config()
    chat_loop(cfg)
    print("👋 再见！")
