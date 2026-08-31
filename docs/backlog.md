# Backlog

> 全部技术需求池，按序号排列。状态流转：`待规划` → `规划中` → `已规划` → `WIP` → `待用户验收` → `Done`。暂缓任务已确认当前不执行。

## 任务总览

> 表头不能随意修改，即使表格清空了，也要保留表头，保留一个空表。

| 状态   | 分组       | 编号  | 任务                                         | 评估 |
| ------ | ---------- | ----- | -------------------------------------------- | ---- |
| Done   | Agent 升级 | AR    | Agent Runtime V1：状态化多步执行             | 8.2  |
| Done   | Agent 升级 | AR1   | Runtime 核心语义（框架无关）                 |      |
| Done   | Agent 升级 | AR2   | Runtime 能力层接入                           |      |
| Done   | Agent 升级 | AR3   | Runtime 编排接入与入口路由                   |      |
| Done   | Agent 升级 | AR4   | Runtime 追踪与评估                           |      |
| Done   | Agent 升级 | AR5   | Runtime 入口配置注入修复                     |      |
| Done   | Agent 升级 | AR6   | Runtime 真实闭环验收与候选详情修复           | 8.2  |
| Done   | Agent 升级 | AR7   | Runtime 非终止能力失败会反复消耗预算         |      |
| Done   | 代码治理   | TIDY6 | agent 目录按功能分包重组（方案 B）           | 8.5  |
| Done   | 配置治理   | CFG8  | 价格配置故障隔离，核心功能可用               | 8.7  |
| Done   | 前端导航   | NAV1  | 恢复组图发现入口                             | 8.5  |
| Done   | 代码治理   | TIDY5 | agent 目录整理（退役文件移入 bak/ + README） | 8.4  |
| Done   | 运行治理 | OBS1  | Agent 日志格式与 Runtime Trace 关联不完整    |      |
| Done   | 对话查询   | GQ1   | 非 RAG 回答可保存为黄金用例                  |      |
| Done   | Agent 升级 | AR8   | Runtime 多步执行缺少用户可理解的过程反馈     | 8.31 |
| 已规划 | Agent 升级 | AR9   | Runtime 检索硬约束失守且未阻止错误交付       |      |
| Done   | Agent 升级 | AR10  | Runtime 最终回复入选照片展示文件名而非 ID    |      |
| Done   | 工作流治理 | EVAL1 | 归档前阶段合理性专项检查规则                 |      |
| 暂缓   | 代码治理   | BQ3   | 未鉴权服务暴露任意 SQL 查询                  |      |
| 已取代 | 对话查询   | CQ4   | 创作型查询（Compose）专用管线                |      |

> v1.0.15 已归档：PS10、BQ1–BQ2、BQ4–BQ6、BQ8–BQ11、DOC2、TIDY1–TIDY4、CFG1–CFG7，详见 [v1.0.15](archive/v1.0.15.md)。
> v1.0.14 已归档：CQ1–CQ3、CQ5、CQ6、AQL2-1、AQL2-2，详见 [v1.0.14](archive/v1.0.14.md)。
> 其余 6 项待规划任务经审阅后迁至 [未来需求暂存](design/2099-01-01-future-requirements.md)。

### NAV1 恢复组图发现入口

- **状态**：Done（2026-08-31，用户验收确认）
- **背景**：用户无法从侧栏进入用于展示视觉聚类结果的「组图发现」页。`ClusterView.vue`、`/cluster` 路由、Agent 的聚类计算/结果查询 API 和结果存储均仍在，直接访问 `#/cluster` 可进入现有页面。
- **分析**：根因是 2026-08-24 的侧栏重排：提交 `4e90a6d` 将时间线和黄金用例移入底部、加入图文工坊和草稿管理时，旧侧栏中的「组图发现」菜单项及 `GitNetworkOutline` 图标导入被一并移除；路由的当前选中逻辑却保留，说明这是导航遗漏，不是聚类功能下线。组图发现（视觉相似聚类）与主题发现（编辑选题提案）语义不同，现有设计文档也明确要求两者保持独立。
- **方案**：恢复独立的「组图发现」导航，沿用现有 `/cluster` 路由与网络节点图标，不改聚类页面、数据、接口或结果存储。入口放在侧栏底部固定区：紧随「黄金用例」，位于「设置」之前；同步保持 `/cluster` 的当前选中态。该位置由用户于 2026-08-31 确认。
- **实施任务**：
  - 在侧栏恢复组图发现图标依赖和底部固定入口，排列为“时间线 → 黄金用例 → 组图发现 → 设置”。
  - 运行前端类型检查与生产构建，确认导航改动未影响现有页面。
- **验收**：侧栏存在可见入口；点击后打开现有组图发现页面，可加载历史聚类结果并可发起聚类；主题发现入口和其他导航行为不回归。
- **实施记录（2026-08-31）**：在 `SideMenu.vue` 恢复 `GitNetworkOutline`，并在底部固定区按“时间线 → 黄金用例 → 组图发现 → 设置”的顺序加入「组图发现」入口；复用既有 `/cluster` 路由及选中态逻辑，未改动聚类页面或后端。
- **（用户）验收操作**：刷新或重启前端，在侧栏底部点击「组图发现」。
- **预期结果**：入口位于「黄金用例」下方、「设置」上方；点击后打开组图发现页并正常显示历史聚类结果。
- **最小回传**：回复“NAV1 已通过”。
- **AI 自动验证**：`pnpm build` 通过，已完成 Vue TypeScript 类型检查和 Vite 生产构建。
- **关单方式**：用户回复确认后，AI 在同一轮将任务改为 `Done` 并注明确认日期，不追加核验。
- **关单记录（2026-08-31）**：用户确认 NAV1 已通过。

### CFG8 价格配置故障隔离，核心功能可用

- **状态**：Done（2026-08-31，用户验收确认）
- **背景**：`prices.yaml` 格式或模型映射错误时，`PhotoAgent` 在 FastAPI 应用创建阶段严格加载并校验价格表，异常直接终止 Agent 服务启动；主题发现页面因此无法加载历史和生成数据。价格表仅服务于 Token 用量观测及 Runtime 的成本预算，不应成为主题发现、聊天和检索等核心功能的可用性前提。
- **分析**：价格配置本身仍需严格校验，不能静默按零成本记录；问题在于把辅助观测配置的失败提升为整个服务的启动失败。Runtime 的成本预算依赖可靠价格，配置失效时不可继续以不准确成本触发预算判断。
- **方案**：在 Agent 初始化边界隔离价格配置故障。保留价格表的完整结构与启用模型校验；校验失败时记录可定位的告警和“成本追踪不可用”状态，仍创建可处理主题发现、聊天和检索请求的服务实例。Token 用量记录明确标识为不含成本；Runtime 仅在价格可用时启用成本上限，价格不可用时保留步数和超时预算并在日志/追踪中说明成本预算已停用。健康检查或诊断入口暴露该降级状态，供页面与运维定位配置问题。
- **实施任务**：
  - 调整 Agent 初始化与价格追踪的边界，形成可查询的价格配置可用状态和统一告警。
  - 让 Runtime 按价格状态决定是否启用成本预算，避免错误地将未知成本视为零。
  - 补充价格文件缺失、YAML 损坏、结构无效、模型价格缺失四类自动测试；验证正常价格配置仍启用成本累计与成本预算。
  - 补充服务构造/健康诊断测试，确认价格配置异常时主题发现相关服务仍可创建并对外说明降级原因。
