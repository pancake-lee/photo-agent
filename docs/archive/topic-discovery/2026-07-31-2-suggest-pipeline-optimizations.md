# 主题发现交互式管线后续优化 — 方案设计

> 中枢文档：[2026-07-27-5-topic-discovery-hub.md](2026-07-27-5-topic-discovery-hub.md) — 本专题全部关联产物的汇总入口
>
> 本文档覆盖 3.8 交互式管线评估（7.3/10）发现的四个衍生优化任务（B13 / 3.9 / B12 / 3.10），以及用户提出的管线产出简化（3.11）。
>
> **评估**：7.3/10（结构清晰度 8 / 决策合理性 8 / 验收可执行性 7 / 代码一致性 5 / 方案完整性 7），详见 [评估报告](../../eval/reports/2026-07-31-suggest-pipeline-optimizations-design.json)

## 1. 任务概览

| 编号 | 名称 | 类型 | 体量 | 优先级 |
|------|------|------|------|--------|
| B13 | 双存储写入冗余 | 技术消债 | 中等 | P0（为后续改动减负） |
| **3.11** | **管线产出简化：每次仅生成 1 个选题** | **简化重构** | **小** | **P0（数据模型统一）** |
| 3.9 | 管线步骤可视化增强 | 功能补全 | 中等偏大 | P1（用户感知最强） |
| B12 | 手动选题直觉模式下照片被忽略 | 交互修复 | 小 | P2 |
| 3.10 | 选题版本对比功能 | 功能增强 | 中等 | P3 |

建议执行顺序：**3.11 → B13 → 3.9 → B12 → 3.10**。理由：3.11 先统一数据维度（一次运行=一条记录），B13 统一存储（一个文件=唯一数据源），两个消债任务做完后，后续功能开发的复杂度大幅降低。

---

## 2. B13：双存储写入冗余

### 2.1 问题

选题历史同时维护 `suggest_history.json`（v1）和 `suggest_history_v2.json`（v2）两份文件。每次写入操作（run / rating / delete / manual-run / rerun）需同步更新两份数据，涉及 server.py 中 12 处写入点。v1 为纯兼容层，当前无实际消费者依赖旧格式。

存储函数四对（load/save × v1/v2）代码高度重复，仅文件名不同。

### 2.2 方案

**翻转依赖方向**：v2 成为唯一数据源，v1 不再独立存储。读取 v1 格式时从 v2 数据动态生成。

具体改动：

1. **删除 v1 写入**：5 个写入端点（`run` / `rating` / `delete` / `manual-run` / `rerun`）移除所有 `_suggest_history_lock` + `_save_suggest_history` 调用，只保留 v2 写入
2. **v1 列表接口改为从 v2 生成**：`GET /api/suggest/history` 从 `_load_suggest_history_v2` 读取，将每条 v2 记录投影为 v1 扁平格式（去掉 `versions`、`current_version_id`，从 active version 提取 `title`/`angle`/`photo_ids` 等字段）
3. **合并存储函数**：将 `_load_suggest_history_v2` / `_save_suggest_history_v2` 重命名为 `_load_suggest_history` / `_save_suggest_history`（去掉 v2 后缀），旧的 v1 函数删除。锁统一为一个 `_suggest_history_lock`
4. **保留旧文件**：`suggest_history.json` 不再写入，但不删除（方便用户回退时需要）。可在后续版本清理

### 2.3 关键决策

- **懒迁移**：保留现有 `_migrate_to_v2` 逻辑。GET detail 时若在 v2 中找不到记录，回退查旧 v1 文件并懒迁移（只读 v1，不写回）
- **rating / delete 的 v1 兼容**：rating 直接操作 v2 item 的 top-level `rating` 字段；delete 直接删除 v2 item。列表接口从 v2 生成时自然反映最新状态
- **不删除旧文件**：`suggest_history.json` 保留不删，但标记为 deprecated。后续用户确认无问题后可手动删除

### 2.4 范围

