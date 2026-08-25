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
| Done   | 图片管理   | CL1  | 上传/VLM/Embed 闭环 + 废弃描述同步清理 | 8.4  |
| Done   | 图片管理   | CL2  | VLM HTTP 请求无超时                    |      |
| Done   | 图文工坊   | PS1  | 后端基础 + 图文工坊核心页面            | 8.0  |
| Done   | 图文工坊   | PS5  | 照片详情大图查看（图文工坊 + 图片管理共用） | 8.3  |
| Done   | 图文工坊   | PS2  | 图片管理选择模式                       | 8.5  |
| Done   | 图文工坊   | PS3  | 主题发现采纳入口                       | 8.3  |
| Done   | 图文工坊   | PS4  | 导出功能                               | 7.8  |
| Done   | 图文工坊   | PS6  | 文案生成提示词结构重构                 | 8.0  |

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
- **状态**：Done
- **评估**：8.4（正确性 8.5 健壮性 8.5 可维护性 8.5 简洁性 9 准确性 9 完整性 9 一致性 9 惊喜度 7 可用性 9 交互体验 8.5 AI增量 9），详见 [2026-08-23-cl1-vlm-embed-closed-loop](../data/eval_reports/2026-08-23-cl1-vlm-embed-closed-loop.md)
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
  - [x] 上传照片后详情页点"生成描述"，真实调 VLM，description 入库并展示，转圈结束
  - [x] 顶部"VLM"按钮批量处理所有无描述照片并写库
  - [x] "Embed"按钮把有描述照片 embed 进 Chroma，对话/RAG 能检索到新照片
  - [x] 后端启动不再读 descriptions.json
  - [x] 详情页与 DescriptionModal 正确展示模型与生成时间（来自 DB）
  - [x] 删除照片后 DB/文件/Chroma 三处一致

---

### CL2 VLM HTTP 请求无超时

- **状态**：Done
- **背景**：CL1 评估发现 `vlm_client.go` 的 `describeImage` 使用 `http.DefaultClient` 发起 VLM API 请求，未设置超时。批量处理时 4 个 worker 并发调用火山方舟 API，若 API 挂起（网络异常或服务端无响应），worker goroutine 将永久阻塞，队列无法完成也无法中止。
- **方案**：新增包级变量 `vlmHTTPClient = &http.Client{Timeout: 60 * time.Second}`，替换 `http.DefaultClient`。
- **分析**：60s 超时覆盖 VLM 模型推理时间（通常 5-20s），留足余量。超时后 `Do()` 返回 context deadline exceeded 错误，worker 正确标记失败并继续下一张。
- **验收**：
  - [x] VLM HTTP 请求有合理超时（60s）
  - [x] 超时后 worker 正确标记失败并继续处理下一张

---

### PS1 后端基础 + 图文工坊核心页面

- **状态**：Done
- **评估**：8.0（正确性 8.5 健壮性 7.5 可维护性 7.5 简洁性 8），详见 [评估报告](../data/eval_reports/2026-08-25-post-studio-ps-series.md)
- **背景**：图文工坊是"创作工作台"，接收两条路径的输入（图片管理选图 / 主题发现采纳提案），提供 AI 辅助文案生成和编辑能力。设计文档：[docs/design/2026-08-23-post-studio-design.md](design/2026-08-23-post-studio-design.md)
- **方案**：
  - Go 后端：新增 `drafts` 表（id / title / content / photo_ids JSON / style / source / status / created_at / updated_at），幂等迁移；DAO 层 CRUD；service 层业务逻辑；API 端点 `POST /api/v1/drafts`（创建）、`PUT /api/v1/drafts/:id`（更新）、`DELETE /api/v1/drafts/:id`（删除）、`GET /api/v1/drafts`（列表）、`GET /api/v1/drafts/:id`（详情）
  - Python AI 服务：新增 `POST /api/post-studio/generate`（提示词模式：接收 photo_ids + style + prompt → 从 Go 获取照片描述 → 构建 prompt → 调 LLM → 返回标题 + 正文）和 `POST /api/post-studio/refine`（草稿模式：接收 content + style → 润色优化 → 返回修改后文本）。复用现有 `conf.C.LLM` 配置，不新增配置项
  - Vue 前端：新增 `PostStudio.vue`（单栏布局：照片区 + 文案区，含风格选择器、两种生成模式切换、标题/正文编辑、保存草稿）和 `DraftManagement.vue`（草稿列表，含标题/照片缩略图/文案预览/时间/来源/状态）；路由 `#/post-studio` 和 `#/drafts`；菜单增加“图文工坊”和“草稿管理”入口；照片网格支持拖拽排序（vuedraggable）和移除
  - 页面间传参：URL query params（`#/post-studio?photo_ids=a,b,c`、`#/post-studio?draft_id=xxx`）
  - 更新 tech.md API 设计和项目结构