- **验收**：价格配置正常时，现有成本追踪和 Runtime 成本预算行为不变；价格配置异常时，Agent 可启动、主题发现页面仍能加载历史并发起生成，日志或诊断明确显示价格配置错误与成本追踪降级；自动测试覆盖正常和四类异常边界。
- **实施记录（2026-08-31）**：
  - `PhotoAgent` 将价格文件读取、格式校验和启用模型校验隔离为辅助能力；异常时记录降级原因，继续完成服务初始化。
  - Token 用量表新增 `cost_tracked` 标记，价格不可用时仍保留 Token 用量但明确成本未追踪，CLI 汇总不会把未知成本显示为零。
  - Runtime 配置链路新增价格可用状态，异常时停用成本上限，步数与超时上限保持生效；`runtime.check` trace 记录 `cost_budget_enabled`。
  - `GET /api/chat/health` 返回 `pricing_available` 与 `pricing_error`，可直接诊断降级原因。
  - 自动验证：`agent/.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`，170/170 通过；覆盖价格文件缺失、YAML 损坏、结构无效、模型价格缺失、服务健康诊断、成本标记和 Runtime 成本预算正常/降级分支。
- **（用户）验收操作**：临时将 `.local/my-config.yaml` 的 `Prices.Path` 改为一个不存在的文件，重启 Agent 后打开主题发现页面并加载或生成一次选题；确认后恢复原路径并重启。
- **预期结果**：价格错误以“Token 成本不追踪，Runtime 成本预算已停用”的告警出现，`/api/chat/health` 的 `pricing_available` 为 `false` 且包含错误原因；主题发现历史仍可加载，选题请求不因价格配置失败而报服务不可用。
- **最小回传**：回复“CFG8 已通过”；若失败，贴出 Agent 启动日志中价格告警后的报错片段。
- **AI 自动验证**：170/170 单测通过，已覆盖全部可自动验证的正常和异常分支。
- **关单方式**：用户回复确认后，AI 在同一轮将任务改为 `Done` 并注明确认日期，不追加核验。
- **关单记录（2026-08-31）**：用户确认 CFG8 已通过。

### EVAL1 归档前阶段合理性专项检查规则

- **状态**：Done（2026-08-31，文档规则已落地）
- **背景**：常规评估以单任务功能和质量评分为主，容易遗漏跨任务形成后的日志可追溯性、输入输出语义边界和多步任务等待体验；但把这类检查放入每个任务收尾会造成不必要的流程负担。
- **方案**：仅在用户明确准备版本归档时，对本次全部 `Done` 条目执行阶段合理性专项检查；当任务总览中除明确不执行状态外均为 `Done` 时，AI 只主动询问一次是否需要该检查。专项检查覆盖可观测性、产物语义边界、长任务体验、验证闭环和阶段适配，仍只登记问题不设计修复方案。
- **实施任务**：
  - 在评估指南写明专项检查的触发条件、必查项、阶段边界和一次性主动提醒规则。
  - 在项目管理模式写明“先评估、再由用户决定是否归档”的路由关系。
- **验收**：普通任务收尾不会自动进入专项检查；用户明确要求归档前评估时会执行完整检查；全部可执行任务 Done 时仅主动询问，不自动评估或归档。
- **实施记录（2026-08-31）**：已更新 `docs/handbook/eval-guide.md` 与 `docs/handbook/work-modes.md`，并定义 `暂缓`、`已取代`、`已拒绝` 为主动提醒时的明确不执行状态；用户暂缓后等待任务总览变化或用户再次主动提出归档才可重复询问。
- **AI 自动验证**：交叉核对评估指南、项目管理流程和本条触发/验收语义一致。

### OBS1 Agent 日志格式与 Runtime Trace 关联不完整

- **状态**：Done（2026-08-31，用户验收确认）
- **背景**：`logs/agent.log` 同时写入 Make 命令和普通打印、应用日志、Uvicorn 启动与 access 日志。应用日志有时间、模块和等级，但没有源文件和行号；Uvicorn 使用另一种格式。Runtime 虽另有可重放 JSONL trace，聊天接口返回的 `trace_id` 没有在会话消息或页面中保留。
- **严重程度**：P1，当前运行链路可用，但一次 Runtime 请求的诊断信息分散且难以稳定定位、关联。
- **证据**：[当前阶段合理性专项评估](eval/reports/2026-08-31-current-stage-rationality.md)。
- **分析**：根因不是 Runtime 未产出轨迹，而是运行日志、Trace 和会话三套载体各自独立：启动脚本把混合标准输出重定向到同一文件，Python 应用与 Uvicorn 又各自配置格式；`trace_id` 虽在即时响应中返回，却未写入会话消息，前端刷新后无从关联。现有 JSONL Trace 已满足步骤重放，不应再引入额外观测平台或重复存储完整轨迹。
- **方案**：将 Agent 服务运行日志收敛为独立、统一字段的 JSONL 文件，覆盖应用、Uvicorn 启动和 access 记录，并包含时间、等级、模块、事件/消息、源文件位置及可用时的 `trace_id`；启动脚本的控制台输出不再与该文件混写。聊天请求创建 Trace 后，将其作为请求上下文贯穿应用日志；回复消息持久化 `trace_id`，会话读取与即时响应保持一致，聊天页在每条 AI 回复的元信息中展示可识别的轨迹编号。Trace 本体继续只保留在现有执行轨迹目录，页面不复制大体积事件内容。
- **实施任务**：
  - 建立 Agent 服务统一日志配置与请求级 Trace 上下文，统一应用、Uvicorn 启动/access 的 JSONL 字段和源位置；调整启动日志去向，隔离 Make/控制台杂讯。
  - 扩展会话消息的 SQLite 迁移、写入和读取，持久化聊天回复的 `trace_id`；同步 API 响应和前端类型/会话状态。
  - 在聊天回复元信息展示轨迹编号，使刷新或重新进入会话后仍可把结果、运行日志与已有 JSONL Trace 对上。
  - 增加服务日志格式、Trace 上下文、会话迁移/持久化和前端消息呈现测试；验证旧会话可正常读取且轨迹字段为空时不影响页面。