| 文件 | 变更 |
|------|------|
| `agent/chain/server.py` | 合并存储函数、移除 v1 写入、列表接口改为从 v2 生成 |
| 前端 | 无改动（API 响应格式不变） |

### 2.5 验收

- [x] `GET /api/suggest/history` 返回的数据与当前一致（字段、顺序、数量）
- [x] run / rating / delete / manual-run / rerun 五个端点功能正常
- [x] 旧 v1 文件中仍有数据时，detail 懒迁移正常工作
- [x] 无并发写入问题

---

## 3. 3.9：管线步骤可视化增强

### 3.1 问题

3.8 评估发现三个层次的问题：

1. **步骤卡片无照片缩略图**：设计文档 2.2 节明确提到「照片缩略图网格」，但展开态仅展示 JSON 数据和 payload 文本。用户看到的是 `photo_ids: ["abc123...", "def456..."]`，而非直观的照片网格
2. **编辑器偏技术化**：编辑步骤数据依赖 JSON 文本框。对于「修改直觉」这个操作，用户需要理解 `intuitions` 数组格式和 `inspired_indices` 字段。虽然部分步骤类型（采样、RAG）已使用照片选择器，但直觉/提案/校验步骤仍是原始 JSON
3. **重跑无进度反馈**：rerun 端点耗时 30-60 秒（LLM 调用），前端只显示一个小 spinner，用户不知道执行到哪个阶段

### 3.2 方案

#### 3.2.1 步骤卡片：照片缩略图网格

步骤卡片展开态中，当 `step.data` 包含 `photo_ids` 字段时，额外渲染一个照片缩略图网格。

- 调用 Go 后端 `/api/v1/photos?ids=...` 按 ID 批量加载照片（含 `thumbnail_url`）
- 网格布局：每行 4-6 张，缩略图尺寸约 80×80px，hover 显示描述/文件名
- 降级：照片加载失败时显示 photo_id 文本（相当于当前行为）

需要增强的步骤类型：

| 步骤 event | 展示内容 |
|-----------|---------|
| `suggest.stage1.sample` | 采样照片网格 |
| `suggest.stage2.rag.end` | RAG 匹配照片网格 |
| `suggest.stage2.diversity` | 过滤后照片网格 |
| `suggest.stage3.validation` | 最终照片序列（带叙事角色标注） |

#### 3.2.2 编辑器：结构化表单

将 JSON 文本编辑器替换为结构化表单（按步骤类型）：

| 步骤 event | 当前编辑器 | 改为 |
|-----------|-----------|------|
| `suggest.stage1.intuitions` | JSON 文本框 | 结构化表单：标题 + 角度 + 理由 + 启发照片选择器 |
| `suggest.stage3.proposal` | JSON 文本框 | 结构化表单：标题 + 角度 + 理由 + 照片序列（拖拽排序 + 叙事角色输入） |
| `suggest.stage3.llm.end` | JSON 文本框 | 同 proposal |
| `suggest.stage1.llm.start` / `suggest.stage3.llm.start` | 文本框 | 保持文本框（prompt 编辑确实是文本场景） |
| `suggest.stage1.sample` / RAG 步骤 | 照片选择器（已实现） | 保持不变 |

#### 3.2.3 重跑进度反馈

采用 SSE（Server-Sent Events）推送阶段进度：

- 后端：rerun 端点改为 SSE 响应。在 Stage 1/2/3 开始和完成时推送事件
- 前端：`useSuggestDetail` 中 `rerunFromStep` 改为 EventSource 连接，暴露 `rerunProgress` 状态（当前阶段 + 进度文本）
- UI：在详情 Modal 右侧顶部显示阶段进度条（Steps 组件），替代纯 spinner

事件格式：
```json
{"event": "progress", "data": {"stage": 1, "label": "Stage 1 灵感发现", "status": "running"}}
{"event": "progress", "data": {"stage": 1, "label": "Stage 1 灵感发现", "status": "done"}}
{"event": "complete", "data": {"detail": {...}}}
{"event": "error", "data": {"message": "..."}}
```

### 3.3 关键决策

