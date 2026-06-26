# Photo Agent — 从零部署指南

> 本文档描述在新环境中从零部署 Photo Agent 的全部流程。
> 交互方式：CLI（`agent/chain/photo_agent.py`）、Web 对话界面、HTTP API 服务。
> Go 后端提供照片元数据 API 和 Embedding 代理，Python Agent 提供 AI 对话和会话管理。

---

## 部署全景

```
1. 环境准备（Go + Python）
   ↓
2. 配置文件（.local/my-config.yaml）
   ↓
3. VLM 预处理（batch_vlm → descriptions.json + 压缩图片）
   ↓
4. 启动 Go 后端（server → AutoSync：EXIF + 结构化属性提取 + SQLite）
   ↓
5. 启动 Python Agent — CLI 或 API 模式 + Web 前端
```

**运行时组件的关系**：

```
Web (:10006) ─── /api/v1/* ──→ Go Backend (:10004)       [图片管理]
     └── /api/chat/*,/api/embed/*,/api/golden-queries/*,/api/cluster/* ──→ Python Agent (:10005)  [AI 对话]

Python Agent
  ├── CLI: stdin/stdout 交互式聊天
  ├── HTTP Server (:10005, --serve 模式)
  │     ├── POST /api/chat/sessions          创建会话
  │     ├── GET  /api/chat/sessions          会话列表
  │     ├── POST /api/chat/sessions/{id}/messages  发送消息
  │     └── DELETE /api/chat/sessions/{id}   删除会话
  ├── 会话管理: sessions list | sessions resume <id>
  ├── Embed 队列: Web 批量/单张 Embedding（异步处理）
  ├── Embedding CLI: scripts/batch_embed.py（批量命令行工具）
  ├── RAG 检索: Embedding → Chroma（纯向量相似度，结构化过滤走 Text-to-SQL）
  ├── SQL 查询: Text-to-SQL → Go API
  ├── 工具调用: Function Calling → Go API (OpenAPI)
  └── 回答生成: LLM

Go Backend (:10004)
     ├── 照片元数据 CRUD (SQLite)
     ├── 文件服务（图片访问）
     ├── Embedding 代理 (/v1/embeddings)
     └── AutoSync 自动导入（EXIF 提取 + 结构化属性解析）
```

---

## 1. 环境准备

### 1.1 基础工具

| 工具 | 版本要求 | 用途 |
|------|---------|------|
| Go | ≥ 1.23 | 编译 Go 后端 |
| Python | 3.12 | AI 服务层 |
| uv | 最新版 | Python 环境和包管理 |

### 1.2 Python 环境

```bash
cd /root/code/photo-agent/agent

# 安装 Python 3.12
uv python install 3.12

# 创建虚拟环境
uv venv .venv --python 3.12

# 安装依赖
source .venv/bin/activate
uv sync
```

> 如果系统 sqlite3 < 3.35，Chroma 需要 `pysqlite3-binary`：
> ```bash
> uv pip install pysqlite3-binary
> ```

### 1.3 编译 Go 后端

```bash
cd /root/code/photo-agent
make backend

# 检查编译产物
ls bin/
# 应包含: server batch_vlm
```

---

## 2. 配置文件

### 2.1 创建个人配置

```bash
cd /root/code/photo-agent
cp configs/config.yaml .local/my-config.yaml
```

### 2.2 填写必填项

编辑 `.local/my-config.yaml`：

#### LLM — 对话和意图识别

```yaml
llm:
  base_url: "https://api.openai.com/v1"     # 或火山引擎/通义千问地址
  api_key: "sk-xxxxxxxx"
  model: "gpt-4o-mini"                      # 或 doubao-seed-1-6-251015
```

#### VLM — 照片视觉描述生成

```yaml
vlm:
  api_key: "sk-xxxxxxxx"                    # 可与 LLM 共用 Key
  model: "gpt-4o-mini"                      # 需支持视觉能力的模型
  base_url: "https://api.openai.com/v1"
  concurrency: 3                            # 并发数（按 API 配额调整）
  retry: 3
```

#### Embedding — 向量化

```yaml
embedding:
  api_key: "sk-xxxxxxxx"                    # Embedding API Key
  model: "text-embedding-3-small"
  base_url: "https://api.openai.com/v1"
  chunk_strategy: "none"                    # none / fixed_size
```

#### 存储路径

```yaml
storage:
  project_root: "."
  photo_src: "./data/photos"                # 照片源目录（batch_vlm 输入）
  photo_path: "./data/photos"               # 照片服务目录
  descriptions_path: "./data/descriptions.json"
```

#### 其他

```yaml
server:
  addr: ":10004"                            # Go 后端监听地址

prices:
  path: ./configs/prices.yaml               # Token 价格追踪（可选）
```