- **分析**：
  - 草稿存 Go SQLite 而非 Python：草稿引用照片 ID，Go 是照片元数据唯一数据源，保持一致性
  - Python 生成文案时通过 Go API 获取照片描述（与现有 RAG/Text-to-SQL 模式一致），不直接访问 Go 数据库
  - 文案生成采用非流式响应（结果填入可编辑文本区，非对话场景）
  - 照片网格拖拽使用 vuedraggable（Vue 3 + SortableJS），需新增依赖
- **验收**：
  - [x] 图文工坊页面可空状态进入，能添加照片、选风格、输入提示词生成文案
  - [x] 草稿模式可粘贴文本并润色优化
  - [x] 照片网格支持拖拽排序和移除
  - [x] 保存草稿后出现在草稿管理列表
  - [x] 草稿管理列表点击进入图文工坊继续编辑
  - [x] 菜单顺序与设计文档一致

---

### PS5 照片详情大图查看（图文工坊 + 图片管理共用）

- **状态**：Done
- **评估**：8.3（正确性 8.5 健壮性 7.5 可维护性 7.5 简洁性 8），详见 [评估报告](../data/eval_reports/2026-08-25-post-studio-ps-series.md)
- **背景**：图文工坊的照片区原先点击照片无任何响应，缺少查看原图的途径。用户要求复用图片管理的详情抽屉，并升级为大图查看：不遮挡左侧菜单栏、左右切换上一张/下一张，图文工坊与图片管理的上/下一张 UI/UX 一致但列表不同。
- **方案**：
  - 升级共享组件 `PhotoDetail.vue`：由 `NDrawer` 抽屉改为全屏灯箱（左侧半透明遮罩 + 放大原图 + 左右切换按钮 + `i/N` 计数 + 文件名）+ 右侧详情面板（EXIF / AI 描述 / Embedding，实色底白字）；`left: 220px` 避开左侧菜单栏；新增 `navList` 属性与 `navigate` 事件驱动上/下一张；新增 `showVlmActions` 控制处理按钮显隐
  - 图片管理：传入当前照片窗口作为 `navList`，`navigate` 事件接 `fetchPhotoDetail`
  - 图文工坊：点击照片缩略图打开详情，`navList` 为已选帖子照片列表，`showVlmActions=false` 只读展示
  - 交互：退出按钮、点击遮罩、Esc 关闭；←/→ 键盘切换上/下一张
- **分析**：详情数据复用 `photoServiceGetPhotoDetail` 拉取完整 `PhotoDetail`；图文工坊与图片管理共用同一组件，仅数据列表与处理按钮显隐不同
- **验收**：
  - [x] 点击照片打开大图详情，不遮挡左侧菜单栏
  - [x] 左右按钮 + 键盘切换上一张/下一张，计数正确
  - [x] 图文工坊用已选照片列表，图片管理用当前照片窗口
  - [x] 右侧详情面板文字可读，图文工坊不显示 VLM/Embed 处理按钮

---

### PS2 图片管理选择模式

- **状态**：Done
- **评估**：8.5（正确性 8.5 健壮性 7.5 可维护性 7.5 简洁性 8），详见 [评估报告](../data/eval_reports/2026-08-25-post-studio-ps-series.md)
- **背景**：图片管理页需增加多选模式，作为图文工坊的"路径 B（自选图片）"入口。设计文档：[docs/design/2026-08-23-post-studio-design.md](design/2026-08-23-post-studio-design.md)
- **方案**：
  - PhotoManagement 顶栏增加"选择模式"切换按钮（与浏览模式互斥）
  - 选择模式下：每张照片显示复选框，顶栏显示已选数量 + "图文工坊"按钮
  - 支持全选 / 取消全选
  - 支持区间选择：选中 2 张照片后顶栏出现"区间选择"按钮，点击后勾选两张之间（按拍摄时间排序）的所有照片
  - 连拍组展开后子图可单独选中
  - 点击"图文工坊"按钮，携带已选 photo_ids 跳转 `#/post-studio?photo_ids=...`
- **分析**：选择模式状态在 PhotoManagement 组件内部管理，无需全局状态
- **验收**：
  - [x] 图片管理可切换选择模式，显示复选框
  - [x] 支持全选 / 取消全选
  - [x] 支持区间选择（选中 2 张后勾选中间所有照片）
  - [x] 连拍组子图可单独选中
  - [x] 点击"图文工坊"按钮跳转并携带正确照片

---

### PS3 主题发现采纳入口