- **照片批量加载时机**：步骤卡片展开时才加载（懒加载），避免首次打开详情时请求过多照片
- **缩略图缓存**：同一 session 内已加载的照片由 composable 缓存，不重复请求
- **SSE vs WebSocket**：选 SSE，因为只需单向推送（服务端→客户端），不需要双向通信。rerun 期间只推 3-6 个事件
- **编辑器渐进增强**：先做直觉/提案的结构化表单（最高频编辑场景），其他步骤保持 JSON 编辑作为 fallback

### 3.4 范围

| 文件 | 变更 |
|------|------|
| `web/src/components/SuggestStepCard.vue` | 增加照片缩略图网格（展开态） |
| `web/src/components/SuggestStepEditor.vue` | 直觉/提案步骤改为结构化表单 |
| `web/src/composables/useSuggestDetail.ts` | 增加照片缓存、SSE 进度连接、rerunProgress 状态 |
| `web/src/components/SuggestDetailModal.vue` | 重跑进度条替代纯 spinner |
| `web/src/types/suggest.ts` | 新增 `RerunProgress` 类型 |
| `agent/chain/server.py` | rerun 端点改为 SSE 响应，阶段间推送事件 |
| `agent/chain/suggest.py` | 无需改动（rerun 端点本身已知道当前在哪个阶段） |

### 3.5 验收

- [x] 采样/RAG/校验步骤展开时显示照片缩略图网格
- [x] 缩略图 hover 显示文件名/描述
- [x] 编辑直觉步骤时使用表单而非 JSON 文本框
- [x] 重跑时显示阶段进度（Stage 1/3 → Stage 2/3 → Stage 3/3）
- [x] 重跑失败时显示错误信息（替代"请求失败"）
- [x] 照片加载失败时降级显示 photo_id 文本

---

## 4. B12：手动选题直觉模式下照片被忽略

### 4.1 问题

`manual-run` 端点（server.py:1281-1291）中，当用户同时提供 `intuition` 和 `photo_ids` 时，`_stage1_generate_intuitions` 检测到 `intuitions_override` 非空后走 early return（suggest.py:314），完全忽略 `photo_ids_override`。用户选择的照片被静默丢弃，只有直觉文本进入流程。

设计文档 2.5 节说"若提供了直觉，跳过 Stage 1 LLM，直接进入 Stage 2+3"，本意是跳过 LLM 直觉生成，但用户视角是"我选了照片 + 填了直觉，两者应该都生效"。

### 4.2 方案

**让用户的照片和直觉同时生效**：当两者都提供时，跳过 Stage 1 LLM 和 Stage 2 RAG，直接将用户照片作为候选池送入 Stage 3 LLM。

具体改动：

1. **后端** `manual-run` 端点：当 `intuition` 和 `photo_ids` 同时非空时，将用户照片传入 `_stage3_generate_proposals` 的 `expanded_photos_override` 参数（跳过 RAG）。仅提供直觉无照片时保持现有行为（走 RAG）；仅提供照片无直觉时保持现有行为（走完整管线）
2. **前端** `SuggestManualModal`：Step 2 填写直觉时，如果已选了照片，显示提示文字"你选择的照片将作为 AI 选题的候选池，AI 将在这些照片中选择最佳组合"
3. **前端** 按钮文案：hasIntuition && selectedPhotos.length > 0 时按钮文案改为"用我选的照片生成选题"

### 4.3 范围

| 文件 | 变更 |
|------|------|
| `agent/chain/server.py` | manual-run 端点：照片+直觉同时存在时传入 expanded_photos_override |
| `agent/chain/suggest.py` | 无需改动（override 参数已就绪） |
| `web/src/components/SuggestManualModal.vue` | 增加提示文字 + 动态按钮文案 |

### 4.4 验收

- [x] 选照片 + 填直觉 → 生成的选题照片全部来自用户所选照片池
- [x] 仅填直觉 → 行为不变（跳过 Stage 1，走 RAG）
- [x] 仅选照片 → 行为不变（走完整管线）
- [x] Step 2 界面上有明确的照片-直觉关系说明

