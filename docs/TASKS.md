# Photo Agent - 开发任务拆分

## 项目约束

- **周期**：3 个工作日（AI 辅助开发）
- **人力**：1 人 + AI（你扮演"总指挥"，AI 负责具体编码）
- **交付标准**：每天结束有一个可运行的里程碑
- **架构**：Dify + Go 双栈，零 Python、零前端框架

---

## Day 1：Go 后端核心代码

**目标**：Go 后端能独立运行，导入流水线完成一次端到端导入（扫描 -> VLM -> SQLite -> Dify 知识库）。

### 任务清单

| #    | 任务                                                                            | 预估耗时 | 产出文件                                  |
| ---- | ------------------------------------------------------------------------------- | -------- | ----------------------------------------- |
| 1.1  | 创建 Go 目录结构 + go.mod                                                       | 20min    | `backend/` 完整目录树                   |
| 1.2  | Go：Gin 路由骨架 + 健康检查接口                                                 | 30min    | `backend/internal/api/routes.go`        |
| 1.3  | Go：GORM 模型 + SQLite 初始化                                                   | 40min    | `backend/internal/model/*.go`           |
| 1.4  | Go：配置管理（Viper + 环境变量）                                                | 30min    | `backend/internal/config/config.go`     |
| 1.5  | Go：VLM HTTP 客户端封装                                                         | 1h       | `backend/internal/vlm/client.go`        |
| 1.6  | Go：导入任务 API（创建、查询、日志）                                            | 1h       | `backend/internal/api/import.go`        |
| 1.7  | Go：目录扫描 + 时间线标签解析（从配置指定的 md 表格读取，按 EXIF 拍摄时间匹配） | 1h       | `backend/internal/service/scanner.go`   |
| 1.8  | Go：文件复制到 data/photos/                                                     | 30min    | `backend/internal/service/storage.go`   |
| 1.9  | Go：导入流水线（读取预描述、匹配时间线、写入 SQLite）                           | 1.5h     | `backend/internal/service/processor.go` |
| 1.10 | Go：元数据保存到 SQLite                                                         | 30min    | `backend/internal/service/photo.go`     |
| 1.11 | Go：Dify 知识库文档写入 API                                                     | 1h       | `backend/internal/vlm/dify.go`          |
| 1.12 | Go：批量 VLM 预处理脚本（独立运行）                                             | 1h       | `backend/cmd/batch_vlm/main.go`         |

### 当日验收标准

由 `backend/test/backendTest.go` 端到端测试覆盖：

```bash
# 编译
make backend

# 运行基础 API 测试 + AutoSync 流程测试（无需外部依赖）
./bin/backendTest -l

# 运行完整测试（含真实 VLM 调用，需 -c 传入含 vlm 配置的文件）
./bin/backendTest -l -c .local/pancake.yaml
```

测试覆盖范围：

- 健康检查接口
- 导入任务创建、执行、查询、日志
- 照片 CRUD（列表、详情、原图、缩略图）
- 时间线列表和关联照片查询
- 标签列表和关联照片查询
- AutoSync 流程（server 启动自动同步 descriptions.json -> SQLite）
- batch_vlm 全流程（真实 VLM 调用 -> descriptions.json，需 -c 配置）

### 完成情况

- [X] 1.1-1.12 全部完成，后端模块编译通过，服务可启动，E2E 测试通过
- [X] 批量 VLM 预处理已完成，共计 977 张图片
  - 第一批（250 张）：Doubao-Seed-1.6-vision，约 400,000 tokens（含前期测试，统计不精确）
  - 第二批（727 张）：Doubao-1.5-vision-pro-32k，剩 91,828 / 共 500,000 tokens
  - Batch VLM done: success=727, failed=0, skipped=250, total=977, elapsed=21m39s
- [X] `photo_path` 配置问题已修复

### 风险与应对

| 风险                         | 应对                                                                          |
| ---------------------------- | ----------------------------------------------------------------------------- |
| API Key 配置错误导致调用失败 | 先写一个 `test_vlm.go` 单独测试 VLM 调用；脚本支持 `--dry-run` 先验证配置 |
| Go 依赖下载慢                | 配置 GOPROXY=https://goproxy.cn                                               |
| Dify API 写入知识库失败      | 记录失败文档，导入任务状态标记为部分完成                                      |

