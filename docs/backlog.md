# Backlog

> 全部技术需求池，按序号排列。状态流转：`待规划` → `规划中` → `已规划` → `WIP` → `待用户验收` → `Done`。暂缓任务已确认当前不执行。

## 任务总览

> 表头不能随意修改，即使表格清空了，也要保留表头，保留一个空表。

| 状态   | 分组       | 编号  | 任务                                         | 评估 |
| ------ | ---------- | ----- | -------------------------------------------- | ---- |
| Done   | Agent Runtime | AR4-1 | 会话上下文构建器：历史选择、压缩与引用     | 8.4  |
| Done   | Agent Runtime | AR4-2 | 跟进消息识别与入口全路径接入               | 8.2  |
| Done   | Agent Runtime | AR4-3 | Runtime 任务快照与多轮局部失效续跑         | 8.4  |
| Done   | Agent Runtime | AR4-4 | V4 多轮金用例与评估基线                     | 8.3  |
| 待规划 | Agent Runtime | AR4-5 | 真实 LLM 环境下跟进识别与消解质量未验证     |      |
| 待规划 | Agent Runtime | AR4-6 | 长程指代的上下文充分性退化                  |      |
| 待规划 | Agent Runtime | AR4-7 | 补选语义保留无确定性保障                    |      |
| 已取代 | Agent Runtime | AR16  | 会话多轮连续性缺失（展开为 AR4-1–AR4-4）   |      |
| 已取代 | Agent Runtime | AR17  | 对话历史无选择与压缩（展开为 AR4-1–AR4-4） |      |
| 待规划 | Agent Runtime | AR18  | 入口分类封闭集，新开放目标静默降级         |      |
| 暂缓   | 代码治理   | BQ3   | 未鉴权服务暴露任意 SQL 查询                  |      |

> v1.0.18 已归档：AR3-1–AR3-8，以及拆分为 AR3 系列后关闭的 AR15，详见 [v1.0.18](archive/v1.0.18.md)。
> v1.0.17 已归档：AR2-1–AR2-7、CQ7、DL1、AR11–AR14、HARN1，以及已取代的 CQ4，详见 [v1.0.17](archive/v1.0.17.md)。
> v1.0.16 已归档：AR、AR1–AR10、TIDY5–TIDY7、CFG8、NAV1、OBS1、GQ1、EVAL1，详见 [v1.0.16](archive/v1.0.16.md)。
> v1.0.15 已归档：PS10、BQ1–BQ2、BQ4–BQ6、BQ8–BQ11、DOC2、TIDY1–TIDY4、CFG1–CFG7，详见 [v1.0.15](archive/v1.0.15.md)。
> v1.0.14 已归档：CQ1–CQ3、CQ5、CQ6、AQL2-1、AQL2-2，详见 [v1.0.14](archive/v1.0.14.md)。
> 其余 6 项待规划任务经审阅后迁至 [未来需求暂存](design/2099-01-01-future-requirements.md)。

### AR4-1 会话上下文构建器：历史选择、压缩与引用

- **状态**：Done
- **背景**：AR17。会话消息在 `session_store` 中只作为展示数据持久化，推理链路从未读取，全仓不存在历史选择、压缩、摘要逻辑。
- **方案**：新增框架无关纯模块 `internal/context/`（package by feature，输入为纯消息字典列表，不 import 其他功能包）。输入会话历史 + 当前问题，输出结构化会话上下文：近期窗口原文保留（默认最近两组问答）、更早轮次压缩为单行摘要（用户问题原样 + 回答首行 + 照片数）、照片等大对象只保留 ID 引用不进上下文、总长度有硬上限；约束优先级为当前用户消息 > 更早轮次硬约束原文 > 摘要。产物供入口路由与跟进识别消费。
- **验收**：选择（窗口内外区别处理）、压缩（长会话输出有界）、引用（照片详情不进入上下文）、优先级（当前要求不被摘要覆盖）四类单测；空会话、单轮、长会话边界覆盖。
- **实施记录**（2026-09-07）：`internal/context/builder.py` 落地，逐项截断（轮数 + 单条 + 照片引用上限）自然有界，未引入额外总长截断分支；`tests/test_context_builder.py` 9 项通过。
- **评估**：8.4（正确性 8.5 健壮性 8.0 可维护性 8.5 简洁性 8.5），详见 [2026-09-07-ar4-v4-planning-context](eval/reports/2026-09-07-ar4-v4-planning-context.md)

