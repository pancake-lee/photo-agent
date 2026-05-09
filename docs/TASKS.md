# Media Agent - 开发任务拆分

## 项目约束

- **周期**：5 个工作日（AI 辅助开发）
- **人力**：1 人 + AI（你扮演"总指挥"，AI 负责具体编码和文档）
- **交付标准**：每天结束有一个可运行的里程碑
- **优先级**：P0 必须完成，P1 尽量完成，P2 看时间

---

## Day 1：项目骨架与基础设施

**目标**：搭建 Go 后端 + Python AI 服务 + CLI 三个骨架，所有基础设施就绪，能成功调用 AI 模型。

### 任务清单

| #   | 任务                                                    | 预估耗时 | 产出文件                                        |
| --- | ------------------------------------------------------- | -------- | ----------------------------------------------- |
| 1.1 | 创建 Go 后端目录结构 + `go.mod`                         | 30min    | `backend/` 完整目录树                           |
| 1.2 | Go：编写 Gin 路由骨架 + 健康检查接口                    | 1h       | `backend/internal/api/routes.go`                |
| 1.3 | Go：编写 GORM 模型 + SQLite 初始化                      | 1.5h     | `backend/internal/model/*.go`, `database.go`    |
| 1.4 | Go：编写配置管理（Viper + 环境变量）                    | 1h       | `backend/config/config.go`                      |
| 1.5 | Python AI：创建目录结构 + FastAPI 骨架                  | 30min    | `ai/` 完整目录树                                |
| 1.6 | Python AI：封装 VLM 调用（图片 -> 描述文本）            | 2h       | `ai/services/vlm.py`                            |
| 1.7 | Python AI：封装 LLM 调用                                | 1h       | `ai/services/llm.py`                            |
| 1.8 | Python AI：封装 Embedding + 初始化 Chroma               | 1.5h     | `ai/services/embedding.py`, `services/vector.py`|
| 1.9 | Python AI：编写健康检查接口                             | 30min    | `ai/main.py` (GET /ai/health)                   |
| 1.10| CLI：创建目录结构 + Click 骨架                          | 30min    | `cli/` 目录树 + `main.py`                       |
| 1.11| CLI：编写 `init` 命令（创建数据目录）                   | 1h       | `cli/commands/init.py`                          |

### 当日验收标准

```bash
# 启动 Python AI 服务
$ cd ai && uvicorn main:app --reload --port 8000
# Swagger UI 可访问: http://localhost:8000/docs

# 另开终端，测试 AI 调用
$ python -c "from services.vlm import describe_image; print(describe_image('test.jpg'))"
# 成功返回图片描述

# 启动 Go 后端
$ cd backend && go run cmd/server/main.go
# 健康检查
$ curl http://localhost:8080/api/v1/health
{"status":"ok"}

# 测试 Go + Python 连通性
$ curl http://localhost:8080/api/v1/health/ai
{"ai_status":"ok"}
```

### 风险与应对

| 风险                         | 应对                                        |
| ---------------------------- | ------------------------------------------- |
| API Key 配置错误导致调用失败 | 先写一个 `test_api.py` 脚本单独测试每个模型 |
| Go 依赖下载慢               | 配置 GOPROXY=https://goproxy.cn             |
| Chroma 初始化报错            | 降级方案：用 FAISS（纯内存，无需持久化）    |

---

## Day 2：照片导入流水线

**目标**：完成照片导入的核心流程，Go 管理元数据，Python 生成描述和标签，全部进入向量库。

### 任务清单

| #   | 任务                                                    | 预估耗时 | 产出文件                                        |
| --- | ------------------------------------------------------- | -------- | ----------------------------------------------- |
| 2.1 | Go：实现照片元数据 API（导入批次创建、更新、查询）      | 2h       | `backend/internal/api/photo.go`                 |
| 2.2 | Go：实现照片目录扫描（从文件夹名解析时间线标签）        | 1h       | `backend/internal/service/photo_scanner.go`     |
| 2.3 | Python AI：实现单张照片描述生成（VLM + 标签提取）       | 2h       | `ai/services/vlm.py`, `services/tag_extractor.py`|
| 2.4 | Python AI：实现描述文本嵌入并存入 Chroma                | 1.5h     | `ai/services/vector.py`                         |
| 2.5 | CLI：实现 `photo import` 命令（扫描 -> Go 创建 -> AI 描述 -> Go 更新） | 2.5h     | `cli/commands/photo.py`                         |
| 2.6 | 准备摄影照片（整理时间线文件夹）                        | 1h       | `data/photos/*/`                                |
| 2.7 | （可选）准备真人短片截图                                | 1h       | `data/assets/shortfilm/*.jpg`                   |

### 当日验收标准

```bash
# 单文件夹照片导入
$ media-agent photo import ./data/photos/2024-02-云南/ --timeline "2024-02-云南"
> 发现 45 张照片
> Go 创建元数据: 45/45
> AI 生成描述: 45/45
> 全部处理完成，已建立向量索引

# 验证
$ curl http://localhost:8080/api/v1/photos?timeline=2024-02-云南
# 返回 45 条记录

$ curl -X POST http://localhost:8000/ai/search -d '{"query":"雪山"}'
# 返回匹配结果
```

