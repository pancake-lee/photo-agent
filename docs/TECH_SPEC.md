# Media Agent - 技术方案文档

## 1. 架构设计

### 1.1 架构原则

- **Go + Python 双栈**：Go 做工程后端（API + 业务 + 数据），Python 做 AI 引擎（VLM + LLM + 向量检索）
- **职责分离**：Go 负责元数据管理和业务流程，Python 负责纯 AI 计算
- **单机可运行**：两个服务进程运行在一台机器上，通过本地 HTTP 通信
- **模型可插拔**：LLM / VLM / Embedding 模型通过配置切换

### 1.2 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                     CLI 交互层 (Python Click + Rich)        │
│                      media_agent/cli/main.py                │
└─────────────────────────────┬───────────────────────────────┘
                              │ HTTP
┌─────────────────────────────▼───────────────────────────────┐
│                    Go Backend (Gin + GORM)                  │
│                   media_agent/backend/                      │
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │   API 层    │  │  业务服务层  │  │   数据访问层         │ │
│  │  (Gin)      │  │  (Service)  │  │  (GORM + SQLite)    │ │
│  │             │  │             │  │                     │ │
│  │ • 路由定义  │  │ • 素材管理  │  │ • 素材元数据        │ │
│  │ • 请求校验  │  │ • 会话管理  │  │ • 会话记录          │ │
│  │ • 中间件    │  │ • 导入任务  │  │ • 导入日志          │ │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘ │
└─────────┼────────────────┼────────────────────┼────────────┘
          │                │                    │
          │         ┌──────┴──────┐             │
          │         │  文件系统    │             │
          │         │ (本地存储)   │             │
          │         └─────────────┘             │
          │                                     │
          └─────────────────┬───────────────────┘
                            │ HTTP JSON
┌───────────────────────────▼───────────────────────────────┐
│               Python AI Service (FastAPI)                 │
│                    media_agent/ai/                        │
│                                                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐│
│  │   Agent     │  │   工具层     │  │     模型层           ││
│  │ (LangChain) │  │  (Tools)    │  │   (Models)          ││
│  │             │  │             │  │                     ││
│  │ • 意图理解  │  │ • 向量检索  │  │ • VLM API           ││
│  │ • 工具路由  │  │ • 标签查询  │  │ • LLM API           ││
│  │ • 记忆管理  │  │ • 素材分析  │  │ • Embedding         ││
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘│
└─────────┼────────────────┼────────────────────┼───────────┘
          │                │                    │
          └────────────────┴────────┬───────────┘
                                    │
                          ┌─────────▼─────────┐
                          │    Chroma 向量库   │
                          │  (本地持久化存储)   │
                          └───────────────────┘