- **验收**：一次 Runtime 请求的应用日志、Uvicorn access 记录和 Trace 事件可按同一 `trace_id` 关联；JSONL 每行均含统一基础字段与源文件位置，运行日志不再混入 Make 命令；刷新会话后，AI 回复仍显示与响应一致的轨迹编号；旧会话兼容读取；新增自动测试覆盖上述边界。
- **实施记录（2026-08-31）**：
  - 服务启动时将应用与 Uvicorn 启动日志统一写入 `logs/agent.jsonl`；每行均包含时间、等级、模块、事件、消息、源文件位置和 Trace 编号。聊天请求的 access 记录由服务中间件写入同一 JSONL，避免 Uvicorn 默认 access 格式混入。
  - 顶层启动脚本继续将开发期 Make/控制台输出写入既有 `logs/agent.log`；结构化服务日志独立写入 `logs/agent.jsonl`，不与控制台杂讯混写。
  - 会话消息 SQLite 自动迁移 `trace_id` 列。聊天请求创建 Trace 后，应用日志、Trace JSONL、即时响应和持久化 AI 回复共用该编号；聊天页面回复元信息展示“轨迹 <编号>”，旧消息为空时不展示。
  - 自动验证：Agent 单测 179/179 通过（含 JSONL 基础字段与 Trace 上下文、旧会话迁移及 Trace 持久化）；前端 Vitest 9/9 通过、`pnpm build` 通过。
- **（用户）验收操作**：启动 Agent 后，在聊天页发起一条 Runtime 请求并刷新该会话。
- **预期结果**：该 AI 回复显示轨迹编号；`logs/agent.jsonl` 中可按该编号找到应用和 `http.access` 记录，`data/agent/execution-traces/` 中可找到同编号 Trace；开发期控制台输出仍保留在 `logs/agent.log`。
- **最小回传**：回复“OBS1 已通过”；若失败，贴出同一轨迹编号附近的 `agent.jsonl` 两行。
- **AI 自动验证**：已完成单测、前端测试和生产构建；未启动常驻服务，真实 Uvicorn 启动链路保留给本次人工验收。
- **关单方式**：用户回复确认后，AI 在同一轮将任务改为 `Done` 并注明确认日期，不追加核验。
- **关单记录（2026-08-31）**：用户确认 OBS1 已通过。

### GQ1 非 RAG 回答可保存为黄金用例

- **状态**：Done（2026-08-31，自动验收通过）
- **背景**：聊天页只要 AI 回答带照片就显示“保存为黄金用例”。Runtime 多步任务返回的是选片和文案产物，也会出现该入口；SQL、Combined 等非纯 RAG 路由同样没有被排除。黄金用例当前用于单张 RAG 的 P@10/R@10/MRR，混入创作或其他路由结果会使检索评估样本失去固定语义。
- **严重程度**：P1，功能表面可用，但评估数据会被错误的交互引导逐步污染。
- **证据**：[当前阶段合理性专项评估](eval/reports/2026-08-31-current-stage-rationality.md)。
- **分析**：黄金用例的当前数据模型和评估器只定义了“查询文本 → RAG 相关照片”的单一语义，尚未实现 SQL、Combined、路由或 Runtime 的独立标注结构和指标。以“是否附带照片”决定保存资格，把输出形态误当成评估语义，是污染入口的根因。
- **方案**：将聊天页的“保存为黄金用例”入口收紧为仅 `rag` 路由的带照片回答；SQL、Tool、Combined、Runtime、错误和历史缺失路由类型的消息均不显示该入口。后端黄金用例 API 仍保持既有 RAG 数据契约，不为未定义指标的路由伪造兼容字段。入口条件抽为明确的路由语义判断，并以组件测试锁定，后续若要评估其他路由，需先单独定义对应标注模型和指标。
- **实施任务**：
  - 在聊天视图按消息的 `query_type` 判断黄金用例保存资格，仅为纯 RAG 且有照片的 AI 回复显示入口。
  - 保持黄金用例创建 API、JSON 格式和 RAG 评估器不变，避免将非 RAG 产物写入现有检索基线。
  - 补充前端消息元信息测试：RAG 有照片时可保存，Runtime/SQL/Combined/Tool/错误及旧消息均不可保存；运行前端类型检查和生产构建。
- **验收**：仅 RAG 照片回答显示“保存为黄金用例”；Runtime、SQL、Combined 和 Tool 的带照片回答不显示该入口；现有黄金用例创建和评估无回归；新增前端测试覆盖允许与拒绝边界。
- **实施记录（2026-08-31）**：将保存资格提炼为明确的路由语义判断，仅允许带照片的 RAG 助手回复显示入口；黄金用例 API、JSON 数据和 RAG 评估器未改动。
- **AI 自动验证**：新增前端测试覆盖 RAG 有/无照片、Runtime、SQL、Combined、Tool、错误和历史缺失路由；Vitest 9/9 通过，`pnpm build` 通过；Agent 单测 179/179 通过。

### AR8 Runtime 多步执行缺少用户可理解的过程反馈

- **状态**：Done（2026-09-01，用户验收确认）
- **专题中枢**：[Agent Runtime 专题中枢](design/2026-08-31-2-agent-runtime-hub.md)
- **背景**：真实山西 Runtime 请求约耗时 98 秒，页面全程只显示“思考中...”与 spinner，并禁用输入。用户无法判断当前正在解析旅行、检索、选片还是生成文案，也无法从页面关联 Runtime 轨迹。
- **严重程度**：P1，短查询的等待方式可接受，但开放目标多步执行的等待体验不符合已具备 Trace 能力的当前阶段。
- **证据**：[当前阶段合理性专项评估](eval/reports/2026-08-31-current-stage-rationality.md)。
- **分析**：Runtime 已在循环内稳定产出 `decide / execute / observe / check` 事件，缺口在同步 HTTP 请求完成前这些事件无法抵达浏览器。仅在前端猜测阶段或按固定时间轮换文案会产生与实际执行脱节的假进度；必须由实际 Runtime 事件驱动。当前单用户场景不要求断线续跑或取消能力，无需为此引入后台任务、任务状态存储和轮询协议。
- **方案**：采用单请求 SSE 流式反馈。聊天请求开始后保持现有同步执行语义：服务端识别到 `runtime` 路由时，立即推送任务已进入多步处理；Runtime 每次真实 `decide / execute / observe / check` 后，将事件归约为用户过程快照，并在最终结果前持续推送。快照按“第 N 步”组织，包含易懂的阶段标题、当前状态、决策意图、执行结果和必要的数量/已确认事实；例如“匹配时间线 → 已确认山西旅游”“查询照片 → 找到 20 张候选”“挑选代表照片 → 连拍已折叠，选出 6 张”“生成发布文案”。动作、参数、观察和检查仍以现有 Trace 为事实源；新增纯翻译层集中维护能力名、观察结果到用户语言的映射，禁止由前端猜测进度。

  聊天页为 Runtime 回复创建默认收起的“执行过程”面板。执行中实时追加或更新步骤，完成后与最终答案、照片一起成为该回复的一部分；展开后可查看每一步的决策原因、已确认事实、候选/入选数量和完成/停止结果。技术细节置于步骤内的二级“执行细节”区域，默认也收起：可展示实际 SQL、结构化查询条件、调用的能力和数量统计；不展示日志原文、系统提示词、完整照片 ID 列表、模型原始输出或内部异常堆栈。服务端将轻量过程快照随助手消息持久化，使刷新和重新进入会话仍能回看；JSONL Trace 继续承担完整调试与重放，不复制大体积内容。
