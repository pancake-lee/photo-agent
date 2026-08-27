"""
    Text-to-SQL 链路：自然语言 → Schema 提示 + Few-shot → LLM 生成 SQL → 安全校验 → 执行 → 格式化回答

    核心功能供 photo_agent 复用，独立演示见 demo/text_to_sql_demo.py。

    架构:
        1. Schema 提示: 定义 photos 表结构、字段类型、可查询维度
        2. Few-shot 示例: 基础与结构化属性查询样例，引导 LLM 生成正确 SQL
        3. LLM 生成: ChatPromptTemplate (System + Few-shot Human/AI + 用户问题)
        4. SQL 安全校验: validate_select_only 确保仅 SELECT（客户端双重保险）
        5. 执行查询: 通过 Go 后端 /api/v1/query/sql 接口执行（Python 不直连 SQLite）
        6. 格式化回答: 将结果集转为自然语言摘要
"""

import json
import logging
import pathlib
import re
import sys
import typing

import langchain_core.prompts as lc_prompts

import config
import db.sqlite_client as sqlite_client
import utils.llm_factory as llm_factory

logger = logging.getLogger(__name__)

# 属性值缓存（按 base_url），避免每次生成 SQL 都请求 Go 后端
_attr_cache: dict[str, dict] = {}


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
    # === 结构化属性过滤 (objects / colors / scene / lighting / mood / composition) ===
    # 注意: 属性值必须匹配数据库中实际存储的值（由 Go mapping 函数产出），
    # 系统提示中会列出当前数据库的可用值，LLM 生成 SQL 时应参照系统提示而非硬编码示例值。
    {
        "question": "逆光的风景照",
        "sql": "SELECT id, filename, description, lighting, scene FROM photos WHERE lighting LIKE '%backlit%' AND scene IN ('nature', 'mountain', 'water') ORDER BY shot_at DESC LIMIT 20",
    },
    {
        "question": "暖色调的人像照片",
        "sql": "SELECT id, filename, description, colors FROM photos WHERE colors LIKE '%warm%' AND (objects LIKE '%person%' OR objects LIKE '%people%') ORDER BY shot_at DESC LIMIT 20",
    },
    {
        "question": "黑白高对比度的照片",
        "sql": "SELECT id, filename, description, colors FROM photos WHERE (colors LIKE '%monochrome%' OR colors LIKE '%black_white%') AND colors LIKE '%high_contrast%' ORDER BY shot_at DESC LIMIT 20",
    },
    {
        "question": "柔和光线的照片",
        "sql": "SELECT id, filename, description, lighting FROM photos WHERE lighting LIKE '%soft%' ORDER BY shot_at DESC LIMIT 20",
    },
    {
        "question": "宁静氛围的水边照片",
        "sql": "SELECT id, filename, description, mood, scene FROM photos WHERE (mood LIKE '%calm%' OR mood LIKE '%melancholy%') AND scene = 'water' ORDER BY shot_at DESC LIMIT 20",
    },
    {
        "question": "有哪些街拍照片？",
        "sql": "SELECT id, filename, description, scene FROM photos WHERE scene LIKE '%street%' OR scene LIKE '%urban%' ORDER BY shot_at DESC LIMIT 20",
    },
]

# --------------------------------------------------------------------------- #
# Prompt 构建
# --------------------------------------------------------------------------- #

SQL_SYSTEM_PROMPT_TEMPLATE = (
    "你是一位 SQL 专家。根据下面的数据库表结构和示例，将用户的问题转换为正确的 SQLite SQL 查询。\n\n"
    "表结构:\n"
    "{schema}\n\n"
    "结构化属性字段说明（均为 TEXT 类型，逗号分隔多值，查询时使用 LIKE 匹配）。\n"
    "**以下是当前数据库中实际存在的值，请 STRICTLY 仅使用这些值构造 LIKE 模式：**\n\n"
    "{attr_values}\n\n"
    "规则:\n"
    "1. 仅生成 SELECT 查询语句\n"
    "2. 字段名必须严格匹配表结构\n"
    "3. 字符串值用单引号包裹\n"
    "4. 时间比较使用 strftime 函数\n"
    "5. JSON 标签字段 tags 用 LIKE 匹配\n"
    "6. 结果限制在 20 条以内，除非用户明确要求更多\n"
    "7. 如果问题无法从表中回答，返回: SELECT '无法回答' AS result\n"
    "8. 只输出纯 SQL，不要任何 Markdown 代码块或解释\n"
    "9. 结构化属性字段（objects/colors/scene/lighting/mood/composition）使用 LIKE '%value%' 模糊匹配，多条件用 AND/OR 组合\n"
    "10. **重要**: 仅使用上面列出的数据库实际值，不要自创值。如果用户查询的概念在数据库中没有对应值，使用语义最接近的已有值"
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
    # from langchain_core.prompts import SemanticSimilarityExampleSelector
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
        ("system", SQL_SYSTEM_PROMPT_TEMPLATE),
        few_shot,
        ("human", "{question}"),
    ])


