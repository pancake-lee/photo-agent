# Photo Agent - 开发任务拆分

- 周期：3 个工作日（AI 辅助开发）
- 架构：Dify + Go 双栈，零 Python、零前端框架

## Day 1：Go 后端核心代码

目标：Go 后端能独立运行，导入流水线完成一次端到端导入（扫描 -> VLM -> SQLite -> Dify 知识库）。

### 任务清单

- `backend/` 完整目录树 — 创建 Go 目录结构 + go.mod
- `backend/internal/api/routes.go` — Gin 路由骨架 + 健康检查接口
- `backend/internal/model/*.go` — GORM 模型 + SQLite 初始化
- `backend/internal/config/config.go` — 配置管理（Viper + 环境变量）
- `backend/internal/vlm/client.go` — VLM HTTP 客户端封装
- `backend/internal/api/import.go` — 导入任务 API（创建、查询、日志）
- `backend/internal/service/scanner.go` — 目录扫描 + 时间线标签解析（从配置指定的 md 表格读取，按 EXIF 拍摄时间匹配）
- `backend/internal/service/storage.go` — 文件复制到 data/photos/
- `backend/internal/service/processor.go` — 导入流水线（读取预描述、匹配时间线、写入 SQLite）
- `backend/internal/service/photo.go` — 元数据保存到 SQLite
- `backend/internal/vlm/dify.go` — Dify 知识库文档写入 API
- `backend/cmd/batch_vlm/main.go` — 批量 VLM 预处理脚本（独立运行）

### 当日验收标准

由 `backend/test/backendTest.go` 端到端测试覆盖：
`make backend && ./bin/backendTest -l -c .local/my-config.yaml`

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

## Day 2：查询 API + Dify 配置

目标：所有查询 API 可用，Dify Agent 能成功调用 Go 工具，知识库可检索。

### 任务清单

- `backend/internal/api/photo.go` — 照片列表 API（分页、过滤：timeline/tags/keyword）
- `backend/internal/api/photo.go` — 照片详情 API
- `backend/internal/api/photo.go` — 图片文件服务端点（支持 ?size=thumb 缩略图）
- `backend/internal/api/timeline.go` — 时间线列表 API
- `backend/internal/api/timeline.go` — 时间线照片 API
- `backend/internal/api/tag.go` — 标签列表 API + 标签照片 API
- Dify Web UI — Dify 知识库配置（创建数据集、检索设置）
- Dify Web UI — Dify Agent 配置（系统提示词、Function Calling）
- Dify Web UI — Dify 工具配置（OpenAPI Schema 导入 6 个工具）

### 当日验收标准

由 `backend/test/backendTest.go` 端到端测试覆盖：
`make backend && ./bin/backendTest -l -c ./configs/config.yaml`

- 时间线列表 GET `/api/timelines` 返回正确列表
- 按时间线查照片 GET `/api/timelines/{name}/photos` 返回关联照片
- 照片列表分页过滤 GET `/api/photos?timeline=xxx&tag=xxx`
- 照片详情 GET `/api/photos/{id}` 包含正确元数据
- 图片文件服务 GET `/api/photos/{id}/image` 和 `?size=thumb` 正常返回
- Dify Agent 聊天测试："列出所有时间线"、"帮我找云南的雪山照片" 等场景

### 完成情况

- [X] 2.1-2.6 Go 查询 API 全部实现，E2E 测试通过
- [X] 2.7-2.9 Dify 配置完成（知识库、Agent、工具）
  - `init_dify` 脚本通过 Console API 自动登录、创建知识库、上传描述、轮询索引
  - Dify v1.14.0 登录兼容：密码 Base64 编码，cookie + CSRF token 校验
  - dify 部署从简化版升级为官方完整 docker-compose（12 服务），自包含于本仓库
  - dify DSL 导入遇到自定义 tool 的 provider_id UUID 问题，解决后经验浓缩到 `dify/dsl/SKILL.md` 和 `dify/SKILL.md`

## Day 3：联调 + 交付

目标：完整流程跑通，有演示数据，README 能让陌生人 10 分钟跑起来。

### 任务清单

- `-` — 端到端导入测试（用真实照片文件夹跑完整流程）
- `-` — 端到端对话测试（检索、时间线查询、标签查询）
- `backend/internal/service/...` — 导入并发控制完善（3 并发 + 失败重试 3 次）
- `各处 middleware` — 错误处理 + 结构化日志完善
- `demo_data/timeline.md` — 演示数据准备（准备时间线 md 表格 + 测试照片）
- `README.md` — README 完善（痛点 + 亮点 + 快速启动指南）
- `-` — 全量测试 + Bug 修复

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
```

### 完成情况

- [X] 3.1-3.7 全部完成，完整端到端流程已跑通
- [X] server 启动自动同步（AutoSync）已上线，无需手动触发导入
- [X] E2E 测试 `backendTest -l` 覆盖 Group 1（基础 API）+ Group 2（AutoSync）
- [X] E2E 测试 `backendTest -l -c ./configs/config.yaml` 覆盖 Group 3（真实 VLM）
- [X] 火山引擎 multimodal embedding 代理已完成，兼容 OpenAI API 格式
- [X] Dify Agent 已跑通，支持自然语言检索照片、时间线查询、标签查询