---

## Day 2：查询 API + Dify 配置

**目标**：所有查询 API 可用，Dify Agent 能成功调用 Go 工具，知识库可检索。

### 任务清单

| #   | 任务                                                            | 预估耗时 | 产出文件                             |
| --- | --------------------------------------------------------------- | -------- | ------------------------------------ |
| 2.1 | Go：照片列表 API（分页、过滤：timeline/tags/keyword）           | 1h       | `backend/internal/api/photo.go`    |
| 2.2 | Go：照片详情 API                                                | 30min    | `backend/internal/api/photo.go`    |
| 2.3 | Go：图片文件服务端点（支持 ?size=thumb 缩略图）                 | 1.5h     | `backend/internal/api/photo.go`    |
| 2.4 | Go：时间线列表 API                                              | 30min    | `backend/internal/api/timeline.go` |
| 2.5 | Go：时间线照片 API                                              | 30min    | `backend/internal/api/timeline.go` |
| 2.6 | Go：标签列表 API + 标签照片 API                                 | 30min    | `backend/internal/api/tag.go`      |
| 2.7 | **手动**：Dify 知识库配置（创建数据集、检索设置）         | 30min    | Dify Web UI                          |
| 2.8 | **手动**：Dify Agent 配置（系统提示词、Function Calling） | 30min    | Dify Web UI                          |
| 2.9 | **手动**：Dify 工具配置（OpenAPI Schema 导入 6 个工具）   | 1h       | Dify Web UI                          |

### 当日验收标准

由 `backendTest` 端到端测试覆盖：

```bash
# 基础 API 测试覆盖所有查询接口
./bin/backendTest -l
```

验证项目：

- 时间线列表 GET `/api/timelines` 返回正确列表
- 按时间线查照片 GET `/api/timelines/{name}/photos` 返回关联照片
- 照片列表分页过滤 GET `/api/photos?timeline=xxx&tag=xxx`
- 照片详情 GET `/api/photos/{id}` 包含正确元数据
- 图片文件服务 GET `/api/photos/{id}/image` 和 `?size=thumb` 正常返回
- Dify Agent 聊天测试："列出所有时间线"、"帮我找云南的雪山照片" 等场景

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
- **缩略图生成**：Go 调用 `github.com/disintegration/imaging` 生成 300px 宽缩略图

### 完成情况

- [X] 2.1-2.6 Go 查询 API 全部实现，E2E 测试通过
- [X] 2.7-2.9 Dify 配置完成（知识库、Agent、工具）
  - `init_dify` 脚本通过 Console API 自动登录、创建知识库、上传描述、轮询索引
  - Dify v1.14.0 登录兼容：密码 Base64 编码，cookie + CSRF token 校验
  - dify 部署从简化版升级为官方完整 docker-compose（12 服务），自包含于本仓库
  - dify DSL 导入遇到自定义 tool 的 provider_id UUID 问题，解决后经验浓缩到 `dify/dsl/SKILL.md` 和 `dify/SKILL.md`

---

## Day 3：联调 + 交付

**目标**：完整流程跑通，有演示数据，README 能让陌生人 10 分钟跑起来。

### 任务清单

| #   | 任务                                          | 预估耗时 | 产出文件                         |
| --- | --------------------------------------------- | -------- | -------------------------------- |
| 3.1 | 端到端导入测试（用真实照片文件夹跑完整流程）  | 1h       | -                                |
| 3.2 | 端到端对话测试（检索、时间线查询、标签查询）  | 1h       | -                                |
| 3.3 | 导入并发控制完善（3 并发 + 失败重试 3 次）    | 1h       | `backend/internal/service/...` |
| 3.4 | 错误处理 + 结构化日志完善                     | 1h       | 各处 middleware                  |
| 3.5 | 演示数据准备（准备时间线 md 表格 + 测试照片） | 1h       | `demo_data/timeline.md`        |
| 3.6 | README 完善（痛点 + 亮点 + 快速启动指南）     | 1.5h     | `README.md`                    |
| 3.7 | 全量测试 + Bug 修复                           | 1.5h     | -                                |

### 当日验收标准

