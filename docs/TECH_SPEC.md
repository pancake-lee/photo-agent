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
- **VLM 图片描述**：GPT-4o-mini / Qwen-VL / 火山引擎 Doubao-vision — Go Backend 直接 HTTP 调用
- **Embedding**：text-embedding-3-small / Qwen-Embedding — Dify 内部配置

---

## 3. 数据流

### 3.1 照片导入流程

所有照片必须先经 `batch_vlm` 预处理生成描述，server 导入时不再实时调用 VLM。导入流水线如下：

```
用户在 Dify 聊天输入："导入 ~/Photos/"
    ↓
Dify Agent: 意图识别 → 调用 import_photos 工具
    ↓
Go: 创建导入任务 (SQLite)
Go: 递归扫描文件夹，收集所有图片文件
Go: 读取 EXIF 拍摄时间
Go: 根据拍摄时间匹配时间线文件（配置指定的 md 表格）中的活动名称
Go: 读取预生成的 descriptions.json，匹配照片路径获取描述
Go: 复用已压缩图片（batch_vlm 已将压缩后的 JPG 存入 PhotoPath）
Go: 保存元数据到 SQLite (路径/时间线/标签/描述/拍摄时间/EXIF)
Go: 通过 Dify API 将描述写入知识库 (照片ID + 描述文本)
    ↓
Dify: 自动 Embedding → 存入向量库
Go: 更新导入任务状态为完成
    ↓
Dify Agent: 回复 "导入完成，共 45 张照片"
```

**工作流约束**：
- 所有照片必须先经 `batch_vlm` 预处理，server 导入时不再实时调用 VLM
- 时间线标签完全来自用户提供的 md 表格，不依赖文件夹命名
- 压缩后的 JPG 直接存入 `data/photos/` 作为最终存储文件，server 导入时直接复用
- 无预描述时以空描述入库，不调用 VLM

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

**图片在回复中的展示**：Agent 回复中包含 Markdown 图片链接 `![描述](http://localhost:8080/api/photos/{id}/image)`，Dify 的 Markdown 渲染器会自动展示图片。用户点击可查看原图。

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
4. 逐步写入 `descriptions.json`（避免中途崩溃丢失全部进度）
5. 输出处理统计（成功 / 失败 / 总耗时）

**默认提示词**（可在配置文件中通过 `vlm.prompt` 自定义，空时回退到此默认值）

```
请详细描述这张照片的内容。包括：
- 主体内容（人/物/风景）
- 场景环境（室内/室外、自然/城市）
- 光线氛围（明亮/昏暗、自然光/人工光）
- 色彩风格（鲜艳/柔和、冷暖倾向）
- 构图特点（前景/背景、对称/非对称）
```

**脚本使用方式**

```bash
cd backend/cmd/batch_vlm
go run main.go -input /root/project/photos/ -output ../../data/descriptions.json
```

---

## 4. API 设计

### 4.1 Go Backend API

```
GET    /api/health                  健康检查

# 照片管理
GET    /api/photos                 照片列表 (分页, query: timeline, tag, keyword)
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

# TODO: VLM 代理端点（当前未注册路由，如有需要后续补充）
# POST   /internal/vlm/describe      单张图片描述 (body: multipart/form-data 图片)
```

### 4.2 Dify 自定义工具配置

Dify 通过 OpenAPI Schema 配置外部工具，指向 Go Backend：

| 工具名 | 方法 | Go API | 用途 |
|--------|------|--------|------|
| `list_timelines` | GET | `/api/timelines` | 列出所有时间线 |
| `get_photos_by_timeline` | GET | `/api/timelines/{name}/photos` | 按时间线查照片 |
| `get_photos_by_tags` | GET | `/api/photos?tag={tag}` | 按标签查照片 |
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
├── dify/
│   ├── docker-compose.yaml       # Dify 本地部署配置
│   ├── dsl/                      # Agent DSL 文件
│   └── ...                       # 配套配置
├── data/
│   ├── photos/                   # 照片文件存储
│   ├── sqlite/                   # SQLite 数据库文件
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
go run cmd/server/main.go
# 默认端口 :8080
```

### 8.3 配置文件

**Go (`backend/configs/server.toml`)**：

```toml
[server]
addr = ":8080"

[db]
sqlite_path = "./data/sqlite/photo_agent.db"

[storage]
photo_path = "./data/photos"
descriptions_path = "./data/descriptions.json"
timeline_path = "./data/timeline.md"

[vlm]
provider = "volcengine"          # 或 openai / qwen
api_key = "your-api-key"
model = "doubao-vision-pro"      # 或 gpt-4o-mini / qwen-vl-max
base_url = "https://ark.cn-beijing.volces.com/api/v3"
concurrency = 3
retry = 3
max_image_size_mb = 1

[dify]
base_url = "http://localhost"    # Dify 根地址，不带 /v1
api_key = "your-dify-api-key"
dataset_id = "your-dataset-id"
email = "your-dify-email"
password = "your-dify-password"
dataset_name = "照片描述库"
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
| VLM 批量预处理 | Go 独立脚本 | 耗时长、费用高，独立运行避免开发阶段重复调用 |
| 图片在聊天中展示 | Dify Markdown | Agent 回复包含图片 URL，Dify 自动渲染 |

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