### AR4-2 跟进消息识别与入口全路径接入

- **状态**：Done
- **背景**：AR16 路由侧 + AR18 最小跟进识别切片。每条消息独立走七类封闭分类，"刚才那组""不要那么文艺"等指代与追加修改被当全新请求处理。
- **方案**：入口分类节点在会话有历史时注入 AR4-1 的紧凑历史块，分类标签增加 `followup`（跟进消息不走七类，AR18 切片）；命中 followup 后由独立的消解调用输出改写后的独立完整问题、目标路径与受影响部分（改写问题供下游消费）。`RouterState` 增加 `effective_question`，SQL/RAG/Tool/Combined/Runtime 五条下游路径统一改消费 `effective_question`（首条消息等于原问题，单轮行为不变）。无历史的会话分类行为与提示词完全不变。
- **验收**：mock LLM 下验证 followup 分支路由与 effective_question 传递；首条消息路径回归不变；五条路径各自的 effective_question 消费有单测。
- **实施记录**（2026-09-07）：`_classify_node` 有历史分支 + `_followup_resolve_node` 消解节点 + 条件边接入路由图；五路径经 `_effective_question` 统一消费；消解显式声明的目标类型与快照不一致时按声明目标全新执行（`runtime_goal_declared` 区分分类默认值）；server `send_message` 与 CLI `sessions resume` 完成接线；`tests/test_followup_routing.py` 16 项 + server 接线回归通过。
- **评估**：8.2（正确性 8.5 健壮性 8.0 完整性 8.0 一致性 8.5），详见 [2026-09-07-ar4-v4-planning-context](eval/reports/2026-09-07-ar4-v4-planning-context.md)

### AR4-3 Runtime 任务快照与多轮局部失效续跑

- **状态**：Done
- **背景**：AR16 执行侧 + V4 文档「多轮修改如何运行」。修改类跟进（"还是用刚才第二组，但不要那么文艺，再补两个不同场景"）目前只能按全新任务重跑，有效产物不保留。
- **方案**：`session_store` 新增 `runtime_task_snapshots` 表（session_id 逻辑关联，无外键），Runtime 结束时保存任务快照；`state.py` 提供任务状态的序列化/反序列化往返（经目标契约校验重建）。`run_runtime` 增加 `prior_task` 续跑入口：保留权威范围、已确认事实、照片缓存与仍有效的产物；按消解结果局部失效（受影响里程碑重新入待办、对应产物作废，未受影响部分保留）；用户约束合并时当前消息优先。既有澄清续跑管道（runtime_pending_clarifications）保持不变。跨任务 Memory（长期偏好）不在本轮，等多次会话证据。
- **验收**：序列化往返一致性；续跑保留有效产物、失效部分重开；约束合并且当前优先；快照 CRUD；澄清续跑回归不变。
- **实施记录**（2026-09-07）：`dump_task`/`load_task`/`resume_task`（受影响部分词汇表 scope/selection/copy/report/topics，选片或文案失效均作废旧文案以防完成要件瞬间满足）落 `state.py`；`run_runtime` 返回 `task_dump` 与 `goal_type`；快照表 CRUD 与会话删除清理落地；澄清续跑路径不读快照、不注入历史，行为与 V3 一致；`tests/test_runtime_resume.py` 14 项通过。
- **评估**：8.4（正确性 8.5 健壮性 8.0 Constraint Retention 9.0 Multi-turn Task Success 8.5），详见 [2026-09-07-ar4-v4-planning-context](eval/reports/2026-09-07-ar4-v4-planning-context.md)

