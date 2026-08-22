# 归档文档

## [commitlint](`https://github.com/conventional-changelog/commitlint`)

| prefix   | desc         |
| -------- | ------------ |
| build    | 构建相关     |
| chore    | 杂项         |
| ci       | CI/CD 相关   |
| docs     | 文档         |
| feat     | 功能         |
| fix      | 修复         |
| perf     | 性能         |
| refactor | 重构         |
| revert   | 回退         |
| style    | 代码风格     |
| test     | 测试         |
| 以下为   | 个人额外加的 |
| gen      | 生成代码     |
| improve  | 优化代码     |
| tidy     | 整理、清理   |
| bak      | 备份         |

---
> 下面记录讨论中被否定、推翻或变更的方案，留档备查。

## batch_vlm 并发安全问题

**问题**：`descriptions.json` 在并发 VLM 处理中存在两个安全隐患。

**背景**：batch_vlm 默认 3 并发调用 VLM API，每张处理完的结果先写入内存 map，每处理满 10 张时保存一次中间结果到 JSON 文件（原子写入），全部完成后最终保存到文件。

**隐患 1 — map 并发读写 panic**

- `saveResult` 内部 `json.MarshalIndent` 遍历 map，但调用时未加锁
- 同时其他 goroutine 可能正在写入 `result[relPath] = ...`
- 后果：`fatal error: concurrent map read and map write`

**隐患 2 — 文件非原子写入**

- `os.WriteFile` 直接覆盖目标文件，不是原子操作
- 并发保存或程序中断时可能产生半写损坏的 JSON
- 一旦损坏，之前所有 VLM 调用结果丢失

**修复方案**（[backend/cmd/batch_vlm/main.go](backend/cmd/batch_vlm/main.go)）：

- 中间保存时先 `mu.Lock()` 深拷贝 map 到 snapshot，解锁后再 Marshal + WriteFile
- `saveResult` 改为临时文件 + `os.Rename` 原子覆盖

---

## config.go 中 dify.base_url 的 default 值与文档不一致

**问题**：`backend/internal/config/config.go` 中 `DifyConfig.BaseURL` 的 default 值为 `"http://localhost/v1"`，但文档和实际 init_dify 代码都要求**不带** `/v1` 的 Dify 根地址。

**影响**：如果用户不手动覆盖配置，init_dify 会构造出错误的 Console API 路径（`http://localhost/v1/console/api/login`），导致登录失败。

**待修复**：将 `config.go` 中 `DifyConfig.BaseURL` 的 default 改为 `"http://localhost"`。

---

## 火山引擎多模态 Embedding 在 Dify 中的配置踩坑

**背景**：Dify 知识库需要使用 Embedding 模型将照片描述向量化。选用火山引擎的 `doubao-embedding-vision-251215`。

**问题 1：Dify 无法直接配置火山 Embedding URL**

- 火山的 Embedding URL 为 `https://ark.cn-beijing.volces.com/api/v3/embeddings/multimodal`，但 Dify 的 openai-api-compatible 插件会自动在配置的 base_url 后追加 `/embeddings`
- 如果直接在 Dify 中配置火山 URL，会被追加为 `/embeddings/multimodal/embeddings`，导致请求失败
- **解决**：通过 Go 后端提供 `/v1/embeddings` 代理，Dify 中配置 `http://host.docker.internal:10000/v1`，由 Go 后端转发到火山真实 URL

**问题 2：火山 Embedding 文档不完善**

- `doubao-embedding` 文档缺少接入指引，正确的模型 ID 和 URL 不明确
- 当前使用 `doubao-embedding-vision-251215` 作为确认可用的版本

**状态**：已通过 Go 后端 Embedding 代理解决，Dify 中配置代理地址即可。

---

## 1. 技术栈变更记录

### 1.1 纯 Python 单栈 → Go + Python 双栈（重新启用）

**初始决策（2026-05-08）**：纯 Python 单栈（FastAPI + LangChain + Chroma）。

**理由**："不能太杂"，5 天周期紧张，AI 生态 Python 最完整。

**推翻（同日）**：用户表示 go+py 不复杂，且能复用 Go 代码库，手写 Go 效率高。

**最终决策**：Go + Python 双栈。

- **Go 后端**：API 路由、业务逻辑、SQLite 数据访问、文件管理（Gin + GORM）
- **Python AI 服务**：VLM、LLM Agent、向量检索、Embedding（FastAPI + LangChain + Chroma）
- **Python CLI**：用户交互（Click + Rich），调用 Go API

