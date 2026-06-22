# Photo Agent — 从零部署指南

> 本文档描述在新环境中从零部署 Photo Agent 的全部流程。
> 核心交互方式为 `agent/chain/photo_agent.py` CLI，Go 后端提供照片元数据 API 和 Embedding 代理。

---

## 部署全景

```
1. 环境准备（Go + Python）
   ↓
2. 配置文件（.local/my-config.yaml）
   ↓
3. VLM 预处理（batch_vlm → descriptions.json + 压缩图片）
   ↓
4. 启动 Go 后端（server → AutoSync：EXIF + 结构化属性提取 + SQLite + Dify）
   ↓
5. 启动 Python Agent（photo_agent.py → AutoEmbed → Chroma → 对话）
```

**三个运行时组件的关系**：

```
用户 → photo_agent.py (CLI)
         ├── 启动时 AutoEmbed: Go API → Chroma 本地向量库（进度条）
         ├── RAG 检索: Embedding → Chroma
         ├── SQL 查询: Text-to-SQL → Go API /api/v1/query/sql
         ├── 工具调用: Function Calling → Go API (OpenAPI)
         └── 流式回答: LLM 生成

Go Backend (:10000)
     ├── 照片元数据 CRUD (SQLite)
     ├── 文件服务（图片访问）
     ├── Embedding 代理 (/v1/embeddings)
     └── AutoSync 自动导入（EXIF 提取 + 结构化属性解析 + Dify 同步）
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
  addr: ":10000"                            # Go 后端监听地址

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

> **注意**：先启动 Go 后端，Python Agent 启动时需要它提供数据（AutoEmbed）和 Embedding 代理。

---

## 5. 启动 Python Agent

```bash
cd /root/code/photo-agent/agent
source .venv/bin/activate

python chain/photo_agent.py -c ../.local/my-config.yaml
```

### 5.1 启动流程（AutoEmbed）

Agent 启动时自动执行 AutoEmbed，无需手动运行索引脚本：

1. 检查 Go 后端健康状态
2. 从 Go API 获取全部照片数据（含结构化属性）
3. 对比本地 Chroma manifest（增量检测）
4. 如有新增/变更：显示进度条，自动完成 Embedding → Chroma
5. 完成后进入对话模式

```
AutoEmbed: Go 后端健康检查通过
AutoEmbed: 增量同步 15 张照片到 Chroma...
  Embedding: [██████████████████████████████] 15/15 (100%)
AutoEmbed: Chroma 同步完成，共 450 条文档
```

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

---

## 6. 验证清单

- [ ] `make backend` 编译通过，`bin/` 下有 `server` `batch_vlm`
- [ ] `.local/my-config.yaml` 中 API Key 有效，`vlm` 模型支持视觉
- [ ] `./bin/batch_vlm -c .local/my-config.yaml -dry-run` 配置校验通过
- [ ] `data/descriptions.json` 包含每张照片的描述和拍摄时间
- [ ] `./bin/server -c .local/my-config.yaml` 启动，`/api/v1/health` 返回 OK
- [ ] API 返回的照片数据包含结构化属性字段（objects / colors / scene / lighting / mood / composition）
- [ ] `python chain/photo_agent.py -c ../.local/my-config.yaml` 启动时 AutoEmbed 正常完成
- [ ] 对话中 RAG 检索返回相关结果

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

# 3. 重启 Python Agent，AutoEmbed 自动检测变更并增量索引
cd agent && source .venv/bin/activate
python chain/photo_agent.py -c ../.local/my-config.yaml
```

> 如果你正在开发中频繁重启，也可以在 agent 对话中直接问新照片相关问题 —— AutoEmbed 每次启动都会检查并同步。

### Q: Chroma 索引完全重建？

删除 manifest 和数据目录后重启 Agent 即可：

```bash
rm -rf ./data/chroma/
cd agent && source .venv/bin/activate
python chain/photo_agent.py -c ../.local/my-config.yaml
# AutoEmbed 检测到无 manifest → 自动全量重建
```

### Q: Go 后端日志？

默认写入 `backend/data/logs/server/`。终端查看加 `-l`：

```bash
./bin/server -c .local/my-config.yaml -l
```

### Q: 如何更换 LLM 供应商？

修改 `.local/my-config.yaml` 中对应 `base_url` 和 `model`。项目通过 OpenAI 兼容 API 调用，支持火山引擎、通义千问、DeepSeek 等。