### 关键设计决策

- **照片描述 Prompt**：
  ```
  请详细描述这张照片的内容。包括：
  - 主体内容（人/物/风景）
  - 场景环境（室内/室外、自然/城市）
  - 光线氛围（明亮/昏暗、自然光/人工光）
  - 色彩风格（鲜艳/柔和、冷暖倾向）
  - 构图特点（前景/背景、对称/非对称）
  ```
- **标签提取**：对描述文本调用 LLM，提取 5-10 个关键词

---

## Day 3：Agent 核心编排

**目标**：Python AI 服务实现 Agent 能力，Go 后端对接，CLI 支持对话。

### 任务清单

| #   | 任务                                                    | 预估耗时 | 产出文件                                        |
| --- | ------------------------------------------------------- | -------- | ----------------------------------------------- |
| 3.1 | Python AI：设计 Agent System Prompt + 工具定义          | 1.5h     | `ai/agent/prompts.py`                           |
| 3.2 | Python AI：实现向量检索工具                             | 1h       | `ai/tools/vector_search.py`                     |
| 3.3 | Python AI：实现时间线查询工具                           | 1h       | `ai/tools/timeline_query.py`                    |
| 3.4 | Python AI：实现标签查询工具                             | 1h       | `ai/tools/tag_query.py`                         |
| 3.5 | Python AI：搭建 LangChain Agent（ReAct / Tool Calling） | 3h       | `ai/agent/orchestrator.py`                      |
| 3.6 | Go：实现对话 API（加载历史 -> 调用 Python AI -> 保存记录）| 2h       | `backend/internal/api/chat.go`                  |
| 3.7 | Go：实现会话历史管理（SQLite CRUD）                     | 1.5h     | `backend/internal/service/session.go`           |
| 3.8 | CLI：实现 `chat` 命令（交互式对话）                     | 2h       | `cli/commands/chat.py`                          |
| 3.9 | Python AI：编写 Agent 单元测试                          | 1h       | `ai/tests/test_agent.py`                        |

### 当日验收标准

```bash
# 测试 Agent 对话
$ media-agent chat
> 帮我找云南的雪山照片
# 期望：返回匹配照片列表

# 测试时间线问答
$ media-agent chat
> 2024年我去过哪些地方拍照
# 期望：返回时间线列表

# API 测试
$ curl -X POST http://localhost:8080/api/v1/chat \
  -d '{"message":"帮我找云南的雪山照片"}'
{"reply":"找到 3 张匹配照片...","tools_used":["vector_search"]}
```

---

## Day 4：完善与测试

**目标**：完善所有 API，CLI 交互美化，端到端测试通过。

### 任务清单

| #   | 任务                                                    | 预估耗时 | 产出文件                                        |
| --- | ------------------------------------------------------- | -------- | ----------------------------------------------- |
| 4.1 | Go：完善照片查询 API（分页、过滤、搜索）                | 1.5h     | `backend/internal/api/photo.go`                 |
| 4.2 | Go：完善时间线 API                                      | 1h       | `backend/internal/api/timeline.go`              |
| 4.3 | Go：添加错误处理和用户友好响应                          | 1.5h     | 各处 middleware                                 |
| 4.4 | Go：生成 Swagger 文档                                   | 1h       | `backend/internal/api/routes.go`                |
| 4.5 | CLI：`chat` 命令 Rich 美化（表格、面板、进度条）        | 2h       | `cli/commands/chat.py`                          |
| 4.6 | CLI：实现 `debug` 子命令                                | 1.5h     | `cli/commands/debug.py`                         |
| 4.7 | CLI：添加全局选项（--config, --verbose）                | 1h       | `cli/main.py`                                   |
| 4.8 | 端到端测试（完整流程脚本）                              | 1.5h     | `tests/e2e/test_full_flow.py`                   |

### 当日验收标准

```bash
# 全流程测试
$ media-agent init
$ media-agent photo import ./data/photos/ --recursive
$ media-agent chat
# 成功进行 3 轮以上对话

# API 完整测试（curl 所有端点）
$ ./tests/e2e/test_api.sh
# 全部通过
```

---

## Day 5：部署、测试与交付

**目标**：项目可完整运行，有演示数据，文档齐全，可对外展示。

### 任务清单