### 1.2 Go + Python 双栈（最初建议）→ 复杂分布式架构（被否定）

**最初建议**：Go Gateway（Kratos）+ MySQL + MinIO + Milvus + Python AI 服务。

**否定原因**：用户要求"尽情简化"，MinIO/MySQL/Kratos 对单机 demo 没必要。

**最终架构**：Go（Gin + GORM + SQLite）+ Python（FastAPI + Chroma + 本地文件）。

### 1.3 Go + Python 双栈 → Dify + Go 双栈（零 Python）

**变更时间（2026-05-09）**：Day 1 开发中，Python AI 服务侧工作量被 Dify 覆盖。

**最终架构**：Dify（Docker）+ Go（Gin + GORM + SQLite），零 Python。

### 1.4 Dify + Go 双栈 → Dify + Go + Python 三栈（重新引入 Python AI 服务层）

**变更时间（2026-05-12 起）**：第二轮开发中，重新引入 Python AI 服务层。

**变更原因**：

1. **学习目的**：LangChain / LangGraph / Chroma / Text-to-SQL / Function Calling 等 AI 工程概念需要通过代码实践掌握
2. **深度优化**：Dify 的图形化编排适合快速出效果，但 Python 层可实现更精细的 Agent 流程控制（查询路由、流式输出、工具绑定）
3. **技术债务可控**：Python 层完全通过 HTTP 调用 Go 后端，不直接访问数据库或文件系统，边界清晰

**最终架构**：

- **Dify**：Agent 图形化编排、知识库 RAG、自带聊天 UI（作为另一条实现路径）
- **Go 后端**：照片元数据 CRUD、文件服务、导入流水线、VLM 预处理、Embedding HTTP 代理、统计 API
- **Python AI 服务层**：LangChain 编排、Chroma 向量检索、Text-to-SQL、LangGraph 查询路由、Function Calling 工具调用、流式输出

**变更时间（2026-05-09）**：在 Day 1 开发过程中，Python AI 服务侧的工作量被 Dify 完全覆盖。

**变更原因**：

1. **Agent 编排**：Dify 提供图形化工作流可观测 + 自带聊天 UI，无需手写 Python Agent 代码
2. **知识库 RAG**：Dify 内置向量检索（Weaviate）和 Embedding，无需自建 Chroma
3. **模型管理**：Dify 统一管理 LLM / Embedding / Rerank 的 API Key 和参数，无需在 Python 中维护多套配置
4. **开发效率**：零前端框架 + 零 Python，技术栈收缩为纯 Go + Docker，维护成本显著降低

**最终架构**：Dify（Docker 本地部署）+ Go（Gin + GORM + SQLite）。

- **Dify**：Agent 编排、知识库 RAG、聊天 UI、模型管理、工作流可视化
- **Go 后端**：照片元数据 CRUD、文件管理、导入任务调度、VLM HTTP 代理
- **零 Python**：VLM 视觉描述、Embedding 均通过云端 API 由 Go 直接 HTTP 调用

---

## 2. 数据集变更记录

**方案演进链条**：

1. 爱死机短片 → 版权风险，否定
2. Blender《Sintel》开源短片 → 无版权风险，一度被接受
3. **最终推翻**：全部改用真实摄影素材

**最初选择动漫素材的原因**：角色特征固定，适合展示"角色知识库""一致性检查"等高级功能。

**推翻原因**：真实需求优先。300 张摄影照片是用户真实拥有的数据，项目日常可用比演示效果更重要。

**关键调整**：

- 不做人物身份识别
- "角色档案问答" → "摄影档案问答"（时间线/标签）
- "剧本创作辅助" → "摄影主题分析与创作建议"
- "角色一致性检查" → 砍掉

---

## 3. 被砍掉的功能

| 功能           | 最初优先级 | 砍掉原因                           |
| -------------- | ---------- | ---------------------------------- |
| 素材分析助手   | P1         | 视觉 AI 厂商直接提供，无造轮子意义 |
| 角色一致性检查 | P2         | 数据集改为摄影素材后，无"角色"概念 |

---

## 4. 数据集决策讨论（2026-05-08）

**问题**：用真实摄影素材还是动漫/影视素材？

**核心考量**：

- 摄影素材：真实需求，VLM 对真实照片识别更稳（训练数据以照片为主）
- 动漫素材：功能展示完整（角色知识库等），但无真实使用场景

**决策**：采用真实摄影素材为主，产品定位改为"个人摄影资产助手"。

**真人短片**：可选辅助展示（展示 VLM 对真人场景的识别），非主要数据集。