- **实施任务**：
  - 定义 Runtime 过程快照及其用户语言翻译边界：按步骤聚合决定、执行、观察与检查事件；为时间线匹配、SQL/RAG/混合检索、照片详情、连拍折叠与选片、文案生成、超限引导及失败/预算停止提供准确、可读的标题、结果和可选技术细节。
  - 在 Runtime 与聊天入口之间增加进度事件通道，复用同一真实事件同时写 Trace 和推送快照；聊天 `POST` 改为 SSE 事件序列，覆盖已受理、Runtime 开始、步骤更新、最终结果和错误。非 Runtime 查询仍走同一接口并只接收最终结果，不生成过程面板。
  - 扩展会话消息的 SQLite 迁移、写入、读取和聊天类型，持久化 Runtime 的轻量过程快照；与 OBS1 的 `trace_id` 持久化在同一次迁移中保持兼容，旧消息无快照时正常显示。
  - 改造前端请求解析为 `fetch` 流读取：Runtime 开始时在当前等待回复上实时渲染步骤，最终事件原子落为既有答案/照片/元信息。新增默认收起的过程面板和步骤内二级执行细节，完成后仍可展开回看；短查询不显示该面板。
  - 增加后端翻译器、SSE 事件顺序/异常终态、会话快照持久化和旧库迁移测试；增加前端 SSE 解析及 Runtime/非 Runtime 条件渲染测试，并运行 Agent 全量测试、前端类型检查和生产构建。
- **验收**：真实 Runtime 请求在等待期间按实际执行步骤实时显示用户可理解的过程，顺序与 Trace 一致且不出现定时伪进度；过程面板默认收起，展开后可回看决策、执行结果和受控的技术细节；SQL 等必要细节可展开查看但不会暴露日志原文、提示词、完整 ID 列表或堆栈；最终答案和照片行为不回归，刷新会话后过程仍可回看；非 Runtime 查询不出现过程面板；SSE、翻译、持久化、前端渲染和回归测试全部通过。
- **实施记录（2026-08-31）**：聊天发送接口改为单请求 SSE。`accepted` 后仅在真实 Runtime 进入循环时发送 `runtime.started`，随后将每个 `decide / execute / observe / check` Trace 事件归约为同一份用户步骤快照，最后发送 `final` 或 `error`。快照仅含阶段、状态、决策意图、结果、确认事实以及受控查询条件/SQL 等细节，不含日志原文、提示词、照片 ID 列表或异常堆栈。Runtime 最终步骤随助手消息写入 SQLite，旧消息读取为空数组。前端以 fetch 流解析 SSE，仅 Runtime 显示默认收起的“执行过程”与二级“执行细节”。
- **AI 自动验证**：Agent 全量测试 185/185 通过，覆盖 Runtime 快照翻译、事件顺序、终态、SQLite 迁移与持久化及控制台日志格式；前端 Vitest 11/11 通过，覆盖 SSE 分段解析和非正常帧；`pnpm build` 通过。
- **验收中追加（2026-08-31）**：Agent 服务新增与后端一致的 `-l` 控制台日志开关。`make dev` 默认携带该参数，控制台输出紧凑文本（时间、级别、模块、Trace、消息，末尾附源文件和行号）；控制台和 `logs/agent.jsonl` 的源码位置均收敛为“最后一级目录/文件名:行号”，不写绝对路径，JSONL 继续供生产日志平台使用。
- **（用户）验收操作**：重启前端后在聊天页发送“找山西旅游第一天的照片并生成发布文案”，等待期间观察“执行过程”面板（应自动展开并逐条增加步骤，无需手动展开），完成后刷新该会话；再发送一个普通 RAG 查询。
- **预期**：面板从任务开始即自动展开，Runtime 步骤按真实执行持续逐条出现、与轨迹顺序一致，不再长时间只有 loading 后一次性出现；终态后气泡内排列为“执行过程（收起）→ 回复 → 相关照片”，过程可手动展开回看，技术细节不泄露内部日志/ID；最终答案与照片正常，刷新后过程仍在；普通查询没有过程面板。
- **最小回传**：回复“AR8 验收通过”或描述一个可见异常。
- **关单记录（2026-09-01）**：用户确认 AR8 验收通过，含实时重绘修复与“执行过程 → 回复 → 照片”展示顺序（与 AR10 回归修复同一次山西请求验证）。
- **验收反馈（2026-08-31）**：用户确认最终过程内容可接受，但在执行期间页面持续显示 loading，直到最终回复才一次性出现过程。该现象不满足“真实步骤实时显示”的验收条件，本条不关单。
- **补充分析**：服务端 Runtime 事件和 SSE 事件序列已有单元测试，但前端把 `runtime.started` 时加入响应式数组的消息保留为普通对象，后续 `runtime.step` 与 `final` 继续修改该普通对象。数组实际渲染的是 Vue 转换后的代理对象，普通对象修改不会触发视图更新；最终 `isLoading` 改变触发一次重绘，才使全部内容同时可见。默认收起的过程面板也进一步削弱了执行期间的可见性。
- **补充方案**：过程消息创建后始终通过响应式数组中的对象更新；Runtime 执行期间自动展开过程面板，任务终态后恢复默认收起。增加以逐帧 SSE 输入验证 DOM 增量更新的前端测试，而不只测试解析器和最终状态。
- **补充验收**：一次真实 Runtime 请求中，首个 `runtime.started` 后立即出现过程容器；每个后续 `runtime.step` 到达后无需等待 `final` 即可在界面观察到新增或更新的步骤；完成后答案、照片和历史回看不回归。
- **补充实施记录（2026-09-01）**：
  - 过程消息在 push 进响应式数组后重新取回数组内的 Vue 代理对象，后续 `runtime.step` / `final` 一律通过代理更新，步骤变化即时触发视图重绘，不再依赖 `isLoading` 变化时的一次性重绘。
  - 过程面板从 ChatView 抽为 `RuntimeProcessPanel` 组件：Runtime 执行期面板出现即自动展开（0 步时显示“正在规划任务...”占位），终态后恢复默认收起；历史回看与普通查询保持默认收起。
  - 新增前端测试决策（用户委托 AI 评估）：比较 happy-dom（轻量、启动快，选定）、jsdom（更完整但更重更慢）、vitest browser mode（需 Playwright + 浏览器二进制，过重）、@vue/test-utils（公开 `createApp().mount()` 已够用）；最终仅新增 happy-dom 一个 dev 依赖，且以 per-file 注解只让新测试运行在 DOM 环境。
  - 新增 `useChat.spec.ts` 逐帧 SSE DOM 增量测试：首个 `runtime.started` 即出现展开的过程容器、每个 `runtime.step` 无需等待 `final` 即在 DOM 增量出现、`final` 后答案落位并恢复收起、非 Runtime 查询不出现面板；负向自检确认保留旧写法时该测试失败。
- **调序追加（2026-09-01，用户要求）**：执行过程面板移至消息气泡首位，执行期间与终态后均排列为“执行过程 → 回复 → 相关照片”，与流式展示的时间顺序连贯；面板分隔线从上方改为下方（隔开过程与回复），测试壳同步该顺序并在终态断言面板先于回复内容。
- **AI 自动验证**：前端 Vitest 13/13 通过（含 2 个逐帧 DOM 新测试）、`pnpm build`（vue-tsc 类型检查 + Vite 生产构建）通过。本轮仅改前端，Agent 侧无变更。

