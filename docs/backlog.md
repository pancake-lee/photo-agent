# Backlog

> 全部技术需求池，按序号排列。
> 状态流转：`待规划`（尚无方案）→ `规划中`（Planner 产出方案中）→ `已规划`（方案就绪，可执行）→ `WIP`（开发中）→ `Done`（已完成）
> 其他状态：`Ongoing`（长期任务）、`Rejected`（明确拒绝）、`Abandoned`（已废弃）
>
> 任务详情按统一结构组织（用户原始描述 / 状态 / 背景 / 方案 / 分析 / 验收 / 评估），作为角色间文件交接协议。「用户原始描述」为可选字段，仅当任务直接来源于用户口述需求时填写。「评估」为可选字段，评测后填入综合总分和各维度得分。

## 任务总览

| 状态   | 阶段       | 序号 | 任务                           | 评估 |
| ------ | ---------- | ---- | ------------------------------ | ---- |
| 待规划 | 导入工作流 | W12  | ImportWorkflow.vue 拆分        |      |
| 已规划 | 组图检索   | GR1  | 三 Collection 向量库改造       |      |
| 已规划 | 图片管理   | CL1  | 上传/VLM/Embed 闭环 + 废弃描述同步清理 |      |

> 其余 6 项待规划任务经审阅后迁至 [docs/design/2026-08-22-future-requirements.md](design/2026-08-22-future-requirements.md)。

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

> 历史待规划任务（1.4 / 3.2 / 3.3 / 4.1 / 4.2 / B2）已于 2026-08-22 审阅后迁移至 [docs/design/2026-08-22-future-requirements.md](design/2026-08-22-future-requirements.md)。

---

### 导入工作流（Windows 客户端）

> W1-W11 已在 v1.0.9 归档：[docs/archive/v1.0.9.md](archive/v1.0.9.md)

### W12 ImportWorkflow.vue 拆分

- **状态**：待规划
- **背景**：`web/src/views/ImportWorkflow.vue` 已达 1010 行（模板+脚本+样式混排），三步流程（新建活动/分析报告/上传同步）全部单文件承载，任何一步的调整都要在千行文件中定位。三轮评估持续登记的可维护性债务，非功能缺陷。
- **方案**：-
- **分析**：-
- **验收**：-
  - [ ] 按三步拆为子组件，单文件行数降至合理范围
  - [ ] 拆分后三步流程行为不变

---

### GR1 三 Collection 向量库改造（组图检索）

- **状态**：已规划
- **方案**：[docs/design/2026-08-22-grouped-photo-retrieval.md](design/2026-08-22-grouped-photo-retrieval.md)
- **背景**：连拍分组功能已上线（v1.0.10），但 Embedding 和向量检索仍以单张照片为单位。连拍组在向量库中产生大量冗余条目，导致检索结果被同组照片占据。
- **分析**：
  - 技术方案：新增两个向量集合（精细组 / 模糊组），仅入库封面图描述。现有全量集合保持不变
  - 入库改造：Embedding 管线启动时从 Go 后端获取连拍组封面映射，处理照片时判断是否为封面图，是则同时写入对应组集合
  - 检索改造：RAG 检索和选题管线的检索函数增加粒度参数，按粒度查询不同集合
  - Go 后端新增一个接口，返回所有连拍组的封面图 ID 和照片数，供 Python 侧入库路由使用
  - Python 侧新增一个门面类统一管理三个向量集合实例，EmbedQueue 和 RAG 均通过它操作
  - 前端聊天界面新增粒度选择器，检索结果根据粒度展示单张或组卡片，组卡片复用现有 BurstGroupModal 展开
  - photo_refs 数据结构在组模式下增加组 ID 和照片数，前端据此判断展示方式
  - 清理逻辑扩展到三个集合：删除照片时全集合清理，连拍组重建后 force 重新嵌入更新组集合
  - 现有 `photos` 集合无需数据迁移，新集合通过 force 重新嵌入自动填充
