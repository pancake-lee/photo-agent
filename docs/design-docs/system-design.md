# Photo Agent 系统设计与接口参考

> 规划类型为资料驱动规划，来源为项目既有技术说明。本文保留详细数据流、接口和模型约定，系统导航见[架构入口](../ARCHITECTURE.md)。

> Go 业务后端（照片存储/EXIF/VLM/Embedding代理）+ Python AI 服务层（LangGraph 编排/Chroma 向量检索/Text-to-SQL） + Web 前端（Vue 3 + NaiveUI）。
> 早期曾用 Dify 验证 Agent 可行性，现已不作为核心方案。

## 专题设计

- [Web 照片上传](2026-06-18-web-photo-upload-design.md)记录原片、缩略图和同名处理。
- [聚类结果审阅](2026-07-26-cluster-review-design.md)记录向量聚类、主题生成和标题评估。
- [Agent 多步任务](2026-08-31-agent-tasks-design.md)记录目标准入、权威范围、恢复和多轮续跑。
- [检索黄金用例与回归](2026-08-25-golden-query-design.md)记录用例契约、指标快照和三层回归。
- [AI 照片资产质量](2026-08-26-ai-asset-quality-design.md)记录描述校验、向量版本和检索准入。
- [Windows 桌面导入](2026-08-11-desktop-import-design.md)记录中转目录、收藏 NEF 迁移与同步边界。
- [主题发现](2026-08-01-topic-discovery-feature-design.md)记录提案管线、版本重跑和工坊交接。
- [连拍分组](2026-08-19-burst-grouping-design.md)记录双档识别、重算、组内取数与封面维护。
- [图片管理分段浏览](2026-08-20-lb-photo-list-browsing-design.md)记录筛选、导航定位及双向窗口。
- [组图检索](2026-08-22-grouped-retrieval-design.md)记录检索粒度、组向量集合与同步。
- [图文工坊](2026-08-23-post-studio-feature-design.md)记录照片编排、文案生成、草稿和导出。

- [照片选择与已选展示](2026-08-26-photo-selection-design.md)记录覆盖层、会话协议和组内精选。

---

## 1. 整体架构

```mermaid
flowchart LR
    A["Web 前端<br>Vue 3 + NaiveUI, :10006"]
    A -->|"/api/v1/*"| B["Go Backend<br>:10004"]
    A -->|"/api/chat/* 等"| C["Python Agent API<br>:10005"]

    C -->|Text-to-SQL| D["Go /api/v1/sql/query"]
    C -->|Function Calling| E["Go /v1/openapi.json → 工具调用"]
    C -->|RAG| F["ChromaDB<br>本地向量库"]
    C -->|Embedding| G["Go /v1/embeddings<br>代理"]
    C -->|聚类分析| H["ChromaDB 向量聚类<br>HDBSCAN + UMAP"]
    C -->|选题建议| I["suggest.py<br>三阶段编辑视角提案"]
    C -->|黄金用例| J["data/agent/retrieval-golden-queries.json"]

    B --> K["照片 CRUD / 文件服务 / 统计 API"]
    B --> M["VLM: 实时调用 VLM API 生成描述"]
    B --> N["Embedding HTTP 代理<br>OpenAI 格式 → 火山引擎"]
    B --> O["SQLite<br>照片元数据 + 结构化属性"]
```

### 1.1 职责边界

- **Go 后端**：照片元数据管理、文件服务、上传导入、VLM 实时描述生成、Embedding 代理、SQL 查询执行、OpenAPI 自描述。**不负责**：Agent 编排、向量检索、对话管理。
- **Python AI 服务层**：LangGraph Agent 编排、Chroma 向量检索、Text-to-SQL（NL→LLM→SQL→Go执行）、Function Calling 工具调用、FastAPI 对话服务。**不负责**：直接访问数据库或文件系统（所有数据操作通过 Go API）。
- **Web 前端**：照片管理（上传/浏览/筛选/删除）、AI 对话界面、选题/聚类/图文工坊结果浏览、VLM/Embedding 队列可视化、导入工作流与设置。**不负责**：AI 推理、文件存储。

