# Photo Agent

> 个人摄影资产 AI 助手。通过对摄影作品进行 AI 视觉描述、建立时间线与标签知识库、构建向量检索系统，让用户可以用自然语言与自己的照片库对话，实现智能检索、摄影档案问答和创作辅助。

## 项目定位

- **产品定位**：个人摄影资产 AI 助手
- **求职方向**：AI 应用开发 / AI Agent 开发
- **开发模式**：AI 辅助开发，用户作为"总指挥"，AI 负责具体编码和文档输出
- **技术栈**：Dify + Go 双栈。Dify 本地部署负责 Agent 编排、知识库 RAG、聊天 UI（图形化工作流可观测），Go 负责业务后端（照片元数据、文件服务、导入任务、VLM 代理、Embedding 代理），零 Python、零前端框架。
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
    - `pconfig` — 配置管理（TOML/YAML、default tag、Scan 到结构体）
    - `plogger` — 基于 zap 的日志（console/json 模式、kratos 兼容）
    - `putil` — HTTP 请求封装（`NewHttpRequestJson`、`HttpDo`）、字符串/路径/时间工具
    - `papp` — Runner 模式（`RunRetry`、`RunInterval`、`RunTimeout`）
  - 如果发现 pgo 封装有缺陷或需要扩展，可以同步维护 pgo
- 输出 Markdown 文档时减少使用表格
  - 长文本内容会把表格撑得很宽，阅读体验差
  - 优先使用标题层级（## / ###）+ 无序列表（-）+ 缩进组织内容
  - 仅在数据对比（如配置参数对照）等真正适合表格的场景使用表格
- 要识别任务类型，进而判断是否需要更新文档
  - 方案改动，包括我主动修改方案，或者因改动代码导致方案变化的，都应该自动更新对应文档内容
    - 方案改动较大，应该在对话中先简短描述方案改动点，确认后修改到文档中，再确认后进行代码修改
    - 方案改动不大，则无需对话先确认，直接修改文档，然后让我确认文档后，进行代码修改
    - 如果我主动说“全自动修改”等意思，那么就无需确认，直接完成所有修改
  - 方案不变，只是修改具体的代码实现

## 文档索引

- [docs/PRD.md](docs/PRD.md) — 产品需求。一句话：让摄影照片库"会说话"的 AI Agent。面向摄影爱好者，核心能力是用自然语言检索照片、基于历史作品问答和激发创作思路。
- [docs/TECH_SPEC.md](docs/TECH_SPEC.md) — 技术方案。Dify + Go 双栈。照片数据流：`batch_vlm` 预处理（生成 `descriptions.json`）→ `server` 启动自动同步到 SQLite + Dify 知识库，无需手动触发导入。
- [docs/TASKS.md](docs/TASKS.md) — 3 天开发任务拆分。每天结束交付一个可运行的里程碑，Dify + Go 双栈。
- [docs/note.md](docs/note.md) — 决策备忘。记录被否定/推翻的技术栈和数据集方案，以及前期讨论归档。
- [docs/learn.md](docs/learn.md) — 技术学习笔记。
- [docs/DIFY_SETUP.md](docs/DIFY_SETUP.md) — Dify 部署与配置指南。包含 docker-compose 启动、模型配置、Agent 创建、工具导入步骤。
- [docs/dify_tools_openapi.yaml](docs/dify_tools_openapi.yaml) — Dify 自定义工具 OpenAPI Schema，6 个工具指向 Go Backend API。
- [dify/dsl/photo-agent.yml](dify/dsl/photo-agent.yml) — Dify Agent DSL 文件。包含系统提示词、模型配置、工具绑定、知识库引用，可导入复现 Agent 配置。
- [dify/dsl/SKILL.md](dify/dsl/SKILL.md) — DSL 开发技能。涵盖 DSL 结构差异、Agent 工具配置、导入陷阱（InFailedSqlTransaction）与标准工作流程，含人工介入节点。
- [dify/SKILL.md](dify/SKILL.md) — Dify 自动化工作流技能。AI 主导 DSL 生成与 API 调用，但在环境依赖和副作用操作时必须停下来向用户汇报。
- [.claude/EXCALIDRAW_NOTES.md](.claude/EXCALIDRAW_NOTES.md) — Excalidraw 文件维护经验。index 格式安全范围、shape-text 双向绑定、boundElements 引用有效性等踩坑记录。

## 文档职责与冲突裁决

### 核心原则

- 按一下文档层级，优先以高层文档为准，向下修改内容
- 当冲突发生时，判断修改时间，以新修改的内容为准
- 处理冲突后需要向我报告冲突

### 文档层级（从高到低）

1. **本文件（README.md）**
   - 职责：项目定位、全局协作规则、文档索引、AI 行为约定
   - 当其他文档与 README 的协作规则/全局约定冲突时，以 README 为准

2. **docs/PRD.md — 产品需求**
   - 职责：定义产品"做什么"，包括功能范围、用户故事、验收标准、优先级（P0/P1/P2）
   - 不包含：具体 API 参数、CLI 命令、部署命令（这些属于技术/操作文档）
   - 当 TECH_SPEC 的技术方案无法满足 PRD 的功能需求时，优先满足 PRD，调整技术方案

3. **docs/TECH_SPEC.md — 技术方案**
   - 职责：定义"怎么做"，包括架构设计、API 契约、数据模型、技术选型
   - 不包含：执行进度、具体部署步骤（这些分别属于 TASKS 和 DIFY_SETUP）
   - 当代码实现与 TECH_SPEC 的 API 设计冲突时，以代码为准，更新 TECH_SPEC

4. **docs/TASKS.md — 任务拆分与进度**
   - 职责：开发计划、每日里程碑、完成情况、人工执行记录
   - 当任务执行结果与 PRD/TECH_SPEC 的设计有偏差时，在 TASKS 中记录实际执行情况，并视情况同步更新上游文档

5. 实际的代码实现

6. **docs/USAGE.md — 部署操作手册**
   - 职责：从零到可聊天的完整操作步骤
   - 当操作步骤与代码实际参数冲突时，以代码为准（例如 init_dify 的启动参数）

开发任务拆分和进度记录在 [docs/TASKS.md](docs/TASKS.md)。Day 1（Go 后端核心）、Day 2（查询 API + Dify 配置）、Day 3（联调 + Docker Compose + 交付）已完成。当前为迭代优化阶段，主要工作包括：server 启动自动同步、`descriptions.json` 嵌入 EXIF 拍摄时间、时间线日期解析与匹配优化。

**构建命令**：

- `make backend` — 编译全部二进制到 `bin/`
- `make clean` — 清理构建输出
