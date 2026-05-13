# 第二轮计划

> 与 AI 共建 Photo Agent 的 AI 服务层，7 天完成向量检索、Text-to-SQL、LangGraph 工作流等核心能力落地。
> 目标：所有模块可运行、可演示，与现有 Go 后端打通。

---

## 架构定位

```
用户浏览器
    ↓ HTTP
Dify Web UI (Agent 编排 + 知识库 RAG + 聊天 UI)
    ↓ Function Calling
    ├─→ Go Backend (:10000)  ← 工具层（数据读写 + 文件服务）
    └─→ Python AI Service    ← 推理层（LangChain/LangGraph/Chroma）
            ↓ HTTP 调用工具
            Go Backend API
```

- **Go Backend**：工具层。照片元数据 CRUD、EXIF 提取、文件服务、统计查询 — 所有数据类接口都在 Go 中实现
- **Python AI Service**：推理层。LangChain Chain、Chroma 向量检索、Text-to-SQL、LangGraph 工作流 — 只做 AI 编排，通过 HTTP 调用 Go 工具获取数据
- **Python 不自己管理数据库、不重复实现 CRUD**，需要新工具时扩展 Go server

---

## 一、总体时间规划（7 天）

| 阶段 | 天数 | 目标 |
| --- | --- | --- |
| 第 1 阶段：Go 工具扩展（EXIF + 统计） | Day 1 | 扩展 Go 后端 Photo 模型与导入流水线，增加 EXIF 字段，新增统计 API |
| 第 2 阶段：LangChain + Chroma 向量库 | Day 2 | 跑通 LangChain 核心链路，Chroma 向量检索接入 |
| 第 3 阶段：文档分块 + Text-to-SQL | Day 3 | 实现分块策略，NL2SQL 链路落地 |
| 第 4 阶段：SSE + Function Calling | Day 4 | 流式对话接口，LLM 自主调用照片工具 |
| 第 5 阶段：LangGraph 查询路由 | Day 5 | 用 StateGraph 实现 SQL / RAG 条件路由工作流 |
| 第 6 阶段：评估指标 + AI 工程保障 | Day 6 | 检索效果评估，重试 / 降级 / Token 成本追踪 |
| 第 7 阶段：联调 + 文档 | Day 7 | 全链路联调，整理文档，确保可演示 |

---

## 二、每日任务

### Day 1：Go 后端扩展 — EXIF 元数据 + 统计工具 API

> 为后续 Python Agent 准备数据工具接口。所有变更在 Go 后端完成，不涉及 Python 代码。

#### 1.1 扩展 Photo 模型

在现有 `photos` 表新增 EXIF 字段：

```
brand         TEXT    — 品牌（统一大写简称：NIKON/CANON/SONY/...）
model         TEXT    — 相机型号
lens          TEXT    — 镜头型号
focal_length  TEXT    — 焦距，如 "35mm"
aperture      TEXT    — 光圈，如 "f/3.2"
iso           INTEGER — ISO 感光度
exposure_time TEXT    — 快门速度，如 "1/125"
latitude      REAL    — GPS 纬度（十进制）
longitude     REAL    — GPS 经度（十进制）
altitude      REAL    — GPS 海拔
```

涉及文件：
- `internal/model/photo.go`：新增上述字段，GORM AutoMigrate 自动添加列
- descriptions.json 中的 `shot_at` 改为直接从源文件 EXIF 读取，不再依赖 json 传递

#### 1.2 改造 EXIF 读取

将现有的 `GetExifShotAt` 扩展为 `GetExifInfo`，返回完整 EXIF 结构体：

- 当前只读了 `DateTimeOriginal` 一个 tag
- 扩展读取：Make、Model、LensModel、FocalLength、FNumber、ISOSpeedRatings、ExposureTime、GPSInfo
- 品牌规范化：NIKON CORPORATION → NIKON，Canon Inc. → CANON 等
- GPS DMS → 十进制转换
- 评估 `rwcarlsen/goexif` 对 Nikon/Canon MakerNote 的兼容性，必要时切换到 `dsoprea/go-exif`

涉及文件：
- `internal/service/processor.go`：`GetExifShotAt` → `GetExifInfo`
- `internal/service/sync.go`：`importNewPhoto` / `resolvePhotoData` 适配新字段
- `internal/service/photo.go`：`SavePhoto` 适配新字段