> Dify 配置段无需填写，保持默认即可。AutoSync 检测到 Dify 凭据为空时会跳过 Dify 同步。

---

## 3. VLM 预处理照片

### 3.1 放置照片

将照片放入 `storage.photo_src` 目录（默认 `data/photos/`）：

```bash
cp -r /path/to/your/photos/* ./data/photos/
```

> 支持格式：`.jpg` `.jpeg` `.png` `.webp`

### 3.2 运行 batch_vlm

```bash
cd /root/code/photo-agent
./bin/batch_vlm -c .local/my-config.yaml
```

参数：

| 参数 | 说明 |
|------|------|
| `-c` | 配置文件路径 |
| `-input` | 照片目录（覆盖 `photo_src`） |
| `-force` | 强制重新处理全部 |
| `-no-dedup` | 禁用 MD5 去重 |
| `-dry-run` | 仅测试配置，不调用 VLM |

运行细节：
- 并发调用 VLM，每张照片生成一段结构化视觉描述（JSON 格式）
- 自动读取 EXIF 提取拍摄时间
- 每 10 张自动保存中间结果，支持断点续传
- MD5 去重：相同内容只处理一次

**输出** `data/descriptions.json`：

```json
{
  "DSC_0001.JPG": {
    "description": "```json\n{\n  \"subject\": {...},\n  \"scene\": {...},\n  ...\n}\n```",
    "model": "gpt-4o-mini",
    "processed_at": "2026-06-11T10:30:00Z",
    "shot_at": "2025-03-15T07:22:00Z"
  }
}
```

> VLM 输出为 markdown 包裹的结构化 JSON，包含 subject / scene / lighting / color_palette / composition / mood 等维度。Go 后端 AutoSync 会自动解析这些字段存入数据库。

---

## 4. 启动 Go 后端

```bash
cd /root/code/photo-agent
./bin/server -c .local/my-config.yaml
```

启动时自动执行：
1. 初始化 SQLite（`data/sqlite/photo_agent.db`），自动迁移表结构
2. AutoSync：扫描 `photo_path`，对比 `descriptions.json`，增量导入到 SQLite
   - 解析 VLM 描述中的结构化 JSON → objects / colors / scene / lighting / mood / composition
   - 读取文件 EXIF（品牌、型号、镜头、焦距、光圈、ISO、GPS 等）
   - 时间线匹配（根据拍摄时间匹配 `timeline.md` 中的活动）
   - 可选：同步到 Dify 知识库（如已配置凭据）

> **注意**：先启动 Go 后端，Python Agent 的 Embedding 功能需要 Go 提供照片数据和 Embedding 代理。

---

## 5. 启动 Python Agent

Python Agent 支持三种运行模式，由参数控制（不指定参数时默认为 CLI 聊天模式）。

### 5.0 模式选择

```bash
cd /root/code/photo-agent/agent
source .venv/bin/activate

# CLI 聊天模式（默认）
python chain/photo_agent.py -c ../.local/my-config.yaml

# HTTP API 服务模式（Web 对话接口）
python chain/photo_agent.py -c ../.local/my-config.yaml --serve
python chain/photo_agent.py -c ../.local/my-config.yaml --serve 9999   # 自定义端口

# 会话管理
python chain/photo_agent.py -c ../.local/my-config.yaml sessions list
python chain/photo_agent.py -c ../.local/my-config.yaml sessions resume <session_id>
```

### 5.1 启动流程

Agent 启动时初始化以下组件：

1. **SessionStore** — SQLite 会话管理
2. **PhotoAgent** — LangGraph 查询路由（含 Token 追踪）
3. **ChromaPhotoStore** — ChromaDB 向量库连接（复用已有数据，不做自动索引）
4. **EmbedQueue** — Embedding 异步队列（等待 Web 或 CLI 触发）

启动后 **不会自动执行 Embedding**，需要通过以下方式手动触发：

- **Web 界面**：点击"开始批量 Embed"按钮 → 调用 `/api/embed/queue/start`
- **CLI 工具**：`python scripts/batch_embed.py -c config.yaml`

**ChromaDB 存储设计**：ChromaDB 仅存储描述文本的 Embedding 向量 + 最小标识（`photo_id`、`chunk_index`），不冗余存储 Go SQLite 已有的结构化属性（objects/colors/scene/lighting/mood/composition 等）。结构化查询统一走 Text-to-SQL → Go API。详见 `docs/chroma-metadata-design.md`。

### 5.2 路由机制

LangGraph 自动将用户问题分发到三个分支：

| 路由 | 触发条件 | 示例 |
|------|---------|------|
| `sql` | 统计、EXIF 筛选 | "Nikon 拍了几张？""ISO 大于 800 的照片" |
| `rag` | 内容描述、场景、情绪 | "找一下日落的照片""有猫咪的吗" |
| `tool` | 列表、详情、时间线 | "列出所有时间线""看看最近的照片" |

### 5.3 其他模式

```bash
# 评估模式
python chain/photo_agent.py -c ../.local/my-config.yaml --eval