- **验收**：
  - [ ] 全量集合入库行为不变，现有检索功能不受影响
  - [ ] 精细组 / 模糊组集合仅包含对应档位连拍组的封面图
  - [ ] 聊天界面可切换检索粒度，组模式返回组级别结果
  - [ ] 组结果展示封面图 + 照片数，点击展开查看组内全部照片
  - [ ] 删除照片后三个集合均清理
  - [ ] 连拍组重建后 force 重新嵌入可正确更新组集合

---

### CL1 上传/VLM/Embed 闭环（VLM 实时生成 + 废弃描述同步清理）

- **用户原始描述**：图片管理已完成迭代（能上传、能管时间线）。详情页点"生成描述"和"生成 Embedding"应实时调用 vlm/embedding 模型生成并展示到页面；顶部 VLM/Embed 按钮处理所有缺数据的照片（Embed 指已有 VLM 描述但未 embed 的照片）。descriptions.json 及 batch_vlm 已废弃，后端启动时的描述同步逻辑应移除，让上传/vlm/embed 在页面形成闭环，embed 生成直接入库 Chroma。
- **状态**：已规划
- **背景**：v1.0.10 后图片管理页已具备上传/时间线/连拍分组/分段浏览能力，但 VLM 描述仍是"从预生成文件同步"的旧机制。`DescribePhoto`/`StartVlmQueue`（`svc_vlm.go`）只读 `descriptions.json` 同步到 DB，不调 VLM。新导入照片（如 `202608-山西旅游` 目录 239 张）不在该文件里，点"生成描述"返回 `Queued:false` 且前端一直转圈。真正的 VLM 生成工具 `batch_vlm`（`backend/cmd/batch_vlm` + `internal/vlm/client.go`/`compress.go` + `internal/service/vlm_pipeline.go`/`vlm_queue.go`）在提交 `65653be`（backend-new 替换 backend）时被删，只剩陈旧二进制 `bin/batch_vlm`。
- **分析**（闭环缺口 + 废弃清单）：
  - 缺口 1（功能）：Go 后端无任何 VLM 生成代码，`conf.C.VLM` 只被 embedding 代理复用，`DescribePhoto`/`StartVlmQueue` 是纯文件同步。
  - 缺口 2（数据）：详情页 `description_model`/`description_time` 来自 `GetPhotoDetail` 里的 `getDescriptionEntry`（读 descriptions.json），photos 表无这两列，清理后需入库。
  - 缺口 3（前端）：`handleTriggerDescribe` 成功时不清 `processingIds`，`PhotoGrid` 的 `processing` 一直转圈。
  - Embed 侧已闭环（Python `EmbedQueue` 取描述 → 分块 → embed → Chroma），无需改。
  - 废弃代码：`descriptions.go` 整文件、`svc_auto_sync.go` 整文件（目录扫描导入 + MD5 dedup + descriptions.json 读取，`parseVlmAttrs`/`extractJSONBlock` 迁出复用）、`svc_vlm.go` 的 `loadDescriptions`/`getDescriptionEntry` 用法、`svc_photo.go` 的 `getDescriptionEntry`、`conf.C.Storage.DescriptionsPath`、`defaultService.go` 的 `AutoSync()` 调用、`bin/batch_vlm` 及 docs 引用。上传成为唯一导入路径（`createPhotoRecord` 已含 EXIF/时间线匹配）。