### AR9 Runtime 检索硬约束失守且未阻止错误交付

- **状态**：已规划（2026-09-01 方案细化）
- **专题中枢**：[Agent Runtime 专题中枢](design/2026-08-31-2-agent-runtime-hub.md)
- **问题档案**：[Runtime 检索约束幻觉问题全记录](design/2026-09-01-1-runtime-constraint-hallucination.md)（问题、讨论决策、方案方向、实施与效果持续更新）
- **背景**：山西发帖请求的真实执行中，时间线已解析为“山西”，但第 2 步 SQL 将“太原植物园、黄昏、植物”等仅用于叙事补充的信息混入筛选条件，得到 `rows=0`。第 3 步又在结构化过滤为空时回退到全库 RAG，候选不再受“山西旅游第一天傍晚”限制；最终仍选图并生成了带有“太原植物园”的确定性文案。
- **严重程度**：P0，返回照片和文案均可能与用户明确要求不符，且 Runtime 将错误路径判定为完成。
- **分析**：这是由 LLM 生成 SQL 引入了不具备数据库表达条件的软提示，继而由混合检索的通用“空结果回退纯 RAG”策略丢弃硬约束所共同造成的约束幻觉/语义失守，不是单条 SQL 语法错误。完成检查当前只验证“已有入选照片和文案”，未验证这些产物是否仍属于用户硬约束确定的候选集，因此没有任何环节阻止交付。
- **方案**：语义与修复方向详见问题记录。2026-09-01 规划确认两个决策：约束解析与范围物化放在**循环内能力**（不引入循环外预处理）；Runtime 的 hybrid_search **保留并收紧**（聊天 combined 路由是独立实现，不受影响）。技术方案：
  - **约束解析能力**：resolve_trip 扩展为约束解析能力。一次 LLM 调用同时抽取时间线提示、天序（第一天/最后一天/具体日期/无）、时段词（清晨/上午/中午/下午/傍晚/夜晚）、软提示清单（地点、景物、氛围等）；程序校验：时间线沿用现有确定性名称匹配，时段按程序内固定映射表转小时窗（如傍晚=17–19 点），非法值按“无该约束”处理不终止。时间线被提及但匹配不上时维持现有确定性终态。
  - **权威范围物化**：能力内由程序按校验后的结构化条件拼装范围 SQL（只含硬约束：时间线 + 天序 + 小时窗）并执行，物化为权威候选范围写入任务状态；locate 里程碑语义从“定位旅行”变为“确认范围”。抽不出任何硬约束时范围标记为“不受限”（全库），不做交集强制。范围为空（受限但 0 张）时进入新的确定性终态，向用户说明条件与放宽建议，禁止后续选片与文案。
  - **归约层统一交集**：候选类观察在归约时与权威范围求交集（范围受限时）。软提示检索（sql/rag/hybrid 的 query）命中数为零时，候选保留为整个范围，即软提示只影响范围内排序，永远不能清空或替换范围。
  - **检索能力收紧**：sql_search 在范围建立后 query 只承载软提示；hybrid_search 删除“SQL 为空/过宽/交集为空 → 采用全库 RAG”的替代语义，改为范围内语义排序，不命中时返回范围本身；rag_search 为范围内候选排序，RAG 失败不替换范围。decide 提示词同步改写，不再鼓励把已确认事实塞进检索 query。
  - **完成检查与交付阻断**：selected_photos 要件在范围受限时增加“入选 ⊆ 权威范围”判定；select_photos 对 LLM 挑选结果做范围归属校验；范围外入选被阻断时进入可解释失败，不生成带确定性地点/场景断言的文案。
  - **过程与 Trace**：Trace 与过程面板记录范围条件及来源、范围数量、软提示用途、交集与阻断原因；进度翻译器提供范围步骤标题与空范围终态的用户语言（如“确认候选范围 → 山西旅游第一天傍晚，共 N 张”/“未找到符合条件的照片”）。
- **实施任务**：
  - 任务状态层：任务状态新增权威范围结构（结构化条件 + 物化 ID 集 + 是否受限）；新增范围类观察的归约规则；候选类观察归约时与范围求交集；空范围确定性终态及最终输出的用户说明；状态摘要与最终输出呈现范围信息。
  - 能力层：resolve_trip 扩展为约束解析能力（抽取 + 校验 + 范围 SQL 物化，SQL 由程序拼装不经 LLM）；sql/rag/hybrid 按上述语义收紧；select_photos 增加范围归属校验。
  - 检查层：完成检查增加范围归属判定，范围外入选阻断交付。
  - 编排与翻译层：decide 提示词改写（硬约束已入范围、query 只写软提示）；runtime 事件扩展范围字段；进度翻译器新增范围步骤与终态文案。
  - 测试：更新现有 resolve_trip/hybrid 断言；新增确定性测试覆盖山西用例（范围 SQL 只含硬约束、软提示不入 WHERE、最终照片全在范围内）、空范围终态（不调全库 RAG、不选片、不写文案）、RAG 返回范围外结果被交集过滤、范围内 RAG 重排、范围外入选阻断、无硬约束不受限路径。
- **验收**：同一山西请求中，SQL 权威候选范围只由“山西 + 最早日期 + 傍晚时间段”决定，太原植物园等信息不导致候选归零；所有最终照片均在该范围内。若范围确实为空，Runtime 明确结束并说明没有符合条件的照片，不调用全库 RAG 选图或生成虚构地点文案；日志/过程面板能说明范围、软提示用途和阻断原因；自动测试覆盖所有边界。

### AR10 Runtime 最终回复入选照片展示文件名而非 ID

- **状态**：Done（2026-09-01，AI 自动验证关单）
- **专题中枢**：[Agent Runtime 专题中枢](design/2026-08-31-2-agent-runtime-hub.md)
- **背景**：山西发帖的真实回复末尾“入选照片：”列出的是 UUID 形式的照片 ID。该行由程序在最终输出组装时拼接（不是 LLM 文案内容），对用户不可读。
- **分析**：`build_final_output` 直接拼接 `selected_ids`。文件名只在能力执行时的详情对象里；真实决策顺序（检索 → 挑选 → 文案）不保证先执行 fetch_photo_details，挑选能力内部临时拉取的详情也不写回状态缓存，因此最终组装时缓存中通常没有入选照片的文件名。
- **方案**：挑选观察 payload 携带入选照片的 `{id, filename}` 最小详情；归约时写入 `photo_cache`（不覆盖已有完整详情，保持有界淘汰）；`build_final_output` 按入选顺序展示文件名，缓存缺失时回退照片 ID。
- **实施记录（2026-09-01）**：`select_photos` 观察新增 `photos` 字段；`_apply_photos_selected` 并入缓存并抽出共用的 `_trim_photo_cache`；最终输出经 `_selected_photo_labels` 优先取文件名。前端与 SSE 无需改动（photos 缩略图列表本就独立传输）。
- **回归与修复（2026-09-01，用户报告）**：首版把最小 `{id, filename}` 摘要写入 `photo_cache`，而 `_cached_photos` 的缓存语义是“命中即完整详情”，`write_post` 缓存全部命中后拿到无 `description` 的残缺记录，被图文工坊判定“所选 N 张照片都还没有 AI 描述”并终止（照片实际有 AI 描述）。修复：挑选观察携带完整详情记录（挑选时详情就在手），归约按完整记录并入缓存；新增“挑选观察必须含 description”断言与“挑选后 write_post 直接用缓存完整详情走真实 generate_post”回归测试，负向自检确认残缺 payload 下测试失败。
- **AI 自动验证**：Agent 全量单测 188/188 通过。下次山西请求的回复末尾将显示文件名，且不再出现误报的缺描述终止。
- **关单记录（2026-09-01）**：用户重发山西请求验证通过，不再误报缺描述，入选照片显示文件名。

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
- **实施任务**：
  - Agent：分类提示词、专用节点、连拍折叠、收缩与超限兜底。
  - 配置：补齐 Compose 两个阈值。
  - 测试：覆盖折叠、两级收缩、超限深链和分类回归。
  - 前端（如需）：提供图文工坊入口。
