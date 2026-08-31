# Backlog

> 全部技术需求池，按序号排列。状态流转：`待规划` → `规划中` → `已规划` → `WIP` → `待用户验收` → `Done`。暂缓任务已确认当前不执行。

## 任务总览

> 表头不能随意修改，即使表格清空了，也要保留表头，保留一个空表。

| 状态 | 分组 | 编号 | 任务 | 评估 |
| ---- | ---- | ---- | ---- | ---- |
| 待用户验收 | Agent 升级 | AR1 | Agent Runtime V1：状态化多步执行 | |
| 暂缓 | 代码治理 | BQ3 | 未鉴权服务暴露任意 SQL 查询 | |
| 已取代 | 对话查询 | CQ4 | 创作型查询（Compose）专用管线 | |

> v1.0.15 已归档：PS10、BQ1–BQ2、BQ4–BQ6、BQ8–BQ11、DOC2、TIDY1–TIDY4、CFG1–CFG7，详见 [v1.0.15](archive/v1.0.15.md)。
> v1.0.14 已归档：CQ1–CQ3、CQ5、CQ6、AQL2-1、AQL2-2，详见 [v1.0.14](archive/v1.0.14.md)。
> 其余 6 项待规划任务经审阅后迁至 [未来需求暂存](design/2099-01-01-future-requirements.md)。

### BQ3 未鉴权服务暴露任意 SQL 查询

- **状态**：暂缓
- **背景**：默认服务全局调用 `SetIgnoreAuth`，同时注册了接收调用方 SQL 文本的 QueryService。当前服务监听全部网络接口；虽使用只读数据库连接，调用方仍可读取任意可访问表和元数据。
- **严重程度**：P0，未授权数据访问风险。
- **证据**：[后端代码质量基线评估](eval/reports/2026-08-29-backend-code-quality-baseline.md)。
- **方案**：当前开发阶段保留 `SetIgnoreAuth` 与自由只读 SQL 查询，不改变接口、监听方式或开发调试效率。将风险、启动条件和后续收敛方向迁入 FR-11；当服务需要被非受信任网络、多人或真实用户访问时，必须先恢复鉴权并收紧查询能力，再继续发布。
- **验收**：FR-11 可独立追溯本决策及后续启动条件；BQ3 不进入当前开发队列。

### CQ4 创作型查询（Compose）专用管线

- **状态**：已取代（2026-08-31，由 AR1 承接）
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
- **取代说明**：专用管线不再作为独立形态验收。连拍折叠、两级收缩、超限深链逻辑在 AR1 子阶段 2 迁移为 Runtime 挑选临时能力；原定的山西请求人工验收并入 AR1 验收。Compose 两个阈值配置继续复用。
- **关单说明（2026-08-31）**：AR1 子阶段 2 已完成迁移（`agent/runtime/capabilities.py` 的 `collapse_burst_candidates` / `prepare_select_candidates` / `select_token` / `select_photos`），`_compose_node` 专用管线已删除，原单测断言全部迁入 `tests/test_runtime_capabilities.py`。CQ4 正式关闭，不再有独立交付物。

### AR1 Agent Runtime V1：状态化多步执行

- **状态**：待用户验收
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
- **子阶段拆分**：
  1. **Runtime 核心语义（框架无关）** ✅：`agent/runtime/`（state/budget/completion/registry），33 个纯函数单测覆盖归约规则、完成要件判定、预算停止，不依赖 LangGraph 与真实 LLM
  2. **能力层接入** ✅：`agent/runtime/capabilities.py` 注册 7 项能力（sql_search / rag_search / hybrid_search / resolve_trip / fetch_photo_details / select_photos / write_post）；CQ4 折叠收缩深链逻辑迁入 select_photos，原单测断言迁入 `tests/test_runtime_capabilities.py` 后全量通过
  3. **编排接入与入口路由** ✅：`agent/runtime/graph.py` 组装 decide → execute → reduce → check 循环图 + 条件回环；classify 新增 runtime 类别（兼容 compose 输出）；`_compose_node` 删除、`_runtime_node` 接入；server 串 tracer 传入 route；配置 Agent 段 Runtime 预算键（可选，缺省 12 步 / 300 秒 / 2 元）+ 模板与部署文档；前端 routeLabel 补 runtime 与 combined
  4. **追踪与评估** ✅：tracer 输出 runtime.decide / execute / observe / check / trace_summary 事件；伪 LLM 驱动的完整轨迹还原测试通过；检索回归 L0/L1 通过（L2 需 Agent 服务重启后执行）
  5. **真实环境验收与收尾** ✅：prd / tech / deploy / backlog 文档同步完成，CQ4 关单说明已补
