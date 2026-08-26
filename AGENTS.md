# AGENTS.md — Photo Agent

> 项目定位：AI 选题助手，让摄影照片库"会说话"。
> 技术栈：Go（Gin+GORM+SQLite）+ Python（FastAPI+LangChain/Chroma）+ Vue 3（NaiveUI）。
> 开发模式：AI 辅助开发，用户作为"总指挥"。

---

## 全局行为约束

以下规则适用于所有工作模式：

- **减少 Markdown 表格**：优先用列表（`-`）组织内容。仅当表格每行内容可控制在 80 字符以内时才用表格（如 `docs/backlog.md` 的任务总览表）。宽表格在编辑器中阅读体验差
- **Mermaid 流程图方向**：默认 `flowchart TD`（向下）。当图中某一级存在超过 6 个平级节点时改用 `flowchart LR`（向右），让同级节点纵向排列获得更宽展示空间
- **方案选择**：存在多个可行方案时，先列出方案（含核心利弊）让用户选择，不要自行决定
- **单任务串行**：一个对话回合只沿一条线索推进一个任务。不要同时诊断两个 bug、同时提两个方案、同时问两个不相关的问题
- **避免上下文爆炸**：一次只聚焦一个具体问题，先读取最小必要代码，分析并解决后再继续
- **不要滥用 try catch** 处理代码问题，要真正解决代码错误的根源
- **根因优先**：本项目体量较小，遇到问题优先找根因并直接修复，而不是叠加容错/降级逻辑。典型反例：配置缺失时应直接指引用户补配置，而非加"配置不可用时的容错分支"
- **表间不用数据库外键**：表关联只用普通列做逻辑关联，由 service 层代码保证写入/清理的一致性，不建 FOREIGN KEY 约束。外键的强制性规则虽安全，但会限制删除顺序、增加迁移负担，降低宽容度；倾向表不约束、代码写完整，出现不一致就修复代码
- **配置文件读取**：调试配置相关问题时，可以读取 `.local/` 下的用户本地配置文件。但绝不能将隐私数据（API Key、密码等）写入会被提交到仓库的文件（config 模板中的占位符除外）
- **不要做 Git 暂存/提交/推送**等修改操作，用户自行管理版本控制
- **禁止遗留后台进程**：启动进程前先检查残留，禁止 `&` 或 `nohup` 后直接结束对话，对话结束前清理所有启动的进程
- **WEB 开发**：优先用 pnpm，无需启动 Dev Server 并抓取页面验证（改代码后用户自己启动）
- **代码提交信息**：产出代码后给简短中文 commit 信息，一行/一句话，符合 commitlint 规范
- **Go 工具链**：始终设 `GOTOOLCHAIN=local`，不使用 Go 自动 toolchain 下载
- **主动沟通**：发现阻塞性问题时，积极向用户说明情况并给出选择（如"方案 A：我加容错自动降级；方案 B：你补充配置，我给你具体指引"）。不要把问题默默记入 backlog 等用户自己发现
- **协作规则双文件同步**：`CLAUDE.md` 与 `AGENTS.md` 是 Codex 和 Claude 工作流共同使用的全局规则，内容必须始终保持一致。任一文件发生修改时，必须在同一轮同步修改另一文件；新增规则、索引和流程说明也必须同时维护两份文件
- **专题中枢文档**：当一个需求及其衍生需求跨越了多个提交、多次修改、多个文档记录时，应编写一份中枢文档（`docs/design/YYYY-MM-DD-<序号>-<topic>-hub.md`）集中串联所有关联产物。中枢文档包含：关联文档索引（设计/评估/backlog/提交）、完整时间线、各项完成度、下一轮建议。所有被关联的文档应在顶部反向链接到中枢文档，形成有顺序的链条。每次经过一轮评估/规划/生成后更新中枢文档

---

## 工作模式

AI 根据触发词自动切换模式。触发后，读取 `docs/handbook/work-modes.md` 中对应模式的完整流程执行。

