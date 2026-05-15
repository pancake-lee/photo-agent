# 第二轮计划

## 架构定位

```
Chat CLI (Agent 编排 + 知识库 RAG + 聊天 CLI)
  ├─→ Go Backend (:10000)  ← 工具层（数据读写 + 文件服务）
  └─→ Python AI Service    ← 推理层（LangChain/LangGraph/Chroma）
```

## 一、总体时间规划（7 天）

> 实际推进速度更快，但任务保留这样的人物切分，就不改了

- Day 1 Go 工具扩展
  - 扩展 Go 后端 Photo 模型与导入流水线，增加 EXIF 字段，新增统计 API

- Day 2 LangChain + Chroma 向量库
  - 跑通 LangChain 核心链路，Chroma 向量检索接入

- Day 3 Text-to-SQL + RAG 照片级聚合
  - 实现 NL2SQL 链路，RAG 检索结果按照片聚合去重

- Day 4 SSE + Function Calling
  - 流式对话接口，LLM 自主调用照片工具

- Day 5 LangGraph 查询路由
  - 用 StateGraph 实现 SQL / RAG 条件路由工作流

- Day 6 评估指标 + AI 工程保障
  - 检索效果评估，重试 / 降级 / Token 成本追踪

- Day 7 联调 + 文档
  - 全链路联调，整理文档，确保可演示

## 二、每日任务

### ✅ Day 1（已完成）：Go 后端扩展 — EXIF 元数据 + 统计工具 API

> 所有变更在 Go 后端完成，不涉及 Python 代码。

#### 1.1 扩展 Photo 模型，获取并存储 EXIF

`internal/model/photo.go` — `Photo` 结构体新增 10 个 EXIF 字段：`Brand`, `Model`, `Lens`, `FocalLength`, `Aperture`, `ISO`, `ExposureTime`, `Latitude`, `Longitude`, `Altitude`。
GPS 字段用 `*float64` 指针，缺失时存 NULL。
GORM AutoMigrate 自动添加列。
并完成响应的读/写/传递代码。

#### 1.2 新增统计 API

`GET /api/photos/stats` — 返回 `total`、`brands`、`lens`、`focal_ranges`（5 段分桶）、`gps`、`monthly`、`hourly` 七维度统计。

`GET /api/photos` 新增筛选参数：`brand`、`lens`、`focal_min`/`focal_max`、`iso_min`/`iso_max`。

### ✅ Day 2：LangChain + Chroma 向量库

#### 🔧 前置准备

- 创建 Python 项目目录结构
  - `mkdir -p agent/{chain,embedding,vectorstore,scripts}`
- 创建虚拟环境
  - `python3 -m venv venv`
- 安装核心依赖
  - `pip install langchain langchain-openai chromadb requests python-dotenv httpx`
- 解决系统 sqlite3 版本过低导致 ChromaDB 无法启动的问题
  - `pip install pysqlite3-binary`

### 编码文件

- `agent/pyproject.toml` — Python 项目依赖定义
  - `pip install .` 或 `pip install -e .`
  - `requirements.txt`只是描述这个目录下py代码的依赖包列表，`pyproject.toml`则可以描述整个项目的情况
  - pip install -r requirements.txt

- `agent/config.py`
  - 提供 `Config` 类统一管理所有配置（LLM、Embedding、Go 后端地址）
  - `load_config()` 从 `-c`指定配置文件 读取 `llm `/`embedding `/`server` 配置
- `agent/chain/chat_agent.py`
  - V1 聊天循环，跑通LLM调用
    - 用上ChatPromptTemplate构造输入
    - 输入分为System/Human/AI
    - 用上`|`管道符“串联”处理方法

- Embedding
  - `agent/embedding/chunking.py`
    - 三种分片策略已实现，通过 `chunk_text` 统一入口分发
      - `none`：不分块，整块存储（默认，适用于短文档）
      - `fixed_size`：按固定字数分片，带重叠窗口（`chunk_size`/`chunk_overlap` 可配置，`chunk_size` 默认值优先取配置，无配置时按 `context_size * 50%` 计算，兜底 500）
      - `markdown_heading`：按 Markdown 标题分片（默认二级标题 `##`，`heading_level` 可配置 1-6）
    - `chunk_text` 统一调用入口，用枚举值指定分块策略，用户自己做策略的配置或者选择，然后调用该接口进行分块
    - `chunk_test_auto` 内部实现了一个根据输入内容做简单识别的自动策略，短文本不分块，长文本如果是md格式则尝试分块，否则按长度分块
    - `agent/scripts/index_photos.py` 增量索引脚本已接入配置驱动的分块策略，`_strategy_label` 记录策略参数用于变更检测
  - `agent/embedding/embedder.py`
    - 调用go-server `/v1/embeddings` 代理，标准 OpenAI 格式
    - 未使用 `langchain_openai.OpenAIEmbeddings`，原因是其默认启用 tiktoken 会将文本预编码为 token ID 数组传给 API，而 go-server 代理只接受原始字符串 input。禁用 tiktoken 后又依赖 transformers tokenizer，不在当前依赖中，故直接使用 httpx 发送标准 OpenAI 格式请求。
    - `agent/embedding/demo_embedding.py` — 演示脚本，从 JSON 取头尾各 1 条 → 分片 → Embedding → 输出结果

