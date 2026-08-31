# Backlog

> 全部技术需求池，按序号排列。状态流转：`待规划` → `规划中` → `已规划` → `WIP` → `待用户验收` → `Done`。暂缓任务已确认当前不执行。

## 任务总览

> 表头不能随意修改，即使表格清空了，也要保留表头，保留一个空表。

| 状态 | 分组 | 编号 | 任务 | 评估 |
| ---- | ---- | ---- | ---- | ---- |
| 待用户验收 | Agent 升级 | AR1 | Agent Runtime V1：状态化多步执行 | |
| 待用户验收 | 代码治理 | TIDY6 | agent 目录按功能分包重组（方案 B） | |
| 待用户验收 | 配置治理 | CFG8 | 价格配置故障隔离，核心功能可用 | |
| Done | 代码治理 | TIDY5 | agent 目录整理（退役文件移入 bak/ + README） | |
| 暂缓 | 代码治理 | BQ3 | 未鉴权服务暴露任意 SQL 查询 | |
| 已取代 | 对话查询 | CQ4 | 创作型查询（Compose）专用管线 | |

> v1.0.15 已归档：PS10、BQ1–BQ2、BQ4–BQ6、BQ8–BQ11、DOC2、TIDY1–TIDY4、CFG1–CFG7，详见 [v1.0.15](archive/v1.0.15.md)。
> v1.0.14 已归档：CQ1–CQ3、CQ5、CQ6、AQL2-1、AQL2-2，详见 [v1.0.14](archive/v1.0.14.md)。
> 其余 6 项待规划任务经审阅后迁至 [未来需求暂存](design/2099-01-01-future-requirements.md)。

### CFG8 价格配置故障隔离，核心功能可用

- **状态**：待用户验收
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
  - 重启 Python Agent（`make dev` 或 `python cli/photo_agent.py -c ../.local/my-config.yaml --serve`）
  - 在对话界面发送原始山西请求：「找山西旅游第一天的照片并生成发布文案」
- **预期结果**：回复标注「Runtime 多步」标签，包含标题、正文文案和第一天照片（无同连拍组重复照片）；日志出现 `[runtime]` 步骤记录；`data/agent/execution-traces/` 当日 jsonl 含 runtime.decide/execute/observe/check/trace_summary 事件
- **最小回传**：回复「AR1 已通过」或贴出回复截图/文本；如异常，贴 `[runtime]` 日志片段
- **AI 自动验证**：166 个单测全量通过（含伪 LLM 驱动的三步闭环、预算停止、轨迹还原）；检索回归 L0/L1 通过
- **关单方式**：用户回复确认后，AI 在同一轮将任务改为 `Done` 并注明确认日期，不追加核验

### TIDY5 agent 目录整理（退役文件移入 bak/ + README）

- **状态**：Done（2026-08-31，AI 自动验证关单）
- **背景**：AR1 完成后 agent/ 目录混杂早期学习性 demo、一次性调试脚本与 codegen 脚手架，职责不清晰
- **动作**：
  - 新增 `agent/README.md`（列表形式描述各目录与文件职责）与 `agent/bak/`（退役文件暂存，用户后续手动删除）
  - 移入 bak/：`demo/` 全目录及其配套 `tests/test_query_router.py`（16 个用例仅覆盖已退役的旧路由）、`scripts/debug_pid.py`（一次性 PID 调参）、`chain/test_suggest_smoke.py`（suggest 管线重构后早已过期，运行即报 AttributeError）、backend-sdk 的 codegen 自带 `test/`（87 个文件）与 CI 脚手架（tox.ini/.travis.yml/git_push.sh/test-requirements.txt）
  - 文档同步：`docs/tech.md` §9 移除 demo/ 条目并指向 agent/README.md；`docs/handbook/eval-guide.md` 移除过期 smoke 命令
- **AI 自动验证**：`tests/` 全量 166 用例通过；`chain.test_post_studio_smoke` 通过；`chain.server` / `photo_agent` / `eval_engine` / `trace_replay` import 正常
- **遗留说明**：`make venv` 重建环境后需手动 `uv pip install -e ./backend-sdk`，已写入 agent/README.md

### TIDY6 agent 目录按功能分包重组（方案 B）

