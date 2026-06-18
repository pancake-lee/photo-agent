# Photo Agent - 技术方案文档

> 设计约束：Dify 本地部署作为 Agent 编排入口之一（图形化工作流可观测 + 自带聊天 UI），Go 负责业务后端与 API 网关，Python AI 服务层负责智能推理（LangChain / LangGraph / Chroma / Text-to-SQL），零前端框架。

## 1. 架构设计

### 1.1 核心原则

- **双入口**：Dify Web UI 提供图形化 Agent 交互（适合快速演示），Python CLI 提供深度定制的 Agent 体验（适合学习和技术迭代）
- **Go 作为业务后端与 API 网关**：照片元数据 CRUD、文件管理、导入任务调度、VLM 调用、Embedding HTTP 代理、统计 API
- **Python AI 服务层作为推理层**：LangChain 编排、Chroma 向量检索、Text-to-SQL、LangGraph 查询路由、Function Calling 工具调用、流式输出
- **零前端框架**：不引入 Next.js/React/Vue 等前端框架，聊天界面使用 Dify 自带 UI 或 Python CLI

### 1.2 整体架构

```
用户浏览器 / 用户终端
    ↓ HTTP                    ↓ CLI
Dify Web UI (:80, Docker)    Python AI Service
    ├── Agent 意图识别         ├── LangChain 聊天编排
    ├── 知识库向量检索 (RAG)   ├── Chroma 向量检索
    ├── 工具调用 → Go API      ├── Text-to-SQL
    └── 模型管理               ├── LangGraph 查询路由
    ↓ HTTP (OpenAPI)           └── Function Calling → Go API
Go Backend (:10000)
    ├── 照片元数据管理 (GORM + SQLite)
    ├── 文件服务 (本地文件系统)
    ├── 导入流水线 (并发控制、重试)
    ├── VLM / Embedding HTTP 代理
    └── 统计 API (EXIF 聚合分析)
```

### 1.3 职责边界

- **Dify 负责**：图形化 Agent 编排、知识库向量检索（Weaviate）、工作流可视化、模型管理、Web 聊天 UI
- **Dify 不负责**：文件存储、业务数据持久化、批量导入调度、VLM 直接调用、Python 推理层
- **Go 负责**：照片元数据管理、文件服务、导入流水线、时间线/标签查询、VLM HTTP 代理、Embedding HTTP 代理、图片文件服务端点、统计 API、OpenAPI 文档自描述
- **Go 不负责**：Agent 编排（由 Dify 或 Python 层负责）、向量检索（由 Chroma 或 Dify 负责）、对话管理、UI 渲染
- **Python AI 服务层负责**：LangChain 聊天编排、Chroma 向量检索、Text-to-SQL（NL 转 SQL）、LangGraph 查询路由、Function Calling 工具调用、流式输出打印
- **Python AI 服务层不负责**：直接访问数据库或文件系统（所有数据操作通过 Go API）

---

## 2. 技术选型

### 2.1 Agent 层（双入口）

**Dify 侧（图形化入口）**：
- **Dify 社区版**：Docker 本地部署，Agent 编排 + 知识库 + 工作流可视化 + 自带聊天 UI
- **Agent 模式**：Function Calling（工具调用稳定，可观测）
- **知识库检索**：语义搜索 + 全文搜索混合（Dify 内置 Weaviate）

**Python AI 服务侧（深度定制入口）**：
- **LangChain**：聊天提示模板、链式调用、流式输出
- **LangGraph**：StateGraph 查询路由（结构化查询走 SQL 分支，语义查询走 RAG 分支）
- **Function Calling**：`llm.bind_tools()` 绑定 Go 后端 OpenAPI 工具，LLM 自主决策调用
- **Chroma**：本地向量数据库，存储照片描述 Embedding，支持语义检索
- **Text-to-SQL**：自然语言转 SQL，查询 EXIF 元数据
- **流式输出**：SSE 流式对话，PID 速度控制平滑打印

### 2.2 业务后端

- **Go 1.22+**：业务后端语言
- **Gin**：HTTP 路由框架
- **GORM**：ORM + SQLite
- **SQLite**：单机数据持久化
- **本地文件系统**：照片文件存储

### 2.3 AI 模型（云端 API）