---

## 2. 技术栈

- **Web 前端**：Vue 3 (Composition API + TypeScript) + NaiveUI + Vite
- **Python Agent**：FastAPI + LangChain + LangGraph + ChromaDB + httpx
- **Go 后端**：Kratos v2 + GORM + SQLite + ImageMagick
- **AI 模型**：GPT-4o-mini / Qwen / 火山引擎 Doubao（LLM + VLM + Embedding）

---

## 3. 核心数据流

### 3.1 照片导入与 VLM 闭环

```mermaid
flowchart TD
    A[Web 上传照片] --> B["POST /api/v1/photos/upload<br>保存原图 → 压缩缩略图 → 读 EXIF → 写入 SQLite"]
    B --> C["详情页点击'生成描述'"]
    C --> D["POST /api/v1/photos/:id/describe<br>Go 后端实时调用 VLM API"]
    D --> E["VLM 返回描述 + 结构化 JSON 块"]
    E --> F["解析结构化属性<br>objects/colors/scene/lighting/mood/composition"]
    F --> G["写入 SQLite photos 表<br>description + description_model + description_time + 6 个属性"]
    G --> H["顶栏 Embed 按钮触发<br>Python EmbedQueue → Go Embedding 代理 → ChromaDB"]
```

### 3.2 Agent 查询路由（LangGraph）

```mermaid
flowchart TD
    A["用户问题（自然语言）"] --> B["[classify] 结构化路由决策<br>直接路径 | 已注册 Runtime 目标 | 未支持目标"]

    B -->|sql| C["[_sql_node]<br>NL → generate_sql() → LLM 生成 SQL<br>→ Go POST /api/v1/sql/query 执行<br>→ 结果格式化为自然语言"]

    B -->|rag| D["[_rag_node]<br>问题 → Embedding → ChromaDB 向量检索 Top-K<br>→ 按 photo_id 聚合去重 → 比值断层过滤<br>→ 拼接上下文 → LLM 生成回答"]

    B -->|tool| E["[_tool_node]<br>LLM.bind_tools(Go OpenAPI spec)<br>→ LLM 自主决策调用哪个 API<br>→ 执行 HTTP 请求 → 结果返回 LLM → 生成回答"]

    B -->|combined| F["[_combined_node]"]
    F --> G["generate_filter_sql()<br>LLM 生成结构化过滤 SQL"]
    G --> H["execute_sql_for_ids()<br>sql_ids（必须含 id 字段）"]
    F --> I["retrieve_photo_ids()<br>rag_ids（纯向量语义检索）"]
    H --> J["intersection = sql_ids ∩ rag_ids<br>保持 RAG 相似度排序"]
    I --> J
    J --> K["_fetch_photos_batch()<br>并行获取照片详情"]
    K --> L["LLM 生成最终回答"]

    J -.->|"降级策略（任一失败 → 纯 RAG）<br>SQL异常 / SQL>50条 / SQL空 / 交集空 / 整体异常"| D

    B -->|runtime| N["[_runtime_node]<br>Agent Runtime 多步执行<br>（开放目标：选片 + 创作）"]

    B -->|unsupported_goal| U["[_unsupported_goal_node]<br>说明当前边界，不执行照片库操作"]

    C --> M["[_answer_node]<br>聚合结果 → answer + photos"]
    D --> M
    E --> M
    L --> M
    N --> M
    U --> M
```

### 3.2.1 Agent Runtime 开放目标执行

已注册的开放目标进入 Runtime，单步查询沿用直接路由。Runtime 按约束确认范围、执行能力并检查交付要件。详细循环、失败恢复和多轮快照见 [Agent 多步任务详细设计](2026-08-31-agent-tasks-design.md)。

### 3.3 Combined 组合查询详解

这是 `"蓝调时刻的街拍"` 一类复合查询的核心流程：

