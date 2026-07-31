# 主题发现交互式管线 — 人工评估 UX 修复

> 中枢文档：[2026-07-27-5-topic-discovery-hub.md](2026-07-27-5-topic-discovery-hub.md)

## 1. 初始评估发现（B16/B17/B18）

1. **卡片整卡可点击触发详情，干扰文本交互**
2. **"城市剪影志"详情无法展示步骤数据**：`steps=[]` 但 `trace_expired=false`
3. **详情 UUID 不直观**：截断字符串难以辨认照片

## 2. 已完成的修复

### 交互修复

| 编号 | 内容 | 涉及 |
|------|------|------|
| B16 | 整卡 `@click` 改为独立「详情」按钮 | `SuggestView.vue` |
| B17 | `POST /api/suggest/run` 创建时回放 trace 填充步骤；详情接口补偿空步骤 | `server.py` |
| B18 | 最终结果 UUID 文本改为缩略图网格 | `SuggestDetailModal.vue` |

### 步骤卡片照片展示增强

- **RAG 匹配结果**：全部缩略图无数量限制，每张下方显示 `distances` 和 `ratio_gaps`
- **多样性过滤**：按日期分组展示保留（绿框）/ 移除（红框）的因果关系，无移除的组不展示
- **提案解析**：全部缩略图 + `role_in_narrative` 叙事角色
- **原始数据折叠**：有照片/payload 的步骤默认折叠数据；无可视化内容的步骤默认展开

后端同步扩展：`suggest.stage2.diversity` trace 事件新增 `kept_photo_ids` 和 `diversity_details` 字段。

涉及：`SuggestStepCard.vue`（重写）、`suggest.py`（多样性数据扩展）

### 详情弹窗简化

- 移除左边栏版本时间线、版本对比功能
- 最终结果区展示全部照片，无 12 张限制

涉及：`SuggestDetailModal.vue`

### 清理回退路径代码

移除 `suggest.py` 中三维度属性分析（高频未成组 / 时间线规律 / 稀缺优质）全部相关代码：`CandidateGroup`、`_check_embedding_health`、6 个分析函数、`_LEGACY_SUGGEST_SYSTEM_PROMPT`、`_build_legacy_prompt`、`_parse_legacy_response` 等。`run_suggest` 简化为纯三阶段路径，失败直接返回错误。

同步清理：`trace_replay.py` 回退步骤、`server.py` docstring、前端分类/管线标签映射。

涉及：`suggest.py`（净删 ~580 行）、`trace_replay.py`、`server.py`、`SuggestView.vue`、`SuggestDetailModal.vue`、`types/suggest.ts`

## 3. 任务清单

| 编号 | 任务 | 状态 |
|------|------|------|
| B16 | 卡片「详情」按钮替代整卡点击 | ✅ |
| B17 | 自动选题步骤数据为空 | ✅ |
| B18 | 详情弹窗推荐照片缩略图 | ✅ |
| — | 步骤卡片照片展示增强（全量缩略图 + 元数据 + 因果 + 折叠） | ✅ |
| — | 详情弹窗移除左边栏，改单栏布局 | ✅ |
| — | 清理三维度属性分析回退路径 | ✅ |
| — | 多样性过滤：无移除的组不展示 | ✅ |
