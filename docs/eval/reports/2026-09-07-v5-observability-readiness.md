# V5 自适应优化证据链就绪度评估

> 评估对象：现有 Agent 日志、Trace、用量记录与会话记录是否足以支持后续按 V5 指引作判断。  
> 评估日期：2026-09-07  
> 范围：仅代码静态走查与本地既有只读 Trace/SQLite 样本；未启动服务，未调用真实 LLM 或修改真实数据。

## 摘要

**6.2/10，可用于定位单次 Runtime 问题，尚不足以作为 V5 的生产优化决策依据。**

现有系统已经有请求级 `trace_id`、Runtime 决策/执行/护栏/归约/终态事件、JSONL 应用访问日志、会话消息与 Token 聚合记录。它能够解释一次 Runtime 为什么结束、调用了什么能力及是否发生恢复。

但 V5 所需的核心比较单位是“同一请求从入口路由到最终用户结果”的完整记录。目前直接 SQL/RAG/Tool/Combined 路径没有同等的结构化步骤事件；端到端耗时、Token 成本和用户是否接受结果分别落在不同记录中，且缺少稳定关联。故不能可靠比较不同执行结构的质量、成本与延迟。

## 评分

### Runtime 轨迹可复盘性：8.5/10

得分点：

- `Tracer` 把同一操作的事件写入 JSONL，并以 `trace_id` 串联；Runtime 已输出 `runtime.decide`、`execute`、`guardrail`、`observe`、`check` 和 `trace_summary`。
- Runtime 事件包含动作、候选/入选数量、完成缺口、恢复计数、终态、步骤数和局部耗时；大 payload 使用引用文件保存。`GET /api/chat/traces/{trace_id}` 可回放 Runtime 轨迹。
- 2026-09-07 样本中可直接统计 15 条 `runtime.trace_summary`：10 条 `complete=true`，5 条为非完整终态；能力调用序列与恢复计数可见。

失分点：

- `runtime.trace_summary` 没有端到端耗时；各内部事件存在局部 `duration_ms` 或累计耗时，但没有可直接比较的统一请求完成时长。
- 回放器只展示定义的 Runtime/选题步骤，会跳过 `chat.query`、`chat.answer` 和通用 HTTP 访问记录，单次复盘仍需跨文件人工拼接。

### 全路径执行可观测性：5.5/10

得分点：

- 聊天 API 为请求创建 `trace_id`，并记录最终 `chat.query`（含 `query_type`）与 `chat.answer`（含结果照片 ID、答案长度）。
- 应用 JSONL 的 HTTP access 记录携带同一请求上下文中的 `trace_id` 和 `duration_ms`。

失分点：

- 入口分类只写普通文本日志；没有将模型原始分类、路由依据、置信信号或降级原因作为结构化 Trace 事件保存。
- SQL、RAG、Tool、Combined 等直接路径没有与 Runtime 对等的结构化执行事件、终态分类或结果质量字段。因而不能从 Trace 中统计“某类请求是否被错误送入较重/较轻路径”。
- `chat.query` 在路由完成后才写入，无法单独表示入口选择与下游实际执行结构之间是否一致。

### 成本与延迟可归因性：4.5/10

得分点：

- `token_usage` SQLite 表记录模型、输入/输出 Token、成本和时间；HTTP access 日志记录请求耗时。
- Runtime 对价格可用性和预算进行了状态记录。

失分点：

- `token_usage` 没有 `trace_id`、会话、路由或任务字段，只能按日期和模型聚合，不能计算每个请求或每种执行结构的成本。
- 样本中的 15 条 Runtime 汇总全部为 `cost=0.0`，而同日 `token_usage` 有 78 次 `deepseek-v4-flash` 调用记录；两者无法归因，也不能核验 Runtime 成本字段是否代表真实请求成本。
- HTTP 耗时在 `logs/agent.jsonl`，而 Trace 事件在 `data/agent/execution-traces/`；虽可借 `trace_id` 人工关联，但没有面向分析的统一记录，且非 Runtime 路径没有可与耗时对应的终态。

### 结果与用户反馈可判定性：4.5/10

得分点：

- 会话存储保存用户/助手消息、`query_type`、`trace_id`、照片引用和 Runtime 进度；可定位后续对话。
- Runtime 的 `complete`、终态原因、完成要件和产物数量可用于判断技术终态。

失分点：

- 不存在与初始结果关联的接受、拒绝、编辑幅度或人工评价事件；后续消息只能作为非结构化文本保存，不能计算 V5 验收中的 User Acceptance / Edit Rate。
- 技术完成不等于用户结果有效，直接路径和 Runtime 路径均没有统一的任务成功标签。

### 长期趋势可用性：6.0/10

得分点：

- JSONL 按日落盘，当前工作区保留 2026-07-26 至 2026-09-07 的历史文件，足以做一次离线样本检查。

失分点：

- Trace 回放按 7 天有效窗口判断；`Tracer.cleanup_old()` 定义了清理逻辑，但静态搜索未发现调用点。工作区中超过 7 天的文件仍存在，说明“实际保留”和“可回放有效期”不一致，不能作为可靠的长期采样口径。
- 没有按路由、执行结构、成功终态、成本、延迟和用户结果汇总的趋势产物，因此无法从既有记录直接发现某条路径已高频且稳定。

## 对 V5 指标的覆盖结论

- **Route Quality**：不足。能看到最终 `query_type`，但缺入口依据、实际执行结构与统一成功结果的关联。
- **Route Escalation Success**：不适用/不足。当前没有 V5 升级事件；现有记录也无法表达“低复杂度路径携带观察升级”。
- **End-to-End Task Success**：Runtime 部分可判断；全路径不足。
- **p50/p95 Latency**：原始 HTTP 时长存在，但缺按执行结构和终态的统一分析记录。
- **Cost per Successful Task**：不足。Token 成本不能关联到请求和成功终态。
- **User Acceptance / Edit Rate**：不足。没有结构化用户结果事件。

## 执行证据

- 审阅：`agent/cli/server.py`、`agent/cli/photo_agent.py`、`agent/internal/runtime/graph.py`、`agent/internal/evals/tracer.py`、`agent/internal/evals/trace_replay.py`、`agent/infra/token_tracker.py`、`agent/internal/chat/session_store.py`。
- 只读样本：`data/agent/execution-traces/2026-09-07.jsonl`；其中 Runtime 汇总 15 条，完整 10 条、非完整 5 条，报告成本合计为 0。
- 只读用量库：`data/agent/sqlite/token_usage.db`；2026-09-07 的 `deepseek-v4-flash` 为 78 次调用、95,454 输入 Token、65,907 输出 Token，但无请求关联字段。

## 评估结论

当前可支持“这一次 Runtime 为什么失败或停下”的诊断，也能为 V2/V4 的可靠性回归提供证据；但还不能支持“哪种执行结构更经济、更快、且更被用户接受”的 V5 判断。问题已登记为 OBS2，后续应由规划模式决定范围与口径。