```mermaid
flowchart TD
    A["用户: 逆光的雪山照片"] --> B["classify → combined<br>结构化维度 逆光 + 语义内容 雪山"]

    B --> C["1. SQL 结构化过滤<br>generate_filter_sql<br>LLM 根据实际 DB 属性值生成 SQL<br>→ Go 执行"]
    C --> D["sql_ids: p1, p3, p5, p7, ..."]

    D --> E["2. RAG 语义检索<br>retrieve_photo_ids<br>Embedding → ChromaDB Top-20<br>→ 聚合 → 断层过滤"]
    E --> F["rag_ids: p3, p7, p1, p10, p2, ...<br>（相似度排序）"]

    F --> G["3. 交集（保持 RAG 排序）<br>intersection = p3, p7, p1<br>从 rag_ids 中筛选同时在 sql_ids 中的"]

    G --> H["4. 批量获取照片详情<br>_fetch_photos_batch<br>并行 GET /api/v1/photos/id"]

    H --> I["5. LLM 生成回答"]
```

**SQL 值动态获取**：每次 `generate_sql()` / `generate_filter_sql()` 调用前，先从 Go `GET /api/v1/sql/photos/attribute-values` 获取数据库中实际存在的属性值，拼入 System Prompt。LLM 只能使用实际值构造 LIKE 模式，避免生成数据库中不存在的值。结构化属性值是 VLM 输出的中文原文（如「逆光」「暖黄」「室内」），不再做中英映射。

### 3.4 Text-to-SQL 链路细节

```mermaid
flowchart TD
    A[用户问题] --> B["1. 获取 Schema<br>GET /api/v1/sql/photos/schema<br>字段名/类型/可空性"]
    B --> C["2. 获取属性值<br>GET /api/v1/sql/photos/attribute-values<br>6 个字段的 distinct 值"]
    C --> D["3. 构建 Prompt<br>System: 表结构 + 属性值 + 生成规则<br>Few-shot: 若干 NL→SQL 示例<br>Human: question"]
    D --> E["4. LLM 生成 SQL<br>temperature=0"]
    E --> F["5. 提取 SQL<br>处理 Markdown 代码块包裹"]
    F --> G["6. 安全校验<br>仅允许 SELECT"]
    G --> H["7. Go 执行<br>POST /api/v1/sql/query<br>返回 rows"]
```

### 3.5 VLM 预处理