| #   | 任务                                                    | 预估耗时 | 产出文件                                        |
| --- | ------------------------------------------------------- | -------- | ----------------------------------------------- |
| 5.1 | 编写 Go Dockerfile                                      | 1h       | `backend/Dockerfile`                            |
| 5.2 | 编写 Python AI Dockerfile                               | 1h       | `ai/Dockerfile`                                 |
| 5.3 | 编写 docker-compose.yml（Go + Python + 数据卷）         | 1h       | `docker-compose.yml`                            |
| 5.4 | 部署脚本和启动指南                                      | 1h       | `ops/start.sh`, `ops/README.md`                 |
| 5.5 | 准备完整演示数据                                        | 2h       | `demo_data/`                                    |
| 5.6 | 编写项目 README（痛点+亮点+快速启动）                   | 2h       | `README.md`                                     |
| 5.7 | 运行全量测试，修复 Bug                                  | 2h       | -                                               |
| 5.8 | 录制/编写演示流程文档                                   | 1.5h     | `docs/DEMO.md`                                  |

### 演示数据准备

```
demo_data/
└── photos/
    ├── 2024-02-云南/
    │   ├── IMG_0234.jpg
    │   ├── IMG_0241.jpg
    │   └── ...
    ├── 2023-10-青岛/
    │   ├── IMG_0012.jpg
    │   └── ...
    └── 2025-01-生日/
        └── ...
```

### 当日验收标准

```bash
# Docker 一键启动
$ docker-compose up -d
$ docker-compose logs -f
# 两个服务都启动成功

# 完整流程测试
$ media-agent init
$ media-agent photo import demo_data/photos/ --recursive
$ media-agent chat
# 成功进行 3 轮以上对话，检索和问答均正常

# 测试通过 checklist
- [ ] Go API 所有端点可访问
- [ ] Python AI 所有端点可访问
- [ ] CLI 所有命令可执行
- [ ] Agent 对话 10 轮无报错
- [ ] 向量检索 Top-5 准确率 > 70%
- [ ] Docker 一键启动成功
```

---

## 开发节奏检查点

每天结束时对照以下检查点，确保不偏离轨道：

### Day 1 检查点

- [ ] `uvicorn` 能启动，Python Swagger UI 可访问
- [ ] `go run` 能启动，Go 健康检查可访问
- [ ] Go 能成功调用 Python AI 服务
- [ ] `python test_api.py` 三个模型（LLM/VLM/Embedding）都能成功调用
- [ ] SQLite 和 Chroma 初始化无报错

### Day 2 检查点

- [ ] Go API 能创建/查询照片元数据
- [ ] Python AI 能生成描述并返回标签
- [ ] CLI `photo import` 能完整跑通
- [ ] Chroma 中向量数量 == 导入照片数量

### Day 3 检查点

- [ ] Python Agent 能正确选择工具
- [ ] Go 对话 API 能保存历史并返回回复
- [ ] CLI `chat` 能进行多轮对话
- [ ] 回复中有素材引用

### Day 4 检查点

- [ ] CLI `chat` 交互流畅，Rich 输出美观
- [ ] API 可用 curl 完整测试
- [ ] 端到端测试脚本全部通过

### Day 5 检查点

- [ ] Docker 两个容器都能启动并运行
- [ ] README 能让陌生人 10 分钟内跑起来
- [ ] 有至少 3 个演示对话案例

---

## 风险预案

| 风险                     | 概率 | 影响 | 预案                                              |
| ------------------------ | ---- | ---- | ------------------------------------------------- |
| API 调用费用过高         | 中   | 成本 | 用 GPT-4o-mini，批量导入限制并发                  |
| Day 1 双栈骨架搭不完     | 高   | 进度 | Go 和 Python 分两天搭，Day 1 优先 Python AI 服务  |
| Day 2 素材处理太慢       | 高   | 进度 | 先用 20 张图做小数据集验证，剩余批量处理放后台    |
| Day 3 Agent 工具路由不准 | 中   | 体验 | 降级为固定路由（关键词匹配 + LLM 辅助）           |
| 时间不够，P1 做不完      | 高   | 范围 | P1 摄影主题分析可简化为"基于检索结果的简单建议"   |
| Go ↔ Python 联调出问题   | 中   | 进度 | 定义好接口契约，用 curl 先单独测试每个端点        |

---

## AI 协作模式

作为"总指挥"，你每天的工作流程：

1. **晨会（30min）**：看 TASKS.md，明确今天要做什么
2. **派任务（持续）**：把具体编码任务交给 AI，提供上下文和需求
   - Go 任务交给熟悉 Go 的 AI
   - Python 任务交给熟悉 Python 的 AI
   - 或者同一个 AI 按顺序处理
3. **验收（每完成一个任务）**：运行代码，验证是否达标
4. **日会（30min）**：对照检查点，确认里程碑，调整明天计划
5. **记录（5min）**：更新 TASKS.md 进度，记录阻塞问题

**给 AI 的 Prompt 模板**：

```
请帮我实现 [Go/Python] [模块名] 的 [功能]。

上下文：
- 这是 Media Agent 项目的 [Day X] 任务
- 相关设计文档在 docs/PRD.md 和 docs/TECH_SPEC.md
- 已有代码：[列出相关文件]
- 接口契约：[Go/Python 之间的 API 定义]

需求：
- [具体需求]
- [输入/输出格式]
- [边界条件]

验收标准：
- [可运行的测试命令]
```