- **验收**：单元测试覆盖收缩分支且全量通过；（用户）重启 Agent 后重发原始山西请求，回复含第一天照片、标题和文案，无同连拍组重复照片，日志出现 `[compose]` 阶段记录。
- **实施记录**：已加入 `compose` 路由、SQL 候选、连拍封面折叠、两级阈值收缩和超限 `photo_ids` 深链；模板与本地配置已补齐 Compose 阈值，自动单元测试已覆盖核心分支。
- **取代说明**：专用管线不再作为独立形态验收。连拍折叠、两级收缩、超限深链逻辑在 AR2 迁移为 Runtime 挑选临时能力；原定的山西请求人工验收并入 AR6 验收。Compose 两个阈值配置继续复用。
- **关单说明（2026-08-31）**：AR2 已完成迁移（`agent/runtime/capabilities.py` 的 `collapse_burst_candidates` / `prepare_select_candidates` / `select_token` / `select_photos`），`_compose_node` 专用管线已删除，原单测断言全部迁入 `tests/test_runtime_capabilities.py`。CQ4 正式关闭，不再有独立交付物。

### AR Agent Runtime V1：状态化多步执行

- **状态**：Done（2026-08-31，AR6 用户验收确认）
- **专题中枢**：[Agent Runtime 专题中枢](design/2026-08-31-2-agent-runtime-hub.md)
- **背景**：当前 Agent 为单发路由形态，一次分类进入单条管线后直接产出回答，无执行中再决策。开放目标（山西第一天发帖）的路径取决于每步返回的事实，CQ4 用专用管线硬编码承接，但新的组合需求会不断要求新增专用管线。按学习路径 V1 引入 Agent Runtime：目标跨多次能力调用持续执行，观察归约进任务状态，完成要件满足或预算耗尽时结束。
- **方案**：详见 [Agent Runtime V1 设计](design/2026-08-31-1-agent-runtime-v1-design.md)。要点：
  - 新增 runtime 模块：TaskState（goal/constraints/resolved_facts/artifacts/progress）、显式状态归约、确定性完成检查、预算（步数/时长/成本）、能力注册表，全部框架无关纯 Python
  - LangGraph 仅作编排外壳：decide → execute → reduce → check 循环图 + 条件回环；模型只做 decide，程序管执行/状态/预算/完成检查
  - 入口路由调整：开放目标（原 compose 类）进 Runtime，四类单步查询保持现有管线直调
  - 能力层：封装现有 SQL 检索 / RAG 检索 / 混合检索 / Go OpenAPI 工具；CQ4 折叠收缩深链逻辑迁移为「照片挑选」临时能力，「文案创作」临时能力复用图文工坊提示词
  - photo_agent 瘦身为入口分发，compose 专用节点移除；server / demo 调用点同步
  - 配置 Agent 段新增 Runtime 预算键（最大步数/超时秒数/成本上限），沿用 Compose 两级阈值
  - tracer 新增 runtime 步骤事件（decide/execute/observe/check）与轨迹摘要
  - 前端对话界面查询类型标签补 Runtime

### AR1 Runtime 核心语义（框架无关）

- **状态**：Done
- **实施记录**：`agent/runtime/` 的 state / budget / completion / registry 已完成；33 个纯函数单测覆盖归约规则、完成要件判定、预算停止，不依赖 LangGraph 与真实 LLM。

### AR2 Runtime 能力层接入

- **状态**：Done
- **实施记录**：`agent/runtime/capabilities.py` 已注册 7 项能力（sql_search / rag_search / hybrid_search / resolve_trip / fetch_photo_details / select_photos / write_post）；CQ4 折叠收缩深链逻辑已迁入 select_photos，原单测断言已迁入 `tests/test_runtime_capabilities.py`。

### AR3 Runtime 编排接入与入口路由

- **状态**：Done
- **实施记录**：`agent/runtime/graph.py` 已组装 decide → execute → reduce → check 循环图与条件回环；runtime 路由、Compose 迁移、预算配置、前端类型标签及文档同步均已完成。

### AR4 Runtime 追踪与评估

- **状态**：Done
- **实施记录**：tracer 已输出 runtime.decide / execute / observe / check / trace_summary；伪 LLM 驱动的完整轨迹还原测试通过，检索回归 L0/L1 通过。

### AR5 Runtime 入口配置注入修复

- **状态**：Done
- **验收失败分析（2026-08-31）**：原始山西请求已被分类为 `runtime`，但在外层查询路由图进入 Runtime 节点时立即抛出 `TypeError: _runtime_node() missing 1 required positional argument: 'runtime_config'`，未执行任何 Runtime 步骤。根因是 LangGraph 的节点配置注入依赖约定的配置参数形式；该节点使用了未被识别的参数名，导致框架只传入 State。现有测试直接调用节点函数，绕过了外层图的实际调用路径，未能发现这一集成断点。
- **修复方案**：对齐 Runtime 入口节点与其他路由节点的 LangGraph 配置注入约定，确保外层图实际执行时能向 Runtime 传递配置、成本状态与追踪器；新增经编译外层路由图进入 Runtime 的集成回归测试，以伪 Runtime 执行器断言请求可返回回答、照片和 Runtime 类型，不触发真实 LLM、数据库或网络调用。
- **实施任务**：
  - 修正 Runtime 入口节点的配置接收约定，消除真实图执行与直接函数调用之间的行为差异。
  - 补充外层路由图的 Runtime 分支集成测试，并保留已有节点映射单测。
  - 运行 Agent 全量单测；重启后以原始山西请求完成 HTTP 与浏览器验收，核对 Runtime 轨迹事件。
- **本轮实施记录（2026-08-31）**：
  - Runtime 入口节点已采用 LangGraph 可识别的配置注入形式；外层查询图可将请求实际分发到 Runtime。
  - 新增编译后外层路由图的 Runtime 分支回归测试，覆盖配置、回答、照片和查询类型的端到端状态传递；`tests.test_runtime_graph` 11/11、Agent 全量 171/171 通过。
  - 临时 Agent 服务的同一 HTTP 请求不再返回 500，日志确认进入 `resolve_trip → sql_search → select_photos`，并返回 HTTP 200。