- **VLM 描述生成**：Go 后端 `VlmServer` — 单张实时调用火山方舟 Responses API 生成描述，批量模式遍历无描述照片逐张生成。描述 + 模型名 + 时间直接写入 SQLite photos 表
- **图片压缩**：VLM 调用前自动用 ImageMagick 压缩（`convert -resize 512x512> -quality 85`），上传时同样压缩生成缩略图
- **结构化提取**：`parseVlmAttrs()` 从 VLM 输出的 ```json 块中解析 6 个维度（objects/colors/scene/lighting/mood/composition）

### 3.6 ChromaDB 向量库设计

ChromaDB 保存向量、照片与分块标识、向量版本和组图元数据。Go SQLite 维护拍摄属性，组合查询以照片 ID 汇合语义与结构化结果。

**索引流程**：

```
photos 表 description → 分块器（chunk_strategy 配置控制）→ Embedding(Go代理) → ChromaDB
```

**检索流程**：

```
问题 → Embedding → ChromaDB.query(Top-K chunks) → _aggregate_by_photo()
→ _filter_by_ratio_gap() → 构建上下文 → LLM 回答
```

- 分块策略：由 `Embedding.ChunkStrategy` 配置控制，支持 none（不分块，默认）/ fixed_size（固定字数）/ markdown_heading（按标题）；fixed_size 时使用 `Embedding.ChunkSize=500`、`Embedding.ChunkOverlap=50`
- 聚合：同一照片多 chunk 只保留距离最小的一条
- 自动截断：相邻距离比值 ≥1.8 时截断（Max Ratio Gap），保留相关性高的结果

### 3.7 活动目录与时间线同步

拍摄活动直接对应 `Storage.PhotoSrc` 下的普通一级子目录，隐藏工作目录不参与。目录名为活动名称的事实来源；活动时间、备注和稳定 UUID 写在目录内的 `.photo-agent.json`，日期支持 `YYYY-MM-DD` 或带时区的 RFC3339，也可留空。首次迁移尽量继承旧事件日期、备注，其余从照片时间或目录年月初始化。

- 照片位置：数据库保存 `activity_id`、`timeline`（可查询的当前目录名缓存）及 `filename`。API `file_path` 由目录名和文件名组合，不再持久化完整或相对文件路径；旧 `file_path` 列清空并停止写入，旧人工归属标记不再参与决策。
- 同步：启动及位置相关请求之前扫描目录，根据稳定 ID 识别外部改名，同步名称缓存、展示预览、导入去重键和回收记录；不重新执行 VLM 或 Embedding，向量仍通过照片 ID 关联。相同目录元数据 ID、大小写冲突、损坏元数据或缺失已绑定目录均报错，不猜测合并。
- 改名：客户端修改活动名会改源目录，按同一同步流程迁移预览并更新数据库。预览附带身份标识，支持移动后、数据库提交前中断的重试。数据库写入失败会尝试回滚预览；客户端操作失败会尝试恢复原目录和元数据，返回包含恢复失败原因的错误。
- 导入：回执返回稳定活动 ID 与当前名称，后续请求也可携带照片 ID，使旧回执在活动改名后仍能定位。相同活动内按 JPG 摘要复用已归档图片，收藏用逻辑或合并；缺省 NEF 的收藏导入不会覆盖已有配对。不同 JPG 内容继续按冲突规则另存。
- 边界：存在正式上传保留位置时禁止改名；直接在文件系统改名遇到此情况，需要先恢复原名并完成导入。正在选片且尚无归档回执的批次，改名后需重新选择当前活动。
- 删除：只能删除没有照片记录、有效回收记录、上传保留位置且目录为空的活动。活动时间不参与文件归属，也不生成散片组。
- 兼容：原重算 API 改为同步执行目录核对，成功返回 `completed`，状态接口返回本次核对数量。旧事件 CRUD 转接目录服务；旧 `timeline_events` 表保留 schema，完成迁移后清空，不再维护活动副本。

实现入口：[目录同步](../../backend/internal/defaultService/service/activity_directory.go)、[活动服务](../../backend/internal/defaultService/service/svc_timeline.go)、[数据迁移](../../backend/internal/defaultService/data/dao_activity.go)。产品验收见[时间线管理](../product-specs/photo-agent.md#28-时间线管理)。

---

## 4. API 设计

### 4.1 Go Backend API(`/api/v1`)

**照片管理**：

- `GET /photos` — 照片列表（分页、timeline/tag/keyword/brand/lens/focal/iso 筛选、排序）
- `GET /photos/stats` — 综合统计（total/brands/lens/focal/gps/monthly/hourly）
- `GET /photos/segments` — 分段导航（当前筛选+排序下每个分段的 key/label/count/offset）
- `GET /photos/ai-audit` — AI 描述质量审核（批量修复前的只读候选摘要）
- `GET /photos/:id` — 单张详情（含 6 个结构化属性）
- `GET /photos/:id/image` — 图片文件（?size=thumb 缩略图）
- `POST /photos/:id/describe` — 单张 VLM 描述生成
- `POST /photos/:id/ai-validate` — 重新执行当前描述的本地质量校验（不调用 VLM）
- `POST /photos/:id/ai-health` — 回写照片的向量处理结论（由 Embedding 服务调用）
- `PUT /photos/:id/tags` — 更新标签
- `PUT /photos/:id/shot_at` — 修改拍摄时间（写 DB + 回写 EXIF）
- `DELETE /photos/:id` — 删除照片（DB + 文件）
- `POST /photos/upload` — 上传照片（冲突检测：overwrite/skip/keep_both）

**VLM 队列**：

- `POST /vlm/queue/start` — 启动批量 VLM（普通批次处理缺描述，force 还纳入当前描述待复核的照片）
- `POST /vlm/queue/stop` — 停止队列
- `GET /vlm/queue/status` — 队列进度（total/completed/failed/current）
- `GET /vlm/describe/progress` — 单张描述进度

**查询 & Schema**：

- `POST /sql/query` — 执行 SELECT SQL（安全校验，仅允许 SELECT）
- `GET /sql/photos/schema` — 表结构（反射自 model.Photo）
- `GET /sql/photos/attribute-values` — 6 个结构化字段的 distinct 值

**标签**：

- `GET /tags` — 标签列表
- `GET /tags/:name/photos` — 某标签下照片
- `POST /tags/bind` — 批量绑定标签
- `POST /tags/unbind` — 批量解绑标签

**时间线**：

- `GET /timelines` — 时间线列表
- `GET /timelines/:name/photos` — 某时间线下照片
- `GET /timeline-events` — 时间线事件列表
- `POST /timeline-events` — 新建或更新活动事件
- `POST /timeline-events/recompute` — 同步活动目录，成功返回 completed
- `GET /timeline-events/recompute/status` — 最近一次目录同步计数
- `DELETE /timeline-events/:id` — 删除空活动目录

**连拍分组**：

- `GET /burst-groups/config` — 连拍分组阈值配置
- `PUT /burst-groups/config` — 更新阈值配置
- `POST /burst-groups/rebuild` — 重建连拍分组
- `GET /burst-groups/status` — 分组状态
- `PUT /burst-groups/:group_id/cover` — 设置组封面

**图文工坊草稿**：

- `POST /drafts` — 创建草稿（title/content/photo_ids/style/source/input_mode/prompt/draft_input）
- `PUT /drafts/:id` — 更新草稿
- `DELETE /drafts/:id` — 删除草稿
- `GET /drafts` — 草稿列表
- `GET /drafts/:id` — 单条草稿详情
- `GET /drafts/:id/export` — 导出已保存草稿的 ZIP

**存储**：

- `POST /storage/conflicts` — 检查待上传文件名的重名情况
- `GET /storage/info` — 存储根目录状态信息

**其他**：

- `GET /health` — 健康检查

**独立路由**（非 `/api/v1` 前缀）：

- `POST /v1/embeddings` — Embedding 代理（OpenAI 格式 → 火山引擎）
- `GET /v1/embeddings/health` — Embedding 服务配置可用性检查
- `GET /v1/openapi.json` — OpenAPI 3.0 自描述（Python Agent 工具解析）

### 4.2 Python Agent API（FastAPI, :10005）

**对话**：

- `GET /api/chat/health` — 健康检查，包含价格配置是否可用及降级原因
- `POST /api/chat/sessions` — 创建会话
- `GET /api/chat/sessions` — 会话列表
- `GET /api/chat/sessions/:id` — 会话详情
- `GET /api/chat/sessions/:id/messages` — 会话消息列表
- `PATCH /api/chat/sessions/:id` — 更新标题
- `DELETE /api/chat/sessions/:id` — 删除会话
- `POST /api/chat/sessions/:id/messages` — 发送消息，返回 SSE：`accepted`、Runtime 真实步骤快照（仅 runtime）、`final` 或 `error`

**Embedding 管理**：

- `GET /api/embed/stats` — 嵌入统计（对比 Go DB 照片数）
- `GET /api/embed/audit` — 嵌入一致性审计
- `GET /api/embed/progress` — 嵌入进度
- `POST /api/embed/cleanup` — 清理孤儿文档
- `POST /api/embed/groups/sync` — 同步嵌入分组
- `POST /api/embed/photos/status` — 批量查询嵌入状态
- `POST /api/embed/queue/start` — 启动批量嵌入
- `POST /api/embed/queue/stop` — 停止队列
- `GET /api/embed/queue/status` — 嵌入进度
- `POST /api/embed/photos/:id` — 单张嵌入
- `GET /api/embed/photos/:id` — 嵌入详情

**黄金查询用例**：

- `GET /api/golden-queries` — 用例列表
- `POST /api/golden-queries` — 创建用例
- `PUT /api/golden-queries/:id` — 全量更新用例文本、分类、备注和关联照片
- `POST /api/golden-queries/import` — 批量导入
- `DELETE /api/golden-queries/:id` — 删除用例
- `POST /api/golden-queries/:id/photos` — 追加单张期望照片，已存在的照片跳过
- `POST /api/golden-queries/evaluate` — 运行评估，返回 P@10/R@10/MRR；带 `golden_id` 时只评估该条，明细含 `golden_id`

**选题建议（主题发现）**：

- `POST /api/suggest/run` — 自动生成选题建议（三阶段编辑视角提案管道），结果自动保存
- `POST /api/suggest/random-sample` — 随机采样照片 ID
- `POST /api/suggest/manual-run` — 手动选题（自选照片 + 可选直觉）
- `GET /api/suggest/history` — 历史选题列表（时间倒序）
- `GET /api/suggest/history/:id` — 单条选题摘要
- `GET /api/suggest/history/:id/detail` — 完整详情（含 versions + 管线步骤）
- `DELETE /api/suggest/history/:id` — 删除选题记录
- `PATCH /api/suggest/history/:id/rating` — 更新评分（1-5 星）
- `PATCH /api/suggest/history/:id/version/:vid/switch` — 切换活跃版本
- `POST /api/suggest/history/:id/rerun` — 从指定步骤重跑（返回完整 detail）
- `POST /api/suggest/history/:id/rerun-stream` — SSE 进度推送版重跑

**聚类分析**：

- `POST /api/cluster/run` — 执行聚类（参数：min_cluster_size 等）
- `GET /api/cluster/status/:task_id` — 聚类任务状态
- `GET /api/cluster/results` — 历史聚类结果列表
- `GET /api/cluster/results/:id` — 聚类结果详情（含每个 cluster 的照片列表）
- `DELETE /api/cluster/results/:id` — 删除聚类结果
- `POST /api/cluster/results/:id/clusters/:cid/generate-theme` — 为指定聚类生成主题标签
- `POST /api/cluster/results/:id/generate-all-themes` — 批量生成所有（或指定）簇的主题
- `POST /api/cluster/results/:id/evaluate-themes` — 批量评估簇标题（支持 cluster_ids 筛选）
- `POST /api/cluster/results/:id/clusters/:cid/evaluate-theme` — 单簇标题评估（不含跨簇规则）
- `GET /api/eval/reports` — 历史评估报告列表
- `GET /api/eval/reports/:id` — 单份评估报告详情

**图文工坊**：

- `POST /api/post-studio/generate` — 提示词模式生成文案（photo_ids + style + prompt → title + content + warnings）
- `POST /api/post-studio/refine` — 草稿模式润色文案（content + style + photo_ids → title + content + warnings）

### 4.3 Web 前端路由

- `#/photos` (PhotoManagement) — 照片管理主页（浏览/筛选/上传/删除）
- `#/timelines` (TimelineManagement) — 时间线管理
- `#/chat/:sessionId?` (ChatView) — AI 对话界面
- `#/suggest` (SuggestView) — 选题建议（主题发现）
- `#/golden-queries` (GoldenQueryManagement) — 黄金查询用例管理
- `#/cluster` (ClusterView) — 聚类分析与组图发现
- `#/post-studio` (PostStudio) — 图文工坊（创作工作台）
- `#/drafts` (DraftManagement) — 草稿管理
- `#/settings` (SettingsView) — 设置（连拍分组阈值等）
- `#/import` (ImportWorkflow) — 导入工作流