- **LLM 对话**：GPT-4o-mini / Qwen-Turbo / 火山引擎 Doubao — Dify 或 Python 层配置
- **VLM 图片描述**：GPT-4o-mini / Qwen-VL / 火山引擎 Doubao-vision — Go Backend `batch_vlm` 直接 HTTP 调用
- **Embedding**：text-embedding-3-small / 火山引擎 Doubao-embedding-vision — **Go Backend `/v1/embeddings` 代理**（兼容 OpenAI 格式，转发至火山多模态 Embedding API）

**为什么 Embedding 走 Go 代理**：

火山引擎的多模态 Embedding URL 格式（`/embeddings/multimodal`）与 OpenAI 标准格式（`/embeddings`）不兼容，Dify 的 openai-api-compatible 插件会自动追加 `/embeddings` 到配置的 base_url 后，导致请求路径错误。Go 后端提供 `/v1/embeddings` 代理，内部转发到火山真实 URL，对上层（Dify 和 Python）暴露标准 OpenAI 格式。

---

## 3. 数据流

### 3.1 照片导入流程

所有照片必须先经 `batch_vlm` 预处理生成描述，server 启动时自动同步到 SQLite 和 Dify，无需手动触发。导入流水线如下：

```
batch_vlm 增量处理照片目录
    ↓
输出/更新 descriptions.json
    ↓
启动 server
    ↓
Go: 后台自动同步 (AutoSync)
Go: 扫描 photo_path 下所有图片
Go: 读取 descriptions.json，匹配照片路径获取描述
Go: 对比 SQLite photos 表，识别新增/变更
Go: 新照片：读取 EXIF → 匹配时间线 → 写入 SQLite → 同步 Dify
Go: 已有照片：如 description 变化 → 更新 SQLite → 同步 Dify
Go: 无变化 → 跳过
    ↓
Dify: 自动 Embedding → 存入 Dify 向量库 (Weaviate)
    ↓
Python: 运行 index_photos.py → 生成 Embedding → 存入 Chroma (本地向量库)
```

**工作流约束**：
- 所有照片必须先经 `batch_vlm` 预处理，server 不再实时调用 VLM
- 时间线标签完全来自用户提供的 md 表格，不依赖文件夹命名
- 压缩后的 JPG 直接存入 `data/photos/` 作为最终存储文件，server 自动复用
- 无预描述时以空描述入库，不调用 VLM
- 增量场景：新照片放入目录 → 运行 `batch_vlm`（自动跳过已有）→ 重启 server（自动同步增量）

**预描述文件的生成**：通过独立脚本 `backend/cmd/batch_vlm/main.go` 提前批量处理，不依赖 Dify 或其他服务。脚本扫描照片文件夹，调用 VLM API，输出 `descriptions.json`。

**批量导入并发控制**：VLM API 调用限制并发数（默认 3 并发），避免费用过高和速率限制。失败自动重试 3 次。

### 3.2 聊天对话流程

```
用户在 Dify Web UI 输入自然语言
    ↓
Dify Agent: 意图识别
    ├─ 需要检索照片描述 → Dify 知识库 RAG (内部)
    ├─ 需要查时间线/标签 → 调用 Go API 工具
    ├─ 需要照片列表 → 调用 Go API 工具
    └─ 纯创作建议 → 直接 LLM 生成
    ↓
Dify: 整合工具结果 + RAG 结果 → 生成回复
    ↓
Dify Web UI 渲染回复（文本 + Markdown 图片链接）
```

#### Python CLI 聊天对话流程

```
用户在终端输入自然语言
    ↓
LangGraph 查询路由 (StateGraph)
    ├─ 结构化统计查询（如"我有多少张照片"）→ SQL 分支
    │     ↓
    │   Text-to-SQL：LLM 根据 Schema 生成 SELECT 语句
    │     ↓
    │   安全校验 → Go 后端 /api/query/sql 执行
    │     ↓
    │   结果格式化为自然语言
    │
    ├─ 语义检索查询（如"找雪山照片"）→ RAG 分支
    │     ↓
    │   Embedding → Chroma 向量检索 Top-K
    │     ↓
    │   按 photo_id 聚合去重
    │     ↓
    │   拼接上下文 → LLM 生成回答
    │
    └─ 工具调用查询（如"列出所有时间线"）→ Function Calling 分支
          ↓
        LLM 自主决策调用工具
          ↓
        OpenAPI 工具解析 → Go API 执行
          ↓
        工具结果返回 LLM → 生成回答
    ↓
流式输出（SSE + PID 速度控制平滑打印）
```

