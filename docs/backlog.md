# Backlog

> 全部技术需求池，按序号排列。状态流转：`待规划` → `规划中` → `已规划` → `WIP` → `待用户验收` → `Done`。暂缓任务已确认当前不执行。

## 任务总览

> 表头不能随意修改，即使表格清空了，也要保留表头，保留一个空表。

| 状态   | 分组       | 编号  | 任务                                         | 评估 |
| ------ | ---------- | ----- | -------------------------------------------- | ---- |
| 待规划 | 对话查询   | CQ7   | 聊天 SQL 日期过滤未换算本地时区              |      |
| 暂缓   | 代码治理   | BQ3   | 未鉴权服务暴露任意 SQL 查询                  |      |
| 已取代 | 对话查询   | CQ4   | 创作型查询（Compose）专用管线                |      |

> v1.0.16 已归档：AR、AR1–AR10、TIDY5–TIDY7、CFG8、NAV1、OBS1、GQ1、EVAL1，详见 [v1.0.16](archive/v1.0.16.md)。
> v1.0.15 已归档：PS10、BQ1–BQ2、BQ4–BQ6、BQ8–BQ11、DOC2、TIDY1–TIDY4、CFG1–CFG7，详见 [v1.0.15](archive/v1.0.15.md)。
> v1.0.14 已归档：CQ1–CQ3、CQ5、CQ6、AQL2-1、AQL2-2，详见 [v1.0.14](archive/v1.0.14.md)。
> 其余 6 项待规划任务经审阅后迁至 [未来需求暂存](design/2099-01-01-future-requirements.md)。

### CQ7 聊天 SQL 日期过滤未换算本地时区

- **状态**：待规划
- **背景**：真实库 `shot_at` 混合 UTC(+00:00) 与本地(+08:00) 偏移，聊天链路 text-to-SQL 的 few-shot 示例仍使用裸 `DATE(shot_at)`，跨午夜日期的过滤存在最多 8 小时语义漂移。AR9 已在 Runtime 范围 SQL 中经 `localtime` 修正并经真实库验证，聊天独立管线未同步。
- **严重程度**：P2，跨午夜日期的查询可能多出或漏掉一天的照片，不影响数据完整性。
- **证据**：[Agent Runtime 专题中枢](design/2026-08-31-2-agent-runtime-hub.md) §1 当前遗留；[v1.0.16 归档](archive/v1.0.16.md) 已知边界与后续入口。

### BQ3 未鉴权服务暴露任意 SQL 查询

- **状态**：暂缓
- **背景**：默认服务全局调用 `SetIgnoreAuth`，同时注册了接收调用方 SQL 文本的 QueryService。当前服务监听全部网络接口；虽使用只读数据库连接，调用方仍可读取任意可访问表和元数据。
- **严重程度**：P0，未授权数据访问风险。
- **证据**：[后端代码质量基线评估](eval/reports/2026-08-29-backend-code-quality-baseline.md)。
- **方案**：当前开发阶段保留 `SetIgnoreAuth` 与自由只读 SQL 查询，不改变接口、监听方式或开发调试效率。将风险、启动条件和后续收敛方向迁入 FR-11；当服务需要被非受信任网络、多人或真实用户访问时，必须先恢复鉴权并收紧查询能力，再继续发布。
- **验收**：FR-11 可独立追溯本决策及后续启动条件；BQ3 不进入当前开发队列。

### CQ4 创作型查询（Compose）专用管线

- **状态**：已取代（2026-08-31，由 AR 承接）
- **背景**：「找山西旅游第一天的照片并生成发布文案」这类“选照片 + 做发布内容”的请求未被现有四条路由准确承接。用户期望确定性流程：SQL 查候选 → 连拍去重 → LLM 挑选发布照片并生成标题文案；候选过多时逐级收缩，最终引导用户进图文工坊自选。
- **分析**：分类器对同一请求会落入 `tool` 或 `combined`，说明需独立类别；照片表、连拍组、时间线和图文工坊深链的数据基础已具备。
- **方案**：详见 [创作型查询设计](design/2026-08-28-1-compose-query-design.md)。新增第五类 `compose` 路由和确定性候选管线，按连拍组折叠、两级阈值收缩后交由 LLM 挑选并创作；超限时给出携带候选照片的图文工坊深链；以 `[compose]` 记录各阶段条目数。
- **取代说明**：专用管线不再作为独立形态验收。连拍折叠、两级收缩、超限深链逻辑在 AR2 迁移为 Runtime 挑选临时能力；原定的山西请求人工验收并入 AR6 验收。Compose 两个阈值配置继续复用。
- **关单说明（2026-08-31）**：AR2 已完成迁移（`agent/runtime/capabilities.py` 的 `collapse_burst_candidates` / `prepare_select_candidates` / `select_token` / `select_photos`），`_compose_node` 专用管线已删除，原单测断言全部迁入 `tests/test_runtime_capabilities.py`。CQ4 正式关闭，不再有独立交付物。

## 产品定位决策

**从**：“个人摄影资产 AI 助手”（泛化，容易堆砌技术）
**到**：「AI 选题助手」，AI 像员工提案，用户像主编审阅。

核心 workflow：拍摄→入库→AI 定期推送选题建议（推荐照片组合 + 发角度）→用户判断选哪个、如何微调→用户自己发布。

**主动不做的事**：

