# 第二轮计划

> 与 AI 共建 Photo Agent 的 AI 服务层，7 天完成向量检索、Text-to-SQL、LangGraph 工作流等核心能力落地。
> 目标：所有模块可运行、可演示，与现有 Go 后端打通。

---

## 一、总体时间规划（7 天）

| 阶段                                 | 天数  | 目标                                                 |
| ------------------------------------ | ----- | ---------------------------------------------------- |
| 第 1 阶段：Python + FastAPI + Pandas | Day 1 | 搭建 Python 服务框架，读写 API，处理照片 EXIF 元数据 |
| 第 2 阶段：LangChain + Chroma 向量库 | Day 2 | 跑通 LangChain 核心链路，Chroma 向量检索接入         |
| 第 3 阶段：文档分块 + Text-to-SQL    | Day 3 | 实现分块策略，NL2SQL 链路落地                        |
| 第 4 阶段：SSE + Function Calling    | Day 4 | 流式对话接口，LLM 自主调用照片工具                   |
| 第 5 阶段：LangGraph 查询路由        | Day 5 | 用 StateGraph 实现 SQL / RAG 条件路由工作流          |
| 第 6 阶段：评估指标 + AI 工程保障    | Day 6 | 检索效果评估，重试 / 降级 / Token 成本追踪           |
| 第 7 阶段：联调 + 文档               | Day 7 | 全链路联调，整理文档，确保可演示                     |

---

## 二、每日任务

### Day 1：Python + FastAPI + Pandas

- 搭建 Python 虚拟环境，初始化 `python-service` 服务目录
- 完成 FastAPI 基础接口（路由、Pydantic 模型校验、依赖注入）
- 用 Pandas 读取照片 EXIF 信息，处理多品牌字段差异、GPS 转换、时间规范化
- 输出清洗后的 DataFrame 到 SQLite `photos` 表
- 编写照片分布统计脚本（按品牌、镜头、地点、时段）

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
