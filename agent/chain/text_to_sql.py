"""
    Text-to-SQL 链路：自然语言 → Schema 提示 + Few-shot → LLM 生成 SQL → 安全校验 → 执行 → 格式化回答

    用法:
        cd agent
        python chain/text_to_sql.py -c ../.local/my-config.yaml

    架构:
        1. Schema 提示: 定义 photos 表结构、字段类型、可查询维度
        2. Few-shot 示例: 3~5 个典型 NL→SQL 样例，引导 LLM 生成正确 SQL
        3. LLM 生成: ChatPromptTemplate (System + Few-shot Human/AI + 用户问题)
        4. SQL 安全校验: validate_select_only 确保仅 SELECT（客户端双重保险）
        5. 执行查询: 通过 Go 后端 /api/query/sql 接口执行（Python 不直连 SQLite）
        6. 格式化回答: 将结果集转为自然语言摘要
"""

import json
import pathlib
import re
import sys
import typing

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import langchain.prompts as lc_prompts
import langchain.schema as lc_schema
import langchain_openai as lc_openai

import config
import db.sqlite_client as sqlite_client


# --------------------------------------------------------------------------- #
# Few-shot 定义
# --------------------------------------------------------------------------- #

FEW_SHOT_EXAMPLES = [
    {
        "question": "我有多少张照片？",
        "sql": "SELECT COUNT(*) AS photo_count FROM photos",
    },
    {
        "question": "用 Nikon 相机拍的照片有哪些？",
        "sql": "SELECT filename, description, shot_at FROM photos WHERE brand = 'NIKON' ORDER BY shot_at DESC LIMIT 20",
    },
    {
        "question": "2024 年 3 月拍的照片数量",
        "sql": "SELECT COUNT(*) AS count FROM photos WHERE strftime('%Y-%m', shot_at) = '2024-03'",
    },
    {
        "question": "ISO 大于 1600 的高感光度照片",
        "sql": "SELECT filename, iso, description FROM photos WHERE iso > 1600 ORDER BY iso DESC LIMIT 20",
    },
    {
        "question": "带有 GPS 信息的照片有多少张？",
        "sql": "SELECT COUNT(*) AS gps_count FROM photos WHERE latitude IS NOT NULL",
    },
    {
        "question": "焦距在 24mm 到 70mm 之间的照片",
        "sql": "SELECT filename, focal_length, description FROM photos WHERE CAST(REPLACE(REPLACE(focal_length, 'mm', ''), ' ', '') AS REAL) BETWEEN 24 AND 70 LIMIT 20",
    },
]

# --------------------------------------------------------------------------- #
# Prompt 构建
# --------------------------------------------------------------------------- #

SQL_SYSTEM_PROMPT = (
    "你是一位 SQL 专家。根据下面的数据库表结构和示例，将用户的问题转换为正确的 SQLite SQL 查询。\n\n"
    "表结构:\n"
    "{schema}\n\n"
    "规则:\n"
    "1. 仅生成 SELECT 查询语句\n"
    "2. 字段名必须严格匹配表结构\n"
    "3. 字符串值用单引号包裹\n"
    "4. 时间比较使用 strftime 函数\n"
    "5. JSON 标签字段 tags 用 LIKE 匹配\n"
    "6. 结果限制在 20 条以内，除非用户明确要求更多\n"
    "7. 如果问题无法从表中回答，返回: SELECT '无法回答' AS result\n"
    "8. 只输出纯 SQL，不要任何 Markdown 代码块或解释"
)


