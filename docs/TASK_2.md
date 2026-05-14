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

- Day 3 文档分块 + Text-to-SQL
  - 实现分块策略，NL2SQL 链路落地

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

### Day 2：LangChain + Chroma 向量库

#### 🔧 前置准备

- 创建 Python 项目目录结构
  - `mkdir -p agent/{chain,embedding,vectorstore,scripts}`
- 创建虚拟环境
  - `python3 -m venv venv`
- 安装核心依赖
  - `pip install langchain langchain-openai chromadb requests python-dotenv httpx`
- 解决系统 sqlite3 版本过低导致 ChromaDB 无法启动的问题
  - `pip install pysqlite3-binary`

编码文件：

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
    - 原文分片的实现，可以扩展多种分片方法
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

### Day 3：文档分块 + Text-to-SQL

- 实现文档分块策略：短描述（<500 字）整块存储，长描述用递归分块 + 重叠窗口，每块带照片 ID 前缀
- 检索时按块查询，返回时聚合到照片级别
- 理解 Text-to-SQL 原理：Schema 提示 + Few-shot 示例 → LLM 生成 SQL
- 定义 `photos` 表 Schema，实现 NL2SQL 链路
- SQL 安全校验：只允许 SELECT 语句，执行前解析校验
- 在 FastAPI 暴露自然语言查询接口

---

### Day 4：SSE + Function Calling

- 理解 SSE（Server-Sent Events）原理，在 FastAPI 实现流式输出接口
- 对接 Go 后端 SSE 代理，前端展示打字机效果
- 定义照片工具函数：`search_photos`、`archive_photos`
- 实现 Function Calling：LLM 根据用户意图自动选择并调用工具
- 跑通"找照片"→触发搜索，"归档照片"→触发归档的完整链路

---

### Day 5：LangGraph 查询路由

- 理解 LangGraph 与 LangChain 的区别：显式 State + 条件分支 vs 线性 Chain
- 掌握 StateGraph 核心概念：State（TypedDict）、Node、Edge、Conditional Edge
- 实现查询路由 StateGraph：
  - 入口节点 `classify`：判断查询类型（结构化统计 / 语义检索）
  - 条件分支：`sql` 分支走 Text-to-SQL，`rag` 分支走 Chroma 检索 + LLM 生成
  - 汇聚节点 `answer`：格式化最终回答
- 在 FastAPI 暴露 `/workflow/query` 接口，替换直接链路调用
- 跑通两类查询：统计型走 SQL 分支，语义型走 RAG 分支

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
