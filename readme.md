# Photo Agent

> 个人摄影资产 AI 助手。通过对摄影作品进行 AI 视觉描述、建立时间线与标签知识库、构建向量检索系统，让用户可以用自然语言与自己的照片库对话，实现智能检索、摄影档案问答和创作辅助。

## 项目定位

- **产品定位**：个人摄影资产 AI 助手
- **求职方向**：AI 应用开发 / AI Agent 开发
- **开发模式**：AI 辅助开发，用户作为"总指挥"，AI 负责具体编码和文档输出
- **技术栈**：Dify + Go 双栈。Dify 本地部署负责 Agent 编排、知识库 RAG、聊天 UI（图形化工作流可观测），Go 负责业务后端（照片元数据、文件服务、导入任务、VLM 代理），零 Python、零前端框架。
- **核心能力**：智能检索（P0）/ 摄影档案问答（P0）/ 主题分析与创作建议（P1）/ 时间线关联分析（P2）

## AI小规则

- 阅读README然后等待指令
  - 每次新的对话，我都会让你先阅读readme，了解项目当前情况，你只需要回复收到
- 请总结变更到README
  - 每次完成一个需求点，我会请你总结"变更内容"到readme.md或note.md
    - readme记录的是每个新对话必须先加载的上下文，全局都需要遵循的事情
    - note记录的是一些细节，比如遇到过的问题，某个逻辑的实现细节等等
    - 另外关于具体代码实现的细节，更倾向于记录到对应代码文件的头部注释
    - 跨代码文件协作的实现细节可以记录到note中
  - 你应该按照当前文档的标题结构，分类修改或添加内容
  - 不要单纯追加内容，导致文档无限增长
  - 总结后，你再在对话中给我一个简短的中文的Git提交信息，尽可能是一行/一句话的信息，且符合commitlint规范
- 每次修改了代码后，如果需要测试效果
  - 可以直接帮我执行`./build.bat`，将编译并重启程序，编译报错无法从控制台获取，需要我手动获取后发给你，不要因此不停重复编译
  - 不用等待该脚本退出，后续我来操作，并且会再次与你对话。
- 不修改
  - 当我说"不修改"时，则当前内容只希望你分析问题/提供方案，但不要修改代码
- 代码风格以"手动修改代码"为最高优先级
  - AI在实现需求前，需要先阅读当前相关代码，优先复用你已经手动沉淀的命名、分层、注释和参数组织方式
  - 当手动代码与历史实现冲突时，以最新手动代码风格为准
- 本文的TODO中，已完成的功能从TODO删掉，功能适当写到合适的地方，而不是在TODO中描述实现的功能
- 不要以变更记录来写入readme，直接插入内容到现有标题中，比如直接修改主要功能的条目，增加条目，或者增加编码规范等等
- 不要滥用try catch来处理代码问题，要真正解决代码错误地根源
- 不要帮我做git暂存/提交/推送等等修改操作
- 避免上下文爆炸：分析/修改代码时，一次只聚焦一个具体问题
  - 先读取最小必要代码，分析并解决当前问题，再继续下一个
  - 不要同时加载多个不相关的问题，避免反复读取大量文件导致上下文压缩循环
  - 每个问题处理完后，用简短总结标记进度，再进入下一个
- 环境路径映射规则
  - `/root/project/` 是只读挂载（宿主机项目目录映射到容器）
  - `batch_vlm` 压缩 `/root/project/` 下图片时，输出到 `storage.photo_path` 对应路径（默认 `./data/photos/`），保持原始目录结构
- 优先复用 pgo 代码库封装
  - `/root/code/pgo` 是本人维护的 Go 代码库，`pkg/` 下包含大量日常封装
  - 本项目通过 `go.work` 直接引用本地 pgo，而非 import GitHub 版本
  - 编码时优先使用 pgo 已有封装：
    - `pconfig` — 配置管理（TOML/YAML、环境变量覆盖、default tag、Scan 到结构体）
    - `plogger` — 基于 zap 的日志（console/json 模式、kratos 兼容）
    - `putil` — HTTP 请求封装（`NewHttpRequestJson`、`HttpDo`）、字符串/路径/时间工具
    - `papp` — Runner 模式（`RunRetry`、`RunInterval`、`RunTimeout`）
  - 如果发现 pgo 封装有缺陷或需要扩展，可以同步维护 pgo
- 输出 Markdown 文档时减少使用表格
  - 长文本内容会把表格撑得很宽，阅读体验差
  - 优先使用标题层级（## / ###）+ 无序列表（-）+ 缩进组织内容
  - 仅在数据对比（如配置参数对照）等真正适合表格的场景使用表格