- **方案**：
  1. 复用旧 VLM 调用逻辑（作为库，不恢复 batch_vlm CLI）：从 `65653be^` 取 `internal/vlm/client.go`（火山方舟 Responses API：`input_image` + `input_text`）与 `compress.go`（ImageMagick 压缩到 512px），适配新 conf（`conf.C.VLM`）与 `putil.NewHttpRequestJson`。`conf.go` 的 `VLM` 增加 `Prompt` 字段（读 `.local/vlm_prompt.md`），图片从 `PhotoPath` 取已压缩图。调用链为：web 发起 → 后端 `VlmServer` API → 该库调火山方舟 → 写 DB。
  2. 改造 `VlmServer`：`DescribePhoto` 单张实时生成描述 → 解析结构化属性 → 写 DB；`StartVlmQueue`/`runVlmQueue` 遍历 `GetPhotosWithoutDescription` 批量生成（加并发控制）。复用 `parseVlmAttrs`。
  3. 加列：photos 表加 `description_model`/`description_time`（`migrate.go` 幂等 `AddColumn`），生成时写入；`GetPhotoDetail` 改读 DB。
  4. 删除 AutoSync 与 descriptions.json：删 `descriptions.go` 与 `svc_auto_sync.go` 整文件，`defaultService.go` 移除 `service.AutoSync()`；`parseVlmAttrs`/`extractJSONBlock`/`vlmJSON` 迁到 VLM 服务文件复用；`conf.go` 去掉 `DescriptionsPath`。上传成为唯一导入路径（`createPhotoRecord` 已含 EXIF/时间线匹配，无需目录扫描）。
  5. 前端：`handleTriggerDescribe` 成功路径也清理 `processingIds`（或由 `onComplete` 统一刷新详情）；`useVlmQueue` 单张入队后触发轮询。
  6. 清理 batch_vlm：删 `bin/batch_vlm` 二进制，不恢复 `backend/cmd/batch_vlm` CLI 源码；更新 tech.md/note.md/README/deploy.md 中 batch_vlm 引用。
- **验收**：
  - [ ] 上传照片后详情页点"生成描述"，真实调 VLM，description 入库并展示，转圈结束
  - [ ] 顶部"VLM"按钮批量处理所有无描述照片并写库
  - [ ] "Embed"按钮把有描述照片 embed 进 Chroma，对话/RAG 能检索到新照片
  - [ ] 后端启动不再读 descriptions.json
  - [ ] 详情页与 DescriptionModal 正确展示模型与生成时间（来自 DB）
  - [ ] 删除照片后 DB/文件/Chroma 三处一致

---

## 决策历史