```

### 1.3 模块职责

| 服务       | 模块       | 技术         | 职责                                       |
| ---------- | ---------- | ------------ | ------------------------------------------ |
| Go Backend | API        | Gin          | HTTP 路由、请求校验、响应封装              |
| Go Backend | Service    | Go           | 业务逻辑：素材管理、会话管理、导入任务编排 |
| Go Backend | Repository | GORM         | SQLite 数据访问（CRUD）                    |
| Go Backend | Config     | Viper        | 配置管理、环境变量                         |
| Python AI  | API        | FastAPI      | AI 服务 HTTP 接口                          |
| Python AI  | Agent      | LangChain    | 意图理解、工具路由、回复生成               |
| Python AI  | VLM        | OpenAI SDK   | 视觉描述模型封装                           |
| Python AI  | LLM        | OpenAI SDK   | 大语言模型封装                             |
| Python AI  | Vector     | Chroma       | 向量存储与检索                             |
| CLI        | Main       | Click + Rich | 用户交互、命令解析、结果展示、服务编排     |

---

## 2. 技术选型

### 2.1 Go 后端

| 组件      | 选型          | 版本  | 理由                                     |
| --------- | ------------- | ----- | ---------------------------------------- |
| HTTP 框架 | **Gin**       | ^1.9  | Go 最流行的 Web 框架，生态成熟，性能优秀 |
| ORM       | **GORM**      | ^1.25 | Go 最流行的 ORM，支持 SQLite，开发效率高 |
| 配置      | **Viper**     | ^1.18 | 支持环境变量、配置文件，Go 项目标配      |
| 日志      | **Zap**       | ^1.27 | 高性能结构化日志                         |
| 校验      | **validator** | ^10.0 | 请求参数校验                             |

### 2.2 Python AI 服务

| 组件        | 选型          | 版本   | 理由                                |
| ----------- | ------------- | ------ | ----------------------------------- |
| API 框架    | **FastAPI**   | ^0.115 | 异步高性能，自动生成 Swagger        |
| Agent 框架  | **LangChain** | ^0.3   | JD 要求，工具调用/记忆/链式编排完善 |
| VLM/LLM SDK | **OpenAI**    | ^1.0   | 统一封装，支持多模型切换            |
| 向量数据库  | **Chroma**    | ^0.5   | 纯 Python，无需独立服务，嵌入式运行 |
| 数据校验    | **Pydantic**  | ^2.0   | FastAPI 和 LangChain 都原生支持     |

### 2.3 AI 模型

| 用途           | 推荐模型                   | 备选                 | 备注                                   |
| -------------- | -------------------------- | -------------------- | -------------------------------------- |
| 视觉描述 (VLM) | **GPT-4o-mini**            | Qwen-VL-Max          | 成本低（$0.15/M tokens），视觉理解足够 |
| Agent LLM      | **GPT-4o-mini**            | Kimi k1.5 / Qwen-Max | 同一模型即可，减少配置复杂度           |
| 文本嵌入       | **text-embedding-3-small** | BGE-small-zh         | OpenAI embedding 性价比高，中文支持好  |

### 2.4 依赖清单

**Go (`backend/go.mod`)**：

```
github.com/gin-gonic/gin v1.9.1
gorm.io/gorm v1.25.5
gorm.io/driver/sqlite v1.5.4
github.com/spf13/viper v1.18.2
go.uber.org/zap v1.27.0
github.com/go-playground/validator/v10 v10.16.0
```

**Python (`ai/requirements.txt`)**：

```
fastapi>=0.115.0
uvicorn[standard]>=0.32.0
pydantic>=2.0.0
langchain>=0.3.0
langchain-openai>=0.2.0
langchain-community>=0.3.0
chromadb>=0.5.0
httpx>=0.27.0
python-dotenv>=1.0.0
pillow>=10.0.0
```

**Python CLI (`cli/requirements.txt`)**：

```
click>=8.0.0
rich>=13.0.0
httpx>=0.27.0
python-dotenv>=1.0.0
```

---

## 3. 数据模型设计

### 3.1 Go 业务模型（GORM）

```go
// backend/internal/model/photo.go
type Photo struct {
    ID          uint           `gorm:"primaryKey" json:"id"`
    Path        string         `gorm:"index;not null" json:"path"`        // 相对路径
    Filename    string         `json:"filename"`
    Timeline    string         `gorm:"index" json:"timeline"`             // 时间线标签
    Tags        string         `json:"tags"`                              // JSON 数组字符串
    Description string         `json:"description"`                       // AI 描述
    Status      string         `gorm:"default:pending" json:"status"`     // pending / processing / done / failed
    CreatedAt   time.Time      `json:"created_at"`
    UpdatedAt   time.Time      `json:"updated_at"`
}

// backend/internal/model/session.go
type ChatSession struct {
    ID        string    `gorm:"primaryKey" json:"id"`              // UUID
    Title     string    `json:"title"`
    Messages  []ChatMessage `gorm:"foreignKey:SessionID" json:"messages"`
    CreatedAt time.Time `json:"created_at"`
}