### AR4-4 V4 多轮金用例与评估基线

- **状态**：Done
- **背景**：V4 验收（Context Sufficiency / Context Utilization / Constraint Retention / Multi-turn Task Success）需要可重复的锚定证据；Planner 两维度（Plan Executability / Replan Precision）按 2026-09-07 决策等长任务证据，本轮不评。
- **方案**：图级 mock 金用例覆盖多轮修改主线（选片发帖 → 跟进改文案 → 跟进补选重写）与跟进识别消解；全量离线回归纳入；`docs/eval/baseline.md` 登记 V4 维度基线，由单测锚定、可重复生成。
- **验收**：金用例断言完整轨迹（保留与失效两侧都要断言）；基线条目落地；Agent 全量离线测试通过。
- **实施记录**（2026-09-07）：金用例四条（改文案 1 决策完成、补选重写、快照 JSON 往返主线、换范围全链路重跑）落在 `tests/test_runtime_resume.py`；[评估基线](eval/baseline.md) 已登记 V4 四维度条目；Agent 全量离线 369/369 通过（V4 新增 42 项），未调用真实 LLM。
- **评估**：8.3（Context Sufficiency 8.0 Context Utilization 8.5 完整性 8.0），详见 [2026-09-07-ar4-v4-planning-context](eval/reports/2026-09-07-ar4-v4-planning-context.md)

### AR4-5 真实 LLM 环境下跟进识别与消解质量未验证

- **状态**：待规划
- **背景**：AR4-2 的 followup 分类与跟进消解提示词仅有离线替身断言（注入契约与输出解析），真实会话中指代展开是否准确、受影响部分声明是否合理、把新问题误判为 followup 的比例均无证据。评估报告将其列为准确性维度的主要失分点。
- **严重程度**：P1，多轮体验的真实质量取决于此；执行受真实 LLM 回归授权约束（参照 AR2-7/AR3 惯例）。
- **证据**：[AR4 第一轮评估](eval/reports/2026-09-07-ar4-v4-planning-context.md)。

### AR4-6 长程指代的上下文充分性退化

- **状态**：待规划
- **背景**：Context Builder 的更早轮次摘要只保留用户问题原文、回答首行与照片计数；3 轮以前交付的选片组在历史块中没有 ID 引用，「用刚才第二组」类指代在长会话中无法展开为具体所指，消解只能凭问题原文猜测。
- **严重程度**：P2，近窗口（最近两组）内的指代不受影响，仅长会话退化。
- **证据**：[AR4 第一轮评估](eval/reports/2026-09-07-ar4-v4-planning-context.md)。

### AR4-7 补选语义保留无确定性保障

- **状态**：待规划
- **背景**：AFFECT_SELECTION 续跑保留旧 selected_ids 并在决策提示词中可见，但新的选片观察按归约规则整体替换入选集合；补选场景旧照片是否保留完全依赖选片模型是否遵循改写请求中的保留指令，没有程序性保障。
- **严重程度**：P2，金用例已断言状态可见性，语义保留属模型行为层。
- **证据**：[AR4 第一轮评估](eval/reports/2026-09-07-ar4-v4-planning-context.md)。

### AR16 会话多轮连续性缺失，每条消息独立执行（已取代）

- **状态**：已取代（2026-09-07 V4 规划展开为 AR4-1–AR4-4，随 AR4 系列关闭）
- **背景**：同一会话内每条消息都是无状态独立工作流。`send_message` 仅将当前问题（或澄清续跑拼接串）传入 `agent.route()`，`RouterState` 无历史字段，SQL/RAG/Tool/Combined/Runtime 五条下游路径全部只消费当前 `question`；请求契约 `SendMessageRequest` 也仅 `question + granularity`。会话内指代（"刚才那组"）、追加修改（"不要那么文艺"）全部按全新请求处理。唯一例外是 Runtime 澄清续跑单槽（AR11 遗产），只覆盖相对日/时间线歧义一种场景。
- **证据**：[V0–V3 目标达成回顾](eval/reports/2026-09-07-v0-v3-goal-retrospective.md)。