# 用量统计
python chain/photo_agent.py -c ../.local/my-config.yaml --usage

# 场景演示
python chain/photo_agent.py -c ../.local/my-config.yaml --demo
```

### 5.4 Chat API 服务

启动 API 服务后，可通过 HTTP 接口进行对话：

```bash
python chain/photo_agent.py -c ../.local/my-config.yaml --serve
# 默认监听 http://0.0.0.0:10005
# API 文档: http://localhost:10005/docs
```

API 端点：

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chat/sessions` | 创建会话 |
| GET | `/api/chat/sessions` | 会话列表（按更新时间倒序） |
| GET | `/api/chat/sessions/{id}` | 会话详情（含消息历史） |
| PATCH | `/api/chat/sessions/{id}` | 更新会话标题 |
| DELETE | `/api/chat/sessions/{id}` | 删除会话 |
| POST | `/api/chat/sessions/{id}/messages` | 发送消息 |
| GET | `/api/chat/health` | 健康检查 |

会话标题命名规则：
- 创建时：`YYMMDD-hh:mm:ss`（如 `250623-14:30:00`）
- 首条提问后自动更新：取提问前 8 个字符 + `...`

```bash
# 测试 API
curl http://localhost:10005/api/chat/health

# 创建会话
curl -X POST http://localhost:10005/api/chat/sessions \
  -H 'Content-Type: application/json' -d '{}'

# 发送消息
curl -X POST http://localhost:10005/api/chat/sessions/{session_id}/messages \
  -H 'Content-Type: application/json' \
  -d '{"question": "我有多少张照片？"}'
```

### 5.5 Embedding API

Agent 启动后提供 Embedding 管理 API，Web 界面可进行批量/单张 Embedding。

