# Photo Agent - 开发任务拆分

## 项目约束

- **周期**：3 个工作日（AI 辅助开发）
- **人力**：1 人 + AI（你扮演"总指挥"，AI 负责具体编码）
- **交付标准**：每天结束有一个可运行的里程碑
- **架构**：Dify + Go 双栈，零 Python、零前端框架

---

## Day 1：Go 后端核心代码

**目标**：Go 后端能独立运行，导入流水线完成一次端到端导入（扫描 → VLM → SQLite → Dify 知识库）。

### 任务清单

| #   | 任务                                     | 预估耗时 | 产出文件                              |
| --- | ---------------------------------------- | -------- | ------------------------------------- |
| 1.1 | 创建 Go 目录结构 + go.mod                | 20min    | `backend/` 完整目录树                 |
| 1.2 | Go：Gin 路由骨架 + 健康检查接口          | 30min    | `backend/internal/api/routes.go`      |
| 1.3 | Go：GORM 模型 + SQLite 初始化            | 40min    | `backend/internal/model/*.go`         |
| 1.4 | Go：配置管理（Viper + 环境变量）         | 30min    | `backend/internal/config/config.go`   |
| 1.5 | Go：VLM HTTP 客户端封装                  | 1h       | `backend/internal/vlm/client.go`      |
| 1.6 | Go：导入任务 API（创建、查询、日志）     | 1h       | `backend/internal/api/import.go`      |
| 1.7 | Go：目录扫描 + 时间线标签解析            | 1h       | `backend/internal/service/scanner.go` |
| 1.8 | Go：文件复制到 data/photos/              | 30min    | `backend/internal/service/storage.go` |
| 1.9 | Go：批量 VLM 调用（并发控制 3 并发）     | 1.5h     | `backend/internal/service/processor.go` |
| 1.10 | Go：元数据保存到 SQLite                  | 30min    | `backend/internal/service/photo.go`   |
| 1.11 | Go：Dify 知识库文档写入 API              | 1h       | `backend/internal/vlm/dify.go`        |

### 当日验收标准

```bash
# 启动 Go 后端
$ cd backend && go run cmd/server/main.go
# 健康检查
$ curl http://localhost:8080/api/health
{"status":"ok"}

# 测试导入
$ curl -X POST http://localhost:8080/api/import/jobs \
  -d '{"sourcePath":"./demo_data/photos/2024-02-云南","recursive":false}'
{"id":"job_xxx","status":"processing"}

# 等待完成后验证
$ curl http://localhost:8080/api/import/jobs/job_xxx
{"status":"completed","total_photos":45,"processed_photos":45}

# SQLite 中有记录
$ sqlite3 data/sqlite/photo_agent.db "SELECT COUNT(*) FROM photos"
45

# Dify 知识库中有文档（需在 Dify 后台确认或调用 API 查询）
```

### 风险与应对

| 风险                         | 应对                                          |
| ---------------------------- | --------------------------------------------- |
| API Key 配置错误导致调用失败 | 先写一个 `test_vlm.go` 单独测试 VLM 调用      |
| Go 依赖下载慢                | 配置 GOPROXY=https://goproxy.cn               |
| Dify API 写入知识库失败      | 记录失败文档，导入任务状态标记为部分完成      |

---

## Day 2：查询 API + Dify 配置

**目标**：所有查询 API 可用，Dify Agent 能成功调用 Go 工具，知识库可检索。

### 任务清单

| #   | 任务                                              | 预估耗时 | 产出文件                                  |
| --- | ------------------------------------------------- | -------- | ----------------------------------------- |
| 2.1 | Go：照片列表 API（分页、过滤：timeline/tags/keyword） | 1h   | `backend/internal/api/photo.go`           |
| 2.2 | Go：照片详情 API                                  | 30min    | `backend/internal/api/photo.go`           |
| 2.3 | Go：图片文件服务端点（支持 ?size=thumb 缩略图）   | 1.5h     | `backend/internal/api/photo.go`           |
| 2.4 | Go：时间线列表 API                                | 30min    | `backend/internal/api/timeline.go`        |
| 2.5 | Go：时间线照片 API                                | 30min    | `backend/internal/api/timeline.go`        |
| 2.6 | Go：标签列表 API + 标签照片 API                   | 30min    | `backend/internal/api/tag.go`             |
| 2.7 | **手动**：Dify 知识库配置（创建数据集、检索设置） | 30min    | Dify Web UI                               |
| 2.8 | **手动**：Dify Agent 配置（系统提示词、Function Calling） | 30min | Dify Web UI                               |
| 2.9 | **手动**：Dify 工具配置（OpenAPI Schema 导入 6 个工具） | 1h   | Dify Web UI                               |

### 当日验收标准

```bash
# 所有 Go API 可用 curl 测试
$ curl http://localhost:8080/api/timelines
["2024-02-云南","2023-10-青岛"]

$ curl http://localhost:8080/api/photos?timeline=2024-02-云南
[{"id":"photo_001",...}]

$ curl http://localhost:8080/api/photos/photo_001/image > test.jpg
# 图片可正常打开

# Dify 聊天测试
> 列出所有时间线
# 期望：返回时间线列表

> 帮我找云南的雪山照片
# 期望：通过知识库 RAG + get_photos_by_timeline 工具，返回匹配照片（含 Markdown 图片链接）
```

### 关键设计决策