type ChatMessage struct {
    ID        uint      `gorm:"primaryKey" json:"id"`
    SessionID string    `gorm:"index;not null" json:"session_id"`
    Role      string    `json:"role"`                              // user / assistant / system
    Content   string    `json:"content"`
    ToolsUsed string    `json:"tools_used"`                        // JSON 数组
    Sources   string    `json:"sources"`                           // JSON 数组
    CreatedAt time.Time `json:"created_at"`
}
```

### 3.2 时间线知识库（JSON 文件）

```json
{
  "timelines": {
    "2024-02-云南": {
      "name": "2024-02-云南",
      "photo_count": 45,
      "description": "云南旅拍，以雪山和森林风光为主...",
      "tags": ["雪山", "森林", "人像", "日出"],
      "created_at": "2026-05-08T10:00:00"
    }
  },
  "tag_index": {
    "雪山": ["photos/2024-02-云南/IMG_0234.jpg"],
    "海边": ["photos/2023-10-青岛/IMG_0012.jpg"]
  }
}
```

### 3.3 Chroma 向量存储 Schema（Python）

```python
collection.add(
    ids=["photo_001"],
    documents=["雪山前景，人物背影，蓝天，光线明亮..."],
    metadatas=[{
        "path": "photos/2024-02-云南/IMG_0234.jpg",
        "photo_id": 1,
        "timeline": "2024-02-云南"
    }],
    embeddings=[...]
)
```

---

## 4. 核心流程设计

### 4.1 照片导入流程

```
CLI: media-agent photo import ./photos/2024-02-云南/ --timeline "2024-02-云南"

1. CLI 扫描目录，获取所有图片文件

2. CLI 调用 Go API: POST /api/v1/photos/import_batch
   Go 批量创建 Photo 记录（status = pending）
   Go 返回 batch_id 和 photo_id 列表

3. CLI 逐个调用 Python AI: POST /ai/describe
   - Python VLM 生成描述
   - Python LLM 提取标签
   - Python 将描述文本存入 Chroma（向量库）
   - Python 返回 {description, tags}

4. CLI 调用 Go API: PUT /api/v1/photos/:id
   Go 更新 SQLite（description, tags, status = done）

5. CLI 输出进度和结果
```

### 4.2 Agent 对话流程

```
CLI: media-agent chat
用户输入: "帮我找云南的雪山照片"

1. CLI 调用 Go API: POST /api/v1/chat

2. Go 从 SQLite 加载会话历史（最近 10 轮）

3. Go 调用 Python AI: POST /ai/chat
   传入: {message, history, tools_available}

4. Python Agent 意图理解 + 工具路由
   System Prompt: "你是个人摄影助手..."
   → 调用 vector_search("雪山", timeline="云南")
   → 返回 Top-5 结果

5. Python LLM 汇总生成回复

6. Python 返回 {reply, sources, tools_used}

7. Go 保存会话记录到 SQLite

8. Go 返回给 CLI，Rich 渲染输出
```

### 4.3 摄影主题分析流程

```
用户输入: "分析我 2024 年云南系列的风格特点"

1. CLI 调用 Go API: POST /api/v1/chat

2. Go 加载会话历史

3. Go 调用 Python AI: POST /ai/chat

4. Python Agent 执行工具链
   → timeline_query("2024-02-云南"): Go 从 SQLite 返回概况
   → vector_search("云南", timeline="2024-02-云南")

5. Python LLM 生成分析

6. 返回引用来源
```

---

## 5. API 设计

### 5.1 Go Backend API

| 方法 | 路径                               | 描述                               |
| ---- | ---------------------------------- | ---------------------------------- |
| POST | `/api/v1/photos/import_batch`      | 批量导入照片（创建元数据）         |
| PUT  | `/api/v1/photos/:id`               | 更新照片元数据（描述、标签、状态） |
| GET  | `/api/v1/photos`                   | 列出照片（支持分页、时间线过滤）   |
| GET  | `/api/v1/photos/:id`               | 获取照片详情                       |
| GET  | `/api/v1/photos/search`            | 搜索照片（关键词、时间线过滤）     |
| POST | `/api/v1/chat`                     | 发送消息，获取 Agent 回复          |
| GET  | `/api/v1/chat/:session_id/history` | 获取会话历史                       |
| GET  | `/api/v1/timelines`                | 获取所有时间线列表                 |
| GET  | `/api/v1/timelines/:name`          | 获取某个时间线概况                 |
| GET  | `/api/v1/health`                   | 健康检查                           |

### 5.2 Python AI Service API

| 方法 | 路径           | 描述         |
| ---- | -------------- | ------------ |
| POST | `/ai/describe` | 单张图片描述 |
| POST | `/ai/chat`     | Agent 对话   |
| POST | `/ai/search`   | 向量检索     |
| POST | `/ai/embed`    | 文本嵌入     |
| GET  | `/ai/health`   | 健康检查     |

### 5.3 核心接口详情

**Go: POST /api/v1/photos/import_batch**

```go
type ImportBatchRequest struct {
    Photos   []PhotoMeta `json:"photos" validate:"required,dive"`
    Timeline string      `json:"timeline"`
}

