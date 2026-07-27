# Backlog

> 全部技术需求池，按序号排列。
> 状态流转：`待规划`（尚无方案）→ `规划中`（Planner 产出方案中）→ `已规划`（方案就绪，可执行）→ `WIP`（开发中）→ `Done`（已完成）
> 其他状态：`Ongoing`（长期任务）、`Rejected`（明确拒绝）、`Abandoned`（已废弃）
>
> 任务详情按统一结构组织（状态 / 背景 / 方案 / 分析 / 验收），作为角色间文件交接协议。

## 任务总览

| 状态    | 阶段     | 序号 | 任务                         |
| ------- | -------- | ---- | ---------------------------- |
| Done | Phase 1  | 1.3  | 黄金查询用例管理             |
| 待规划  | Phase 1  | 1.4  | 黄金用例评估体系扩展         |
| Done    | Phase 2  | 2.2  | 聚类标题生成效果差           |
| Done    | Phase 2  | 2.3  | 聚类详情页 UI 优化           |
| 待规划  | Phase 3  | 3.2  | 多轮对话上下文感知           |
| 待规划  | Phase 3  | 3.3  | 摄影报告生成                 |
| Done    | Phase 3  | 3.4  | 主题发现选题相似度过高       |
| 待规划  | Phase 4  | 4.1  | 发布历史分析                 |
| 待规划  | Phase 4  | 4.2  | 系列感维护                   |
| 待规划  | 工程     | R4   | 重构 agent 和 web 的调用代码 |
| Done    | 缺陷修复 | B1   | 主题发现返回空结果           |
| 待规划  | 缺陷修复 | B2   | 时间线规律维度无候选         |
| 待规划  | 缺陷修复 | B3   | parseVlmAttrs 解析失败静默   |
| Done    | 缺陷修复 | B4   | 三阶段主路径 Stage 2 RAG 检索失败 |
| Done    | 缺陷修复 | B5   | 三阶段主路径前置检查缺失     |
| Done    | 缺陷修复 | B6   | _fetch_all_photos 仅返回 300 张 |
| Done    | 工程     | R5   | 选题模块 JSON 解析逻辑重复   |
| Done    | 缺陷修复 | B7   | 三阶段主路径 Embedding 配置部署缺失 |
| 待规划  | 缺陷修复 | B8   | Stage 3 LLM photo_id 无校验（幻觉风险） |
| 待规划  | 缺陷修复 | B9   | 三阶段选题时间跨度约束未强制执行 |
| 待规划  | 工程     | R6   | suggest.py 内联 import re 提升到模块级别 |
| Done    | 工程     | E4   | 网页 Favicon                 |
| Done    | 工程     | E5   | 清理遗留代码与数据           |

---

## 产品定位决策

**从**："个人摄影资产 AI 助手"（泛化，容易堆砌技术）
**到**：「AI 选题助手」，AI 像员工提案，用户像主编审阅。

核心 workflow：拍摄→入库→AI 定期推送选题建议（推荐照片组合 + 发角度）→用户判断选哪个、如何微调→用户自己发布。

**主动不做的事**：

- 不自动发布到社交平台（发送由用户操作）
- 不替代审美判断（AI 推荐，用户决策）
- 不做多模态检索/以图搜图（选题场景不需要）

---

## 拒绝清单（明确砍掉的技术点及其理由）

以下方向已判定为"展示驱动"而非"需求驱动"，明确不做：

- **混合检索**：个人照片库检索准确率够用，混合检索的额外复杂度对选题场景无收益
- **RAG 重排序**：Top-K 精度不足前不做优化。先建评估基线再看是否必要
- **异步后台同步**：300 张照片，启动同步耗时可接受
- **Prometheus 监控**：单机个人工具，出问题看日志足够
- **本地 Embedding 模型**：300 张 Embedding 费用极低，无降本需求
- **proto-first 迁移**：API 数量少，手写维护成本低
- **语音输入**：选题场景无移动端需求
- **多语言支持**：中文用户不需要
- **负样本学习优化 Embedding**：数据量不足以支撑