---

## 5. 项目最初思路（归档）

> 从 readme 迁移，记录项目最初的构思来源和演变过程。

构思起点：当前 AI 文本能力最强，图片/音频/视频能力依次降低，但后三者本身难度也更高。结合之前在动漫公司类似项目经验，思路如下：

1. **视觉描述建库**：先对常见角色图片进行视觉描述，建立文字描述库。以这些描述为上下文，继续对图片用 AI 做视觉描述，通过文本搜索找到特定图片。
2. **数据范围**：原画、分镜图、制作输出图片、成片按镜头切割的截图等。
3. **应用场景演变**：基础检索 → RAG 技术 → AI Agent 应用。本质上是把公司资产做成数据库（文本/图片/音频/视频），在此之上搭建 agent 辅助创作（新剧情剧本、出图出视频）。
4. **角色识别**：人工标识角色，提供有规则命名的角色图片（整/侧/俯视图）。
5. **数据规模**：约 300 张精选摄影照片，不超 1 万张。如顺利，计划用真人短片（按镜头截图后识别）作为展示案例。
6. **Agent 方向论证**：纯检索没必要用 AI，有了文本描述很多搜索技术可建索引。生图生视频核心在模型，不是个人能做出的成果。所以产品形态应是 agent——基于数据 + LLM 结合成 agent 应用，做思考，限于文本输出，不用输出图和视频。
7. **技术偏好**：初学者阶段，无具体偏好。参考 `DemoProject.md` 了解技术能力。
8. **展示形态**：一人团队，AI 辅助的新开发模式。用户扮演开发过程各角色（产品、架构、开发、测试），AI 完成具体文档、代码、部署。产出包括可运行 demo、方案文档、技术博客。

---

## 6. 前期讨论详细结论（归档）

> 从 readme 迁移，记录前期技术方案讨论的全过程。

### 6.1 技术栈详细方案

```
用户 → Python CLI (Click + Rich)
          ↓ HTTP
      Go Backend (Gin / 标准库)
          ├── 业务服务：素材管理、会话管理、导入任务
          ├── SQLite 数据访问
          └── 文件服务
          ↓ HTTP JSON
      Python AI Service (FastAPI + LangChain + Chroma)
          ├── VLM 视觉描述
          ├── LLM Agent 编排
          ├── 向量检索
          └── Embedding
```

- **Go 后端**：API 路由、请求校验、业务逻辑、SQLite CRUD、文件管理。复用用户 Go 工程经验和代码库。
- **Python AI 服务**：纯 AI 能力（VLM / LLM / 向量检索 / Embedding），通过 HTTP 接口对外暴露。
- **Python CLI**：调用 Go API，提供交互式命令行界面。
- **通信**：Go ↔ Python 通过 REST JSON API。

### 6.2 Agent 能力边界

```
P0 (MVP 必须): 智能检索 + 摄影档案问答
P1 (展示价值高): 摄影主题分析与创作建议
P2 (加分项): 时间线关联分析 + 个人摄影风格知识库
```

- **砍掉素材分析助手**：视觉 AI 厂商直接提供，无造轮子意义
- **不做人物身份识别**：亲友相貌相似，提高准确率成本太高，非核心展示场景
- **交互方式**：聊天 API + CLI，Web 界面后续再考虑

### 6.3 数据集详细方案

- **全部使用真实摄影素材**（约 300 张精选照片）
- 按时间线命名文件夹，如 `photos/2024-02-云南/`
- 真人短片截图仅作可选辅助展示

### 6.4 项目优先级与范围

- **优先处理 media_agent**，忽略 team-docflow（DemoProject.md 中的内容）
- 部署目标：前期本地 Docker，性能不足时搬迁云服务器
- 开发周期：5 个工作日（AI 辅助）

### 6.5 待确认清单（已全部确认）

- [x] **技术栈**：Go + Python 双栈（Go 后端 + Python AI 服务 + Python CLI）
- [x] **AI 模型**：云端 API，无本地 GPU
- [x] **Agent 能力边界**：P0/P1/P2 如上，砍掉素材分析助手和角色一致性检查
- [x] **展示素材**：全部使用真实摄影素材
- [x] **向量数据库**：Chroma（Python 侧）
- [x] **业务数据库**：SQLite（Go 侧管理）
- [x] **项目优先级**：忽略 team-docflow，优先处理 media_agent
- [x] **部署目标**：前期本地 Docker 开发测试

---

## 7. 准备工作清单详情（归档）

