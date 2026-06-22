## Phase 1 — 让照片「可被多维检索」✅

### VLM 描述结构化提取（已完成 ✅）

- 原 `agent/scripts/extract_attributes.py`（LLM 提取属性）已被 Go 后端 AutoSync 内置的 `ParseStructuredAttributes` 替代
- VLM 已输出富结构化 JSON，Go 端直接解析（零额外 LLM 成本）
- 解析结果（objects/colors/scene/lighting/mood/composition）直接存入 SQLite Photo 记录

### Chroma 元数据过滤利用 — 自动 where 提取（已完成 ✅）

- `agent/chain/photo_rag.py`：`METADATA_SCHEMA` + `FILTER_PROMPT` + `extract_filters_from_question()`
- 结构化属性随 AutoEmbed 写入 Chroma metadata，支持 scene/lighting/mood where 过滤

### AutoEmbed 启动时自动索引（已完成 ✅）

- `agent/chain/auto_embed.py`：Agent 启动时自动对比 Go API 数据与 Chroma manifest，增量 Embedding + 进度条
- 不再需要手动运行 `index_photos.py`

---

## Phase 2 — Web 前端 + 完善

> 当前 Web 页面处于初步开发阶段（参见 `backend/internal/api/` 内 upload/import 相关路由）。

### TODO — Web 阶段

- [ ] **Web UI：照片画廊页** — 分页浏览、缩略图网格、点击查看详情
- [ ] **Web UI：上传 + VLM 处理** — 上传照片 → 后台 VLM 队列 → 自动生成描述和结构化属性
- [ ] **Web UI：搜索与过滤** — 按场景/光线/情绪/关键词筛选照片
- [ ] **Web UI：Embedding 进度展示** — AutoEmbed 进度条在 Web 端可视化（当前仅为 CLI 进度）
- [ ] **Web UI：结构化属性编辑** — 在线编辑 objects/colors/scene/lighting/mood/composition
- [ ] **完善 VlmQueue** — 当前 `vlm_queue.go` 已有基础框架，需补全上传→VLM→入库→AutoEmbed 的完整流程
- [ ] **AutoEmbed Web 集成** — 上传新照片后自动触发增量 Embedding（不依赖 Agent CLI 重启）

### TODO — 质量

- [ ] **评估基线建立** — `evaluation.py` 的 `relevant_photos` 字段需人工标注，建立 RAG 评估基线
- [ ] **GPS 反向地理编码** — EXIF 中已有经纬度，调用 API 转为地名存入 `location` 字段
- [ ] **SQLite WAL 模式** — `PRAGMA journal_mode=WAL` 提升并发读写效率
- [ ] **日志轮转与分级** — 接入 pgo 日志体系，长期运行不占用过多磁盘

---

## 遗留事项

- [ ] `agent/embedding/embedder.py:63`：Embedding URL 写死为 `{base_url}/v1/embeddings`，应支持配置灵活指定
- [ ] `backend/internal/api/routes.go:41-45`：import API 和 batch_vlm 逻辑重复，需合并统一
- [ ] 匹配时间线的逻辑优化：支持更多日期格式，模糊匹配连续几天到同一活动