---

## 任务详情

### Phase 1

### 1.3 黄金查询用例管理

- **状态**：Ongoing
- **背景**：黄金查询用例定义在 `agent/chain/evaluation.py` 的 `DEFAULT_EVAL_QUERIES`（当前 7 条），硬编码在代码中，覆盖不足且难以维护。需要从"代码写死"转变为"数据驱动"，提供 Web 管理界面，支持从日常对话中一键保存为黄金用例，逐步积累高质量评估集。
- **方案**：
  - 数据存储：Agent 层 JSON 文件 `agent/data/golden_queries.json`，字段含 id / query_text / relevant_photo_ids / category / notes / created_at / updated_at
  - Python Agent 新增 API：`GET/POST/DELETE /api/golden-queries`
  - Web 前端：对话页增加"保存为黄金用例"按钮，新增独立管理页面（路由 `#/golden-queries`），侧边菜单新增入口
  - 评估脚本改为从 JSON 文件加载用例，替代硬编码
- **分析**：-
- **验收**：
  - [ ] Web 对话页可一键保存提问为黄金用例（含自动解析关联照片）
  - [ ] 黄金用例管理页可列表查看、展开详情、删除用例
  - [ ] 评估脚本从 `golden_queries.json` 加载用例并正常运行
  - [ ] 评估基线指标记录到 `docs/eval/baseline.md`

### 1.4 黄金用例评估体系扩展

- **状态**：待规划
- **背景**：当前评估仅覆盖 RAG，需探索更多 use case（Text-to-SQL / Combined / Tool / 多轮对话）并建立对应评估方法。
- **方案**：-
- **分析**：-
- **验收**：-

---

### Phase 2

### 2.2 聚类标题生成效果差

- **状态**：已规划
- **背景**：聚类标题输出"内容未识别"类无意义结果。根因两个：① SQLite 中照片的 objects/colors/scene/lighting/mood 字段全为空，Go 后端 AutoSync 只把原始文本存为 description，未解析 VLM JSON 提取结构化字段；② cluster.py 的 `_build_photo_info_text()` 只拼结构化属性字段，模板没用 description。
- **方案**：
  - 改动 1 — Go 后端新增 `parseVlmAttrs()`，从描述文本中提取 JSON 代码块，解析并映射到 objects/colors/scene/lighting/mood 字段，在 `syncImportPhoto` 和 `syncUpdatePhoto` 中调用
  - 改动 2 — cluster.py 的 `_build_photo_info_text()` 模板同时纳入结构化属性 + 截断的描述文本（前 200 字），`_THEME_SYSTEM_PROMPT` 增加引导：优先从描述文本理解视觉内容
- **分析**：2026-07-26 诊断确认上述根因。原描述文本中的结构化 JSON 信息未被解析利用，聚类标题生成时信息不足，导致 LLM 无法输出有意义的标题。
- **验收**：
  - [ ] AutoSync 后照片的 objects/colors/scene/lighting/mood 字段有值
  - [ ] 聚类标题不再是"内容未识别"类无意义输出
  - [ ] 已有照片批量补齐（重跑 AutoSync 即可）

### 2.3 聚类详情页 UI 优化

- **状态**：已规划
- **背景**：详情弹窗中「评估标题」按钮触发全局评估，评估结果展示在弹窗底部独立区域，用户需要在簇卡片和底部评估结果之间来回对照。
- **方案**：
  - 评估结果内嵌到每个簇卡片内部，按 cluster_id 分组展示
  - 弹窗顶部新增「全部生成」「全部评估」按钮，含二次确认弹窗（可选全部/仅含错误的簇）
  - 汇总信息区展示评估通过率概览，跨簇规则（diverse_labels）结果也在汇总区
  - 每个簇卡片可独立重新评估标题
  - 新增 API：`POST /api/cluster/results/{id}/generate-all-themes`、扩展 `evaluate-themes` 支持 cluster_ids 参数、新增 `POST .../clusters/{clusterId}/evaluate-theme`
  - 方案文档：[2026-07-26-cluster-detail-ui-redesign.md](design/2026-07-26-cluster-detail-ui-redesign.md)