> 从 readme 迁移，开发启动前的准备工作详细说明。

1. **整理摄影照片**
   - 从 300 张精选照片中，挑选 100-200 张用于 demo
   - 按时间线命名文件夹，如 `photos/2024-02-云南/`
   - 格式建议：`{年份}-{月份}-{主题或地点}`

2. **（可选）准备真人短片截图**
   - 找一个无版权真人超短片
   - 截取 20-30 张关键镜头，放入 `assets/shortfilm/` 目录

3. **准备 API Key**
   - OpenAI（GPT-4o-mini）：platform.openai.com
   - 或 Qwen（通义千问）：dashscope.aliyun.com
   - 已有 Kimi key，可作为备选

4. **开发环境**
   - Go 1.22+
   - Python 3.11+
   - 创建 Python 虚拟环境：`python -m venv venv`

---

## 8. 架构演进：Dify 降级为可选 → Web 前端 + Python Agent API（2026-06）

**变更**：原计划 Dify 作为 Agent 编排入口和聊天 UI，实际开发中逐步转向：

- **Agent 编排**：LangGraph StateGraph（Python 侧）替代 Dify Agent
- **聊天 UI**：Vue 3 + NaiveUI Web 前端替代 Dify Web UI
- **对话 API**：Python FastAPI（`chain/server.py`）提供 REST 对话接口
- **向量检索**：ChromaDB（Python 侧）替代 Dify 知识库（Weaviate）

**Dify 现状**：`dify/` 目录保留 Docker 部署配置和 DSL 文件，作为可选验证路径。不再作为核心方案维护。

**原因**：
1. LangGraph 提供更精细的查询路由（4 类节点 + 条件边），Dify 图形化编排灵活性不足
2. Web 前端可定制照片管理功能（上传/筛选/VLM队列/Embedding状态），Dify 只有通用聊天 UI
3. ChromaDB 可控性强，metadata 最小化策略（Route B）在 Dify 知识库中不好实施

---

## 9. ChromaDB 元数据最小化决策 — Route B（2026-06-23）

**背景**：ChromaDB collection 的 metadata 字段设计有两条路线。

**Route A**：ChromaDB 冗余存储结构化属性（objects/colors/scene/lighting/mood/composition），用 `where` 过滤做组合检索。

**Route B**（✅ 采用）：ChromaDB 仅存 `photo_id` + `chunk_index`，所有结构化属性在 Go SQLite 中，结构化过滤走 Text-to-SQL。

**选择 Route B 的原因**：
1. Go SQLite 是唯一数据源，避免 Chroma metadata 与 SQLite 数据冗余及同步问题
2. 职责边界清晰：向量库只管语义相似度，SQL 只管结构化过滤
3. 组合查询（如"逆光的雪山照片"）通过 SQL ∩ RAG 取交集实现，效果优于单一路径

**设计文档**：`docs/design/chroma-metadata-design.md`

---

## 10. Combined 组合查询实现（2026-06-24）

**背景**：用户查询"蓝调时刻的街拍""暖色调的人像""逆光的雪山"等同时涉及结构化维度（光线/色调/场景）和语义内容的复合查询，需要两条路径协同。

**方案 B（✅ 采用）**：分类器增加 `combined` 类型 + LangGraph 新增 `combined_query` 节点，内部并行执行 SQL 过滤和 RAG 语义检索，取 photo_id 交集。

**流程**：
```
classify → "combined"
    ├─ generate_filter_sql() → SQL 执行 → sql_ids
    ├─ retrieve_photo_ids() → RAG 语义检索 → rag_ids
    ├─ intersection = sql_ids ∩ rag_ids（保持RAG相似度排序）
    └─ 5 层降级：SQL异常/过宽(>50)/为空/交集空/整体异常 → 纯 RAG
```

**关键发现**：Go 后端的属性映射函数（`mapScene`/`mapLighting`/`mapMood`）产出的值（如 `backlit`）与最初 text_to_sql.py 硬编码的值（如 `backlight`）不一致，导致 SQL 匹配率为 0。

**修复**：新增 `GET /api/v1/photos/attribute-values` API 返回 DB 中实际 distinct 值，text_to_sql.py 动态获取并拼入 System Prompt，确保 LLM 只生成实际存在的值。

**区别于方案 A**（仅增强分类器描述，让 LLM 自动判断走 SQL 还是 RAG）：方案 B 新增独立节点显式执行两条路径取交集，更可控、可观测、降级策略明确。

---

## 11. 图片上传改为原图直传 + 后端压缩（2026-06）