- `agent/vectorstore/chroma_client.py`
  - 提供 `add` / `delete` / `query` / `get` / `peek` / `count` 方法
  - 内置 `_format_results` / `_format_get_results` 统一格式化 Chroma 原始返回结构
  - 自动处理低版本 sqlite3 兼容（`pysqlite3` 替代注入）

- `agent/scripts/index_photos.py`
  - 从data/descriptions.json，批量生成 Embedding，写入 Chroma。

- `agent/chain/photo_rag.py`
  - index_photos.py已经处理好向量数据入库
  - 用户问题 → Embedding → Chroma 检索 Top-K → 拼接上下文 → LLM 生成

### ✅ Day 3（已完成）：Text-to-SQL + RAG 照片级聚合

#### 3.1 RAG 检索结果聚合到照片级别

`agent/chain/photo_rag.py`：

- 新增 `_aggregate_by_photo`：按 `photo_id` 聚合 chunk 级检索结果，同一照片仅保留相似度最高（距离最小）的一条
- `answer_question` 新增 `aggregate` 参数（默认 `True`），内部先检索 `n_results * 3` 个 chunk，聚合后再返回 `n_results` 张照片
- `chat_loop` 默认使用聚合模式，避免同一照片的多 chunk 在回答中重复出现

#### 3.2 Text-to-SQL 链路

`agent/chain/text_to_sql.py`：

- **Schema 提示**：运行时从 Go 后端 `/api/schema/photos` 获取表结构，`_format_schema` 将 JSON schema 格式化为 LLM 可用的文本（字段名、SQL 类型、JSON tag、可空性 + 注意事项）
- **Few-shot 示例**：6 个典型查询样例（计数、品牌筛选、时间范围、ISO 范围、GPS 统计、焦距数值比较）
- **LLM 生成**：`ChatPromptTemplate` 构建 System + Few-shot + Human 消息链，temperature=0 保证确定性
- **SQL 提取**：`_extract_sql_from_response` 支持 Markdown 代码块和纯文本两种输出格式
- **安全校验**：`validate_select_only` 双保险——首词必须是 `SELECT`，且全文正则扫描禁止 INSERT/UPDATE/DELETE/DROP/CREATE/ALTER/TRUNCATE/REPLACE/ATTACH/DETACH/PRAGMA
- **执行与格式化**：`answer_with_sql` 提供完整链路，通过 Go 后端 `/api/query/sql` 接口执行查询，`format_results` 将结果集转为自然语言摘要

Go 后端：

- `internal/api/query.go`：新增 `POST /api/query/sql` 接口，接收 `{ "sql": "..." }`，返回 `{ "columns": [...], "rows": [...], "count": N }`
- `internal/api/schema.go`：新增 `GET /api/schema/photos` 接口，通过反射从 `model.Photo` 动态提取字段信息（Go 类型、SQL 类型、JSON/GORM tag、可空性），返回结构化 JSON
- `internal/service/query.go`：`ValidateSelectOnly` + `ExecuteSelectSQL`，服务端 SQL 安全校验，默认 limit=100、最大 1000

`agent/db/sqlite_client.py`：

- `QueryClient`：通过 HTTP 调用 Go 后端 `/api/query/sql` 接口执行查询，Python 层不直连 SQLite
- `validate_select_only`：客户端双重保险，仅允许 SELECT，禁止危险关键字
- `safe_execute`：带校验的安全执行入口

#### 3.3 测试

`agent/tests/test_text_to_sql.py`（36 个用例）：

- SQL 安全校验：覆盖合法 SELECT、多行、注释，以及 10+ 种非法注入场景
- SQL 提取：Markdown 代码块、纯文本、含解释文本
- Schema 格式化：字段列表渲染、可空性标记、注意事项渲染
- 结果格式化：空结果、单行、多行、截断
- RAG 聚合：空结果、单 chunk、同照片多 chunk 取最佳、多照片排序、`photo_id` 缺失跳过
- Few-shot 消息构建
- QueryClient：客户端校验拦截、safe_query 异常封装