- **分析**：-
- **验收**：
  - [ ] 评估结果展示在每个簇卡片内部，不再在弹窗底部独立列出
  - [ ] 「全部生成」「全部评估」按钮在弹窗顶部工具栏可见，含二次确认弹窗
  - [ ] 确认弹窗支持"全部处理"和"仅处理含错误的结果"两种范围选择
  - [ ] 每个簇卡片可独立重新评估标题
  - [ ] 评估通过率在汇总信息区可见

---

### Phase 3 — 让选题「有角度」

**问题**：不知道发什么，经常没灵感就断更。
**目标**：AI 定期扫描照片库，主动推送选题建议，像员工提案一样给"主编"审阅。

> Phase 3.1（潜在主题识别）已在 v1.0.6 完成，详见 [归档文档](archive/v1.0.6.md)。

### 3.2 多轮对话上下文感知

- **状态**：待规划
- **背景**：选题讨论需要更自然的对话体验。当前每次查询独立，不支持指代上一轮结果或叠加条件。`RouterState` 需扩展 `history` 字段，支持指代消解（"上一组"→引用上一轮结果）、条件追加（"只要有人物的"→在当前基础上叠加）、否定和扩展。
- **方案**：-
- **分析**：-
- **验收**：支持 4 类追问（指代/追加/否定/扩展），准确率 ≥ 80%

### 3.3 摄影报告生成

- **状态**：待规划
- **背景**：用户需周期性复盘"我这一年拍了什么、风格怎么变的"。复用 Go 后端 `/api/photos/stats` + Chroma 聚类结果，设计 Markdown 报告模板（概览/器材/时间/风格/创作建议），CLI 新增 `--report [year]` 模式。
- **方案**：-
- **分析**：-
- **验收**：输出完整 Markdown 报告，引用具体数据和照片示例

### 3.4 主题发现选题相似度过高

- **状态**：Done
- **背景**：主题发现（`suggest.py`）产出的选题建议中，每组照片都是时间接近、场景接近、风格接近的高相似度组合。不符合功能设计初心——发现用户在图库中没轻易看到的角度。
- **方案**：[2026-07-27-suggest.md](design/2026-07-27-suggest.md)——三阶段编辑视角提案：① 随机采样 → LLM 主题直觉；② RAG + 多样性约束扩展选片；③ LLM 提案。原有三维度保留为备选回退路径。
- **分析**：核心矛盾是算法在找共同点，但选题发现的价值在对比/连接。2026-07-27 评估（[eval-3.4-2026-07-27.json](../data/eval_reports/eval-3.4-2026-07-27.json)）：总分 4.2/10，评估不通过。主路径因 Go 后端 embedding 代理不可用而 100% 回退到旧版三维度，实际选题建议与改进前一致。相关问题已记录为 B4/B5/B6/R5。
- **验收**：
  - [x] 选题提案中至少包含 5 张照片（代码侧 `_STAGE2_MIN_PHOTOS = 5` 约束）
  - [x] 照片时间跨度 > 7 天（Stage 2 多样性采样按日期分组，至多每日期 2 张）
  - [x] 叙事角度描述可被理解为有发布价值（Stage 3 LLM prompt 要求叙事角度 30-60 字）
  - [ ] 运行时验证：实际运行 suggest API，确认选题提案效果

---

### Phase 4 — 让选题「有策略」

**问题**：发了很多组后，整体账号是什么调性？缺什么类型？长期发展没有方向。
**目标**：基于发布历史分析，提供账号级内容策略建议。

### 4.1 发布历史分析

