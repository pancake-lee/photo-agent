# Photo Agent

> 个人摄影资产 AI 助手 —— 让你的照片库"会说话"

> 本项目既是**面向个人的实用工具**，也是**AI 应用开发的学习项目**，具体的代码让抽象的概念有了边界和范围，清晰理解当下各种AI概念，不被流媒体各种吹嘘带着走。

用自然语言与你的照片库对话。Agent 理解你的描述，从数千张照片中精准定位目标，回答关于拍摄经历的问题，并且基于历史作品给出创作建议。

---

## 项目简介

Photo Agent 是一个面向摄影爱好者的 AI 媒体资产管理助手。它通过视觉语言模型（VLM）自动生成每张照片的 AI 视觉描述，构建时间线与标签知识库，搭载向量检索系统，让用户可以用自然语言与自己的照片库进行对话式交互。

**典型使用场景**：

- "帮我找 2024 年在云南拍的雪山人像" → 返回匹配照片列表，附带拍摄参数
- "我拍过几次海边日出？都在哪些地方？" → Agent 基于照片库档案回答
- "分析一下我的人像片和风光片各有什么特点" → 基于实际素材的风格分析
- "今年生日想送什么礼物好？" → 基于历年 3 月 7 日前后的照片提供建议

---

## 核心能力

### 自然语言智能检索

无需翻文件夹、记文件名。描述你想要的画面，Agent 通过向量语义检索 + 结构化 SQL 查询双引擎，精准定位目标照片。

- **语义检索**：基于 VLM 生成的视觉描述，用 Embedding 向量匹配"雪山日照金山"这类模糊描述
- **结构化查询**：EXIF 元数据（品牌、镜头、焦距、ISO、拍摄时间）通过 Text-to-SQL 直接查询
- **混合策略**：LangGraph 自动路由 —— 统计型查询走 SQL，语义型查询走 RAG

### 摄影档案问答

照片库即知识库。Agent 基于全部素材的描述、时间线标签和 EXIF 元数据，回答关于拍摄经历的各类问题。

- 时间线自动匹配：根据 EXIF 拍摄时间自动关联"2024-02 云南旅游"等活动标签
- 多轮对话：支持追问和条件细化（"上一个结果里，只要有人物的"）
- 创作辅助：基于历史作品分析风格特点、构图偏好，激发拍摄灵感

### 流式对话体验

Agent 支持流式输出，回复像打字一样逐字呈现。底层采用 PID 速度控制算法，打印速度平滑且自动跟上 LLM 实际输出节奏。

### 双栈架构，各取所长

- **Dify**：Agent 图形化编排、知识库 RAG、自带聊天 UI，工作流可观测
  - Dify自带默认Agent应用，快速出效果
- **Python AI 服务层**
  - LangChain 、Chroma 、Text-to-SQL、LangGraph 、Function Calling
  - 同样是实现Agent，更多是为了前期学习，后期深度优化Agent流程
- **Go 后端**：高性能业务后端，照片元数据管理、文件服务、导入流水线、VLM预处理照片、Embedding 代理

---

## 架构概览

```
用户浏览器
    ↓ HTTP
Dify Web UI (Docker)
    ├── Agent 意图识别
    ├── 知识库向量检索 (RAG)
    ├── 工具调用 → Go API
    └── 模型管理 (LLM / Embedding)
    ↓ HTTP (OpenAPI Schema)
Go Backend (:10000)
    ├── 照片元数据管理 (GORM + SQLite)
    ├── 文件服务 (本地文件系统)
    ├── 导入流水线 (并发控制、重试)
    ├── VLM / Embedding HTTP 代理
    └── 统计 API (EXIF 聚合分析)
    ↑ HTTP
Python AI Service
    ├── LangChain 聊天编排
    ├── Chroma 向量检索
    ├── Text-to-SQL (自然语言转 SQL)
    ├── LangGraph 查询路由
    └── Function Calling 工具调用
    ↑ CLI
用户终端
```

**数据流**：