---

### ✅ Day 4：Streaming + Function Calling

- Streaming
  - `agent/chain/chat_agent.py` 与 `agent/chain/photo_rag.py`
    - LLM 实例均开启 `streaming=True`，用 `chain.stream()` 执行
  - `agent/utils/streaming_printer.py`
    - 后台线程按当前速度逐字输出，主循环不被阻塞
    - 速度控制用微分先行的PID算法，速度平滑又自动追上LLM实际输出
      - 单纯是学生时代用过，拿来玩玩而已
  - 完整回复拼接后存入对话历史，不影响多轮上下文

- Function Calling
  - Go后端提供自解释的接口`/v1/openapi.json`，获取自己所有接口的OpenAPI文档
    - PS: 顺便，路由统一添加 `v1` 前缀
  - Py侧自动解析 OpenAPI 并转换为 LLM 工具
    - `agent/tools/openapi_client.py` — `OpenAPIClient` 类：
      - `_fetch_doc` 从 `/v1/openapi.json` 拉取文档
      - `_parse_tools` 将 paths → OpenAI function definitions
      - `_build_request` 根据参数构建 HTTP 请求
      - `execute` 发送实际请求并返回结果
    - 工具名生成规则：`{method}_{path_segments}`，如 `get_photos`、`post_photos_id_archive`
  - Function Calling 聊天循环
    - `agent/chain/function_agent.py` — 完整多轮对话 Agent：
      - `llm.bind_tools(function_defs)` 绑定所有可用工具
      - 第一轮llm请求，处理llm的回复
        - 提取 `tool_calls`
        - 执行工具：`tool_client.execute` 发送 HTTP
      - 第二轮llm请求：、
        - 基于工具结果生成最终回答，控制台实时输出
  - 测试 `agent/tests/test_function_calling.py`
    - 12 个用例覆盖工具名生成、参数解析、请求构建、body 拼接、未知工具处理

---

### ✅ Day 5（已完成）：LangGraph 查询路由

- `agent/chain/query_router.py` — LangGraph StateGraph 查询路由
  - `classify` 节点：LLM 分类器，temperature=0，根据问题语义判别 sql/rag，无法判别时兜底 rag
  - `sql_query` 节点：复用 `text_to_sql.answer_with_sql()`，异常时返回错误文本
  - `rag_query` 节点：复用 `photo_rag.answer_question()`，异常时返回错误文本
  - `answer` 节点：从 `sql_result.answer` 或 `rag_answer` 提取最终回答，空值时兜底提示
  - `_build_graph()` 构建 StateGraph：START → classify(llm) → 条件边 → sql_query(llm)/rag_query(llm) → answer → END

---

### Day 6：检索评估 + AI 工程保障

#### 检索评估

- 理解 RAG 评估指标：Precision@K、Recall@K、MRR
- 构建测试集：人工标注 20~50 个查询-相关照片对
- 编写评估脚本，对比不同分块策略的表现，记录基线数据

#### AI 工程保障三件套

- **重试**：所有 LLM/VLM/Embedding 调用接入 `tenacity` 指数退避重试（约 2s/4s/8s），仅对超时和连接异常重试
- **降级**：LangChain Chain 接入 `with_fallbacks`，主模型（Doubao-pro）失败时自动降级到备用模型（Doubao-lite）
- **Token 成本追踪**：SQLite 建 `token_usage` 表，配置 `prices.yaml` 模型单价，调用封装层记录 input/output token 用量并计算成本
- 提供 `/admin/usage` 按天 / 按模型聚合统计接口

---

### Day 7：联调 + 文档

- 全链路端到端联调：Go 后端 ↔ Python 服务 ↔ Chroma ↔ LLM 代理
- 覆盖场景测试：向量检索、Text-to-SQL、SSE 流式对话、Function Calling 工具调用、LangGraph 查询路由
- 验证 AI 工程保障：重试触发、降级切换、Token 追踪落库
- 整理 README，说明 Python 服务层架构、模块职责、启动方式
- 确保所有代码可运行、可演示

## TODO

- 对接LLM的 SSE（Server-Sent Events）原理，WEB前端展示打字机效果
  - 当前还是py写的cli应用，还没有上WEB页面
- 流式输出，和，print直接打印，发生交叉了
  - 进入LLM循环后，所有打印都要走流式输出
