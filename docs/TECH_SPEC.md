# Photo Agent - 技术方案文档

> 设计约束：Dify 本地部署作为 Agent 核心（图形化工作流可观测 + 自带聊天 UI），Go 负责业务后端，零 Python、零前端框架。

## 1. 架构设计

### 1.1 核心原则

- **Dify 作为唯一交互入口**：用户通过 Dify 的 Web UI 进行所有对话，Dify 负责 Agent 编排、知识库 RAG、工作流可视化、模型管理
- **Go 作为业务后端**：照片元数据 CRUD、文件管理、导入任务调度、VLM 调用
- **零 Python、零前端框架**：VLM 视觉描述、Embedding 均通过云端 API 由 Go 直接 HTTP 调用；不引入 Next.js/React/Vue 等前端框架，聊天界面直接使用 Dify 自带 UI

### 1.2 整体架构

```
用户浏览器
    ↓ HTTP
Dify Web UI (:80, Docker)
    ├── Agent 意图识别
    ├── 知识库向量检索 (RAG)
    ├── 工具调用 → Go API
    └── 模型管理 (LLM / Embedding)
    ↓ HTTP (OpenAPI Schema 工具)
Go Backend (:8080)
    ├── 照片元数据管理 (GORM + SQLite)
    ├── 文件服务 (本地文件系统)
    ├── 导入流水线 (并发控制、重试)
    └── VLM HTTP 代理 (云端 API)
```

### 1.3 职责边界

- **Dify 负责**：Agent 意图识别、工具路由、知识库向量检索、工作流可视化、模型管理、聊天 UI 渲染
- **Dify 不负责**：文件存储、业务数据持久化、批量导入调度、VLM 直接调用
- **Go 负责**：照片元数据管理、文件服务、导入流水线、时间线/标签查询、VLM HTTP 代理、图片文件服务端点
- **Go 不负责**：Agent 编排、向量检索、对话管理、UI 渲染

---

## 2. 技术选型

### 2.1 Agent 层

- **Dify 社区版**：Docker 本地部署，Agent 编排 + 知识库 + 工作流可视化 + 自带聊天 UI
- **Agent 模式**：Function Calling（工具调用稳定，可观测）
- **知识库检索**：语义搜索 + 全文搜索混合

### 2.2 业务后端

- **Go 1.22+**：业务后端语言
- **Gin**：HTTP 路由框架
- **GORM**：ORM + SQLite
- **SQLite**：单机数据持久化
- **本地文件系统**：照片文件存储

### 2.3 AI 模型（云端 API）

- **LLM 对话**：GPT-4o-mini / Qwen-Turbo / Kimi — Dify 内部配置
- **VLM 图片描述**：GPT-4o-mini / Qwen-VL — Go Backend 直接 HTTP 调用
- **Embedding**：text-embedding-3-small / Qwen-Embedding — Dify 内部配置

---

## 3. 数据流

### 3.1 照片导入流程

```
用户在 Dify 聊天输入："导入 ~/Photos/2024-02-云南"
    ↓
Dify Agent: 意图识别 → 调用 import_photos 工具
    ↓
Go: 创建导入任务 (SQLite)
Go: 扫描文件夹 → 按文件夹名解析时间线标签
Go: 复制照片到 data/photos/{timeline}/
Go: 对每个照片调用 VLM API (HTTP) 生成描述
Go: 保存元数据到 SQLite (路径/时间线/标签/描述/EXIF)
Go: 通过 Dify API 将描述写入知识库 (照片ID + 描述文本)
    ↓
Dify: 自动 Embedding → 存入向量库
Go: 更新导入任务状态为完成
    ↓
Dify Agent: 回复 "导入完成，共 45 张照片"
```

**批量导入并发控制**：VLM API 调用限制并发数（如 3 个并发），避免费用过高和速率限制。失败自动重试 3 次。

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

**图片在回复中的展示**：Agent 回复中包含 Markdown 图片链接 `![描述](http://localhost:8080/api/photos/{id}/image)`，Dify 的 Markdown 渲染器会自动展示图片。用户点击可查看原图。

---

## 4. API 设计

### 4.1 Go Backend API

```
GET    /api/health                  健康检查

# 照片管理
GET    /api/photos                 照片列表 (分页, query: timeline, tags, keyword)
GET    /api/photos/:id             单张照片详情
GET    /api/photos/:id/image       获取图片文件 (支持缩略图参数 ?size=thumb)

# 时间线
GET    /api/timelines              所有时间线列表
GET    /api/timelines/:name/photos 某时间线下的照片

# 标签
GET    /api/tags                   所有标签列表
GET    /api/tags/:name/photos      某标签下的照片

# 导入任务
POST   /api/import/jobs            创建导入任务 (body: {sourcePath, recursive})
GET    /api/import/jobs/:id        查询导入进度
GET    /api/import/jobs/:id/logs   导入日志

# VLM 代理 (内部使用，也可供 Dify 直接调用)
POST   /internal/vlm/describe      单张图片描述 (body: multipart/form-data 图片)
```