def _fetch_attribute_values(base_url: str) -> dict:
    """
    从 Go 后端获取当前数据库中结构化属性的去重值。

    结果按 base_url 缓存，避免每次 SQL 生成都请求。

    参数:
        base_url: Go 后端地址

    返回:
        {"objects": [...], "colors": [...], "scene": [...], ...}
        如果 API 不可用则返回空 dict
    """
    if base_url in _attr_cache:
        return _attr_cache[base_url]

    try:
        import utils.backend_sdk as bksdk
        query_api = bksdk.get_query_api(base_url)
        resp = query_api.query_service_get_attribute_values()
        values = resp.values or {}
        _attr_cache[base_url] = values
        logger.info(
            "获取属性值: objects=%d colors=%d scene=%d lighting=%d mood=%d composition=%d",
            len(values.get("objects") or []),
            len(values.get("colors") or []),
            len(values.get("scene") or []),
            len(values.get("lighting") or []),
            len(values.get("mood") or []),
            len(values.get("composition") or []),
        )
        return values
    except Exception:
        logger.warning("获取属性值失败，将使用空值列表", exc_info=True)
        return {}


def _format_attribute_values(attr: dict) -> str:
    """
    将属性值 dict 格式化为 LLM prompt 可用的文本。

    参数:
        attr: _fetch_attribute_values 的返回值

    返回:
        格式化后的属性值文本
    """
    if not attr:
        return "（无法获取数据库当前值，请根据字段含义自行判断）"

    lines: list[str] = []
    for field, label in [
        ("objects", "主体类型"),
        ("colors", "主色调"),
        ("scene", "场景类型"),
        ("lighting", "光线类型"),
        ("mood", "情绪氛围"),
        ("composition", "构图特点"),
    ]:
        vals = attr.get(field) or []
        if vals:
            vals_str = ", ".join(vals)
            lines.append(f"- {field} ({label}): {vals_str}")
        else:
            lines.append(f"- {field} ({label}): （暂无数据）")
    return "\n".join(lines)


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


def _format_schema(schema_data) -> str:
    """
    将 API 返回的 schema 格式化为 LLM 可用的文本。

    参数:
        schema_data: Go 后端 /api/v1/schema/photos 返回的 ApiGetPhotoSchemaResponse

    返回:
        格式化后的 schema 文本
    """
    lines: list[str] = []
    lines.append(f"表名: {schema_data.table_name or 'photos'}")
    lines.append("")
    lines.append("字段说明:")

    for field in (schema_data.fields or []):
        name = field.name or ""
        sql_type = field.sql_type or "TEXT"
        json_tag = field.json_tag or ""
        nullable = field.nullable or False
        null_str = "，可能为 NULL" if nullable else ""
        lines.append(f"- {name} ({sql_type}): JSON tag = {json_tag}{null_str}")

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

def _build_llm(cfg: config.Config):
    """构建 LLM 实例（带重试和降级）。"""
    return llm_factory.create_llm(cfg, temperature=0.0)


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

    attr = _fetch_attribute_values(cfg.go_backend_url)
    attr_text = _format_attribute_values(attr)

    llm = _build_llm(cfg)
    prompt = _build_sql_prompt()

    chain = prompt | llm
    response = chain.invoke({
        "schema": schema_text,
        "attr_values": attr_text,
        "question": question,
    })

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
    return result.rows or []


def execute_sql_for_ids(
    base_url: str,
    sql: str,
    limit: int = 50,
) -> list[str]:
    """
    执行 SQL 查询，仅提取 photo id 列表。

    用于组合查询场景（SQL 结构化过滤 + RAG 语义检索取交集）。

    参数:
        base_url: Go 后端地址
        sql:      SQL 字符串（应 SELECT 包含 id 字段）
        limit:    最大返回行数

    返回:
        photo_id 字符串列表（去重）
    """
    rows = execute_sql(base_url, sql, limit=limit)
    ids: list[str] = []
    seen: set[str] = set()
    for row in rows:
        pid = row.get("id")
        if pid and pid not in seen:
            seen.add(pid)
            ids.append(pid)
    return ids


def generate_filter_sql(
    cfg: config.Config,
    question: str,
) -> str:
    """
    为组合查询生成聚焦结构化属性的过滤 SQL。

    与 generate_sql 的区别：提示 LLM 优先使用 objects/colors/scene/lighting/
    mood/composition 等结构化字段，返回的 SQL 必须包含 id 字段。

    参数:
        cfg:      配置对象
        question: 用户问题

    返回:
        生成的 SQL 字符串（已通过安全校验）
    """
    schema_data = _fetch_schema(cfg.go_backend_url)
    schema_text = _format_schema(schema_data)

    attr = _fetch_attribute_values(cfg.go_backend_url)
    attr_text = _format_attribute_values(attr)

    llm = _build_llm(cfg)
    prompt = _build_sql_prompt()

    # 在用户问题前添加结构化过滤引导
    guided_question = (
        f"【结构化过滤】优先使用 objects/colors/scene/lighting/mood/composition "
        f"字段筛选，SELECT 必须包含 id 字段。问题: {question}"
    )

    chain = prompt | llm
    response = chain.invoke({
        "schema": schema_text,
        "attr_values": attr_text,
        "question": guided_question,
    })

    raw_text = str(response.content)
    sql = _extract_sql_from_response(raw_text)

    if not sql:
        raise ValueError("LLM 未生成有效的过滤 SQL")

    _validate_sql_safe(sql)

    return sql


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