```bash
# 完整流程测试
# 1. 运行 batch_vlm 预处理照片
# 2. 启动 server（自动触发 AutoSync）
# 3. 在 Dify 聊天中："帮我找云南的雪山照片"
# 4. 期望：返回匹配照片列表，含 Markdown 图片展示

# 测试通过 checklist
- [x] Go API 所有端点可访问（由 backendTest -l 验证）
- [x] Dify Agent 能正确选择工具
- [x] Agent 对话 5 轮无报错
- [x] 向量检索 Top-5 准确率 > 70%
- [x] README 能让陌生人 10 分钟内跑起来
```

### 完成情况

- [X] 3.1-3.7 全部完成，完整端到端流程已跑通
- [X] server 启动自动同步（AutoSync）已上线，无需手动触发导入
- [X] E2E 测试 `backendTest -l` 覆盖 Group 1（基础 API）+ Group 2（AutoSync）
- [X] E2E 测试 `backendTest -l -c .local/pancake.yaml` 覆盖 Group 3（真实 VLM）
- [X] 火山引擎 multimodal embedding 代理已完成，兼容 OpenAI API 格式
- [X] Dify Agent 已跑通，支持自然语言检索照片、时间线查询、标签查询

---

## 开发节奏检查点

### Day 1 检查点

- [X] `go run` 能启动，健康检查可访问
- [X] `batch_vlm` 能成功调用 VLM API 返回描述
- [X] SQLite 初始化无报错，表结构正确
- [X] 导入任务能创建并完成，SQLite 中有照片记录
- [X] Dify 知识库中有对应数量的文档（通过 `init_dify` 脚本确认）
- [X] 批量 VLM 脚本能独立运行，生成 `descriptions.json`
- [X] `backendTest -l` Group 1 全部通过

### Day 2 检查点

- [X] 所有查询 API 可用（由 backendTest 验证）
- [X] 图片文件服务端点能返回正确图片（含缩略图）
- [X] Dify 知识库配置完成，检索模式正确
- [X] Dify Agent 配置完成，系统提示词已保存
- [X] Dify 工具配置完成，6 个工具可成功调用
- [X] Dify 聊天中"列出时间线"能返回正确结果
- [X] `backendTest -l` Group 2 AutoSync 测试通过

### Day 3 检查点

- [X] 用真实照片跑完一次完整导入 + 对话流程
- [X] 至少 3 个演示对话案例通过
- [X] README 包含快速启动命令
- [X] 全量 E2E 测试通过

---

## 风险预案

| 风险                     | 概率 | 影响 | 预案                                                     |
| ------------------------ | ---- | ---- | -------------------------------------------------------- |
| API 调用费用过高         | 中   | 成本 | 用 GPT-4o-mini / 火山引擎低成本模型，批量导入限制 3 并发 |
| 火山引擎 API 调用失败    | 低   | 进度 | 备用 OpenAI / Qwen API Key，三选一降级                   |
| Day 1 代码量过大做不完   | 中   | 进度 | 优先保证 1.1-1.6 + 1.9 + 1.12，1.7-1.8 可简化            |
| Dify 手动配置耗时超预期  | 高   | 进度 | Day 2 优先配置工具和 Agent，知识库可次日补               |
| Agent 工具路由不准       | 中   | 体验 | 优化系统提示词，明确工具使用场景                         |
| 时间不够，Day 3 测试不足 | 中   | 质量 | 先保证 1 个端到端场景通过，其余放 README 备注            |

---

## 后续优化 TODO

Day 1-3 核心功能已完成，Dify Agent 已跑通。以下为可选增强项：

- [ ] **pgo swagger**：使用 pgo 的 proto 定义导出 swagger，避免 AI 输出不稳定导致文档不同步
- [ ] **`descriptions.json` 嵌入 EXIF 拍摄时间**
  - batch_vlm 输出时从照片 EXIF 提取 `DateTimeOriginal`，写入 `shot_at` 字段
  - server AutoSync 时读取 `shot_at` 匹配时间线
  - 当前 batch_vlm 已支持 EXIF 读取，但时间线匹配逻辑仍需优化
- [ ] **时间线日期解析与匹配优化**
  - 支持更多日期格式（如 "2024.01.01"、"1月1日" 等）
  - 模糊匹配：照片日期落在时间线区间内即匹配
- [ ] **Docker Compose 一键启动**：编排 Dify + Go + 数据卷