### 4.2 Dify 自定义工具配置

Dify 通过 OpenAPI Schema 配置外部工具，指向 Go Backend：

| 工具名 | 方法 | Go API | 用途 |
|--------|------|--------|------|
| `list_timelines` | GET | `/api/timelines` | 列出所有时间线 |
| `get_photos_by_timeline` | GET | `/api/timelines/{name}/photos` | 按时间线查照片 |
| `get_photos_by_tags` | GET | `/api/photos?tags={tags}` | 按标签查照片 |
| `get_photo_detail` | GET | `/api/photos/{id}` | 获取单张照片详情 |
| `import_photos` | POST | `/api/import/jobs` | 创建照片导入任务 |
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
  - 如果提到具体照片，使用 Markdown 图片语法展示照片，格式：![描述](http://localhost:8080/api/photos/{photo_id}/image)
  - 时间线查询使用 list_timelines / get_photos_by_timeline 工具
  - 标签查询使用 get_photos_by_tags 工具
  - 导入照片使用 import_photos 工具
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
    ID          string    `gorm:"primaryKey" json:"id"`
    Filename    string    `json:"filename"`
    FilePath    string    `json:"file_path"`
    Timeline    string    `json:"timeline"`          // e.g. "2024-02-云南"
    Tags        string    `json:"tags"`              // JSON array string
    Description string    `json:"description"`       // VLM generated
    ShotAt      *time.Time `json:"shot_at"`          // EXIF DateTimeOriginal
    Width       int       `json:"width"`
    Height      int       `json:"height"`
    ImportedAt  time.Time `json:"imported_at"`
}

type ImportJob struct {
    ID              string    `gorm:"primaryKey" json:"id"`
    Status          string    `json:"status"`           // pending / processing / completed / failed
    SourcePath      string    `json:"source_path"`
    TotalPhotos     int       `json:"total_photos"`
    ProcessedPhotos int       `json:"processed_photos"`
    FailedPhotos    int       `json:"failed_photos"`
    CreatedAt       time.Time `json:"created_at"`
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
│   ├── cmd/server/
│   │   └── main.go
│   ├── internal/
│   │   ├── api/                  # HTTP handlers
│   │   ├── model/                # GORM 模型
│   │   ├── service/              # 业务逻辑
│   │   ├── config/               # 配置管理
│   │   └── vlm/                  # VLM HTTP 客户端
│   └── go.mod
├── dify/
│   └── docker-compose.yaml       # Dify 本地部署配置
├── data/
│   ├── photos/                   # 照片文件存储
│   └── sqlite/                   # SQLite 数据库文件
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
go run cmd/server/main.go
# 默认端口 :8080
```

### 8.3 环境变量

**Go (`backend/.env`)**：
```
PORT=8080
DB_PATH=./data/sqlite/photo_agent.db
PHOTO_STORAGE_PATH=./data/photos
VLM_API_KEY=your-openai-or-qwen-key
VLM_MODEL=gpt-4o-mini
VLM_BASE_URL=https://api.openai.com/v1  # 或 Qwen/Kimi 的 base URL
DIFY_API_KEY=your-dify-api-key
DIFY_BASE_URL=http://localhost/v1
DIFY_KNOWLEDGE_BASE_ID=your-dataset-id
```

---

## 9. 功能实现方式决策

| 功能 | 实现方式 | 理由 |
|------|---------|------|
| Agent 对话编排 | Dify | 图形化可观测，自带聊天 UI |
| 知识库向量检索 | Dify | 内置 RAG，无需自建向量库 |
| 聊天界面 | Dify | 自带 Web UI，无需前端开发 |
| 照片批量导入 | Go 代码 | 需要异步调度、并发控制、重试机制 |
| 照片元数据管理 | Go 代码 | 业务数据，需要事务和关系查询 |
| 文件服务 | Go 代码 | 本地文件读写，Go 标准库高效 |
| VLM 图片描述 | Go 代码 | HTTP 调用云端 API，Go 可直接实现 |
| 图片在聊天中展示 | Dify Markdown | Agent 回复包含图片 URL，Dify 自动渲染 |

---

## 10. 风险与应对

| 风险 | 概率 | 应对 |
|------|------|------|
| Dify 本地部署资源占用高 | 中 | 限制并发 worker 数，部署在 8G+ 内存机器 |
| Dify 知识库同步延迟 | 中 | 导入时批量写入，失败重试；查询时 Go SQLite 兜底 |
| VLM API 费用过高 | 中 | 批量导入限制并发（3 并发），使用 GPT-4o-mini 低成本模型 |
| Dify 回复中 Markdown 图片渲染异常 | 低 | 确保图片 URL 可访问（同机部署时 localhost 互通），备选方案：只返回文字描述 + 照片 ID |
| Go 调用 VLM 需要图片 base64 编解码性能问题 | 低 | 批量导入异步处理，单图编码在百毫秒级 |