## 文档索引

- [docs/PRD.md](docs/PRD.md) — 产品需求。一句话：让摄影照片库"会说话"的 AI Agent。面向摄影爱好者，核心能力是用自然语言检索照片、基于历史作品问答和激发创作思路。
- [docs/TECH_SPEC.md](docs/TECH_SPEC.md) — 技术方案。Dify + Go 双栈，Dify 负责 Agent 编排/知识库/聊天 UI，Go 负责业务后端/VLM 代理，零 Python/零前端框架。
- [docs/TASKS.md](docs/TASKS.md) — 3 天开发任务拆分。每天结束交付一个可运行的里程碑，Dify + Go 双栈。
- [docs/note.md](docs/note.md) — 决策备忘。记录被否定/推翻的技术栈和数据集方案，以及前期讨论归档。
- [docs/learn.md](docs/learn.md) — 技术学习笔记。
- [backend/test/backend_e2e.go](backend/test/backend_e2e.go) — Day1 E2E 测试程序。自动启停 server、调用全部 API、测试后清理数据。

## 当前状态

- [x] Day 1：Go 后端核心代码（路由/模型/配置/VLM/导入流水线）— 编译通过，健康检查可访问
- [ ] Day 2：查询 API + Dify 配置（工具/OpenAPI/Agent/知识库）
- [ ] Day 3：联调 + Docker Compose + 交付

### Day 1 已完成的模块

后端模块全部实现，编译通过，服务可启动：

**构建命令**（输出到 `./bin/`）：

- `make backend` — 编译 server 和 batch_vlm 到 `bin/`
- `make test-e2e` — 编译 E2E 测试程序到 `bin/e2e_test`
- `make clean` — 清理构建输出

- **API 路由**（Gin）：11 个端点，覆盖健康检查、照片 CRUD、时间线、标签、导入任务
  - 请求体字段统一使用下划线命名（如 `source_path`、`photo_path`）
- **数据层**（GORM + SQLite）：`Photo` / `ImportJob` 两表，自动迁移
- **配置管理**：复用 `pconfig`，TOML + 环境变量覆盖（`PHOTO_AGENT_*` 前缀）
  - 支持的环境变量：`PORT`、`DB_PATH`、`PHOTO_PATH`、`DESCRIPTIONS_PATH`、`TIMELINE_PATH`、`VLM_PROVIDER`、`VLM_API_KEY`、`VLM_MODEL`、`VLM_BASE_URL`、`DIFY_API_KEY`、`DIFY_BASE_URL`、`DIFY_DATASET_ID`
- **VLM 客户端**：纯 HTTP 实现（无 SDK），`volcengine` 走 Responses API，其他走 OpenAI Chat Completions API；调用前自动压缩图片为 JPG（ImageMagick `convert -resize 512x512> -quality 85 -format jpg`），`/root/project/` 下文件压缩后输出到 `PhotoPath` 对应路径，已存在则直接复用
  - 配置项：`vlm.max_image_size_mb`（浮点数，单位 MB）、`vlm.prompt`（自定义描述提示词）
- **导入流水线**：扫描 → 复用已压缩图片（或拷贝到 `data/photos/`）→ 读取预描述（`data/descriptions.json`）→ 根据 EXIF 拍摄时间匹配时间线 → SQLite → Dify 知识库
  - 并发控制：默认 3 并发
  - 无预描述时以空描述入库，不调用 VLM
  - 时间线从配置指定的 md 表格文件读取，根据拍摄时间匹配活动名称
- **批量 VLM 脚本**：`backend/cmd/batch_vlm/main.go`，独立运行，输出 `descriptions.json`
  - 参数：`-config`（指定配置文件）、`-l`（控制台日志开关）、`-force`（强制重做，清理已有压缩图和描述）
  - 去重：已有描述条目自动跳过并汇总数量；已有压缩图直接复用
- **Server 启动参数**：`-config`（指定配置文件）、`-l`（控制台日志开关，默认文件日志）
- **文件服务**：图片统一存储在 `data/photos/` 下，保持原始目录结构；压缩版本即为最终存储文件，server 导入时直接复用
- **E2E 测试**：`backend/test/backend_e2e.go`，可独立运行的测试程序
  - 自动在临时目录准备测试数据（图片、时间线 md、预描述 json）
  - 自动编译并启动 server 子进程，使用独立配置和数据库
  - 顺序测试全部 11 个 API 端点（健康检查、导入任务、照片、时间线、标签）
  - 测试完成后 kill server 并删除临时目录，不留测试数据
