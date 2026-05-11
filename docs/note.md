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

**背景**：batch_vlm 默认 3 并发调用 VLM API，每处理 10 张保存一次中间结果到 JSON。

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