### AR6 Runtime 真实闭环验收与候选详情修复

- **状态**：Done（2026-08-31，用户验收确认）
- **验收失败分析（2026-08-31，第二轮）**：真实请求正确完成旅行定位和 SQL 候选检索（20 张），但 Runtime 的照片详情客户端将后端 `GET /api/v1/photos/{id}` 的响应整体当作照片对象；实际照片位于响应的 `photo` 字段。后端日志确认全部详情请求均为 200，Runtime 却因根级没有 `id` 而丢弃为 0 张。挑选器收到空上下文后输出的 ID 无法通过校验，模型随即重复检索、详情和挑选，直至第 14 步在 367.1 秒超时。故根因是后端响应契约解析错误及失败后的重复决策，不是任务规模或预算不足；配置的 20 步尚未耗尽。
- **方案**：
  - 统一 Runtime 照片详情读取与既有 Agent 客户端的响应契约，提取 `photo` 对象后再写入缓存、连拍折叠、挑选提示和最终照片引用；详情请求失败时保留可定位的失败 ID 与原因，不能静默伪装成“0 张详情”。
  - 为详情为空和挑选产物为空建立确定性失败归约：禁止 LLM 在相同候选集上反复尝试，直接给出可定位的能力失败结果；正常候选详情齐备时，状态摘要只暴露“下一里程碑”，使决策顺序稳定为检索 → 挑选 → 文案。
  - 补充真实 HTTP 响应形状的能力层回归测试、详情缺失的终止测试，以及原始山西请求的伪 LLM 完整路径测试；修复后先以当前 20 步 / 300 秒配置验收。仅在正常路径的时延仍稳定超过 300 秒时，再基于 Trace 调整时长上限，而非先行提高预算。
- **实施任务**：
  - 修正 Runtime 照片详情响应解析并补充失败诊断。
  - 收紧详情/挑选失败后的状态归约与回环条件，杜绝无进展重复调用。
  - 运行 Agent 全量测试；重启后重发原始山西请求，核对一次正常闭环的 Runtime 轨迹、入选照片及文案。
- **实施记录（2026-08-31）**：
  - `fetch_photos_batch` 已按后端契约提取响应中的 `photo` 对象；异常或响应缺少 `photo.id` 时记录照片 ID 与原因。
  - 候选详情全缺失、挑选结果无效均会归约为确定性终止，最终回复明确失败原因，不再将无进展状态反复交给模型或误报为预算耗尽。
  - 自动验证：Runtime 相关测试 51/51、Agent 全量 176/176 通过；使用当前运行的 Go 后端对一张真实候选执行详情读取，确认返回 1 张且含 `id`、`description`。
- **（用户）验收操作**：
  - （可选）在 `.local/my-config.yaml` Agent 段补预算键（不加则用默认 12 / 300 / 2.0）：
    ```yaml
    Agent:
      RuntimeMaxSteps: 12
      RuntimeTimeoutSeconds: 300
      RuntimeCostLimit: 2.0
    ```
  - 重启 Python Agent（`make dev` 或 `python cli/photo_agent.py -c ../.local/my-config.yaml --serve`）
  - 在对话界面发送原始山西请求：「找山西旅游第一天的照片并生成发布文案」
- **预期结果**：回复标注「Runtime 多步」标签，包含标题、正文文案和第一天照片（无同连拍组重复照片）；日志出现 `[runtime]` 步骤记录；`data/agent/execution-traces/` 当日 jsonl 含 runtime.decide/execute/observe/check/trace_summary 事件
- **最小回传**：回复「AR6 已通过」或贴出回复截图/文本；如异常，贴 `[runtime]` 日志片段
- **AI 自动验证**：Runtime 相关测试 51/51、Agent 全量 176/176 通过；真实 Go 后端详情响应读取通过。
- **关单方式**：用户回复确认后，AI 在同一轮将任务改为 `Done` 并注明确认日期，不追加核验
- **关单记录（2026-08-31）**：用户确认 AR6 已验收；原始请求「找山西旅游第一天的照片并生成发布文案」已能初步回答。

### AR7 Runtime 非终止能力失败会反复消耗预算

- **状态**：Done（2026-08-31，AI 自动验证关单）
- **背景**：除照片详情全缺失和挑选结果无效以外，Runtime 的能力异常、无效决策或旅行匹配失败只记录为普通错误观察，仍会回到 LLM 决策。相同失败可重复发生至步数、时长或成本预算耗尽，用户最终只看到预算停止，且会产生不必要的模型调用与等待。
- **严重程度**：P1，开放目标在后端、检索或模型输出异常时的失败结果不够及时、可定位。
- **证据**：[2026-08-31 Agent Runtime 与当前 Done 任务复评](eval/reports/2026-08-31-agent-runtime-and-done-reassessment.md)。
- **方案**：将 Runtime 的无进展失败统一归约为确定性终态。能力执行抛出的异常与编排层拒绝的无效决策写入可定位的终止原因；旅行或时间线无法匹配时也以失败观察结束，不再伪装成可继续的空事实。保留候选超限的图文工坊深链这一正常兜底，不把成功完成和预算停止的输出语义混淆。
- **实施任务**：
  - 收紧错误观察的归约规则，保证未显式声明终态的能力失败也在本步停止。
  - 为旅行/时间线未匹配、无效决策和能力异常提供具体终止原因与面向用户的失败说明。
  - 补充 Runtime 单测和伪 LLM 循环回归，断言失败后不再发生下一次决策或以预算耗尽收尾。
- **验收**：能力异常、无效决策、旅行未匹配均在一次 Runtime 步骤后输出失败原因，不出现“预算已耗尽”；正常山西发帖闭环、候选超限深链和既有 Runtime 全量测试不回归。
- **实施记录（2026-08-31）**：错误观察现在统一归约为终态；未声明具体原因的失败标记为 `capability_failed`。能力执行异常、无效决策和旅行/时间线未匹配分别记录 `capability_execution_failed`、`invalid_decision` 与 `trip_unresolved`，最终回复直接展示失败信息；候选超限深链和正常完成输出不变。
- **AI 自动验证**：Runtime 定向测试 52/52 通过，覆盖无效决策一次终止、能力异常终止、旅行未匹配终止与既有成功/预算/超限路径；Agent 全量单测 177/177 通过。

### TIDY5 agent 目录整理（退役文件移入 bak/ + README）

- **状态**：Done（2026-08-31，AI 自动验证关单）
- **背景**：AR 主体开发后 agent/ 目录混杂早期学习性 demo、一次性调试脚本与 codegen 脚手架，职责不清晰
- **动作**：
  - 新增 `agent/README.md`（列表形式描述各目录与文件职责）与 `agent/bak/`（退役文件暂存，用户后续手动删除）
  - 移入 bak/：`demo/` 全目录及其配套 `tests/test_query_router.py`（16 个用例仅覆盖已退役的旧路由）、`scripts/debug_pid.py`（一次性 PID 调参）、`chain/test_suggest_smoke.py`（suggest 管线重构后早已过期，运行即报 AttributeError）、backend-sdk 的 codegen 自带 `test/`（87 个文件）与 CI 脚手架（tox.ini/.travis.yml/git_push.sh/test-requirements.txt）
  - 文档同步：`docs/tech.md` §9 移除 demo/ 条目并指向 agent/README.md；`docs/handbook/eval-guide.md` 移除过期 smoke 命令