- **2026-06-05**：产品定位从"摄影资产助手"收敛为"AI 选题助手"，废弃 25 项优化点，按 roadmap 四阶段重建 backlog。原有 task_3.md 技术点已吸收或明确拒绝。
- **2026-06-11**：合并 `docs/upgrade.md` 到本文档。upgrade.md 为旧产品定位下的技术升级规划，其中 Prometheus 监控、异步后台同步、proto-first 迁移已被新定位明确拒绝；SQLite WAL 已纳入工程小改进；其余优化项（以图搜图、EXIF/GPS、多模态 Embedding 等）与新定位"主动不做的事"一致，不再单独维护。upgrade.md 已删除，CLAUDE.md/AGENTS.md 文档层级以 backlog.md 替代。
- **2026-07-26**：v1.0.6 版本归档。Phase 0/1/2 全部完成，Phase 3.1 完成，工程改进 E1-E3 及重构 R1-R3 完成。已完成条目迁至 `docs/archive/v1.0.6.md`。
- **2026-07-27**：backlog 条目描述格式规范化。删除表格「简述」列，任务详情统一为结构化字段（状态 / 背景 / 方案 / 分析 / 验收），作为角色间文件交接协议。
- **2026-07-28**：v1.0.7 版本归档。主题发现三阶段编辑视角提案及衍生缺陷修复链（B1/B3/B4/B5/B6/B7/B8/B9/B10）、持久化存储与交互优化（3.5/3.6/3.7/B11）、聚类标题与 UI 优化（2.2/2.3）、工程改进（1.3/R4/R5/R6/E4/E5）全部完成。已完成条目迁至 `docs/archive/v1.0.7.md`。
- **2026-08-01**：v1.0.8 版本归档。主题发现交互式管线（3.8/3.9/3.10/3.11）、缺陷修复（B12/B13/B14/B15/B16/B17/B18）、回退路径清理全部完成。已完成条目迁至 `docs/archive/v1.0.8.md`。
- **2026-08-18**：v1.0.9 版本归档。导入工作流 Windows 客户端（W1-W11，三轮评估 7.7→8.3→8.4）全部完成，用户实测功能基本可用。实机验证遗留项与轻量小项转入日常缺陷修复流程；ImportWorkflow.vue 拆分立 W12 保留。已完成条目迁至 `docs/archive/v1.0.9.md`。
- **2026-08-20**：LB1 照片列表分段浏览完成规划（外部需求并入）。两项关键决策与用户确认：跳转策略用筛选重置式（放弃先拉齐再跳）；排序收敛为仅拍摄时间升/降序（移除文件名/导入时间排序 UI，后端白名单保留）。
- **2026-08-21**：LB2 收尾与 LB3 修复。LB2「只有照片列表滚动」当时误判通过，实际高度链断裂（naive-ui NLayout 内层容器 block 布局致 Content 高度塌陷），滚动加载彻底失效，LB3 补齐高度链修复。
- **2026-08-21**：LB4/LB5/LB6 完成规划。三项决策与用户确认：散片分组粒度取「相邻活动间隔内按月切」（放弃纯按月单组与日期聚簇）；时间线重算保留人工值（photo 表加 timeline_manual 列）；timeline 事件迁数据库表（放弃继续用 JSON 文件）。顶栏重排取「单行 + 弹出收纳」（放弃双行归组与仅重排）。
- **2026-08-21**：LB4/LB5/LB6 完成生成。LB4 修坐标换算（相对滚动容器）与照片卡锚点；LB6 顶栏单行 + NPopover 收纳；LB5 后端 timeline_events 表 + timeline_manual 列 + CRUD/重算接口 + JSON 一次性迁移 + 散片分组单测，前端 /timelines 管理页 + 筛选数据源切 ListEvents。
- **2026-08-21**：LB 系列整体评估（8.1 通过）。运行时实测：分段 offset/count 与 DB 逐项一致、导航跳转高亮正确、sentinel 190=190、JSON 迁移 29 条已发生；LB5 重算未执行（散片运行时效果悬置）。新增 LB7（PhotoManagement.vue 1030 行拆分）、LB8（四项低危遗留）。子代理三项高严重误报（offset 排序方向/排序 UI 残留/气泡无延迟）经复测全部排除。
- **2026-08-22**：LB7/LB8 完成。图片管理页按顶栏、列表浏览、页面编排拆分；请求去重、辅助请求失败提示、本地时区分段键和跨年/同月序号边界测试闭环。
- **2026-08-22**：v1.0.10 版本归档。连拍分组（BG1，P1-P4/P6 代码全部落地）、照片列表浏览（LB1-LB8，整体评估 8.1）、日常小需求（D1/D2）全部完成。BG1 经用户确认按 Done 归档，其 P5 真实库抽检调阈值与 LB5 时间线重算、跨时区分段核对、D1 Windows 双开一并转入日常使用验证，不另立条目。已完成条目迁至 `docs/archive/v1.0.10.md`。
- **2026-08-22**：backlog 待规划任务审阅。7 项待规划任务基于 v1.0.10 代码现状重新评估，6 项（1.4 / 3.2 / 3.3 / 4.1 / 4.2 / B2）确认仍有价值但当前不急于启动完整设计，迁移至 `docs/design/2026-08-22-future-requirements.md` 作为未来需求暂存；W12（ImportWorkflow.vue 拆分）为纯可维护性改进，保留在 backlog 随时可执行。
- **2026-08-22**：GR1 组图检索规划。需求源自用户与 Web AI 讨论产生的设计草案，经代码审阅后修正数据模型名称（`burst_groups` → `photo_groups`）、补全前端已有基础（BurstGroupModal / PhotoCard 角标 / 折叠视图）、对齐现有 Embedding 管线（`embed_queue.py` / `ChromaPhotoStore`）。方案选择：用户选定三 Collection 架构（`photos` / `photos_fine` / `photos_coarse`），封面图入库对应组 Collection，检索时按粒度切换。
- **2026-08-22**：CL1 图片管理闭环规划。VLM 描述生成从"预生成文件同步"改为"实时调用 VLM"，调用链为 web 发起 → 后端 `VlmServer` API 处理（不恢复 batch_vlm CLI，仅复用 `internal/vlm` 包的调用逻辑作为库）；descriptions.json、batch_vlm 及 AutoSync 目录扫描导入一并废弃删除，上传成为唯一导入路径；`description_model`/`description_time` 由 descriptions.json 迁入 photos 表（新增两列）；Embed 侧已闭环（Python EmbedQueue → Chroma）无需改。