---

## 5. 3.10：选题版本对比功能

### 5.1 问题

版本管理支持切换查看不同版本，但缺少两个版本之间的差异对比。用户切换版本后只能靠人工逐字段对比，效率低。

### 5.2 方案

在版本时间线上增加对比模式：用户选择两个版本后，在右侧展示差异视图。

**交互流程**：

1. 版本时间线顶部增加「对比」按钮，点击进入对比模式
2. 对比模式下，每个版本节点增加复选框。用户勾选两个版本后自动展示差异
3. 右侧切换为差异视图，取代步骤列表
4. 再次点击「对比」按钮或点击「退出对比」退出

**差异视图内容**：

| 对比维度 | 展示方式 |
|---------|---------|
| 标题/角度/理由 | 左右双栏文本 diff（新增绿色、删除红色） |
| 照片序列 | 照片网格，新增照片高亮绿框、移除照片红框+半透明 |
| 步骤数据 | 两个版本的步骤摘要并排展示，有差异的字段高亮 |
| 照片中叙事角色变化 | 同一 photo_id 在两个版本中的 `role_in_narrative` 变化 |

**技术实现**：

- 纯前端功能，无需后端改动（版本数据已在 detail 接口中返回）
- 文本 diff：实现简单的 word-level LCS diff，或使用轻量 diff 算法（约 50 行 JS）
- 复用已有组件：版本时间线 + 照片缩略图 + 步骤摘要

### 5.3 范围

| 文件 | 变更 |
|------|------|
| `web/src/components/SuggestVersionTimeline.vue` | 增加对比模式（按钮 + 复选框） |
| `web/src/components/SuggestVersionDiff.vue` | **新建**：差异视图组件 |
| `web/src/components/SuggestDetailModal.vue` | 对比模式下右侧切换为差异视图 |
| `web/src/composables/useSuggestDetail.ts` | 增加对比状态（compareMode, selectedVersions） |
| 后端 | 无改动 |

### 5.4 验收

- [x] 可选择两个版本进行对比
- [x] 文本差异（标题/角度/理由）以 diff 形式高亮展示
- [x] 照片序列差异展示（新增/移除/叙事角色变化）
- [x] 退出对比后恢复步骤列表视图
- [x] 只有一个版本时，对比按钮不可用（灰色提示）

---

## 6. 3.11：管线产出简化 — 每次仅生成 1 个选题

### 6.1 问题

当前一次 `POST /api/suggest/run` 的行为：

```
采样 6-9 张照片 → Stage 1 LLM 生成 2-4 个直觉
→ 每个直觉分别走 Stage 2 RAG → Stage 3 LLM 生成提案
→ 2-4 个 TopicSuggestion → server.py 拆成 2-4 条历史记录
```

这导致三个层面的混乱：

1. **数据维度**：一次运行产生 N 条独立的 `suggest_history` 记录，但它们共享同一个 `trace_id` 和 `generated_at`。从存储角度看是 N 条记录，从用户心智看是"一次选题操作"
2. **展示维度**：前端列表中 N 个卡片排在一起（共享 trace_id），用户会产生"这些卡片是什么关系？"的困惑。交互式管线详情更是按 trace_id 维度设计，一个 trace_id 对应一次管线的完整过程，但 history 里面有多条记录指向同一个 trace_id
3. **性价比**：6-9 张随机采样 → 2-4 个直觉 → 多个 LLM 调用。但 3 张有代表性的照片足以激发 1 个有价值的角度

### 6.2 方案

将管线产出从"多"收窄到"1"：**每次 run 固定 3 张照片 → 1 个直觉 → 1 个提案 → 1 条历史记录**。

具体改动：

**suggest.py 常量**：
```text
_STAGE1_SAMPLE_MIN = 3  （原 6）
_STAGE1_SAMPLE_MAX = 3  （原 9）
```
`_random_sample_photos` 逻辑不变（min=max=3 时就是固定 3 张，日期多样性优先）。