- **AI 自动验证**：`tests/` 全量 166 用例通过；`chain.test_post_studio_smoke` 通过；`chain.server` / `photo_agent` / `eval_engine` / `trace_replay` import 正常
- **遗留说明**：`make venv` 重建环境后需手动 `uv pip install -e ./backend-sdk`，已写入 agent/README.md

### TIDY6 agent 目录按功能分包重组（方案 B）

- **状态**：Done（2026-08-31，用户验收确认）
- **背景**：现有顶层目录按技术组件命名且无依赖方向约定：`tools/` 与 `utils/` 语义重叠（都是 Go 后端接入或通用封装却分居两处）；`db/`、`tools/`、`vectorstore/` 为单文件目录；`chain/` 混装入口、检索分支、业务管线与横切设施。Python 社区无统一工程结构标准，参照 Go 的功能分包思路（入口 + 业务包 + 基础设施），采用 package by feature。期间用户试过数字前缀分层（`01_photo_agent.py`），因 Python 模块名禁止数字开头导致 import 语法错误、服务与测试 broken，已恢复原名（166 测试恢复全绿）
- **目标结构**（依赖方向单向：入口 → 功能包 chat/topics/posts/runtime/evals → infra；功能包之间不互相 import，跨功能复用下沉 infra 或经入口编排）：
  - 顶层入口（自 `chain/` 提出）：`photo_agent.py`（CLI）、`server.py`（FastAPI）、`demo.py`（`--demo` 场景演示）
  - `chat/`（对话查询线）：`photo_rag.py`、`text_to_sql.py`、`session_store.py`
  - `topics/`（选题发现线）：`cluster.py`、`suggest.py`
  - `posts/`（图文工坊线）：`post_studio.py`、`test_post_studio_smoke.py`
  - `evals/`（评估与观测）：`evaluation.py`、`eval_engine.py`、`trace_replay.py`、`tracer.py`
  - `infra/`（基础设施）：`openapi_client.py`、`backend_sdk.py`、`http_client.py`、`llm_factory.py`、`streaming_printer.py`、`token_tracker.py`、`sqlite_client.py`、`chroma_client.py`、`embed_queue.py`、`embedding/`（`chunking.py`、`embedder.py`）
  - 不动：`runtime/`、`config.py`、`tests/`、`scripts/`、`backend-sdk/`、`bak/`、`makefile`、`pyproject.toml`
  - 删除迁空目录：`chain/`、`tools/`、`utils/`、`db/`、`vectorstore/`、`embedding/`
- **实施步骤**：
  - 按映射移动文件，批量更新 import 前缀（`chain.`/`utils.`/`tools.`/`db.`/`vectorstore.`/`embedding.` → 新路径），覆盖 `tests/`、`scripts/eval_regression.py` 与包内互相引用
  - `makefile` dev 目标改 `python3 photo_agent.py`；`pyproject.toml` 的 `py-modules` 补 `server`/`photo_agent`/`demo`
  - 重装 editable 包刷新映射：`uv pip install -e .`（backend-sdk 无需重装）
  - 重写 `agent/README.md` 目录章节（含上述依赖方向规则，作为 agent 目录规范载体）；同步 `docs/tech.md`、`docs/handbook/eval-guide.md` 中路径
- **AI 自动验证**：166 个单测全绿；`server`/`photo_agent` import 正常；`grep` 无旧前缀残留 import（排除 `bak/`、`backend-sdk/`）；`posts.test_post_studio_smoke` 可执行
- **实施记录（2026-08-31）**：
  - 按目标结构完成移动，`chain/`、`tools/`、`utils/`、`db/`、`vectorstore/`、`embedding/` 六个旧目录删除
  - 执行中用户新增规则：import 风格向 Go 靠拢，项目内模块禁止 `from xxx import <符号>`，统一 `import pkg.module as alias` + 限定调用；规则已补强进 `docs/handbook/coding-conventions.md` 导入规范（含标准库/第三方例外），存量 6 处 `from import`（tests 与各模块 docstring 用法示例）全部转换
  - `server.py` 日志初始化的硬编码 `getLogger("chain")` 根因修复为按新包名（chat/topics/posts/evals/infra/runtime/入口）逐包挂 handler，模块内 `getLogger(__name__)` 随包名自动生效
  - `pyproject.toml`：`py-modules` 补 server/photo_agent/demo；`packages.find` 排除 `bak*`（退役代码不得进入 editable 映射）
  - 文档同步：`agent/README.md` 重写（含目录规范章节：依赖方向单向 + import 风格，作为 agent 目录规范载体）；`docs/tech.md` 架构树与 §9；`docs/handbook/eval-guide.md` 与本文件 AR 的 CLI 路径
  - 自动验证结果：166 个单测全绿；`posts.test_post_studio_smoke` 通过；全部新旧模块 import 正常（含 agent 目录外执行，验证 editable 映射）；无 `from <项目模块> import` 与旧前缀残留
  - 二次追加（同日用户要求：金字塔分层 + tech.md 收敛目录粒度）：五个功能包（chat / topics / posts / runtime / evals）套入父目录 `internal/`（类 Go internal/；候选 internal / features / apps / core 中用户选定 internal），形成 `cli → internal → infra` 三层金字塔；import 路径全部加 `internal.` 前缀，server logger 挂载收敛为 3 个包根名（internal / infra / cli）；`docs/tech.md` agent 子树收敛为目录粒度（文件级职责只在 agent/README.md）
  - 追加（同日用户追加要求：顶层不放源码）：三个入口文件移入 `cli/`（类似 Go cmd/；命名弃用 `cmd` 因与 Python 标准库模块重名，实测依赖零引用但属长期遮蔽风险），`config.py` 移入 `infra/`，顶层仅剩 makefile / pyproject.toml / uv.lock / README；入口引用统一别名形式 `import cli.photo_agent as photo_agent`；`cli/photo_agent.py` 加 sys.path 引导支持任意目录直接运行；`pyproject.toml` 移除 `py-modules`；修复三处 `assertLogs("photo_agent")` → `"cli.photo_agent"` 与 server logger 挂载列表（收敛为 7 个包根名）；`pip install -e .` 产生的 `photo_agent_ai.egg-info/` 构建残留已清理（`*.egg-info/` 已在 .gitignore）
- **（用户）验收操作**：`make dev`（或 `python cli/photo_agent.py -c ../.local/my-config.yaml --serve`）启动后在对话页发一条消息冒烟；可顺带执行 AR6 的山西请求（两项验收一次完成）
- **预期结果**：服务正常启动，对话回复正常，日志 `[chat.xxx]`/`[infra.xxx]` 等新包名 logger 输出正常
- **最小回传**：回复「TIDY6 已通过」（可与 AR6 验收合并回复）
- **（用户）验收**：`make dev` 启动后在对话页发一条消息冒烟，回复「TIDY6 已通过」即关单
- **关单记录（2026-08-31）**：用户确认 TIDY6 已通过。

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