- **实施记录**：
  - 新增 `agent/runtime/` 六个模块 + 三个测试文件（state / core / capabilities / graph，共 60 个新测试），全量 166 个测试通过
  - LangGraph 外壳注意点：节点 `config` 参数必须注解为 `RunnableConfig` 才会注入；循环图 recursion_limit 按预算步数 ×5 放大
  - 预算成本维度由 `_CostCallback` 按价格表累加（含 decide 与能力内 LLM 调用），sql/rag 能力内部的历史遗留 LLM 调用（text_to_sql 生成）不计入，与现有全局 Token 追踪行为一致
  - 检索回归 `scripts/eval_regression.py` L0（数据态）/ L1（检索函数）通过；L2（HTTP 契约）需 Agent 服务运行
- **（用户）验收操作**：
  - （可选）在 `.local/my-config.yaml` Agent 段补预算键（不加则用默认 12 / 300 / 2.0）：
    ```yaml
    Agent:
      RuntimeMaxSteps: 12
      RuntimeTimeoutSeconds: 300
      RuntimeCostLimit: 2.0
    ```
  - 重启 Python Agent（`make dev` 或 `python chain/photo_agent.py -c ../.local/my-config.yaml --serve`）
  - 在对话界面发送原始山西请求：「找山西旅游第一天的照片并生成发布文案」
- **预期结果**：回复标注「Runtime 多步」标签，包含标题、正文文案和第一天照片（无同连拍组重复照片）；日志出现 `[runtime]` 步骤记录；`data/agent/execution-traces/` 当日 jsonl 含 runtime.decide/execute/observe/check/trace_summary 事件
- **最小回传**：回复「AR1 已通过」或贴出回复截图/文本；如异常，贴 `[runtime]` 日志片段
- **AI 自动验证**：166 个单测全量通过（含伪 LLM 驱动的三步闭环、预算停止、轨迹还原）；检索回归 L0/L1 通过
- **关单方式**：用户回复确认后，AI 在同一轮将任务改为 `Done` 并注明确认日期，不追加核验

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

- **2026-08-31**：AR1 开发完成待验收。新增 `agent/runtime/`（框架无关核心 + LangGraph 外壳），入口 classify 增加 runtime 类别承接原 compose 开放目标，CQ4 专用管线删除、其折叠/收缩/深链逻辑迁入 select_photos 能力；预算键落在 Agent 段（RuntimeMaxSteps/TimeoutSeconds/CostLimit，缺省 12/300/2.0）；tracer 增加 runtime 步骤事件与轨迹摘要；前端标签补 runtime。166 个测试全量通过。
- **2026-08-31**：AR1 规划，Agent 从单发路由升级为 Agent Runtime V1。编排底座定为 LangGraph 只做 Runtime 外壳（decide/execute/reduce/check 循环图），TaskState、状态归约、完成检查、预算、能力注册表保持框架无关；CQ4 compose 专用管线由 AR1 取代关闭，其折叠/收缩/深链逻辑迁移为挑选临时能力，山西案例验收并入 AR1。
- **2026-08-30**：v1.0.15 归档。完成草稿编辑输入恢复、后端质量治理与关键用户路径闭环、公共文档对齐、工具和运行数据整理、配置契约收敛，共 22 项任务；BQ3、CQ4 继续暂缓，分别受 FR-11 与真实环境验收条件约束。
- **2026-08-30**：BQ1 以“后端代码质量基线评估与问题拆分”范围关单。活动 SQLite 库已确认不含四个旧 AI 状态列，BQ2 改为删除一次性迁移代码；BQ3 按开发阶段决策暂缓并迁入 future requirements；BQ4–BQ6、BQ8 的技术方案和验收已补充至各自 backlog 条目。
- **2026-08-29**：新增 BQ1，建立长期使用的后端代码质量 100 分制标准并接入评估模式；后续以独立逻辑单测、Service 集成测试和关键用户用例闭环组合验证，不以 100% 单元测试覆盖率为目标。
- **2026-08-28**：v1.0.14 归档。完成对话查询链路诊断与修复及资产审核收尾，共 7 项任务；同期确立验证流单向、人工验收即终态的关单规则。