- **状态**：已完成
- **评估**：8.3（正确性 8.5 健壮性 7.5 可维护性 7.5 简洁性 8），详见 [评估报告](../data/eval_reports/2026-08-25-post-studio-ps-series.md)
- **背景**：主题发现生成选题提案后，用户可"采纳"进入图文工坊，作为"路径 A（AI 策展）"入口。设计文档：[docs/design/2026-08-23-post-studio-design.md](design/2026-08-23-post-studio-design.md)
- **方案**：
  - 主题发现选题卡片右上角增加"图文工坊"按钮
  - 点击后跳转 `#/post-studio?topic_id=xxx`
  - 图文工坊根据 topic_id 从 Python 获取选题详情（照片序列 + 标题 + 叙事角度），预填到对应区域
  - 预填内容：照片序列 → 照片区，标题 → 标题输入框，选题理由 → 正文编辑区和草稿输入框，并默认进入草稿润色模式
- **分析**：Python 端已有 `GET /api/suggest/history/:id/detail` 返回完整选题详情，前端获取后传入图文工坊即可
- **验收**：
  - [x] 主题发现卡片有"图文工坊"按钮
  - [x] 点击后跳转图文工坊并进入草稿润色模式，照片/标题/选题理由正确预填
  - [x] 预填内容可自由编辑修改

---

### PS4 导出功能

- **状态**：Done
- **评估**：7.8（正确性 8.5 健壮性 7.5 可维护性 7.5 简洁性 8），详见 [评估报告](../data/eval_reports/2026-08-25-post-studio-ps-series.md)
- **背景**：图文工坊完成编辑后，需支持文本和图片的多种导出方式。设计文档：[docs/design/2026-08-23-post-studio-design.md](design/2026-08-23-post-studio-design.md)
- **方案**：
  - 文本导出（前端完成）：复制为 Markdown、复制为纯文本、下载为 .md 文件（含标题和正文）
  - 图片导出：单张下载复用现有 `GET /api/v1/photos/:id/image`
  - ZIP 打包（Go 后端）：`GET /api/v1/drafts/:id/export`，读取草稿关联照片原图 + 生成 .md 文件，打包为 ZIP 流式返回
- **分析**：照片文件在 Go 服务端，ZIP 打包必须在后端完成；文本导出纯前端操作无需后端参与
- **验收**：
  - [x] 可复制为 Markdown 和纯文本
  - [x] 可下载 .md 文件
  - [x] 可单张下载照片原图
  - [x] 可一键下载 ZIP（原图 + .md 文件）

---

### PS6 文案生成提示词结构重构

- **状态**：Done
- **评估**：8.0（正确性 8.5 健壮性 7.5 可维护性 7.5 简洁性 8），详见 [评估报告](../data/eval_reports/2026-08-25-post-studio-ps-series.md)
- **背景**：用户在图文工坊选 3 张照片生成文案，产出内容与照片完全无关。排查发现 `_fetch_photo_descriptions` 按顶层 key 读 Go 的照片详情响应，而描述嵌在 `photo` 对象内，导致照片描述恒为空，LLM 拿到的是三个空壳。此外提示词结构本身缺少分层设计。设计文档：[docs/design/2026-08-24-1-post-studio-prompt-design.md](design/2026-08-24-1-post-studio-prompt-design.md)
- **方案**：
  - 数据获取改用 `utils/backend_sdk` 的 `photo_service_get_photo_detail`，取结构化对象的 `.photo`，消除手拼 dict key 的 bug 类
  - 提示词分四层：系统提示词（角色 + 平台约束 + 防幻觉 + 输出契约）/ 风格层 / 照片上下文层 / 用户要求层。前两层进 SystemMessage，后两层进 HumanMessage
  - 照片上下文从 VLM 原始 JSON 做提取式摘要，只保留主体、动作、场景、天气、光线、色调、氛围、画面文字、概述，丢弃构图/对比度/景深等技术字段；列表前置拍摄时间跨度汇总；攻略风格额外附 EXIF 参数；超 20 张时降为精简模式
  - 输出改为 JSON 契约 `{"title","content"}`，复用 `suggest.py` 的 `_parse_llm_json_response` 容错解析，替代现在的首行拆分
  - 润色接口新增 `photo_ids`，让润色也能看到照片
  - 无描述照片：全部无描述返回 400 并指引去生成描述，部分无描述则通过响应体 `warnings` 提示
  - 新建 `agent/chain/post_studio.py` 承载提示词与主流程，`server.py` 只保留路由；`STYLE_MAP` 从两处重复收敛为单一常量
  - 前端 `DEFAULT_PROMPT` 置空改为 placeholder 引导，润色请求带 `photo_ids`，展示 `warnings`