```
batch_vlm 预处理（VLM 生成视觉描述 → descriptions.json）
    ↓
server 启动 → AutoSync 自动同步
    ├─→ SQLite（照片元数据 + EXIF）
    └─→ Dify 知识库（自动 Embedding → 向量库）
    ↓
用户自然语言查询 → Agent 意图识别 → RAG / SQL / 工具 → 生成回复
```

---

## 快速开始

### 0. Python 环境

本项目 Python AI 服务层使用 **Python 3.12**，通过 uv 管理版本，项目 venv 位于 `agent/.venv/`。

```bash
# 安装 uv（如未安装）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 安装 Python 3.12
uv python install 3.12

# 创建项目 venv
cd agent
uv venv .venv --python 3.12

# 安装依赖
source .venv/bin/activate
uv pip install langchain langchain-openai chromadb requests python-dotenv httpx langgraph
```

> 系统 Python（3.9）保持不动，避免影响系统其他软件。

### 1. 克隆仓库

```bash
git clone <repo-url>
cd photo-agent
```

### 2. 启动 Dify

```bash
cd dify
docker-compose up -d
```

访问 http://localhost 完成初始化配置

包括配置模型供应商，创建自定义工具，导入DSL等等

### 3. 编译 Go 后端

```bash
make backend
```

### 4. 准备配置

```bash
# 复制公共模板到个人目录（已加入 .gitignore）
cp ./configs/config.yaml .local/my-config.yaml
# 编辑 .local/my-config.yaml，填入 API Key、照片路径等
```

### 5. 预处理照片

```bash
./bin/batch_vlm -c .local/my-config.yaml -input /path/to/your/photos
```

### 6. 启动服务

```bash
./bin/server -c .local/my-config.yaml
# 自动触发 AutoSync，将 descriptions.json 同步到 SQLite + Dify
```

### 7. 对话测试

在 Dify Web UI 中打开 Agent 应用，输入：

> "帮我找云南的雪山照片"

Agent 将自动选择检索策略，返回匹配照片列表，并附带 Markdown 图片展示。

---

## 项目结构

```
photo-agent/
├── backend/              # Go 业务后端
│   ├── cmd/
│   │   ├── server/       # 服务入口 + AutoSync
│   │   ├── batch_vlm/    # 批量 VLM 预处理脚本
│   │   └── init_dify/    # Dify 知识库初始化脚本
│   ├── internal/         # API / Model / Service / Config / VLM
│   └── test/             # E2E 测试
├── agent/                # Python AI 服务层
│   ├── chain/            # LangChain / LangGraph 编排
│   ├── embedding/        # 分块策略 + Embedding 客户端
│   ├── vectorstore/      # ChromaDB 封装
│   ├── db/               # SQLite 查询客户端
│   ├── tools/            # OpenAPI 工具解析与执行
│   ├── utils/            # 流式打印等工具
│   └── scripts/          # 索引脚本、调试脚本
├── dify/                 # Dify 部署配置 + DSL 文件
├── data/                 # 照片文件 / SQLite / descriptions.json
└── docs/                 # 产品需求 / 技术方案 / 任务记录
```

---

## 文档索引

- [docs/prd.md](docs/prd.md) — 产品需求文档。功能范围、用户故事、验收标准、优先级（P0/P1/P2）
- [docs/tech.md](docs/tech.md) — 技术方案文档。架构设计、API 契约、数据模型、Dify 配置
- [docs/task_1.md](docs/task_1.md) — 第一轮开发记录：MVP v1.0.0，Go 后端核心 + Dify Agent 联调（已完成）
- [docs/task_2.md](docs/task_2.md) — 第二轮开发记录：AI 服务层（LangChain + Chroma + Text-to-SQL + LangGraph），Go 后端扩展 + Python 推理层
- [docs/note.md](docs/note.md) — 决策备忘。被否定的技术方案、踩坑记录、前期讨论归档
- [dify/dsl/PhotoAgent.yml](dify/dsl/PhotoAgent.yml) — Dify Agent DSL 文件，可导入复现 Agent 配置

---

## License

MIT