- **照片描述 Prompt**（VLM 调用时）：
  ```
  请详细描述这张照片的内容。包括：
  - 主体内容（人/物/风景）
  - 场景环境（室内/室外、自然/城市）
  - 光线氛围（明亮/昏暗、自然光/人工光）
  - 色彩风格（鲜艳/柔和、冷暖倾向）
  - 构图特点（前景/背景、对称/非对称）
  ```
- **缩略图生成**：Go 调用开源库（如 `github.com/disintegration/imaging`）生成 300px 宽缩略图，避免每次返回原图

---

## Day 3：联调 + Docker Compose + 交付

**目标**：完整流程跑通，Docker 一键启动，有演示数据，README 能让陌生人 10 分钟跑起来。

### 任务清单

| #   | 任务                                              | 预估耗时 | 产出文件                        |
| --- | ------------------------------------------------- | -------- | ------------------------------- |
| 3.1 | 端到端导入测试（用真实照片文件夹跑完整流程）      | 1h       | -                               |
| 3.2 | 端到端对话测试（检索、时间线查询、标签查询）        | 1h       | -                               |
| 3.3 | 导入并发控制完善（3 并发 + 失败重试 3 次）          | 1h       | `backend/internal/service/...`  |
| 3.4 | 错误处理 + 结构化日志完善                         | 1h       | 各处 middleware                 |
| 3.5 | Docker Compose 编排（Dify + Go + 数据卷）         | 1h       | `docker-compose.yml`            |
| 3.6 | 演示数据准备（整理时间线文件夹）                  | 1h       | `demo_data/photos/*/`           |
| 3.7 | README 完善（痛点 + 亮点 + 快速启动指南）         | 1.5h     | `README.md`                     |
| 3.8 | 全量测试 + Bug 修复                               | 1.5h     | -                               |

### 当日验收标准

```bash
# Docker 一键启动
$ docker-compose up -d
$ docker-compose logs -f backend
# Go 后端启动成功

# 完整流程测试
# 1. 在 Dify 聊天中："导入 demo_data/photos/"
# 2. 等待导入完成
# 3. 在 Dify 聊天中："帮我找云南的雪山照片"
# 4. 期望：返回匹配照片列表，含 Markdown 图片展示

# 测试通过 checklist
- [ ] Go API 所有端点可访问
- [ ] Dify Agent 能正确选择工具
- [ ] Agent 对话 5 轮无报错
- [ ] 向量检索 Top-5 准确率 > 70%
- [ ] Docker 一键启动成功
- [ ] README 能让陌生人 10 分钟内跑起来
```

---

## 开发节奏检查点

每天结束时对照以下检查点，确保不偏离轨道：

### Day 1 检查点

- [ ] `go run` 能启动，健康检查可访问
- [ ] `test_vlm.go` 能成功调用 VLM API 返回描述
- [ ] SQLite 初始化无报错，表结构正确
- [ ] 导入任务能创建并完成，SQLite 中有照片记录
- [ ] Dify 知识库中有对应数量的文档（调用 API 确认）

### Day 2 检查点

- [ ] 所有查询 API 可用 curl 测试
- [ ] 图片文件服务端点能返回正确图片（含缩略图）
- [ ] Dify 知识库配置完成，检索模式正确
- [ ] Dify Agent 配置完成，系统提示词已保存
- [ ] Dify 工具配置完成，至少 3 个工具可成功调用
- [ ] Dify 聊天中"列出时间线"能返回正确结果

### Day 3 检查点

- [ ] 用真实照片跑完一次完整导入 + 对话流程
- [ ] Docker Compose 能一键启动两个服务
- [ ] 至少 3 个演示对话案例通过
- [ ] README 包含快速启动命令和截图

---

## 风险预案

| 风险                     | 概率 | 影响 | 预案                                             |
| ------------------------ | ---- | ---- | ------------------------------------------------ |
| API 调用费用过高         | 中   | 成本 | 用 GPT-4o-mini，批量导入限制 3 并发              |
| Day 1 代码量过大做不完   | 中   | 进度 | 优先保证 1.1-1.6 + 1.9，1.7-1.8 可简化          |
| Dify 手动配置耗时超预期  | 高   | 进度 | Day 2 优先配置工具和 Agent，知识库可次日补       |
| Agent 工具路由不准       | 中   | 体验 | 优化系统提示词，明确工具使用场景                 |
| 时间不够，Day 3 测试不足 | 中   | 质量 | 先保证 1 个端到端场景通过，其余放 README 备注    |

---

## AI 协作模式

作为"总指挥"，你每天的工作流程：

1. **晨会（30min）**：看 TASKS.md，明确今天要做什么
2. **派任务（持续）**：把具体编码任务交给 AI，提供上下文和需求
3. **验收（每完成一个任务）**：运行代码，验证是否达标
4. **日会（30min）**：对照检查点，确认里程碑，调整明天计划
5. **记录（5min）**：更新 TASKS.md 进度，记录阻塞问题

**给 AI 的 Prompt 模板**：

```
请帮我实现 Go backend [模块名] 的 [功能]。

上下文：
- 这是 Photo Agent 项目的 Day X 任务
- 相关设计文档在 docs/PRD.md 和 docs/TECH_SPEC.md
- 已有代码：[列出相关文件]
- 接口契约：[API 定义]

需求：
- [具体需求]
- [输入/输出格式]
- [边界条件]

验收标准：
- [可运行的测试命令]
```