- **状态**：待规划
- **背景**：用户标记"已发布"后，统计分析已发主题分布、频率、时间规律，识别缺口（如"风光 70%、人像 20%、街拍 10%，建议补一组街拍"），让用户像主编看"季度选题板"。
- **方案**：-
- **分析**：-
- **验收**：可查看发布历史主题分布，AI 建议"下个月的选题方向"

### 4.2 系列感维护

- **状态**：待规划
- **背景**：跨时间线主题提取（LLM 总结同一季节不同年份的共同主题），发现"对比/延续/变奏"系列（如上个月发了"雨天"系列，这个月补"晴天的同一场景"对比），让账号内容从散装发布到有系列感。
- **方案**：-
- **分析**：-
- **验收**：AI 能识别并建议"对比系列"（如雨天 vs 晴天、2023 vs 2024 同一地点）

---

### 工程

### R4 重构 agent 和 web 的调用代码

- **状态**：待规划
- **背景**：当前 agent 和 web 之间的 API 调用代码为手写，缺乏类型安全和一致性。需生成相应语言的 SDK，替换现有调用代码。
- **方案**：-
- **分析**：-
- **验收**：-

---

### 缺陷修复

### B1 主题发现返回空结果

- **状态**：Done
- **背景**：点击"生成选题建议"提示"未发现候选选题方向"，疑似结构化属性未正确填充导致三个分析维度全空。
- **方案**：[2026-07-27-b1-topic-discovery-empty-fix.md](design/2026-07-27-b1-topic-discovery-empty-fix.md)
- **分析**：2026-07-27 诊断确认根因。SQLite 中 1177 张照片的 objects/colors/scene/lighting/mood 全部为空，但 descriptions.json 中 VLM JSON 块完整。因果链：AutoSync 首次运行时 parseVlmAttrs 尚未实现 → 仅写入 description 文本 → 后续 commit 增加了 parseVlmAttrs 但 syncUpdatePhoto 仅在 description 变化时触发 → 已有照片 description 未变 → 永不会回填属性。与 B2.2 同源但 B1 无 fallback（suggest.py 只能读结构化属性，cluster.py 可读 description 文本）。
- **验收**：
  - [ ] AutoSync 后结构化属性字段有值
  - [ ] suggest API 返回 3-5 个选题建议
  - [ ] CLI `--suggest` 正常输出

### B2 时间线规律维度无候选

- **状态**：待规划
- **背景**：B1 修复后，suggest API 的高频未成组和稀缺优质维度正常产出候选，但时间线规律维度始终返回 0 个候选。诊断日志提示「缺少 shot_at 时间信息、月份照片不足 3 张、或无跨年份规律」。该维度的目标是：发现用户在不同年份的同一月份都有拍摄行为（如每年 3 月都拍花、每年 10 月都拍秋景），从而主动提醒“你每年这个时候都有好照片，今年要不要继续拍一组？”
- **方案**：-
- **分析**：当前 photos 表中 shot_at 字段可能大量为空，导致 `_find_temporal_patterns` 无法按月份分组统计。需要先确认 shot_at 的数据覆盖率，再判断是数据导入问题还是 EXIF 元数据缺失。
- **验收**：-
  - [ ] 确认 shot_at 字段覆盖率
  - [ ] 如数据可用，时间线规律维度产出 ≥ 1 个候选

### B3 parseVlmAttrs 解析失败静默

- **状态**：待规划
- **背景**：评估 B1 修复时发现，`parseVlmAttrs` 在正则匹配失败或 JSON 解析失败时静默返回空字符串，不记录任何日志。异常照片每次 AutoSync 都会重试解析失败，产生无意义的数据库 UPDATE，但运维人员无法从日志中发现。
- **方案**：-
- **分析**：当前 1177 张照片中约 3-4 张属性为空（填充率 99.7%），可能是 VLM JSON 格式异常导致解析失败。静默失败让这类问题不可观测。
- **验收**：-
  - [ ] parseVlmAttrs 解析失败时输出 warning 日志（含 photo ID）
  - [ ] 异常照片不会每次 AutoSync 都重复尝试

