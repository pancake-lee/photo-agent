# CL1 上传/VLM/Embed 闭环 — 评估报告

> **总分**：8.4/10 ✅ 通过（阈值 6.0）
> **评估对象**：VLM 实时描述生成 + Embed 闭环 + descriptions.json/AutoSync/batch_vlm 废弃清理
> **验证提交**：`01545f7`（feat: 生成-Upload/VLM/Embed 闭环）+ `3a695f6`（gen: update generated code）
> **CL2 修复**：`vlm_client.go` 新增 `vlmHTTPClient` 60s 超时，健壮性 7.5 → 8.5

---

## 摘要

CL1 将 VLM 描述生成从"预生成文件同步"彻底改造为"实时调用 VLM → 写 DB → Embed 入库"闭环。6 项验收标准代码侧全部覆盖。废弃代码（descriptions.go、svc_auto_sync.go、batch_vlm 二进制、DescriptionsPath 配置）清理干净无残留。数据库实测 1436 张照片 100% 有描述，239 张已通过新管线生成并写入 description_model/description_time。CL2 修复了 HTTP 客户端无超时问题。

---

## 验收标准逐项

- [x] 上传照片后详情页点"生成描述"，真实调 VLM，description 入库并展示，转圈结束
- [x] 顶部"VLM"按钮批量处理所有无描述照片并写库
- [x] "Embed"按钮把有描述照片 embed 进 Chroma，对话/RAG 能检索到新照片
- [x] 后端启动不再读 descriptions.json
- [x] 详情页与 DescriptionModal 正确展示模型与生成时间（来自 DB）
- [x] 删除照片后 DB/文件/Chroma 三处一致

---

## 代码质量

### 正确性 8.5

**得分点**：
- VLM 调用链清晰：`DescribePhoto` → `describeImage()` → 火山方舟 Responses API → `applyDescriptionToPhoto()` 写 DB（`svc_vlm.go:286-323`）
- 批量队列 4 worker 并发 + channel + WaitGroup，优雅中止通过 `stopCh`/`done` channel 实现（`svc_vlm.go:334-431`）
- 防重入双重保护：`describeTracker`（单张）+ `batchPending`（批量），避免单张与批量冲突（`svc_vlm.go:159-153`）
- DB 迁移幂等：`HasColumn` + `AddColumn` 模式，`description_model`/`description_time` 两列正确添加（`migrate.go:70-81`）
- `GetPhotoDetail` 改为直接读 DB 的 `DescriptionModel`/`DescriptionTime`，不再经过 descriptions.json（`svc_photo.go:228-233`）
- 6 个 parseVlmAttrs 单测全过，覆盖正常/空/畸形/真实输出等场景

### 健壮性 8.5

**得分点**：
- API 错误处理完善：`wrapAPIError` 区分额度超限（`errQuotaExceeded`）和其他错误，额度超限时停止所有 worker（`vlm_client.go:148-158`，`svc_vlm.go:388-391`）
- 图片压缩失败、prompt 文件缺失/为空、图片读取失败均有明确错误返回
- JSON 解析失败时只记 warning 不 panic，返回空属性（`svc_vlm.go:504-512`）
- `maybeCompressImage` 有缓存机制：已压缩过的文件直接复用（`vlm_compress.go:36-38`）
- EmbedQueue 新增 `_processing`/`_batch_pending` 跟踪，与 Go VLM 队列防冲突模式一致
- CL2 修复：`vlmHTTPClient` 60s 超时，避免 worker 永久阻塞（`vlm_client.go:22`）

**失分点**：
- `convert`（ImageMagick）命令依赖系统安装，无版本/可用性检查

### 可维护性 8.5

**得分点**：
- 文件拆分合理：`svc_vlm.go`（队列/API/解析）、`vlm_client.go`（HTTP 调用）、`vlm_compress.go`（图片压缩）
- 命名清晰有表达力：`vlmQueueManager`、`describeTracker`、`applyDescriptionToPhoto`
- `parseVlmAttrs`/`extractJSONBlock` 从废弃的 `svc_auto_sync.go` 迁移复用，注释标明来源
- 测试文件从 `svc_auto_sync_test.go` 重命名为 `vlm_parse_test.go`，保持测试连续性
- proto 新增 `GetDescribeProgress` RPC，SDK 自动生成代码同步更新

**失分点**：
- `resolveCompressOutput` 的 PhotoSrc → PhotoPath 映射逻辑稍显曲折（`vlm_compress.go:66-81`），但功能正确

### 简洁性 9

**得分点**：
- 删除彻底：`descriptions.go`（102 行）、`svc_auto_sync.go`（541 行）、`bin/batch_vlm` 二进制、config 中 `DescriptionsPath` 全部移除
- 不恢复 batch_vlm CLI，仅复用库逻辑，减少代码量
- Python 侧 `config.py` 移除 `descriptions_path`，`embed_queue.py` 增量改动精准
- 前端 composable 复用现有模式（`useVlmQueue`/`useEmbedQueue`），无过度抽象

---

## 功能效果

### 准确性 9

- VLM 实时生成已验证：DB 中 239 张照片有 `description_model=doubao-seed-2-0-lite-260428` 和 `description_time`
- API 响应与设计一致：单张返回 `Queued:true`，批量返回 `task_id`/`total`
- 进度查询 `GetDescribeProgress` 返回 `processing_ids`，前端正确消费

### 完整性 9

- 6 项验收标准代码侧全部覆盖
- VLM + Embed 双队列闭环，单张 + 批量两种模式均支持
- 前端详情页/卡片/列表全链路状态展示（loading/disabled/processing）

### 一致性 9

- VLM 队列模式与 Embed 队列模式保持一致的 API 设计（start/stop/status/progress）
- 前端 composable 模式统一：`useVlmQueue` 和 `useEmbedQueue` 结构对称
- 进度反馈一致：批量用 NTag 进度标签，单张用 NSpin/loading

---

## 用户价值

### 惊喜度 7

- 从"等待批处理文件"到"点一下实时生成"是体验质变
- 但 VLM 生成仍需等待 API 响应（几秒），非即时反馈

### 可用性 9

- 生成后直接查看，批量完成后直接 Embed，无需中间步骤
- 统计面板实时显示"VLM 待处理"/"Embed 待处理"数量

### 交互体验 8.5

- 处理中显示 loading，完成后自动刷新详情并提示"VLM 描述已生成"
- 批量进度实时显示（NTag），点击可中止
- 批量运行时禁用单张触发按钮，避免冲突

### AI 增量 9

- VLM 调用火山方舟视觉模型生成结构化描述是核心 AI 价值
- 描述 → 属性解析 → Embedding → 向量检索全链路 AI 驱动

---

## 运行时验证

- `go build ./...` 编译通过
- `go test TestParseVlmAttrs` 6/6 PASS（0.043s）
- `sqlite3` 验证：1436 张照片，100% 有 description，16.6%（239 张）有 description_model/description_time
- `grep` 确认后端代码中 `descriptions.json`/`AutoSync`/`DescriptionsPath`/`loadDescriptions`/`getDescriptionEntry` 零残留
- `bin/batch_vlm` 已删除确认
- 三个服务（backend/agent/web）全部 HTTP 健康

---

## 下一步建议

- ~~**HTTP 超时**~~：已由 CL2 修复（`vlmHTTPClient` 60s 超时）
- **ImageMagick 可用性**：`convert` 命令依赖系统安装，可考虑启动时检查或文档说明。严重程度：低