def _build_few_shot_prompt() -> lc_prompts.FewShotChatMessagePromptTemplate:
    """
    构建 Few-shot 消息模板。

    使用 FewShotChatMessagePromptTemplate 将示例列表与模板结构解耦，
    方便后续接入 example_selector（如 SemanticSimilarityExampleSelector）
    实现按用户问题动态筛选最相关示例。
    """
    example_prompt = lc_prompts.ChatPromptTemplate.from_messages([
        ("human", "{question}"),
        ("ai", "{sql}"),
    ])

    # 扩展点：未来可替换为 example_selector 实现动态筛选
    # from langchain.prompts import SemanticSimilarityExampleSelector
    # selector = SemanticSimilarityExampleSelector.from_examples(
    #     examples=FEW_SHOT_EXAMPLES,
    #     embeddings=embedder,
    #     vectorstore=Chroma,
    #     k=3,
    # )
    # return lc_prompts.FewShotChatMessagePromptTemplate(
    #     example_prompt=example_prompt,
    #     example_selector=selector,
    # )

    return lc_prompts.FewShotChatMessagePromptTemplate(
        example_prompt=example_prompt,
        examples=FEW_SHOT_EXAMPLES,
    )


def _build_sql_prompt() -> lc_prompts.ChatPromptTemplate:
    """构建 SQL 生成用的 ChatPromptTemplate（含 System + Few-shot）。"""
    few_shot = _build_few_shot_prompt()
    return lc_prompts.ChatPromptTemplate.from_messages([
        ("system", SQL_SYSTEM_PROMPT),
        few_shot,
        ("human", "{question}"),
    ])


# --------------------------------------------------------------------------- #
# Schema 获取与格式化
# --------------------------------------------------------------------------- #

def _fetch_schema(base_url: str) -> dict:
    """
    从 Go 后端获取 photos 表结构。

    参数:
        base_url: Go 后端地址

    返回:
        API 返回的 schema JSON 字典

    异常:
        httpx.HTTPError: HTTP 请求失败
    """
    client = sqlite_client.QueryClient(base_url)
    return client.fetch_schema()


def _format_schema(schema_data: dict) -> str:
    """
    将 API 返回的 JSON schema 格式化为 LLM 可用的文本。

    参数:
        schema_data: Go 后端 /api/schema/photos 返回的 JSON

    返回:
        格式化后的 schema 文本
    """
    lines: list[str] = []
    lines.append(f"表名: {schema_data.get('table_name', 'photos')}")
    lines.append("")
    lines.append("字段说明:")

    for field in schema_data.get("fields", []):
        name = field.get("name", "")
        sql_type = field.get("sql_type", "TEXT")
        json_tag = field.get("json_tag", "")
        nullable = field.get("nullable", False)
        null_str = "，可能为 NULL" if nullable else ""
        lines.append(f"- {name} ({sql_type}): JSON tag = {json_tag}{null_str}")

    notes = schema_data.get("notes", [])
    if notes:
        lines.append("")
        lines.append("注意事项:")
        for note in notes:
            lines.append(f"- {note}")

    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# SQL 解析与校验
# --------------------------------------------------------------------------- #