### B4 三阶段主路径 Stage 2 RAG 检索失败

- **状态**：Done
- **背景**：评估 3.4「主题发现选题相似度过高」时发现，三阶段编辑视角提案的主路径运行时 100% 回退到旧版三维度。根因是 Stage 2 的 RAG 检索调用 Go 后端 `/v1/embeddings` 代理接口，该接口因 Go 端 `Embedding` 配置段不存在（且 VLM 回退的 BaseURL 也为空）而恒定返回 500。
- **方案**：[2026-07-27-b4-b5-b6-r5-fixes.md](design/2026-07-27-b4-b5-b6-r5-fixes.md)——两个改动：① 配置模板 Go 段补充 `Embedding` 结构（仅 `APIKey` 占位，Model/BaseURL 由 Go struct default tag 提供，实际值在 `.local/pancake.yaml` 中）；② `callVolcengineEmbedding` 错误日志增强（包含火山引擎响应体），空 BaseURL 时直接返回明确错误。可选：Go 启动时配置校验。
- **分析**：Python agent 侧的 `embedding` 配置段（含 APIKey/BaseURL/Model）已配置，但 Go 后端的 embedding 代理读取的是 Go 端配置（`conf.C.Embedding`）。Go 配置文件中只有 VLM 段且缺少 APIKey/BaseURL，导致 `getEmbeddingConfig()` 回退到的值全为空。当前 3 个主题直觉的 3 次 RAG 检索全部失败，用户实际看到的选题建议与改进前完全一致。
- **验收**：
  - [ ] `configs/config.yaml` 包含 `Embedding` 段（含 APIKey/Model/BaseURL）
  - [ ] embedding 不可用时，Go 后端返回明确错误信息（含火山引擎响应体），而非仅 `"status code : XXX"`
  - [ ] Go 后端 `/v1/embeddings` 可正常调用并返回 embedding 向量

### B5 三阶段主路径前置检查缺失

- **状态**：Done
- **背景**：评估 3.4 时发现，Stage 1 会在 embedding 服务不可用时仍然消耗 LLM token 生成主题直觉（本次评估中 3 个直觉的 LLM 调用白白浪费），然后因 Stage 2 RAG 全部失败而丢弃。当前代码只在 RAG 调用失败时 catch 异常，但没有在进入三阶段流程前做前置可用性检查。
- **方案**：[2026-07-27-b4-b5-b6-r5-fixes.md](design/2026-07-27-b4-b5-b6-r5-fixes.md)——Go 侧新增 `GET /v1/embeddings/health` 端点，Python 侧 `run_suggest` 在 Stage 1 之前调用健康检查，不可用时直接走回退路径。
- **分析**：三阶段主路径的 LLM 调用次数 = Stage 1（1 次）+ Stage 3（最多 intuition 数量次）。如果 embedding 不可用，所有这些 LLM 调用都浪费了。应在进入 Stage 1 之前先做一个轻量的 embedding 健康检查。
- **验收**：
  - [ ] embedding 不可用时，跳过三阶段主路径直接走回退，不消耗 LLM token
  - [ ] 日志中明确记录跳过原因

### B6 _fetch_all_photos 仅返回 300 张照片

- **状态**：Done
- **背景**：评估 3.4 时发现，suggest API 的 `_fetch_all_photos` 仅返回 300 张照片，而数据库实际有 1,177 张。Stage 1 的随机采样池缩小到 300 张（实际可用 1,177 张），降低了采样的日期覆盖度和偶然发现能力。
- **方案**：[2026-07-27-b4-b5-b6-r5-fixes.md](design/2026-07-27-b4-b5-b6-r5-fixes.md)——根因是 Go handler `SearchPhotos` 用未截断的 `page_size=500` 计算 `totalPages = ceil(1177/500) = 3`，而 DAO 层实际 SQL 查询被截断到 100，导致只取了 3×100=300 张。修复：Go handler 中前置 page_size 截断（与 DAO 一致），Python 侧 `page_size` 改为 100。
- **分析**：`_fetch_all_photos` 使用 SDK 的 `photo_service_search_photos(page=1, page_size=500)` 分页获取，日志显示两个分页 request 返回后总计 300 张。可能是 Go 后端 `SearchPhotos` API 有默认 limit，或 SDK 的分页参数未正确传递。需要排查 Go 后端或 SDK 的分页逻辑。
- **验收**：
  - [ ] `_fetch_all_photos` 返回的照片数量与数据库实际数量一致
  - [ ] Go 后端 `SearchPhotos` 在任意 `page_size` 入参下 `totalPages` 计算正确