**图片在回复中的展示**：Agent 回复中包含 Markdown 图片链接 `![描述](http://192.168.3.159:10000/api/photos/{id}/image)`，Dify 的 Markdown 渲染器会自动展示图片，Python CLI 中终端支持 Markdown 渲染时也会展示。用户点击可查看原图。

**设计决策：图片 URL 放在 pre_prompt 中而非工具返回**

为什么不通过 `get_photo_detail` 工具让后端返回 `image_url`，而是由 Agent 按 prompt 规则直接拼接？

| 方案 | 说明 | 当前选择 |
|------|------|---------|
| **pre_prompt 硬编码 URL** | RAG 片段中提取 photo_id 后直接拼 URL，无需额外工具调用 | ✅ 采用 |
| **工具返回 image_url** | 每次展示图片都调用 `get_photo_detail`，后端动态生成 URL | 备选 |

选择 pre_prompt 硬编码的原因：
1. **图片 URL 是确定性的**（固定 host + 固定路径模板 `/api/photos/{id}/image`），后端无需动态计算
2. **减少一次工具调用**，响应链路更短，延迟更低
3. Dify 前端原生支持 Markdown 图片语法渲染，无需特殊处理

备选方案（工具返回 image_url）适用于以下场景：
- URL 需要动态生成（如带签名临时链接、CDN 域名分发）
- 需要返回缩略图 vs 原图的选择（`?size=thumb`）
- 多环境部署时 host 频繁变化，不便在 prompt 中维护

当前为本地固定部署，IP:Port 稳定，采用 pre_prompt 硬编码。若后续有上述需求，可迁移为工具返回方案。

### 3.3 批量 VLM 预处理脚本

**为什么需要独立脚本**

VLM 调用耗时较长（单张 2-5 秒，300 张约 15-30 分钟），且费用按调用次数计费。开发阶段反复触发导入会重复调用 VLM，成本高且慢。独立脚本提前批量处理一次，开发时直接复用结果。

**脚本位置**：`backend/cmd/batch_vlm/main.go`

**脚本输入输出**

- 输入：照片根文件夹路径（如 `./demo_data/photos/`）
- 输出：`data/descriptions.json`

**descriptions.json 格式**

```json
{
  "photos/2024-02-云南/IMG_001.jpg": {
    "description": "雪山日照金山，前景有五彩经幡...",
    "model": "doubao-vision-pro",
    "processed_at": "2026-05-09T10:30:00Z"
  }
}
```

**脚本执行流程**

1. 递归扫描输入文件夹，收集所有图片文件（jpg / png / jpeg）
2. 对每个图片调用 VLM API（火山引擎 / OpenAI / Qwen），使用默认提示词
3. 并发控制：默认 3 并发，失败自动重试 3 次
4. 每张处理完的结果写入内存 map，每处理满 10 张时保存一次中间结果到文件（临时文件 + 原子 rename），全部完成后最终保存到文件
5. 输出处理统计（成功 / 失败 / 总耗时）

**默认提示词**

项目提供默认提示词模板文件 `configs/vlm_prompt.md`，可在配置文件中通过 `vlm.prompt` 指定自定义提示词文件路径。代码启动时读取提示词文件，若文件不存在或为空则报错，不再内置代码级兜底。

```yaml
vlm:
  prompt: ./configs/vlm_prompt.md    # VLM 描述生成提示词文件路径
```

**脚本使用方式**

```bash
# 编译后使用
./bin/batch_vlm -c .local/my-config.yaml -input /root/project/photos/

# 或开发时直接运行
cd backend/cmd/batch_vlm
go run main.go -input /root/project/photos/ -output ../../data/descriptions.json
```

---

## 4. API 设计

### 4.1 Go Backend API