### AR17 对话历史无选择与压缩，上下文仅当前问题（已取代）

- **状态**：已取代（2026-09-07 V4 规划展开为 AR4-1–AR4-4，随 AR4 系列关闭）
- **背景**：会话消息在 `session_store` 中只作为展示数据持久化，推理链路从未读取；全仓不存在任何针对对话历史的选择、压缩、摘要逻辑（现存的"摘要"均为照片描述提取、状态签名、SQL 结果格式化）。由于历史不进入上下文，有策略的压缩无从谈起，缺的是整条链路。
- **证据**：[V0–V3 目标达成回顾](eval/reports/2026-09-07-v0-v3-goal-retrospective.md)。

### AR18 入口分类封闭集，新开放目标静默降级

- **状态**：待规划
- **背景**：入口为一次性 LLM 分类器，输出七类封闭标签（sql / rag / tool / combined / runtime_post / runtime_comparison / runtime_topics），未命中时静默兜底到 `rag`；Runtime 目标空间固定三种（social_post / photo_comparison / topic_discovery）。不属于既有类别的新开放请求（如废片整理、年度报告）会被降级为单步检索或误配目标契约，用户得不到"系统不认识该目标"的信号。注意：这是 V3 设计文档明示的兼容性边界（刻意取舍），但开放目标侧确实没有出口。修正一点：匹配是 LLM 分类而非字面关键词，泛化能力强于规则匹配，问题在结构不在形式。
- **严重程度**：P2，单步请求走封闭类别+兜底是合理设计（V5 也保留）；缺口仅在开放目标侧扩展性与可感知性。
- **归属**：V4/V5 完成后独立评估（2026-09-07 决策）。V4 多轮落地时会被迫触及入口的最小跟进识别切片（跟进消息不走七类分类），该切片归 V4，不改变 AR18 整体延后。
- **证据**：[V0–V3 目标达成回顾](eval/reports/2026-09-07-v0-v3-goal-retrospective.md)。

### BQ3 未鉴权服务暴露任意 SQL 查询

- **状态**：暂缓
- **背景**：默认服务全局调用 `SetIgnoreAuth`，同时注册了接收调用方 SQL 文本的 QueryService。当前服务监听全部网络接口；虽使用只读数据库连接，调用方仍可读取任意可访问表和元数据。
- **严重程度**：P0，未授权数据访问风险。
- **证据**：[后端代码质量基线评估](eval/reports/2026-08-29-backend-code-quality-baseline.md)。
- **方案**：当前开发阶段保留 `SetIgnoreAuth` 与自由只读 SQL 查询，不改变接口、监听方式或开发调试效率。将风险、启动条件和后续收敛方向迁入 FR-11；当服务需要被非受信任网络、多人或真实用户访问时，必须先恢复鉴权并收紧查询能力，再继续发布。
- **验收**：FR-11 可独立追溯本决策及后续启动条件；BQ3 不进入当前开发队列。

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

- **2026-09-07**：V4 第一轮规划/生成/评估闭环完成，总分 8.3/10（循环目标 8.0 达成）。AR4-1 至 AR4-4 全部 Done：历史经 Context Builder 进入推理链路、followup 识别与消解接入五路径、Runtime 任务快照支持局部失效续跑、四条多轮金用例与 V4 基线落地；Agent 离线全量 369/369（V4 新增 42 项），未调用真实 LLM。评估登记 AR4-5（真实环境验证）、AR4-6（长程指代退化）、AR4-7（补选保留无确定性保障）待规划。详见 [评估报告](eval/reports/2026-09-07-ar4-v4-planning-context.md)。