#### 1.3 新增统计 API

在 Go 路由中新增：

- `GET /api/photos/stats` — 综合统计（品牌/镜头/焦距段/GPS/月份/时段分布）
- `GET /api/photos` — 扩展筛选参数：`brand`、`lens`、`focal_min`/`focal_max`、`iso_min`/`iso_max`

涉及文件：
- `internal/api/routes.go`：注册新路由
- `internal/api/photo.go`：新增 stats handler
- `internal/service/photo.go`：新增统计查询方法

---

### Day 2：LangChain + Chroma 向量库

- 理解 LangChain 核心组件：Prompt Template、LLM/ChatModel、Chain、Tool、Retriever
- 用兼容 OpenAI 的代理封装 Doubao 模型，跑通 LLMChain
- 实现照片问答 Chain：Chroma 检索相关照片描述 → LLM 生成回答
- 搭建 Chroma 向量数据库，定义照片描述 Collection，实现基础 CRUD
- 将现有 VLM 生成的照片描述导入 Chroma，测试检索效果

---

### Day 3：文档分块 + Text-to-SQL

- 实现文档分块策略：短描述（<500 字）整块存储，长描述用递归分块 + 重叠窗口，每块带照片 ID 前缀
- 检索时按块查询，返回时聚合到照片级别
- 理解 Text-to-SQL 原理：Schema 提示 + Few-shot 示例 → LLM 生成 SQL
- 定义 `photos` 表 Schema，实现 NL2SQL 链路
- SQL 安全校验：只允许 SELECT 语句，执行前解析校验
- 在 FastAPI 暴露自然语言查询接口

---

### Day 4：SSE + Function Calling

- 理解 SSE（Server-Sent Events）原理，在 FastAPI 实现流式输出接口
- 对接 Go 后端 SSE 代理，前端展示打字机效果
- 定义照片工具函数：`search_photos`、`archive_photos`
- 实现 Function Calling：LLM 根据用户意图自动选择并调用工具
- 跑通"找照片"→触发搜索，"归档照片"→触发归档的完整链路

---

### Day 5：LangGraph 查询路由

- 理解 LangGraph 与 LangChain 的区别：显式 State + 条件分支 vs 线性 Chain
- 掌握 StateGraph 核心概念：State（TypedDict）、Node、Edge、Conditional Edge
- 实现查询路由 StateGraph：
  - 入口节点 `classify`：判断查询类型（结构化统计 / 语义检索）
  - 条件分支：`sql` 分支走 Text-to-SQL，`rag` 分支走 Chroma 检索 + LLM 生成
  - 汇聚节点 `answer`：格式化最终回答
- 在 FastAPI 暴露 `/workflow/query` 接口，替换直接链路调用
- 跑通两类查询：统计型走 SQL 分支，语义型走 RAG 分支

---

### Day 6：检索评估 + AI 工程保障

#### 检索评估

- 理解 RAG 评估指标：Precision@K、Recall@K、MRR
- 构建测试集：人工标注 20~50 个查询-相关照片对
- 编写评估脚本，对比不同分块策略的表现，记录基线数据

#### AI 工程保障三件套

- **重试**：所有 LLM/VLM/Embedding 调用接入 `tenacity` 指数退避重试（约 2s/4s/8s），仅对超时和连接异常重试
- **降级**：LangChain Chain 接入 `with_fallbacks`，主模型（Doubao-pro）失败时自动降级到备用模型（Doubao-lite）
- **Token 成本追踪**：SQLite 建 `token_usage` 表，配置 `prices.yaml` 模型单价，调用封装层记录 input/output token 用量并计算成本
- 提供 `/admin/usage` 按天 / 按模型聚合统计接口

---

### Day 7：联调 + 文档

- 全链路端到端联调：Go 后端 ↔ Python 服务 ↔ Chroma ↔ LLM 代理
- 覆盖场景测试：向量检索、Text-to-SQL、SSE 流式对话、Function Calling 工具调用、LangGraph 查询路由
- 验证 AI 工程保障：重试触发、降级切换、Token 追踪落库
- 整理 README，说明 Python 服务层架构、模块职责、启动方式
- 确保所有代码可运行、可演示