**Prompt 调整**：
- `_STAGE1_SYSTEM_PROMPT`："输出 2-4 个选题直觉" → "输出 1 个最有价值的选题直觉"
- `_build_stage1_prompt`："请基于以上照片，输出 2-4 个选题直觉" → "请基于以上照片，输出 1 个选题直觉"

LLM 被约束为输出 1 个直觉后，`_parse_intuitions_response` 会返回只含 1 个元素的列表，`_stage3_generate_proposals` 的循环只执行 1 次。

**server.py run 端点**：当前用 `for s in suggestions:` 循环创建多个 history item。简化为 `suggestions` 只有 1 个元素时直接取 `suggestions[0]`。`SuggestBatchResponse` 可保留（向下兼容），`items` 数组只含 1 个元素。

**手动选题**：保持现有行为。用户可以自己选任意数量的照片。3 是"自动生成"模式的默认值，不是全局硬限制。

**备选路径**：保持现有逻辑不变（仅在 embedding 不可用时触发）。

### 6.3 关键决策

- **不是性能优化，是数据模型统一**：核心动机是让"一次运行 = 一条记录 = 一个版本链 = 一个 trace_id"，消除当前 N 条记录共享 trace_id 的多对一关系
- **3 张不是硬编码下限**：手动选题时用户可以自定义照片数量。3 是"自动生成"模式的默认值
- **Stage 2 RAG 扩展不变**：虽然只有 1 个直觉，但 RAG 检索和多样性过滤的逻辑完全不变，只是循环从 N 次变成 1 次
- **不影响交互式管线**：详情 Modal 按 trace_id 加载步骤，一次 run 只产生一个 trace_id

### 6.4 范围

| 文件 | 变更 |
|------|------|
| `agent/chain/suggest.py` | 常量改为 3/3，prompt 改为输出 1 个直觉 |
| `agent/chain/server.py` | run 端点简化循环为单记录写入 |
| 前端 | 无改动（列表和详情天然支持单条记录） |

### 6.5 验收

- [x] 每次 run 随机采样恰好 3 张照片
- [x] Stage 1 LLM 输出恰好 1 个直觉
- [x] Stage 3 LLM 输出恰好 1 个提案
- [x] 最终写入恰好 1 条历史记录
- [x] 手动选题：用户自定义照片数量不受影响
- [x] 备选路径：不受影响
- [x] 历史列表中不再出现多条记录共享同一 trace_id 的情况

---

## 7. 附：代码质量问题收尾

以下问题已在任务实现过程中验证：

| 问题 | 文件 | 说明 |
|------|------|------|
| 版本时间线最后一个节点 CSS 残留空白（`.version-item` 底部 8px padding 对末节点同样生效，仅重置了 `.version-info` 的 padding） | `SuggestVersionTimeline.vue` | 174 |

以下原列问题经代码核实不成立，已排除：

- ~~`prompt_idx = idx` 重复赋值~~：`prompt_idx` 仅在 suggest.py:796 赋值一次，790 行赋值的是 `prompt_text`，为不同变量
- ~~`_migrate_to_v2` 裸 `except Exception`~~：实际捕获 `(OSError, ValueError, KeyError, json.JSONDecodeError)`，非裸异常
- ~~`_save_suggest_history_v2` 未捕获 OSError~~：函数早已更名为 `_save_suggest_history` 且第 161 行有 `except OSError`
- ~~`_migrate_to_v2` 返回值类型标注为 `dict` 但调用方写了 `if v2_item is None`~~：函数签名实际为 `dict | None`，调用方 None 检查完全正确

建议：后续改造版本时间线组件时顺手修 CSS 空白。

---

## 7. 关联文档

- [2026-07-27-5-topic-discovery-hub.md](2026-07-27-5-topic-discovery-hub.md) — 专题中枢
- [2026-07-31-1-suggest-interactive-pipeline.md](2026-07-31-1-suggest-interactive-pipeline.md) — 3.8 交互式管线方案设计
- [2026-07-31-topic-discovery-3.8.json](../../eval/reports/2026-07-31-topic-discovery-3.8.json) — 3.8 评估报告