Vite 开发代理：

- `/api/chat`, `/api/embed`, `/api/golden-queries`, `/api/cluster`, `/api/eval`, `/api/suggest`, `/api/post-studio` → Python Agent (:10005)
- `/api`（其余前缀）→ Go Backend (:10004)

---

## 5. 数据模型

### 5.0 Go 数据库与接口生成

- 表结构的开发源是 `backend/sql/`。在 `backend/` 按 `initDB → gorm → curd` 生成 ORM 模板库、查询模型和常规 CRUD。模板库会重建。生产库由启动迁移按需创建表和补列。 [SQL 源](../../backend/sql/) · [生成目标](../../backend/Makefile) · [启动迁移](../../backend/internal/pkg/db/migrate.go)
- 业务 API 从手写 Proto 生成 Go 契约和 OpenAPI，再由 `api-cli` 生成 Web 与 Agent SDK。表结构或响应字段调整时，核对生成物和实际客户端使用。 [Proto](../../backend/proto/) · [OpenAPI](../../backend/openapi.yaml)
- Service 编排业务，DAO 承担数据访问，表关联由服务和 DAO 维护。 [架构边界](../ARCHITECTURE.md#修改时遵守的边界)

### 5.1 Go SQLite — Photo 表

`photos` 表由 GORM 生成（`backend/internal/pkg/db/model/photos.gen.go`），字段按职责分组：

- **标识**：`id`（主键）、`activity_id`（活动稳定标识）、`filename`、`file_type`；API 的 `file_path` 为组合投影
- **组织**：`timeline`（当前活动目录名缓存）、`tags`（JSON 数组字符串）、`burst_group_id` / `burst_group_coarse_id`（精细/粗略连拍组）
- **AI 描述**：`description`（VLM 原始输出，含 ```json 结构化块）、`description_model`、`description_time`、`description_raw`、`embedding_status`、`embedding_description_time`
- **结构化属性**（VLM 提取，文本类型）：`objects`、`colors`、`scene`、`lighting`、`mood`、`composition`
- **EXIF**：`shot_at`、`width`、`height`、`brand`、`model`、`lens`、`focal_length`（文本格式如 "35mm"）、`aperture`、`iso`、`exposure_time`
- **GPS**：`latitude`、`longitude`、`altitude`
- **时间戳**：`imported_at`

**结构化属性值域（VLM 中文原文直出）**：

`parseVlmAttrs()` 从 VLM 输出的 ```json 块中解析 6 个属性，直接保留 VLM 的中文原文，不做中英映射：

- **objects**：`main_objects` 直出，顿号分隔（如「猫、沙发」）
- **colors**：`dominant_colors` 直出，顿号分隔（如「暖黄、深棕」）
- **scene**：`environment` + `setting`，逗号分隔（如「室内，客厅」）
- **lighting**：`source` + `time_of_day`，逗号分隔（如「侧逆光，清晨」）
- **mood**：`mood` 直出（如「慵懒温馨」）
- **composition**：`focus` / `depth` / `symmetry`，逗号分隔（如「中央，浅景深，不对称」）

### 5.2 ChromaDB 文档

仅存最小元数据：`photo_id`（照片标识）+ `chunk_index`（分块序号）。document 为分块后的描述文本片段，embedding 为 Go 代理返回的向量。结构化属性全部在 Go SQLite 中，ChromaDB 不冗余存储。

---

## 6. 项目结构

```
photo-agent/
├── backend/                      # Go 业务后端
│   ├── internal/
│   │   ├── defaultService/       # 业务入口（defaultService.go 为 HTTP 入口）
│   │   │   ├── service/          # 业务逻辑（photo/vlm/embedding/burst/tag/timeline/...）
│   │   │   ├── data/             # DAO 层
│   │   │   └── conf/             # 配置结构
│   │   └── pkg/                  # db（GORM 模型 + 迁移）、api（Proto 生成代码）等
│   ├── cmd/fixsize/              # 工具：修正图片尺寸
│   └── go.mod
├── agent/                        # Python AI 服务层（依赖方向 cli → internal → infra，目录与文件职责详见 agent/README.md）
│   ├── cli/                      # 入口层（类 Go cmd/）：CLI 编排、FastAPI 服务、场景演示
│   ├── internal/                 # 业务功能包（类 Go internal/）
│   │   ├── chat/                 # 对话查询线（RAG / Text-to-SQL / 会话）
│   │   ├── topics/               # 选题发现线（聚类 / 三阶段提案）
│   │   ├── posts/                # 图文工坊线（文案生成）
│   │   ├── runtime/              # Agent Runtime（开放目标多步执行）
│   │   └── evals/                # 评估与观测（检索评估 / 规则评估 / Trace）
│   ├── infra/                    # 基础设施：配置、LLM 工厂、HTTP、后端 SDK 与 OpenAPI 工具、Chroma、SQLite、嵌入与队列
│   ├── scripts/                  # 检索回归脚本
│   └── tests/                    # 单元测试
├── web/                          # Web 前端
│   └── src/
│       ├── views/                # 照片管理/时间线/对话/选题/聚类/图文工坊/草稿/设置/导入
│       ├── components/           # 通用组件
│       ├── composables/          # 状态管理（usePhotos/useUpload/useChat/useBurstGroups/...）
│       ├── types/                # TypeScript 类型定义
│       └── router/               # Vue Router 配置
├── client/                       # Wails Windows 导入客户端（import/sync）
├── tools/                        # 跨模块开发与验证工具（按语言分目录）
├── configs/                      # 公共配置模板
├── data/                         # 运行时数据（photos/sqlite/chroma/clusters/选题历史/会话/评估报告）
├── dify/                         # 早期 Dify 验证，保留参考（非核心方案）
└── docs/                         # 项目文档
```

---

## 7. 关键设计决策

- **Agent 编排** → LangGraph StateGraph：单步查询（sql/rag/tool/combined）单发路由，开放目标（runtime）进入 decide/execute/reduce/check 循环图；循环图仅是编排外壳，TaskState/归约/完成检查/预算/能力注册表全部框架无关，可脱离 LangGraph 单测
- **向量检索 vs 结构化过滤** → ChromaDB 仅做语义，结构化走 Text-to-SQL：职责边界清晰，避免 Chroma metadata 与 SQLite 冗余同步
- **属性值提示词** → 动态从 DB 获取 distinct 值拼入：结构化属性为 VLM 中文原文直出，LLM 只能使用实际存在的值，避免生成数据库中不存在的值
- **Combined 降级** → SQL 失败/过宽/交集空 → 纯 RAG：保证任何情况下都有结果返回
- **Embedding 代理** → Go `/v1/embeddings` 转发至火山引擎：屏蔽火山多模态 URL 与 OpenAI 格式差异
- **图片 URL 拼接** → Agent prompt 硬编码 URL 模板：确定性 URL，减少一次工具调用
- **前端状态管理** → composables 内 module-level ref：规模小无需 Pinia/Vuex
- **会话持久化** → Python SQLite（session_store）：轻量，无需额外服务
- **ChromaDB 元数据** → 仅存 photo_id + chunk_index：Route B 决策，Go SQLite 是唯一数据源
- **图片压缩** → ImageMagick convert：保留完整 EXIF，统一 JPG 输出

### 已明确拒绝的技术方向

- **混合检索/重排序**：个人照片库检索精度够用，额外复杂度无收益
- **本地 Embedding 模型**：300 张照片 Embedding 费用极低
- **以图搜图/多模态检索**：选题场景不需要
- **Dify 作为核心方案**：早期验证使用，现已切至 LangGraph + FastAPI + Web 前端

---

## 8. 部署

详细部署步骤见 [docs/deploy.md](../deploy.md)。三层共用 YAML 配置：`Http`、`Sqlite` 暂承载 pgo 后端适配，`Agent`、`Web` 承载服务专用地址，`Storage`、`LLM`、`VLM`、`Embedding`、`RAG`、`Evaluation`、`Prices` 承载公共能力。连拍阈值由 Web 设置页写入数据库，代码仅保存数据库无记录时的默认值。模板位于 `configs/config.yaml`，个人配置放在 `.local/my-config.yaml`（gitignore）。

---

## 9. 次要模块速览

- **Go**：
  - `internal/defaultService/service/file_util.go`：EXIF 提取 + 图片尺寸读取 + ImageMagick 压缩
  - `internal/defaultService/service/activity_directory.go`：读取活动目录和元数据，识别改名并同步路径相关状态。见 [活动目录与时间线同步](#37-活动目录与时间线同步)
- **Python**：
  - `internal/evals/`：RAG 检索评估（黄金查询 + MRR/P@10 指标）与聚类规则评估
  - `scripts/`：检索回归脚本；照片嵌入由 VLM/Embedding 队列闭环完成
  - 目录与文件职责总览见 `agent/README.md`；早期学习性 demo 与一次性脚本已移入 `agent/bak/`（待手动删除）
- **Dify**：`dify/` 目录保留 Docker 部署配置和 DSL 文件，作为可选验证路径，不作为核心方案维护