```
GET    /api/health                  健康检查

# 照片管理
GET    /api/photos                 照片列表 (分页, query: timeline, tag, keyword, brand, lens, focal_min/max, iso_min/max)
GET    /api/photos/stats           照片统计（七维度：total/brands/lens/focal_ranges/gps/monthly/hourly）
GET    /api/photos/:id             单张照片详情
GET    /api/photos/:id/image       获取图片文件 (支持缩略图参数 ?size=thumb)

# 时间线
GET    /api/timelines              所有时间线列表
GET    /api/timelines/:name/photos 某时间线下的照片

# 标签
GET    /api/tags                   所有标签列表
GET    /api/tags/:name/photos      某标签下的照片

# 导入任务
POST   /api/import/jobs            创建导入任务 (body: {source_path, recursive})
GET    /api/import/jobs/:id        查询导入进度
GET    /api/import/jobs/:id/logs   导入日志

# SQL 查询（供 Python AI 服务层 Text-to-SQL 使用）
GET    /api/schema/photos          动态获取 Photo 表的 Schema（字段名、类型、可空性）
POST   /api/query/sql              执行安全 SQL（仅 SELECT，服务端+客户端双重校验）

# OpenAPI 工具自描述（供 Python AI 服务层 Function Calling 使用）
GET    /v1/openapi.json            Go 后端 OpenAPI 文档，Python 层自动解析为 LLM 工具

# Embedding 代理
POST   /v1/embeddings              Embedding 代理（兼容 OpenAI 格式，转发至火山引擎多模态 Embedding）
```

### 4.2 Dify 自定义工具配置

Dify 通过 OpenAPI Schema 配置外部工具，指向 Go Backend：

| 工具名 | 方法 | Go API | 用途 |
|--------|------|--------|------|
| `list_timelines` | GET | `/api/timelines` | 列出所有时间线 |
| `get_photos_by_timeline` | GET | `/api/timelines/{name}/photos` | 按时间线查照片 |
| `get_photos_by_tags` | GET | `/api/photos?tag={tag}` | 按标签查照片 |
| `get_photo_detail` | GET | `/api/photos/{id}` | 获取单张照片详情 |
| `import_photos` | POST | `/api/import/jobs` | 刷新照片库数据 |
| `get_import_status` | GET | `/api/import/jobs/{id}` | 查询导入任务进度 |

**知识库检索**无需配置为外部工具，Dify 内部知识库直接通过 RAG 查询。

---

## 5. Dify 配置详情

### 5.1 模型配置

在 Dify 设置 → 模型供应商中配置：

- **系统推理模型**：OpenAI GPT-4o-mini（或 Qwen-Turbo）
- **Embedding 模型**：OpenAI text-embedding-3-small（或 Qwen-Embedding）
- **Rerank 模型**（可选）：Cohere Rerank 或开源模型

### 5.2 知识库配置

1. 创建数据集"照片描述库"
2. 检索设置：
   - 检索模式：语义搜索 + 全文搜索
   - Top-K：5
   - 分数阈值：0.5
3. 文档格式：每篇文档对应一张照片
   ```
   标题：照片 {photo_id}
   内容：{vlm_description}
   元数据：{timeline, tags}
   ```

### 5.3 Agent 配置

- **应用类型**：Agent（支持工具调用）
- **Agent 模式**：Function Calling
- **系统提示词**：
  ```
  你是 Photo Agent，一位个人摄影资产助手。你帮助用户通过自然语言检索照片、回顾拍摄经历、分析摄影主题。

  可用能力：
  1. 通过知识库检索照片描述（语义搜索）
  2. 通过工具查询时间线和标签
  3. 基于历史作品提供创作建议
  4. 通过工具导入本地照片文件夹

  回答时：
  - 如果提到具体照片，使用 Markdown 图片语法展示照片，格式：![描述](http://192.168.3.159:10000/api/photos/{photo_id}/image)
  - 时间线查询使用 list_timelines / get_photos_by_timeline 工具
  - 标签查询使用 get_photos_by_tags 工具
  - 刷新照片库数据使用 import_photos 工具
  - 模糊描述检索使用知识库 RAG（自动）
  ```

### 5.4 工作流可视化

Dify Agent 的 Function Calling 过程在对话界面中可看到：
- 模型思考（意图识别）
- 工具调用（如 `list_timelines`）
- 工具结果
- 最终答案生成

如需更复杂的可视化流程（如条件分支、循环），可在 Dify 中搭建"工作流"类型应用替代简单 Agent。

---

## 6. 数据模型

### 6.1 Go + SQLite

