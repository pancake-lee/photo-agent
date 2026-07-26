# 评估系统升级设计

> 状态：规划中
> 日期：2026-07-26
> 驱动用例：聚类标题生成效果评估（backlog 2.2）

## 一、现状与差距

### 1.1 已有能力

- RAG 检索评估：黄金查询用例 + P@K/R@K/MRR，用例积累中
- 黄金用例管理：Web UI + API，JSON 文件存储
- 日志输出：三份独立日志文件（agent/backend/web.log）

### 1.2 当前日志的不足

以聚类标题生成为例，agent.log 中只有三条结果日志，缺失：

- LLM 请求的完整 prompt 和原始响应
- 每张代表照片的属性值（objects/scene/colors 是否有值）
- LLM 调用耗时、token 用量
- 响应解析走了哪个 fallback 路径

### 1.3 核心差距

1. **无可观测性**：日志只有结果，没有过程。排查问题只能读代码反向推断
2. **无生成质量评估**：聚类标题、对话回复等生成类输出完全没有评估手段
3. **无回归检测**：改完代码后只能靠人工在网页上体验
4. **评估维度单一**：Text-to-SQL、Agent 路由、Combined 查询均无评估覆盖

---

## 二、评估体系全景

### 2.1 评估对象分类

```
检索类      → RAG 检索、Combined 交集 → 黄金用例 + P@K/R@K/MRR ✅ 已有
结构化预测类 → Text-to-SQL、Agent 路由  → 黄金用例 + 精确匹配/语义等价
生成类      → 聚类标题、对话回复       → 启发式规则 + 人工评估（LLM-judge 暂缓）
管道正确性  → VLM JSON→属性、Embedding → 断言检查 + 数据对账
```

### 2.2 四种评估方法及决策

#### 方法 A：黄金用例 + 量化指标

- 适用范围：检索类、结构化预测类（输出有明确对错）
- 当前状态：RAG 已实现，缺少 Text-to-SQL 和路由分类的标注用例

**决策**：让 Text-to-SQL 和路由分类的结果用精简方式展示到对话页面中，跟回复时附带的相关照片一样。保存黄金用例时让用户选择保存哪些维度（RAG 检索 / SQL 查询 / 路由分类 / 全部），逐步积累多类型标注用例。

#### 方法 B：LLM-as-judge

- 适用范围：生成类（聚类标题、对话回复），输出没有唯一正确答案
- 原理：用独立 LLM 按 rubric 打分

**决策**：暂缓。先由人工评估跑通流程，之后再引入 LLM 自动评判。

#### 方法 C：启发式规则

- 适用范围：所有类型的第一道质量门禁
- 典型规则：标题长度、无兜底文本、无 markdown 残留、多样性检查、属性非空率
- 局限：只能检测明显错误，无法评估语义质量

**决策**：需要统一的规则入口和配置方式。待设计：规则配置文件格式、规则引擎、统一 CLI/API 入口。由我（AI）先编写一套初始规则，用户审阅后确定最终形式。

#### 方法 D：结构化追踪日志

- 定位：不是评估方法本身，而是支撑以上三种方法的基础设施
- 目标：排查问题时能回溯完整现场（LLM prompt/response、中间步骤输入输出、耗时、token 用量）

**决策**：方案 B（JSON 结构化日志）+ 方案 C（专用 trace 事件文件）并行执行。

- Go 侧：继续用 pgo 的 plogger，通过 `SetJsonLog` 切换到 JSON 格式输出。需要扩展的字段告诉我，我去改 pgo
- Python 侧：参考 Go 的 JSON 日志结构，自建同格式的日志模块
- 同时保留方案 C：大体积 payload（LLM 完整 prompt/response）写入独立 trace 文件，日志行中只记文件路径引用，避免撑爆日志行
- 否决 OpenTelemetry：单机个人工具不需要分布式追踪的复杂度

### 2.3 方法选择矩阵

| 评估对象 | 黄金用例 | LLM-judge | 启发式 | 结构化追踪 |
|---------|----------|-----------|--------|-----------|
| RAG 检索 | ✅ 已有 | 不需要 | 可选 | ✅ 已有基础 |
| Text-to-SQL | ✅ 主要 | 辅助 | 可选 | 待建设 |
| Agent 路由 | ✅ 主要 | 不需要 | 不需要 | 待建设 |
| 聚类标题 | 可选 | 暂缓 | ✅ 第一道门禁 | 待建设 |
| 对话回复 | 可选 | 暂缓 | 可选 | 待建设 |
| 管道正确性 | 不需要 | 不需要 | ✅ 主要 | ✅ 主要 |

---

## 三、结构化追踪方案

### 3.1 总体策略

Go 和 Python 两侧统一输出 JSON 结构日志，日志行至少包含：`trace_id`、`timestamp`、`level`、`module`、`event`、`data`。大体积 payload 不直接塞进日志行，写入独立文件后在日志中记录路径引用。