- **分析**：主因是响应结构取值错误，一行改动即可修复；但即使修对，直接把 1000+ 字符的 VLM JSON 入提示词仍会让文案偏向技术性描述，因此提示词分层与摘要提取需要一并做。不采用多模态直连是因为主 LLM 为纯文本模型，改用视觉模型会与现有 llm 配置分叉且成本更高
- **验收**：
  - [ ] 生成的文案能准确提到照片里的具体主体和场景
  - [ ] 调整照片拖拽顺序后叙事推进顺序随之改变
  - [ ] 四种风格的文案语气有可辨识差异，攻略风格含相机参数信息
  - [ ] 用户要求留空可正常生成，填写时文案有对应侧重
  - [ ] 润色模式能参考照片内容且不新增草稿外的事实
  - [x] 照片全部无描述时返回明确错误提示，部分无描述时弹出警告
  - [x] LLM 输出带围栏或寒暄时标题正文仍能正确拆分
  - [x] 日志可见照片数、缺描述数、提示词长度

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
- **2026-08-23**：CL1 评估通过（8.4）。VLM 实时生成 + 废弃清理全部落地，6 项验收标准代码侧全覆盖。239 张照片已通过新管线生成描述并入库。CL2 修复 HTTP 客户端无超时问题（`vlmHTTPClient` 60s），健壮性 7.5 → 8.5，总分 8.3 → 8.4。
- **2026-08-23**：图文工坊（PS1-PS4）规划完成。设计文档 `2026-08-23-post-studio-design.md` 已就绪，拆为 4 个子阶段：PS1 后端基础+核心页面、PS2 图片管理选择模式、PS3 主题发现采纳入口、PS4 导出功能。关键决策：草稿存 Go SQLite（照片元数据唯一数据源）；AI 文案生成在 Python 侧，通过 Go API 获取照片描述；复用现有 LLM 配置；页面间用 URL query params 传参。
- **2026-08-24**：PS1 完成。Go 后端新增 drafts 表 + DAO + Service + 5 个 API 端点；Python AI 服务新增 generate/refine 两个端点；Vue 前端新增 PostStudio.vue（单栏布局、拖拽排序、双模式文案生成）和 DraftManagement.vue（草稿列表），路由和菜单更新，tech.md 同步。
- **2026-08-24**：图文工坊 UI 细化 + PS5 照片详情大图查看完成。PS1 页面布局收敛为单栏（照片区上、文案区下），风格选择器支持下拉 + 自定义输入、默认「轻松」，模式按钮蓝/黄着色且切换保留内容，标题移到生成按钮下方与正文一起生成。照片详情复用图片管理 PhotoDetail 并升级为全屏灯箱（大图 + 上/下一张），图文工坊与图片管理共用，仅导航列表与处理按钮显隐不同。
- **2026-08-24**：PS6 文案生成提示词结构重构完成。新建 `agent/chain/post_studio.py` 承载四层提示词与生成/润色主流程；数据获取改走 SDK 结构化对象，修复描述恒为空的取值 bug；照片上下文从 VLM 原始 JSON 做提取式摘要（丢弃构图/对比度等技术字段，攻略风格附 EXIF，超 20 张精简）；输出改 JSON 契约并复用 `_parse_llm_json_response` 容错解析；润色接口新增 photo_ids；无描述照片全部时 400、部分时 warnings。前端 `DEFAULT_PROMPT` 置空改 placeholder 引导、润色带 photo_ids、展示 warnings。代码侧验收项（无描述报错/围栏寒暄解析/日志）已勾选，运行时验证项留待用户部署确认。
- **2026-08-24**：PS2 图片管理选择模式完成。PhotoManagementToolbar 顶栏新增「选择模式」切换按钮（与浏览模式互斥），选择模式下右栏替换为「已选 N 张 + 全选/取消全选/区间选择/图文工坊/退出选择」；PhotoCard 选择模式显示复选框、点击卡片切换选中、隐藏 VLM/Embed/删除操作按钮、选中态绿框高亮；PhotoGrid/PhotoListBrowser 透传选择状态；PhotoManagement 管理 selectedIds（Set），区间选择按拍摄时间顺序勾选两张之间照片，点击「图文工坊」携带 photo_ids 跳转 `#/post-studio`。
- **2026-08-24**：PS2 连拍组处理增强。折叠视图下勾选连拍封面 = 选中整组（跳转 URL 用 `g:<封面id>` 标记），图文工坊以「连拍组」条目展示；PhotoCard 可配置化（showStatus/showEmbed/showDelete/showRemove/showTooltip）供图文工坊复用；BurstGroupModal 增加 curate 模式（多选复选框 +「连拍精选」）；PostStudio 照片列表改为条目联合模型（photo/group），「连拍精选」把连拍组替换为所选子图；草稿 photo_ids 用 `g:` 前缀保留组结构（DraftManagement 缩略图已兼容）。