### R5 选题模块 JSON 解析逻辑重复

- **状态**：Done
- **背景**：评估 3.4 时发现，`_parse_intuitions_response`（Stage 1 用）和 `_parse_legacy_response`（回退路径用）约 80% 逻辑相同（直接解析 → strip markdown → 正则提取数组 → 逐对象提取），各自约 40 行。
- **方案**：[2026-07-27-b4-b5-b6-r5-fixes.md](design/2026-07-27-b4-b5-b6-r5-fixes.md)——提取公共函数 `_parse_llm_json_response(raw, context_label)`，两个现有函数改为一行调用。纯重构，不改变行为。
- **分析**：两份函数的核心差异仅在日志前缀和返回类型推断（list vs dict），可提取公共 `_parse_llm_json_response(raw, context)` 减少约 50 行重复代码。当前 `suggest.py` 共 1249 行，其中约 100 行是 JSON 解析相关。
- **验收**：
  - [ ] 合并后的公共函数覆盖所有现有解析场景
  - [ ] 现有 suggest API 测试通过

### B7 三阶段主路径 Embedding 配置部署缺失

- **状态**：Done
- **背景**：2026-07-27 重新评估 3.4（eval-3.4-v2-2026-07-27.json，总评 5.8/10）后发现，三阶段主路径仍无法运行。根因是 `.local/pancake.yaml` 的 Go 配置段缺少 `Embedding.APIKey` 字段，且 VLM 回退的 `APIKey`/`Model`/`BaseURL` 在 Go 段也为空，导致 `getEmbeddingConfig()` 两次回退后 `BaseURL` 为空字符串。Go 代码的 `Embedding.Model` 和 `Embedding.BaseURL` 已有正确默认值（`doubao-embedding-vision-251215` / `https://ark.cn-beijing.volces.com/api/v3`），仅缺少 `APIKey`。
- **方案**：（用户）在 `.local/pancake.yaml` Go 段添加 Embedding 配置段（含 APIKey/Model/BaseURL）
- **分析**：Python 配置段已有完整的 `embedding.api_key: ark-d4a72e66-...`，只需在 `.local/pancake.yaml` 的 Go 段添加 Embedding 配置即可。这是一个单行配置修复，不属于代码缺陷。
- **验收**：
  - [x] `.local/pancake.yaml` Go 段添加 `Embedding.APIKey`
  - [x] Go 后端 `/v1/embeddings/health` 返回 `{"status":"ok"}`
  - [x] suggest API 三阶段主路径可正常执行（meta.pipeline = editorial_three_stage）

### B8 Stage 3 LLM photo_id 无校验（幻觉风险）

- **状态**：待规划
- **背景**：2026-07-27 第三次评估 3.4（eval-3.4-v3-2026-07-27.json，总评 7.0/10）时发现，'水岸的生命剧场'选题中 LLM 将 photo_id `a2393959-2fb2-41f8-8299-b2a4f973be8c` 误输出为 `a2393959-2fb2-41f8-8299-b2a4f3be8c`（UUID 倒数第二段 `973be8c` 被截断为 `3be8c`），导致 API 响应中包含无效的照片引用。Stage 3 代码（`_stage3_generate_proposals`）对 LLM 返回的 photo_ids 未做任何数据库存在性校验。
- **方案**：-
- **分析**：LLM 在精确复制 UUID 上存在固有弱点。应在 `_stage3_generate_proposals` 中对 LLM 返回的每个 photo_id 做校验：存在于 expanded 列表中则保留，不存在则从 expanded 中取未使用的真实 ID 替换。
- **验收**：-
  - [ ] Stage 3 返回的 photo_ids 全部经过数据库存在性校验
  - [ ] 无效 ID 有明确的修复策略（替换而非丢弃）