**端点**：

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/embed/queue/start` | 启动批量 Embedding（body: `{"force": false}`） |
| POST | `/api/embed/queue/stop` | 中止批量 Embedding |
| GET | `/api/embed/queue/status` | 查询队列运行状态 |
| POST | `/api/embed/photos/{id}` | 单张照片入队 |
| GET | `/api/embed/photos/{id}` | 单张 embedding 详情 |
| POST | `/api/embed/photos/status` | 批量查询是否已嵌入 |
| GET | `/api/embed/stats` | Embedding 统计 |
| POST | `/api/embed/cleanup` | 清理孤立数据 |

**启动流程**：`/api/embed/queue/start` 在启动处理前会自动清理 ChromaDB 中孤立文档（Go 中已删除的照片），然后从 Go API 获取待嵌入列表并启动后台 worker。

**队列状态**：

```json
{
  "running": true,
  "total": 120,
  "completed": 45,
  "failed": 0,
  "current_file": "DSC_0001.JPG"
}
```

Web 前端通过轮询 `/api/embed/queue/status`（间隔 2s）实时更新进度。

### 5.6 Web 前端

```bash
cd /root/code/photo-agent/web
pnpm dev
# 开发服务器: http://localhost:10006
```

Vite 代理配置：
- `/api/chat/*`, `/api/embed/*`, `/api/golden-queries/*`, `/api/cluster/*` → Python Agent (`:10005`)
- `/api/v1/*` → Go Backend (`:10004`)

Web 界面提供：
- **图片管理**：照片浏览、筛选排序、上传、VLM 预处理
- **AI 对话**：新建对话、多轮问答、历史会话管理

需要同时运行 Go Backend、Python Agent（`--serve` 模式）和 Web 前端三个进程。

---

## 6. 验证清单

- [ ] `make backend` 编译通过，`bin/` 下有 `server` `batch_vlm`
- [ ] `.local/my-config.yaml` 中 API Key 有效，`vlm` 模型支持视觉
- [ ] `./bin/batch_vlm -c .local/my-config.yaml -dry-run` 配置校验通过
- [ ] `data/descriptions.json` 包含每张照片的描述和拍摄时间
- [ ] `./bin/server -c .local/my-config.yaml` 启动，`/api/v1/health` 返回 OK
- [ ] API 返回的照片数据包含结构化属性字段（objects / colors / scene / lighting / mood / composition）
- [ ] `python chain/photo_agent.py -c ../.local/my-config.yaml` 正常启动，Agent 初始化成功
- [ ] 对话中 RAG 检索返回相关结果
- [ ] `python chain/photo_agent.py -c ../.local/my-config.yaml --serve` Chat API 健康检查通过
- [ ] `curl http://localhost:10005/api/chat/health` 返回 `{"status":"ok"}`
- [ ] Web 前端 `pnpm dev` 正常启动，图片管理和对话界面均可访问

---

## 常见问题

### Q: batch_vlm 中断后如何恢复？

直接重新运行。已处理的照片自动跳过（通过 `descriptions.json` 和 MD5 去重）。

需重新生成用 `--force`：

```bash
./bin/batch_vlm -c .local/my-config.yaml --force
```

### Q: 新增照片后如何更新？

```bash
# 1. VLM 预处理新照片
./bin/batch_vlm -c .local/my-config.yaml

# 2. 重启 Go 后端触发 AutoSync（自动解析 EXIF + 结构化属性 + 入库）
# server 启动即完成同步，无需额外步骤

# 3. 触发 Embedding（二选一）
# 方式 A: Web 界面点击"开始批量 Embed"
# 方式 B: CLI 命令行
cd agent && source .venv/bin/activate
python scripts/batch_embed.py -c ../.local/my-config.yaml
```

### Q: Chroma 索引完全重建以及清理旧数据？

如需强制全量重建 ChromaDB 索引：

```bash
# 1. 删除旧数据
rm -rf ./data/chroma/

# 2. 重新索引（二选一）
# 方式 A: Web 界面点击"开始批量 Embed"
# 方式 B: CLI
cd agent && source .venv/bin/activate
python scripts/batch_embed.py -c ../.local/my-config.yaml
```

**清理孤立数据**：Go 中已删除的照片可能在 ChromaDB 中残留 embedding 数据。两种方式清理：

- **自动**：每次批量 Embedding 启动（`POST /api/embed/queue/start`）前自动执行 `cleanup_orphans()`，对比 Go 全量 photo_id 并删除 Chroma 中不存在的
- **手动**：`POST /api/embed/cleanup`

**旧数据迁移**：如果 ChromaDB 中有旧版本写入的冗余 metadata（file_path、scene 等），全量重建后新写入的 metadata 仅包含 `photo_id` 和 `chunk_index`。增量更新也会逐步自然替换为瘦身版。

### Q: 为什么 Web 上点击"开始批量 Embed"没有立即反应？

批量 Embed 启动时需要从 Go 后端分页拉取全量照片列表以确定待处理范围，数据量越大等待越久。解决思路：

1. 确保 Go 后端正常运行且响应迅速
2. 尽量减少 ChromaDB 中无效数据（定期清理孤立文档）
3. 如果照片数量极大（>5000），可考虑先用 CLI 工具做全量索引：

```bash
cd agent && source .venv/bin/activate
python scripts/batch_embed.py -c ../.local/my-config.yaml
```

### Q: ChromeDB 为什么不再存储结构化属性？

ChromaDB 仅做语义向量检索，结构化过滤（场景/光线/情绪/EXIF 参数等）统一走 Text-to-SQL → Go API。这样：

- Go SQLite 是结构化数据的唯一数据源，无需维护 ChromaDB ↔ SQLite 同步
- ChromaDB metadata 体积最小化，`get_embedded_photo_ids()` 等操作更快
- 修改结构化查询逻辑只需改 Text-to-SQL prompt，不涉及 ChromaDB schema

详见 `docs/chroma-metadata-design.md`。

### Q: Go 后端日志？

默认写入 `backend/data/logs/server/`。终端查看加 `-l`：

```bash
./bin/server -c .local/my-config.yaml -l
```

### Q: 如何更换 LLM 供应商？

修改 `.local/my-config.yaml` 中对应 `base_url` 和 `model`。项目通过 OpenAI 兼容 API 调用，支持火山引擎、通义千问、DeepSeek 等。

### Q: Chat API 端口冲突？

默认端口 10005，可通过 `--serve` 参数指定其他端口：

```bash
python chain/photo_agent.py -c ../.local/my-config.yaml --serve 9999
```

同时需要更新 `web/vite.config.ts` 中 `/api/chat` 代理的 target 端口。

### Q: 会话数据存储在哪里？

默认存储在 `data/chat_sessions.db`（SQLite），可在配置文件中自定义：

```yaml
chat:
  db_path: ./data/chat_sessions.db
```

### Q: Web 前端如何联调？

同时启动三个进程：
```bash
# 终端 1: Go 后端
./bin/server -c .local/my-config.yaml

# 终端 2: Python Agent (API 模式)
cd agent && source .venv/bin/activate
python chain/photo_agent.py -c ../.local/my-config.yaml --serve

# 终端 3: Web 前端
cd web && pnpm dev
# 访问 http://localhost:10006
```