- **状态**：待用户验收（2026-08-31 开发完成，AI 自动验证通过）
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
  - 文档同步：`agent/README.md` 重写（含目录规范章节：依赖方向单向 + import 风格，作为 agent 目录规范载体）；`docs/tech.md` 架构树与 §9；`docs/handbook/eval-guide.md` 与本文件 AR1 的 CLI 路径
  - 自动验证结果：166 个单测全绿；`posts.test_post_studio_smoke` 通过；全部新旧模块 import 正常（含 agent 目录外执行，验证 editable 映射）；无 `from <项目模块> import` 与旧前缀残留
  - 二次追加（同日用户要求：金字塔分层 + tech.md 收敛目录粒度）：五个功能包（chat / topics / posts / runtime / evals）套入父目录 `internal/`（类 Go internal/；候选 internal / features / apps / core 中用户选定 internal），形成 `cli → internal → infra` 三层金字塔；import 路径全部加 `internal.` 前缀，server logger 挂载收敛为 3 个包根名（internal / infra / cli）；`docs/tech.md` agent 子树收敛为目录粒度（文件级职责只在 agent/README.md）
  - 追加（同日用户追加要求：顶层不放源码）：三个入口文件移入 `cli/`（类似 Go cmd/；命名弃用 `cmd` 因与 Python 标准库模块重名，实测依赖零引用但属长期遮蔽风险），`config.py` 移入 `infra/`，顶层仅剩 makefile / pyproject.toml / uv.lock / README；入口引用统一别名形式 `import cli.photo_agent as photo_agent`；`cli/photo_agent.py` 加 sys.path 引导支持任意目录直接运行；`pyproject.toml` 移除 `py-modules`；修复三处 `assertLogs("photo_agent")` → `"cli.photo_agent"` 与 server logger 挂载列表（收敛为 7 个包根名）；`pip install -e .` 产生的 `photo_agent_ai.egg-info/` 构建残留已清理（`*.egg-info/` 已在 .gitignore）
- **（用户）验收操作**：`make dev`（或 `python cli/photo_agent.py -c ../.local/my-config.yaml --serve`）启动后在对话页发一条消息冒烟；可顺带执行 AR1 的山西请求（两项验收一次完成）
- **预期结果**：服务正常启动，对话回复正常，日志 `[chat.xxx]`/`[infra.xxx]` 等新包名 logger 输出正常
- **最小回传**：回复「TIDY6 已通过」（可与 AR1 验收合并回复）
- **（用户）验收**：`make dev` 启动后在对话页发一条消息冒烟，回复「TIDY6 已通过」即关单

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
- **2026-08-31**：AR1 开发完成待验收。新增 `agent/runtime/`（框架无关核心 + LangGraph 外壳），入口 classify 增加 runtime 类别承接原 compose 开放目标，CQ4 专用管线删除、其折叠/收缩/深链逻辑迁入 select_photos 能力；预算键落在 Agent 段（RuntimeMaxSteps/TimeoutSeconds/CostLimit，缺省 12/300/2.0）；tracer 增加 runtime 步骤事件与轨迹摘要；前端标签补 runtime。166 个测试全量通过。
- **2026-08-31**：AR1 规划，Agent 从单发路由升级为 Agent Runtime V1。编排底座定为 LangGraph 只做 Runtime 外壳（decide/execute/reduce/check 循环图），TaskState、状态归约、完成检查、预算、能力注册表保持框架无关；CQ4 compose 专用管线由 AR1 取代关闭，其折叠/收缩/深链逻辑迁移为挑选临时能力，山西案例验收并入 AR1。
- **2026-08-30**：v1.0.15 归档。完成草稿编辑输入恢复、后端质量治理与关键用户路径闭环、公共文档对齐、工具和运行数据整理、配置契约收敛，共 22 项任务；BQ3、CQ4 继续暂缓，分别受 FR-11 与真实环境验收条件约束。
- **2026-08-30**：BQ1 以“后端代码质量基线评估与问题拆分”范围关单。活动 SQLite 库已确认不含四个旧 AI 状态列，BQ2 改为删除一次性迁移代码；BQ3 按开发阶段决策暂缓并迁入 future requirements；BQ4–BQ6、BQ8 的技术方案和验收已补充至各自 backlog 条目。
- **2026-08-29**：新增 BQ1，建立长期使用的后端代码质量 100 分制标准并接入评估模式；后续以独立逻辑单测、Service 集成测试和关键用户用例闭环组合验证，不以 100% 单元测试覆盖率为目标。
- **2026-08-28**：v1.0.14 归档。完成对话查询链路诊断与修复及资产审核收尾，共 7 项任务；同期确立验证流单向、人工验收即终态的关单规则。