type PhotoMeta struct {
    Path     string `json:"path" validate:"required"`
    Filename string `json:"filename"`
}

type ImportBatchResponse struct {
    BatchID string      `json:"batch_id"`
    Photos  []PhotoInfo `json:"photos"`
}

type PhotoInfo struct {
    ID     uint   `json:"id"`
    Path   string `json:"path"`
    Status string `json:"status"`
}
```

**Python: POST /ai/describe**

```python
class DescribeRequest(BaseModel):
    image_path: str           # 本地绝对路径
    timeline: str | None = None

class DescribeResponse(BaseModel):
    description: str
    tags: list[str]
```

**Go ↔ Python 通信: POST /ai/chat**

```python
class ChatRequest(BaseModel):
    message: str
    history: list[dict]       # [{"role": "user", "content": "..."}, ...]
    timeline: str | None = None

class ChatResponse(BaseModel):
    reply: str
    sources: list[SourceInfo] | None = None
    tools_used: list[str] | None = None

class SourceInfo(BaseModel):
    path: str
    description: str
    score: float
```

---

## 6. 配置设计

### 6.1 Go 后端配置（`backend/config.yaml` 或环境变量）

```yaml
server:
  host: 0.0.0.0
  port: 8080

database:
  dsn: ./data/media_agent.db

ai_service:
  url: http://localhost:8000
  timeout: 30

log:
  level: info
  format: json
```

### 6.2 Python AI 服务配置（`ai/.env`）

```bash
# AI 模型配置
LLM_PROVIDER=openai
LLM_API_KEY=sk-xxx
LLM_MODEL=gpt-4o-mini

VLM_PROVIDER=openai
VLM_API_KEY=sk-xxx
VLM_MODEL=gpt-4o-mini

EMBEDDING_PROVIDER=openai
EMBEDDING_API_KEY=sk-xxx
EMBEDDING_MODEL=text-embedding-3-small

# 数据路径
CHROMA_PERSIST_DIR=./data/chroma
DATA_DIR=./data

# 服务配置
AI_HOST=0.0.0.0
AI_PORT=8000
LOG_LEVEL=INFO
```

### 6.3 目录结构约定

```
media_agent/
├── backend/                 # Go 后端
│   ├── cmd/
│   │   └── server/
│   │       └── main.go
│   ├── internal/
│   │   ├── api/             # HTTP handler (Gin)
│   │   ├── service/         # 业务逻辑
│   │   ├── repository/      # 数据访问 (GORM)
│   │   └── model/           # 数据模型
│   ├── config/
│   │   └── config.yaml
│   └── go.mod
├── ai/                      # Python AI 服务
│   ├── main.py              # FastAPI 入口
│   ├── services/
│   │   ├── vlm.py
│   │   ├── llm.py
│   │   ├── embedding.py
│   │   └── vector.py
│   ├── agent/
│   │   ├── orchestrator.py
│   │   └── prompts.py
│   ├── tools/
│   │   ├── vector_search.py
│   │   └── tag_query.py
│   └── requirements.txt
├── cli/                     # Python CLI
│   ├── main.py
│   ├── commands/
│   │   ├── init.py
│   │   ├── photo.py
│   │   ├── chat.py
│   │   └── debug.py
│   └── requirements.txt
├── data/                    # 数据目录 (gitignore)
│   ├── media_agent.db       # SQLite (Go 管理)
│   ├── chroma/              # Chroma 向量存储 (Python 管理)
│   ├── timeline_kb.json     # 时间线知识库
│   └── photos/              # 原始照片
│       ├── 2024-02-云南/
│       ├── 2023-10-青岛/
│       └── ...
├── docs/                    # 文档
│   ├── PRD.md
│   ├── TECH_SPEC.md
│   ├── TASKS.md
│   └── note.md
└── README.md
```

---

## 7. 部署方案

### 7.1 本地开发运行

**启动 Python AI 服务**：

```bash
cd ai
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env，填入 API Key
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