### B9 三阶段选题时间跨度约束未强制执行

- **状态**：待规划
- **背景**：2026-07-27 第三次评估 3.4 时发现两个时间跨度问题：(1) '水边的独白' 6 张照片仅跨越约 22 小时（Feb 2-3），不满足设计方案验收标准「> 7 天」；(2) '人鸥之间' 中 3 张海鸥照来自同一拍摄会话（同一上午 21 分钟内）。Stage 2 多样性约束（`_STAGE2_MAX_PER_DATE=2`）保证了 RAG 候选的日期分散，但 Stage 3 LLM 在从 30 张候选中选择最终照片序列时不受时间跨度约束。此外，时间跨度验收标准目前仅为日志输出，未作为硬约束。
- **方案**：-
- **分析**：根因在于约束位置——Stage 2 做了日期多样性，但 Stage 3 的 LLM 自由选择最终序列时可以绕过。可能的改进方向：在 Stage 3 prompt 中增加时间多样性要求，或在后处理阶段对 LLM 返回的 photo_sequence 做时间跨度校验。
- **验收**：-
  - [ ] 每条选题的照片时间跨度 ≥ 设计标准
  - [ ] 同日期照片在最终序列中的数量有上限约束

### R6 suggest.py 内联 import re 提升到模块级别

- **状态**：待规划
- **背景**：R5 合并 JSON 解析逻辑后，`import re` 仍在 `_parse_llm_json_response`（第 207 行）和 `_parse_proposal_response`（第 481 行）两处函数体内联。作为项目公共函数，提升到模块顶部更符合 Python 惯例，也能避免每次调用时重复导入的微开销。
- **方案**：-
- **分析**：问题不影响功能，属于代码风格 cleanup。`re` 模块是 Python 标准库，提升到模块顶部无任何副作用。
- **验收**：-
  - [ ] `import re` 提升到模块顶部，删除函数体内的两处内联 import

---

### Done

以下条目已完成，仅保留表格记录，不再展开详情：

- **E4 网页 Favicon**：仓库根目录 favicon/ 放置 SVG favicon，web/public 通过 symlink 引用。
- **E5 清理遗留代码与数据**：删除 extract_attributes.py，清理 descriptions.json 的 shot_at 字段，清理 Go/Python 中结构化属性传递代码。

---

## 决策历史

- **2026-06-05**：产品定位从"摄影资产助手"收敛为"AI 选题助手"，废弃 25 项优化点，按 roadmap 四阶段重建 backlog。原有 task_3.md 技术点已吸收或明确拒绝。
- **2026-06-11**：合并 `docs/upgrade.md` 到本文档。upgrade.md 为旧产品定位下的技术升级规划，其中 Prometheus 监控、异步后台同步、proto-first 迁移已被新定位明确拒绝；SQLite WAL 已纳入工程小改进；其余优化项（以图搜图、EXIF/GPS、多模态 Embedding 等）与新定位"主动不做的事"一致，不再单独维护。upgrade.md 已删除，CLAUDE.md 文档层级以 backlog.md 替代。
- **2026-07-26**：v1.0.6 版本归档。Phase 0/1/2 全部完成，Phase 3.1 完成，工程改进 E1-E3 及重构 R1-R3 完成。已完成条目迁至 `docs/archive/v1.0.6.md`。
- **2026-07-27**：backlog 条目描述格式规范化。删除表格「简述」列，任务详情统一为结构化字段（状态 / 背景 / 方案 / 分析 / 验收），作为角色间文件交接协议。