Python 侧新增 `agent/chain/tracer.py` 封装 emit 逻辑，在关键决策点（LLM 调用前后、解析结果、fallback 触发）埋点。

Go 侧通过 plogger 的 `SetJsonLog` 切换输出格式，在 HTTP 响应 header 中传递 `X-Trace-Id` 给 Python 侧关联。

### 3.2 关键埋点节点

**聚类标题生成链路**：

```
cluster.run.start → umap.reduce → hdbscan.cluster → cluster.save → cluster.run.end
cluster.theme.start → llm.call.start → llm.call.end → parse.theme → cluster.theme.end
```

**Agent 对话链路**（后续扩展）：

```
chat.request.start → classify → sql.generate/execute → rag.retrieve
                   → combined.intersection → llm.answer → chat.request.end
```

### 3.3 输出与轮转

- 日志：`logs/agent.jsonl`、`logs/backend.jsonl`（替换现有文本日志）
- Payload：`data/traces/payloads/YYYY-MM-DD/`
- 保留最近 7 天

---

## 四、聚类标题评估：第一个实践用例

### 4.1 评估维度

- **准确性**：标题是否准确反映照片内容（暂由人工评估）
- **具体性**：是否包含具体视觉描述，而非笼统的"照片合集"
- **格式规范**：长度 6-12 字，无 markdown 残留（启发式规则自动检查）
- **多样性**：不同簇的标题互不相同（启发式规则自动检查）
- **属性可用性**：底层照片的结构化属性是否有值（SQL 查询 / 数据对账）

### 4.2 评估方式

- **启发式规则**（优先实现）：自动检查格式规范、多样性、属性可用性。规则通过配置文件定义，统一入口调用
- **人工评估**（当前）：用户在 Web UI 上逐簇查看标题和照片，判断准确性。后续引入 LLM-judge 自动化

### 4.3 API 设计

新增评估 endpoint 集成到 Python Agent API：

- `POST /api/cluster/results/{id}/evaluate-themes`：执行启发式规则，返回评估报告
- `GET /api/eval/reports`：历史评估报告列表
- `GET /api/eval/reports/{id}`：单份报告详情

评估报告以 JSON 文件存储在 `data/eval_reports/`。

### 4.4 启发式规则入口设计

待确定的问题：规则放在哪里、以什么形式定义、统一入口是什么。

几种可选形式：
- 独立 YAML/JSON 配置文件：可编辑性好，非开发者也容易修改
- Python 代码文件：灵活，支持复杂规则逻辑，但需要编程能力
- 结合：简单规则用配置文件，复杂规则用 Python 函数注册

本阶段由 AI 先找检查点、写一套初始规则给用户审阅，根据审阅反馈确定最终形式。

---

## 五、评估扩展到其他模块

### 5.1 Text-to-SQL

方法：黄金用例标注（query_text + expected_sql），通过 Go 后端实际执行两个 SQL 比较返回的 photo_id 集合是否一致，解决 SQL 等价写法问题。

### 5.2 Agent 路由

方法：标注 query_text → expected_route，直接对 classify() 输出做精确匹配。10-20 条用例即可覆盖四种路由类型。

### 5.3 黄金用例数据结构扩展

当前黄金用例只存储 query_text + relevant_photos（RAG 用）。需扩展支持多类型标注：

- `rag_photos`：RAG 检索相关照片（已有）
- `expected_sql`：Text-to-SQL 期望 SQL
- `expected_route`：路由分类期望结果

保存时用户可选择填写哪些维度。详见 tech.md。

---

## 六、分阶段实施计划

### 阶段一：结构化追踪（基础设施）

- Python 侧新增 `tracer.py`，cluster.py 埋点
- Go 侧 plogger 切换到 JSON 格式
- Trace 事件输出到 `data/traces/`

### 阶段二：聚类标题启发式评估

- 设计启发式规则配置 + 统一入口
- 实现规则检查引擎
- 新增评估 API + 评估报告存储

### 阶段三：前端评估视图

- ClusterView 增加"评估标题"按钮
- 评估报告查看组件

### 阶段四：黄金用例扩展

- 对话页保存黄金用例时支持选择维度
- Text-to-SQL、路由分类的评估脚本

### 阶段五：自动化回归

- 一键评估脚本（RAG + 聚类标题 + Text-to-SQL）
- 基线对比，标记显著下降的维度

---

## 七、方案决策记录

- **OpenTelemetry**：否决，单机个人工具不需要分布式追踪
- **LLM-as-judge**：暂缓，先人工跑通流程再引入
- **Go 日志**：用 plogger `SetJsonLog` 切换 JSON 格式，Python 参考同结构自建
- **Payload 存储**：大体积内容独立文件存储，日志行只记路径引用
- **评估报告存储**：JSON 文件（`data/eval_reports/`），不走 SQLite
- **启发式规则形式**：待定（配置文件 / 代码文件 / 混合），先出初始规则再确定
