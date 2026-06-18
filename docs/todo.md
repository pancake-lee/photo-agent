# Photo Agent — 开发任务清单

> 2026-06-18 | 基于 `docs/ui-design.md` §11 Phase 1

## Phase 1：图片上传与管理 + VLM 队列

### Go 后端

- [x] **8. 抽象 VLM 处理管线为 service** — `internal/service/vlm_pipeline.go`
  - 将 `cmd/batch_vlm/main.go` 的核心逻辑（扫描、并发 VLM、保存 descriptions.json）抽象为可复用 service
  - CLI 和 Web API 共享同一套管线
- [x] **9. 上传 API + 去重逻辑 + 冲突处理**
  - `POST /api/v1/photos/upload` — 接收压缩后的 JPEG，存储到 photo_path
  - 去重判断：同名文件 → 对比 EXIF 拍摄时间 → 冲突 / 自动加后缀 / 直接存储
  - 冲突返回 `{ status: "conflict", conflict: {...} }`，前端二次请求带 `conflict_resolution`
- [x] **10. VLM 队列服务** — `internal/service/vlm_queue.go`
  - 单例结构体：pending channel + start/stop/enqueue/status
  - Worker 消费循环：`select { case <-ctx.Done(): return; case photoID := <-pending: ... }`
  - Stop 语义：cancel context → 清空 pending → 不等待 active
  - API：`POST /api/v1/vlm/queue/start`、`/stop`、`GET /api/v1/vlm/queue/status`、`POST /api/v1/photos/:id/describe`
  - 照片列表/详情 API 增加 `has_description` 字段

### Vue 前端

- [x] **1. 初始化 Vue 项目** — Vite + Naive UI + TypeScript
- [x] **2. 主页面框架** — 左侧边栏 + 内容区 + 暗色主题
- [x] **3. 图片管理页面** — 网格展示 + 分页 + 描述状态按钮
- [x] **4. 图片详情抽屉** — EXIF + 描述展示 + 重新生成按钮
- [x] **5. DescriptionModal** — 描述内容弹窗 + 重新生成
- [x] **6. 上传弹窗** — 文件选择 + 拖拽 + 前端压缩 + 上传
- [x] **7. 去重冲突弹窗** — 并排对比 + 覆盖/跳过/保留两者
- [x] **11. VLM 队列轮询** — useVlmQueue + 全局开关 + 进度指示器 + 中止

---

## Phase 2（后续）：服务器目录批量导入

- [ ] Go 后端：batch-import API（扫描目录 + 导入元数据，不触发 VLM）
- [ ] BatchImportModal（源目录配置 + 导入进度）
- [ ] 导入完成后自动衔接 VLM 队列

## Phase 3（后续）：智能对话

- [ ] 对话页面 + Python Agent 后端接入 + 流式输出

## Phase 4（后续）：高级功能

- [ ] VLM 描述展示与编辑 + 标签管理 + 搜索与多维过滤 + 批量操作