**启动 Go 后端**：

```bash
cd backend
go mod tidy
cp config.example.yaml config.yaml
# 编辑 config.yaml，配置 ai_service.url

go run cmd/server/main.go
```

**使用 CLI**：

```bash
cd cli
pip install -r requirements.txt

media-agent init
media-agent photo import ./data/photos/2024-02-云南/ --timeline "2024-02-云南"
media-agent chat
```

### 7.2 Docker 部署

```yaml
# docker-compose.yml
version: "3.8"
services:
  ai-service:
    build: ./ai
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
      - ./ai/.env:/app/.env
    environment:
      - CHROMA_PERSIST_DIR=/app/data/chroma
      - DATA_DIR=/app/data

  backend:
    build: ./backend
    ports:
      - "8080:8080"
    volumes:
      - ./data:/app/data
      - ./backend/config.yaml:/app/config.yaml
    depends_on:
      - ai-service
```

### 7.3 性能预估

| 场景                          | 耗时    | 瓶颈                |
| ----------------------------- | ------- | ------------------- |
| 单张照片描述                  | 3-5s    | VLM API 调用        |
| 单张照片完整处理（描述+嵌入） | 5-8s    | VLM + Embedding API |
| 100 张照片批量导入            | 8-15min | API 串行调用        |
| 单次对话（含检索）            | 3-5s    | LLM API + 向量检索  |
| 向量检索（Top-10）            | <100ms  | Chroma 本地查询     |

**优化建议**：

- 批量导入时加进度条，支持断点续传
- 照片处理可并行（限制并发数，避免 API 限流）
- Go 后端可并发调用 Python AI 服务

---

## 8. 安全与隐私

- **API Key 管理**：通过 `.env` 注入 Python AI 服务，绝不提交到 Git
- **个人照片保护**：`data/photos/` 加入 `.gitignore`
- **日志脱敏**：日志中不输出完整的 API Key 和图片内容
- **访问控制**：MVP 阶段无用户系统，单机单用户使用

---

## 9. 监控与调试

### 9.1 日志设计

**Go 后端**：结构化 JSON 日志（Zap）

```json
{
  "timestamp": "2026-05-08T10:30:00",
  "level": "INFO",
  "module": "api.chat",
  "session_id": "uuid",
  "event": "ai_chat",
  "duration_ms": 2500,
  "tools_used": ["vector_search"]
}
```

**Python AI 服务**：标准日志 + LangChain 回调追踪

### 9.2 调试工具

- `media-agent debug search "query"`：测试向量检索（调用 Python AI）
- `media-agent debug describe path/to/image.jpg`：测试视觉描述
- `media-agent debug timeline "2024-02-云南"`：查看时间线概况
- Go Swagger UI：`http://localhost:8080/swagger/index.html`
- Python Swagger UI：`http://localhost:8000/docs`

---

## 10. 扩展路线图

### 10.1 短期（V1.1）

- [ ] Go 后端：支持批量并行导入（并发控制）
- [ ] Python AI：支持图片缩略图生成（Pillow）
- [ ] Python AI：支持多模型对比（同一查询用不同模型）
- [ ] CLI：支持配置文件管理

### 10.2 中期（V1.2）

- [ ] 接入 Dify 平台（展示平台使用能力）
- [ ] 支持视频关键帧提取（ffmpeg）
- [ ] Web UI（Streamlit / Gradio）

### 10.3 长期（V2.0）

- [ ] Go 后端增强：用户系统、权限管理
- [ ] 云端部署：支持 OSS + 云数据库
- [ ] 与 Dify 深度集成：提供插件版本