- **2026-09-07**：V4 第一轮规划完成。AR16/AR17 展开为 AR4-1（会话上下文构建器）、AR4-2（跟进消息识别与全路径接入）、AR4-3（Runtime 任务快照与多轮局部失效续跑）、AR4-4（多轮金用例与评估基线）；AR16/AR17 标记已取代。Planner/Replan 全量实现与跨任务 Memory 按 2026-09-07 范围决策延后，本轮多轮续跑中的待办重开即最小 replan 切片。架构依据见 [V4 Planning + Context](design/architecture/06-photo-agent-v4-planning-context.md)。

- **2026-09-07**：v1.0.18 归档。归档 AR3-1–AR3-8，以及拆分为 AR3 系列后关闭的 AR15，共 9 项，版本主题为 Agent Runtime V3 能力系统；V0–V3 目标回顾报告随版本存档引用；AR16–AR18 留存待规划，BQ3 继续暂缓。

- **2026-09-07**：V4/V5 推进顺序确认。按架构版本顺序做 V4 再 V5；AR16/AR17 是 V4 的内容本体，随 V4 规划展开为 AR4-x 系列，不独立成版本、不延后补做；AR18 延后至 V4/V5 完成后独立评估（V4 多轮只需入口的最小跟进识别切片，归 V4）。V4 第一轮范围倾向以 AR16/AR17（Context/Memory/多轮）为主，Planner 部分等长任务证据出现再启用（遵循"复杂度必须由证据购买"）。

- **2026-09-07**：V0–V3 目标达成回顾完成。四个版本退出条件均判定达成（8.0/10）；对话能力三项核验属实（无多轮连续性、无历史压缩、入口封闭分类+兜底），登记 AR16、AR17、AR18 待规划，作为进入 V4/V5 的输入；详见 [回顾报告](eval/reports/2026-09-07-v0-v3-goal-retrospective.md)。

- **2026-09-07**：V3 能力系统完成规划。AR15 不再以笼统父任务保留，按可独立交接和验收的 AR3-1（目标契约）、AR3-2（能力分层）、AR3-3（跨期对比第二目标）、AR3-4（主题发现 Workflow）与 AR3-5（评估基线）展开；架构决策见 [V3 Capability System](design/architecture/05-photo-agent-v3-capability-system.md)，专题链路已同步至 Runtime 中枢。

- **2026-09-07**：AR3-1–AR3-5 完成。Runtime 按目标契约筛选能力与观察，Capability 注册表完成 Tool/Skill/Workflow 契约迁移；接入只读跨期对比目标和范围化主题发现 Workflow。离线全量回归 305/305 通过，未执行真实数据或真实 LLM 回归。

- **2026-09-07**：v1.0.17 归档。归档 AR2-1–AR2-7、CQ7、DL1、AR11–AR14、HARN1，以及已取代的 CQ4，共 14 项完成任务；BQ3 暂缓，AR15 后续拆分为 AR3 系列。

- **2026-09-03**：V2 第二批开发关单（AR2-3、AR2-4、AR2-5，均为 AI 自动验收）。guardrail 落地为 execute 与 reduce 之间的程序节点，按「状态 → 策略」映射执行有界恢复（重试/修复/再决策，恢复预算键 RuntimeRetryMax/RepairMax/RedecideMax），恢复不消耗步数但计入时长成本且预算先行检查；无进展检测以四维状态签名 3 步窗口两级响应（先换策略反馈、仍无进展停止）；语义质量门（选片代表性 + 文案事实依据）在确定性检查通过后按能力声明触发，不通过带反馈修复、耗尽以 quality_gate_failed 停止，完成要件不变；SDK（urllib3）连接失败补入瞬时异常族。Agent 全量单测 282/282 通过。
- **2026-09-03**：V2 第一批开发关单（AR2-1、AR2-2、AR2-6，均为 AI 自动验收）。SQL 校验器接受 WITH 只读 CTE 查询；观察新增六态 status 维度且失败观察强制显式归类；时间线多匹配走澄清并复用 AR11 续跑管道。Agent 全量单测 239/239 通过。
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