- **评估模式** — 触发：`评估`、`评估一下`、`打分`、`检查质量`
  - 读：design/*、baseline.md、目标代码
  - 产出：评估报告（维度评分 + 得分点/失分点）+ backlog 新条目（仅描述问题，不写方案）
- **规划模式** — 触发：`规划一下`、`帮我设计`、`出个方案`、`怎么做`、`我发现问题`、`这里不够好`、`效果不对`、`有个 bug`
  - 读：backlog.md、prd.md、tech.md、note.md，涉及配置问题时读 `.local/` 实际配置文件
  - 产出：design/*.md、backlog 条目更新、任务列表（用户需执行的任务以 `（用户）` 前缀标记）
- **生成模式** — 触发：`按方案执行`、`开始开发`、`实现这个`、`完成开发`
  - 读：design/*.md、tech.md、coding-conventions.md
  - 产出：代码变更、backlog 条目更新
- **项目管理** — 触发：`版本归档`、`归档`、`里程碑`、`版本规划`、`迭代计划`
  - 读：backlog.md、archive/*
  - 产出：archive/*、backlog.md
- **全流程模式** — 触发：`完整走一遍`、`全流程`、`一站式`、`从头到尾`、`整个工作流`、`规划生成评估全流程`
  - 串联规划→生成→评估，适合小体量单会话任务
  - 读：backlog.md、目标代码
  - 产出：代码变更 + backlog 条目更新 + 轻量自检

**模式间交接**：通过 backlog 条目结构化字段（状态 / 背景 / 方案 / 分析 / 验收）传递信息。用户使用 `/clear` 清空上下文后切换角色，AI 读取 backlog + 相关文档即可继续工作。

**详细流程 + 路由规则 + 设计原则**：见 `docs/handbook/work-modes.md`。

---

## 文档层级

冲突时，优先以高层文档为准。修改时间更新者优先。

- **L1** `AGENTS.md` — 全局协作规则、文档索引、工作模式触发。与 `CLAUDE.md` 保持一致。禁区：产品需求、技术细节、任务进度
- **L1.5** `docs/handbook/work-modes.md` — 四种模式的完整流程、路由规则、handoff 协议
- **L1.5** `docs/handbook/eval-guide.md` — AI 评估模式操作指南（工具使用、检查流程）
- **L1.5** `docs/handbook/coding-conventions.md` — 各语言编码规范（Go/Python/Web/Markdown）
- **L1.5** `docs/handbook/doc-review.md` — 文档审阅规范（两版流程）
- **L2** `README.md` — 项目简介、核心价值、快速开始、文档索引。禁区：详细技术方案、任务拆解
- **L3** `docs/prd.md` — 产品"做什么"：功能范围、用户故事、验收标准、P0/P1/P2。禁区：API 设计、数据模型、部署命令
- **L4** `docs/tech.md` — "怎么做"：架构设计、API 契约、数据模型、技术选型。禁区：任务拆分、估时
- **L4** `docs/harness.md` — Harness 工程架构索引：工作模式、评估系统、Trace 日志的高层概览和文档入口。禁区：实现细节
- **L5** `docs/task_*.md` — 开发计划、每日里程碑、完成情况。禁区：产品需求定义、技术架构设计
- **L5** `docs/design/*-hub.md` — 专题中枢文档：串联同一需求及其衍生需求在多次评估/规划/生成轮次中散落的所有文档、评估报告、backlog 条目、提交记录。是专题的唯一入口
- **L6** `docs/note.md` — 被否决的方案、踩坑记录、决策变更历史。禁区：当前生效的方案
- **L6** `docs/eval/baseline.md` — 量化评估基线（RAG 检索 + 模块质量 + 管道正确性）
- **L7** `docs/backlog.md` — 产品演进路线图、Phase 规划、拒绝清单。禁区：API 设计、数据模型
- **L8** `docs/ui-rules.md` — 前端 UI 美学规则
- **L8** `docs/code_review.md` — 历史 code review 报告
- **L9** 代码实现 — 最终事实来源

---

## 环境路径映射

- `/root/project/`：只读挂载，资源的源数据/源文件一般在这里
- `/root/share/`：读写挂载，程序输出文件一般输出到这里，按程序功能做路径管理

---

## 文档索引

- [docs/prd.md](docs/prd.md) — 产品需求、用户故事、验收标准
- [docs/tech.md](docs/tech.md) — 架构设计、API 契约、数据模型
- [docs/backlog.md](docs/backlog.md) — 需求池、演进路线图、拒绝清单
- [docs/terminology.md](docs/terminology.md) — 项目专用名词和中英文命名
- [docs/note.md](docs/note.md) — 决策备忘、否决记录、踩坑记录
- [docs/deploy.md](docs/deploy.md) — 部署指南
- [docs/ui-rules.md](docs/ui-rules.md) — 前端 UI 美学规则
- [docs/harness.md](docs/harness.md) — Harness 工程架构索引
- [docs/handbook/work-modes.md](docs/handbook/work-modes.md) — 工作模式完整流程
- [docs/handbook/eval-guide.md](docs/handbook/eval-guide.md) — AI 评估模式操作指南
- [docs/handbook/coding-conventions.md](docs/handbook/coding-conventions.md) — 各语言编码规范
- [docs/handbook/doc-review.md](docs/handbook/doc-review.md) — 文档审阅规范
- [docs/eval/baseline.md](docs/eval/baseline.md) — 评估基线指标
- [docs/design/2026-08-01-topic-discovery-design.md](docs/design/2026-08-01-topic-discovery-design.md) — 主题发现统合设计文档
- [docs/design/2026-08-22-future-requirements.md](docs/design/2026-08-22-future-requirements.md) — 未来需求暂存（从 backlog 审阅迁出）
- [docs/design/](docs/design/) — 方案设计文档
- [docs/archive/v1.0.8.md](docs/archive/v1.0.8.md) — v1.0.8 版本归档（主题发现交互式管线）
- [docs/archive/v1.0.9.md](docs/archive/v1.0.9.md) — v1.0.9 版本归档（导入工作流 Windows 客户端）
- [docs/archive/v1.0.10.md](docs/archive/v1.0.10.md) — v1.0.10 版本归档（连拍分组与照片列表浏览）
- [docs/archive/](docs/archive/) — 已完成版本的归档
