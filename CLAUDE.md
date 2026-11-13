# CLAUDE.md — Photo Agent

> 项目定位：AI 选题助手，让摄影照片库"会说话"。
> 技术栈：Go（Kratos v2+GORM+SQLite）+ Python（FastAPI+LangChain/Chroma）+ Vue 3（NaiveUI）。
> 开发模式：AI 辅助开发，用户作为"总指挥"。

---

先读取[项目上下文](docs/harness/project-context.md)，按其中的实际路径和项目补充执行。

<!-- harness:begin -->
# Agent 工作入口

先读取 [Harness 总纲](docs/harness/top/HARNESS.md)，再按用户当前意图读取一个对应工作模式及相关任务。文档链接按用途选择，不递归加载整个目录。

## 工作入口

- 澄清需求、设计方案：[规划模式](docs/harness/top/mode-planning.md)。
- 执行已确认方案：[生成模式](docs/harness/top/mode-generation.md)。
- 审查产物、评分与反馈：[评估模式](docs/harness/top/mode-evaluation.md)。
- 版本归档、里程碑和 backlog 治理：[项目管理模式](docs/harness/top/mode-project-management.md)。
- 规划、生成与评估的连续流程：[全流程模式](docs/harness/top/mode-auto.md)。
- 修改 Harness 规则：[审批规则](docs/harness/top/RULES.md)与[外环维护](docs/harness/top/maintenance.md)。

## 专项入口

- 产品与 UI：分别读取 [PRODUCT_SENSE.md](docs/harness/PRODUCT_SENSE.md)、[FRONTEND.md](docs/harness/FRONTEND.md)。
- 软件设计与任务组织：分别读取 [DESIGN.md](docs/harness/DESIGN.md)、[PLANS.md](docs/harness/PLANS.md)。
- 安全、可靠性与长期评分：按任务读取 [SECURITY.md](docs/harness/SECURITY.md)、[RELIABILITY.md](docs/harness/RELIABILITY.md)、[QUALITY_SCORE.md](docs/harness/QUALITY_SCORE.md)。
- 代码修改：读取[通用代码规范](docs/harness/styles/code.md)，再选择 [Go](docs/harness/styles/golang.md)、[Python](docs/harness/styles/python.md)或 [TypeScript](docs/harness/styles/typescript.md)规范。
- 文档输出：读取[文档规范](docs/harness/styles/markdown.md)，再选择[产品规格](docs/harness/styles/product-spec.md)、[设计记录](docs/harness/styles/design-doc.md)、[架构说明](docs/harness/styles/architecture.md)、[记录](docs/harness/styles/record.md)或[参考资料](docs/harness/styles/reference.md)写法。
- Web 工具使用与验证：[Web 规范](docs/harness/styles/web.md)。

项目接入时保留项目自身的架构、运行与配置入口，按[接入规范](docs/harness/top/adoption.md)配置，避免复制多份规则正文。
<!-- harness:end -->

项目专属约束：

- **Design 文档门槛**：任务或需求需要记录的内容在 100 行以内时，不创建独立 `docs/design-docs/` 文档；方案、任务和验收仅记录在 backlog，完成后随版本归档进入 `docs/version/`。超过该篇幅且确有长期复用或跨轮串联价值时，才评估是否创建 design 文档
- **表间不用数据库外键**：表关联只用普通列做逻辑关联，由 service 层代码保证写入/清理的一致性，不建 FOREIGN KEY 约束。外键的强制性规则虽安全，但会限制删除顺序、增加迁移负担，降低宽容度；倾向表不约束、代码写完整，出现不一致就修复代码
- **真实数据与 LLM 回归**：允许只读使用真实数据做回归，禁止修改；如测试必须写入，测试结束后必须恢复数据原貌。调用真实 LLM 的回归用例必须放在独立目录，日常自动回归不得执行；仅当用户在当轮明确授权时才可执行，并在调用前说明实际消耗。


### 本项目附加层级

- **L6** `docs/note.md` — 被否决的方案、踩坑记录、决策变更历史。禁区：当前生效的方案
- **L8** `docs/code_review.md` — 历史 code review 报告

---

## 环境路径映射

- `/root/project/`：只读挂载，资源的源数据/源文件一般在这里
- `/root/share/`：读写挂载，程序输出文件一般输出到这里，按程序功能做路径管理

---

## 文档索引

- [docs/product-specs/photo-agent.md](docs/product-specs/photo-agent.md) — 产品需求、用户故事、验收标准
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — 当前架构、模块职责和数据流
- [docs/design-docs/system-design.md](docs/design-docs/system-design.md) — 详细技术设计、API 契约和数据模型
- [docs/backlog.md](docs/backlog.md) — 需求池、演进路线图、拒绝清单
- [docs/terminology.md](docs/terminology.md) — 项目专用名词和中英文命名
- [docs/note.md](docs/note.md) — 决策备忘、否决记录、踩坑记录
- [docs/deploy.md](docs/deploy.md) — 部署指南
- [docs/harness/FRONTEND.md](docs/harness/FRONTEND.md) — 前端交互原则与项目视觉规范
- [docs/harness/project-context.md](docs/harness/project-context.md) — 项目实际路径、约束与运行证据入口
- [docs/harness/top/HARNESS.md](docs/harness/top/HARNESS.md) — 工作模式完整流程
- [docs/harness/eval-guide.md](docs/harness/eval-guide.md) — AI 评估模式操作指南
- [docs/harness/styles/code.md](docs/harness/styles/code.md) — 各语言编码规范
- [docs/harness/styles/doc-review.md](docs/harness/styles/doc-review.md) — 文档审阅规范
- [docs/eval/baseline.md](docs/eval/baseline.md) — 评估基线指标
- [docs/design-docs/2026-08-01-topic-discovery-design.md](docs/design-docs/2026-08-01-topic-discovery-design.md) — 主题发现统合设计文档
- [docs/design-docs/2099-01-01-future-requirements.md](docs/design-docs/2099-01-01-future-requirements.md) — 未来需求暂存（从 backlog 审阅迁出）
- [docs/design-docs/](docs/design-docs/) — 方案设计文档
- [docs/version/](docs/version/README.md) — 版本记录与历史归档入口