- 不自动发布到社交平台（发送由用户操作）
- 不替代审美判断（AI 推荐，用户决策）
- 不做多模态检索/以图搜图（选题场景不需要）

## 拒绝清单

- 混合检索、RAG 重排序、本地 Embedding、异步后台同步、Prometheus 监控
- proto-first 迁移、语音输入、多语言支持、负样本学习优化

## 决策历史

- **2026-09-02**：v1.0.16 归档。完成 Agent Runtime 多步执行全链路（AR 系列 11 项）、agent 工程治理（TIDY5–TIDY7）、价格配置故障隔离（CFG8）、过程反馈与日志 Trace 关联（AR8/OBS1）、黄金用例语义收紧（GQ1）、导航恢复（NAV1）与归档前检查规则（EVAL1），共 20 项任务；聊天 SQL 时区漂移登记为 CQ7 待规划；BQ3 继续暂缓，CQ4 已取代关闭。
- **2026-09-02**：TIDY7 执行。coding-conventions.md 通用规范新增「同级同构（宽泛指引）」与锚点「调用参数同级同构」（宽泛原则与可执行锚点两层结构，宽泛条目自带作用域限定：只对齐局部、不主动重构存量）；随后按用户指令对 agent/ 存量做一次扫描重构，10 处多行匿名位置 dict 提取命名，219 测试全绿。
- **2026-08-31**：CFG8 规划。价格表保持严格校验，但其故障隔离为成本追踪降级，不能再阻断主题发现、聊天和检索；Runtime 在价格不可用时停用成本上限，继续以步数和超时保障执行边界。
- **2026-08-31**：TIDY6 三次追加：功能包套父目录 `internal/`，形成 `cli → internal → infra` 三层金字塔（类 Go cmd/internal/pkg 映射），internal 内功能包之间禁止互相 import；tech.md 的 agent 结构记录收敛到目录粒度，文件级职责唯一载体为 agent/README.md。
- **2026-08-31**：TIDY6 追加顶层净化：入口文件集中到 `cli/`（类 Go cmd；目录名弃 `cmd` 取 `cli`，避免遮蔽 Python 标准库 cmd 模块），`config.py` 下沉 `infra/`，agent 顶层只保留工程管理文件（makefile / pyproject.toml / uv.lock / README）。
- **2026-08-31**：TIDY6 执行中新增 import 风格规则：项目内模块禁止 `from xxx import <符号>`，统一 Go 式限定调用（`import pkg.module as alias` + `alias.func()`），标准库与第三方例外；规则落在 coding-conventions.md 导入规范，agent/README.md 目录规范章节同步引用。
- **2026-08-31**：TIDY6 方向确认。agent 目录重组采用 package by feature（chat/topics/posts/runtime/evals/infra + 顶层入口），否决数字前缀方案（Python 模块名禁止数字开头，import 语法错误）；依赖方向规则（入口 → 功能包 → infra 单向）随重组写入 agent/README.md 作为目录规范。
- **2026-08-31**：TIDY5 agent 目录整理。退役文件（学习性 demo、一次性脚本、过期 smoke、backend-sdk codegen 脚手架）按原相对路径移入 `agent/bak/` 待手动删除，不直接物理删除；新增 `agent/README.md` 作为目录职责总览入口。166 个测试通过，无需用户操作。
- **2026-08-31**：AR 主体开发完成待验收。新增 `agent/runtime/`（框架无关核心 + LangGraph 外壳），入口 classify 增加 runtime 类别承接原 compose 开放目标，CQ4 专用管线删除、其折叠/收缩/深链逻辑迁入 select_photos 能力；预算键落在 Agent 段（RuntimeMaxSteps/TimeoutSeconds/CostLimit，缺省 12/300/2.0）；tracer 增加 runtime 步骤事件与轨迹摘要；前端标签补 runtime。166 个测试全量通过。
- **2026-08-31**：AR 规划，Agent 从单发路由升级为 Agent Runtime V1。编排底座定为 LangGraph 只做 Runtime 外壳（decide/execute/reduce/check 循环图），TaskState、状态归约、完成检查、预算、能力注册表保持框架无关；CQ4 compose 专用管线由 AR 取代关闭，其折叠/收缩/深链逻辑迁移为挑选临时能力，山西案例验收并入 AR6。
- **2026-08-30**：v1.0.15 归档。完成草稿编辑输入恢复、后端质量治理与关键用户路径闭环、公共文档对齐、工具和运行数据整理、配置契约收敛，共 22 项任务；BQ3、CQ4 继续暂缓，分别受 FR-11 与真实环境验收条件约束。
- **2026-08-30**：BQ1 以“后端代码质量基线评估与问题拆分”范围关单。活动 SQLite 库已确认不含四个旧 AI 状态列，BQ2 改为删除一次性迁移代码；BQ3 按开发阶段决策暂缓并迁入 future requirements；BQ4–BQ6、BQ8 的技术方案和验收已补充至各自 backlog 条目。
- **2026-08-29**：新增 BQ1，建立长期使用的后端代码质量 100 分制标准并接入评估模式；后续以独立逻辑单测、Service 集成测试和关键用户用例闭环组合验证，不以 100% 单元测试覆盖率为目标。
- **2026-08-28**：v1.0.14 归档。完成对话查询链路诊断与修复及资产审核收尾，共 7 项任务；同期确立验证流单向、人工验收即终态的关单规则。