def _extract_sql_from_response(text: str) -> str:
    """
    从 LLM 响应中提取纯 SQL 语句。

    处理场景:
        - Markdown 代码块 ```sql ... ```
        - 普通代码块 ``` ... ```
        - 纯文本中的 SQL

    参数:
        text: LLM 原始输出

    返回:
        提取后的 SQL 字符串
    """
    text = text.strip()

    # 尝试提取 Markdown 代码块
    pattern = re.compile(r"```(?:sql)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)
    match = pattern.search(text)
    if match:
        return match.group(1).strip()

    # 无代码块，取整段
    return text


def _validate_sql_safe(sql: str) -> None:
    """
    校验 SQL 安全性，不安全则抛出 ValueError。

    仅允许 SELECT 查询。
    """
    if not sqlite_client.validate_select_only(sql):
        raise ValueError(f"生成的 SQL 未通过安全校验（仅允许 SELECT）: {sql[:200]}")


# --------------------------------------------------------------------------- #
# LLM 调用
# --------------------------------------------------------------------------- #

def _build_llm(cfg: config.Config) -> lc_openai.ChatOpenAI:
    """构建 LLM 实例。"""
    return lc_openai.ChatOpenAI(
        model=cfg.llm_model,
        api_key=cfg.llm_api_key,  # type: ignore[arg-type]
        base_url=cfg.llm_base_url,
        temperature=0.0,
    )


def generate_sql(
    cfg: config.Config,
    question: str,
) -> str:
    """
    将自然语言问题转换为 SQL。

    参数:
        cfg:      配置对象
        question: 用户问题

    返回:
        生成的 SQL 字符串（已通过安全校验）

    异常:
        ValueError: SQL 生成失败或安全校验未通过
        httpx.HTTPError: Schema API 调用失败
    """
    schema_data = _fetch_schema(cfg.go_backend_url)
    schema_text = _format_schema(schema_data)

    llm = _build_llm(cfg)
    prompt = _build_sql_prompt()

    chain = prompt | llm
    response = chain.invoke({"schema": schema_text, "question": question})

    raw_text = str(response.content)
    sql = _extract_sql_from_response(raw_text)

    if not sql:
        raise ValueError("LLM 未生成有效的 SQL")

    _validate_sql_safe(sql)

    return sql


# --------------------------------------------------------------------------- #
# 查询执行
# --------------------------------------------------------------------------- #

def execute_sql(
    base_url: str,
    sql: str,
    limit: int = 20,
) -> list[dict]:
    """
    通过 Go 后端 API 安全执行 SQL 查询。

    参数:
        base_url: Go 后端地址，如 "http://localhost:10000"
        sql:      SQL 字符串（已通过校验）
        limit:    最大返回行数

    返回:
        查询结果列表（result["rows"]）
    """
    result = sqlite_client.safe_execute(base_url, sql, limit=limit)
    return result.get("rows", [])


# --------------------------------------------------------------------------- #
# 结果格式化
# --------------------------------------------------------------------------- #

def format_results(
    question: str,
    sql: str,
    results: list[dict],
    max_rows: int = 10,
) -> str:
    """
    将查询结果格式化为自然语言摘要。

    参数:
        question: 原始用户问题
        sql:      执行的 SQL
        results:  查询结果
        max_rows: 展示的最大行数

    返回:
        格式化后的回答字符串
    """
    if not results:
        return "未找到匹配的数据。"

    total = len(results)
    lines: list[str] = []
    lines.append(f"查询结果（共 {total} 条）:")
    lines.append("")

    # 取前 max_rows 条展示
    display_rows = results[:max_rows]
    for i, row in enumerate(display_rows, 1):
        items = [f"{k}={v}" for k, v in row.items()]
        lines.append(f"  {i}. {', '.join(items)}")

    if total > max_rows:
        lines.append(f"  ... 还有 {total - max_rows} 条未展示")

    return "\n".join(lines)


def answer_with_sql(
    cfg: config.Config,
    question: str,
) -> dict:
    """
    完整 Text-to-SQL 链路：NL → SQL → 执行 → 格式化。

    参数:
        cfg:      配置对象
        question: 用户问题

    返回:
        {
            "question": 原始问题,
            "sql":      生成的 SQL,
            "results":  原始结果列表,
            "answer":   格式化后的回答,
        }
    """
    sql = generate_sql(cfg, question)
    results = execute_sql(cfg.go_backend_url, sql)
    answer = format_results(question, sql, results)

    return {
        "question": question,
        "sql": sql,
        "results": results,
        "answer": answer,
    }


# --------------------------------------------------------------------------- #
# 交互式演示
# --------------------------------------------------------------------------- #

def _chat_loop(cfg: config.Config) -> None:
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
            sql = generate_sql(cfg, user_input)
            print(f"📋 SQL: {sql}")

            print("📊 执行查询...")
            results = execute_sql(cfg.go_backend_url, sql)
            print(f"✅ 返回 {len(results)} 条结果")

            answer = format_results(user_input, sql, results)
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
    _chat_loop(cfg)
    print("👋 再见！")