```go
type Photo struct {
    ID           string     `gorm:"primaryKey" json:"id"`
    Filename     string     `json:"filename"`
    FilePath     string     `json:"file_path"`
    Timeline     string     `json:"timeline"`          // e.g. "2024-02-云南"
    Tags         string     `json:"tags"`              // JSON array string
    Description  string     `json:"description"`       // VLM generated
    ShotAt       *time.Time `json:"shot_at"`           // EXIF DateTimeOriginal
    Width        int        `json:"width"`
    Height       int        `json:"height"`
    ImportedAt   time.Time  `json:"imported_at"`
    // EXIF 元数据（第二轮新增）
    Brand        string     `json:"brand"`             // 相机品牌，如 "Canon"
    Model        string     `json:"model"`             // 相机型号，如 "EOS R5"
    Lens         string     `json:"lens"`              // 镜头型号
    FocalLength  float64    `json:"focal_length"`      // 焦距（mm）
    Aperture     float64    `json:"aperture"`          // 光圈值，如 2.8
    ISO          int        `json:"iso"`               // ISO 感光度
    ExposureTime string     `json:"exposure_time"`     // 曝光时间，如 "1/200"
    Latitude     *float64   `json:"latitude"`          // GPS 纬度，nullable
    Longitude    *float64   `json:"longitude"`         // GPS 经度，nullable
    Altitude     *float64   `json:"altitude"`          // GPS 海拔，nullable
}

type ImportJob struct {
    ID              string     `gorm:"primaryKey" json:"id"`
    Status          string     `json:"status"`           // pending / processing / completed / failed
    SourcePath      string     `json:"source_path"`
    TotalPhotos     int        `json:"total_photos"`
    ProcessedPhotos int        `json:"processed_photos"`
    FailedPhotos    int        `json:"failed_photos"`
    CreatedAt       time.Time  `json:"created_at"`
    CompletedAt     *time.Time `json:"completed_at"`
}
```

### 6.2 Dify 知识库文档格式

每张照片对应一篇文档：
- **文档标题**：`photo_{id}`
- **文档内容**：VLM 生成的描述文本
- **分段策略**：按句子分段，每段保留上下文

---

## 7. 项目结构

```
photo-agent/
├── backend/                      # Go 业务后端
│   ├── cmd/
│   │   ├── server/               # Server 入口
│   │   │   └── main.go
│   │   ├── batch_vlm/            # 批量 VLM 预处理脚本
│   │   │   └── main.go
│   │   └── init_dify/            # Dify 知识库初始化脚本
│   │       └── main.go
│   ├── internal/
│   │   ├── api/                  # HTTP handlers
│   │   ├── model/                # GORM 模型
│   │   ├── service/              # 业务逻辑
│   │   ├── config/               # 配置管理
│   │   └── vlm/                  # VLM HTTP 客户端
│   ├── test/
│   │   └── backendTest.go        # E2E 测试程序
│   └── go.mod
├── agent/                        # Python AI 服务层
│   ├── chain/                    # LangChain / LangGraph 编排
│   │   ├── chat_agent.py         # 基础聊天 Agent
│   │   ├── function_agent.py     # Function Calling Agent
│   │   ├── react_agent.py        # ReAct 循环 Agent
│   │   ├── photo_rag.py          # RAG 检索 + 照片级聚合
│   │   └── text_to_sql.py        # 自然语言转 SQL
│   ├── embedding/                # 分块策略 + Embedding 客户端
│   ├── vectorstore/              # ChromaDB 封装
│   ├── db/                       # SQLite 查询客户端（HTTP 调用 Go 后端）
│   ├── tools/                    # OpenAPI 工具解析与执行
│   ├── utils/                    # 流式打印等工具
│   ├── scripts/                  # 索引脚本（descriptions.json → Chroma）
│   └── tests/                    # 单元测试
├── dify/
│   ├── docker-compose.yaml       # Dify 本地部署配置
│   ├── dsl/                      # Agent DSL 文件
│   └── ...                       # 配套配置
├── data/
│   ├── photos/                   # 照片文件存储
│   ├── sqlite/                   # SQLite 数据库文件
│   ├── chroma/                   # Chroma 向量数据库
│   └── descriptions.json         # 预生成的照片描述（由脚本生成）
└── docs/
```