**原方案**：前端用 `browser-image-compression` 压缩后再上传。

**现方案**：前端原图直传，Go 后端用 ImageMagick（`convert -resize 512x512> -quality 85 -format jpg`）压缩，保留完整 EXIF。

**原因**：
1. 浏览器压缩会丢失 EXIF 数据（拍摄时间、相机参数等），后端 ImageMagick 可保留
2. 上传链路：原图 → Go 保存原图 + 生成压缩缩略图 → VLM 用压缩图描述 → 原图用于展示

---

## 12. config.go 中 dify.base_url default 值修复

**问题**：见上方第 2 节。Dify 已降级为可选方案，此配置项保留兼容，default 值是否需要修复视后续是否继续使用 Dify 而定。当前状态：未修复，因为 Dify 不在核心路径上。

---

## 13. 导入工作流 NEF 清理：自动删除 → 仅复制（2026-08-12）

**原方案**：客户端执行阶段「复制保留的 NEF 到 like 目录 + 删除其余 NEF + 清空 nef 目录」，并提供「移动到回收站」选项。

**变更**：执行阶段改为「仅复制保留的 NEF 到 like 目录」，不删除任何文件，完成后提示用户 nef/ 目录可自行删除。

**原因**：避免程序误删不可恢复；删除动作交还用户，由用户确认后手动清理，安全性更高。

**影响**：客户端 Go 层不实现删除类文件操作（`MigrateKeptNef` 仅复制）。删除列表仍会计算并展示，供用户参考。

---

## 14. 导入工作流术语统一 + 报告精简（2026-08-13）

**原方案**：NEF 分「保留/删除/未匹配」三类，报告展示迁移列表和删除列表。

**变更**：术语统一为「收藏/留存/废弃」：

- 收藏：like 中有同名 JPG，NEF 保留迁移
- 留存：full 中有、like 中无，NEF 跳过
- 废弃：full/like 中都没有，NEF 跳过

报告不再展示逐文件的迁移列表和删除列表，改用汇总数据（收藏 NEF 数、跳过留存 NEF 数、跳过废弃 NEF 数）。

**原因**：原「删除列表」文案「对应 JPG 已删除」与实际判定（full 有 like 无，即未收藏）不符；真正「照片已删除」的是 unmatched，却标为「未匹配/不处理」。术语错位导致理解矛盾。

**影响**：`ImportAnalysis` 字段由 `keep/delete/unmatched` 改为 `favorite/retained/discarded`；前端步骤 2 只展示统计摘要，不再有折叠列表。

---

## 15. 照片列表排序收敛：三键排序 → 仅拍摄时间升降序（2026-08-20）

**原方案**：图片管理页排序支持拍摄时间 / 文件名 / 导入时间三个键（下拉选择）+ 升降序切换。

**变更**：移除「按文件名 / 按导入时间」排序及对应 UI，仅保留拍摄时间升/降序。后端 `sortBy` 参数与 DAO 白名单保留不动，仅前端不再提供其他入口。

**原因**：分段浏览（LB1）依赖照片流时间有序，非时间排序下按天/活动分段线会反复跳跃失去意义。与其做「切换排序时分段自动退化」的兼容分支，直接收敛排序维度，交互和实现都更简单（用户确认）。

**影响**：PhotoManagement 排序下拉框移除，UI 简化为一个升降序切换按钮。

---

## 16. VLM 描述从预生成文件同步改为实时 API 调用（CL1，2026-08-22）

**原方案**：VLM 描述通过 `batch_vlm` CLI 预生成到 `descriptions.json`，Go 后端启动时 `AutoSync` 读取该文件同步到 SQLite。

**变更**：

- 删除 `descriptions.json`、`batch_vlm` CLI、`AutoSync` 目录扫描导入
- Go 后端 `VlmServer.DescribePhoto` 改为实时调用火山方舟 Responses API 生成描述
- `description_model` / `description_time` 从 descriptions.json 迁入 photos 表（新增两列）
- 上传成为唯一导入路径，VLM/Embed 在 Web 页面形成闭环

**废弃代码**：`descriptions.go`、`svc_auto_sync.go`、`bin/batch_vlm`、`conf.C.Storage.DescriptionsPath`

**复用逻辑**：`parseVlmAttrs` / `extractJSONBlock` / `vlmJSON` 从 `svc_auto_sync.go` 迁入 `svc_vlm.go`；旧 `internal/vlm/client.go` 和 `compress.go` 适配为 `vlm_client.go` 和 `vlm_compress.go`
