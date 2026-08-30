# 3.5 评估报告

- **报告 ID**：eval-3.5-2026-07-28
- **日期**：2026-07-28T01:05:00
- **对象**：3.5 主题发现持久化存储 + 五星打分 + 删除

## 摘要

**总分 7.9/10 ✅ 通过**（阈值 6.0）。

整体评分 7.9/10，通过（阈值 6.0）。核心功能（持久化存储、时间倒序、五星打分、删除）全部正确实现，API 和前端均端到端验证通过。后端遵循项目已有的 JSON 存储模式，前端保持 NaiveUI 组件风格一致。主要改进点：SuggestHistoryItem Pydantic 模型是死代码应移除；JSON 文件无并发锁（当前单用户场景无实际影响）；星级评分缺少 hover 预览和数字分值标签。

## 分维度评分

### 代码质量

#### 正确性 8

得分点：

- POST /api/suggest/run 返回 id + rating 字段，自动持久化到 suggest_history.json
- GET /api/suggest/history 返回时间倒序列表，服务重启后数据不丢失
- PATCH rating 校验 0-5 范围，越界返回 400
- DELETE 删除后列表即时更新，二次删除返回 404
- 前端乐观更新 + 回滚：打分先更新 UI，请求失败时恢复旧值
- 前端删除有 NPopconfirm 确认 + deletingId loading 状态

失分点：

- SuggestHistoryItem Pydantic model 已定义但未在 response_model 中使用（dead code），GET /api/suggest/history 返回无 schema 校验的原始 list[dict]
- JSON 文件并发写入无锁保护：两个并发生成请求可能丢失一条记录（实际单用户场景风险极低）

#### 健壮性 7

得分点：

- JSON 文件不存在时静默返回空列表，无需手动初始化
- JSON 解析失败时降级返回空列表
- 评分越界校验在服务端（Pydantic int + 手动范围判断），前端无法绕过
- 前端 loadHistory 静默失败，不影响页面渲染

失分点：

- loadHistory 静默失败可能导致用户误以为无历史记录（实际是网络问题），缺少错误提示
- suggest_history.json 文件损坏时，所有历史数据丢失且无自动备份机制
- 前端 handleDelete 中先过滤列表再发请求，如果删除失败（非 404），列表已更新但文件未变

#### 可维护性 8

得分点：

- 存储模式与 golden_queries.json 一致（_load / _save / _path），降低认知负担
- API 路径风格与现有 chat/golden-queries/cluster 一致
- 前端新增 editorial_proposal 分类标签，补齐三阶段主路径的缺失映射
- PIPELINE_LABELS 中文化，清晰区分编辑视角 / 三维度分析
- CSS 使用项目已有的 CSS 变量体系（--n-text-color, --n-border-color）

失分点：

- SuggestHistoryItem 模型定义后未使用，会让后续维护者困惑其用途

#### 简洁性 7

得分点：

- 未引入新依赖，纯 stdlib json + pathlib 实现存储
- 存储函数与 golden_queries 的函数签名/实现模式完全一致，无重复设计
- 前端未拆分额外组件文件，保持单文件组件

失分点：

- SuggestHistoryItem Pydantic model 是死代码，应该移除或接入使用
- 前端 star-rating 逻辑可抽取为独立组件，但当前数据量小，尚可接受


### 功能效果

#### 准确性 9

得分点：

- 所有 5 个 API 端点（POST run / GET history / GET detail / DELETE / PATCH rating）端到端验证通过
- 评分持久化：PATCH 后 history 列表可读到更新后的 rating，JSON 文件落盘正确
- 删除后 history 列表正确移除记录
- 时间倒序：insert(0, result) 保证最新记录在列表头部

失分点：

- 旧版 suggest_history.json 不含 rating 字段时，前端取值可能为 undefined（后端有默认值 0 兜底）

#### 完整性 8

得分点：

- 设计文档 4 项需求全部覆盖：持久化、删除、时间倒序、五星打分
- 自动保存：生成即持久化，无需手动操作
- 自动展开最新记录，减少用户点击

失分点：

- 展开后的照片始终显示全部（showAll=true），不再有'展开查看/收起'的切换——旧版有收起功能显示前 3 张
- 星级评分无数字标签（如 '3/5'），纯视觉判断

#### 一致性 9

得分点：

- API JSON 结构与已有 golden_queries / cluster results 风格一致
- 前端复用 NaiveUI（NTag / NButton / NPopconfirm / NModal）与项目全局 UI 一致
- CSS 变量与现有组件对齐，无硬编码色值
- 分类标签颜色/图标体系扩展自然（editorial_proposal 新增紫色）


### 用户价值

#### 可用性 8

得分点：

- 刷新不丢失：核心痛点已解决
- 评分让用户快速标记优质选题，支持后续筛选比较
- 删除确认弹窗防止误操作
- 新生成自动展开，减少操作步骤

失分点：

- 星级无配套数字标签（如 '3/5'），用户无法一眼确认当前分值
- loadHistory 静默失败时，用户看到的空状态与真实无历史记录无法区分

#### 交互体验 7

得分点：

- 摘要栏一目了然（时间/路径/建议数/星级/删除）
- 星星 hover 有 scale 动画反馈
- 删除有 loading 状态（按钮转圈），防止重复点击
- 生成中显示 loading 状态，避免用户不确定是否卡死

失分点：

- 星级评分 hover 时无法预览将要设置的分数（如 hover 星 3 时第 1-3 颗星临时变亮）
- 整个摘要栏可点击展开，但内部的星星和删除按钮也是可交互的——点击目标重叠时需要依赖 stopPropagation
- 展开后的详情卡片 max-height: 60vh + overflow-y: auto，嵌套滚动体验不够流畅

## 下一步建议

- 3.5 星级评分 hover 预览：hover 星 N 时临时亮起 1~N 颗星，移出后恢复实际分值，提升交互反馈
- 3.5 星级评分数字标签：星星旁显示 '3/5' 分值文本，方便用户确认当前打分