---

## 8. 部署

### 8.1 Dify 部署

```bash
cd dify
docker-compose up -d
# 访问 http://localhost 完成初始化配置
# 配置模型供应商、创建知识库、配置 Agent 应用
```

### 8.2 Go Backend 部署

```bash
cd backend
go mod download
go run cmd/server/main.go -c ./configs/config.yaml
# 默认端口 :10000
```

### 8.3 配置文件

**公共配置模板 (`./configs/config.yaml`)**：

Go 后端和 Python AI 服务层共用同一配置文件，通过 `-c` 参数指定路径。

使用方式：

```bash
# 1. 复制模板到个人目录（避免将敏感信息提交到 Git）
cp ./configs/config.yaml .local/my-config.yaml

# 2. 编辑 .local/my-config.yaml，填入你的 API Key、路径等

# 3. 启动时指定配置文件
./bin/server -c .local/my-config.yaml
./bin/batch_vlm -c .local/my-config.yaml -input /path/to/photos/
```

配置项说明见 `./configs/config.yaml` 头部注释。主要段：

- `server` — Go 后端监听地址
- `db` — SQLite 数据库路径
- `storage` — 照片目录、描述文件、时间线文件路径
- `llm` — LLM API Key、模型、base_url
- `vlm` — VLM API Key、模型、并发控制、压缩阈值、提示词
- `embedding` — Embedding API Key、模型、分块策略
- `dify` — Dify 地址、知识库配置、管理员账号

---

## 9. 功能实现方式决策

| 功能 | 实现方式 | 理由 |
|------|---------|------|
| **Dify 侧** |||
| Agent 对话编排 | Dify | 图形化可观测，自带聊天 UI，快速出效果 |
| 知识库向量检索 | Dify（Weaviate） | 内置 RAG，无需自建向量库 |
| 聊天界面 | Dify Web UI | 自带 Web UI，无需前端开发 |
| **Python AI 服务层** |||
| Agent 对话编排 | LangChain + Function Calling | 深度定制 Agent 流程，学习 AI 工程概念 |
| 知识库向量检索 | Chroma | 本地向量库，可控性强，学习 Embedding + 检索原理 |
| Text-to-SQL | LangChain + Go API | NL 转 SQL 查询 EXIF 元数据，结构化查询能力 |
| 查询路由 | LangGraph StateGraph | 自动判断走 SQL 分支还是 RAG 分支 |
| 流式输出 | LangChain SSE + PID 打印 | 实时打字机效果，学习流式 API 调用 |
| **Go 后端** |||
| 照片批量导入 | Go 独立脚本 `batch_vlm` | 耗时长、费用高，独立运行避免开发阶段重复调用 |
| 照片元数据管理 | Go 代码（Gin + GORM） | 业务数据，需要事务和关系查询 |
| 文件服务 | Go 代码 | 本地文件读写，Go 标准库高效 |
| Embedding 代理 | Go `/v1/embeddings` | 兼容 OpenAI 格式，屏蔽火山引擎 URL 差异 |
| 统计 API | Go 代码 | EXIF 聚合分析，多维统计 |
| **通用** |||
| 图片在聊天中展示 | Markdown 图片语法 | Agent 回复包含图片 URL，Dify / CLI 均可渲染 |

---

## 10. 风险与应对

| 风险 | 概率 | 应对 |
|------|------|------|
| Dify 本地部署资源占用高 | 中 | 限制并发 worker 数，部署在 8G+ 内存机器 |
| Dify 知识库同步延迟 | 中 | 导入时批量写入，失败重试；查询时 Go SQLite 兜底 |
| VLM API 费用过高 | 中 | 批量导入限制并发（3 并发），使用 GPT-4o-mini / 火山引擎低成本模型 |
| 火山引擎 API 格式与 OpenAI 不兼容 | 低 | 火山引擎 Ark 平台支持 OpenAI 兼容格式（/v1/chat/completions），只需切换 base URL 和 model 名 |
| Dify 回复中 Markdown 图片渲染异常 | 低 | 确保图片 URL 可访问（同机部署时 localhost 互通），备选方案：只返回文字描述 + 照片 ID |
| Go 调用 VLM 需要图片 base64 编解码性能问题 | 低 | 批量导入异步处理，单图编码在百毫秒级 |
