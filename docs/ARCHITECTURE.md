# Photo Agent 架构

本文定位照片库检索、主题发现与多步创作系统的主要模块。核对范围为源码入口、目录职责和关键静态依赖，详细数据流、API 与模型约定见[系统设计](design-docs/system-design.md)。

## 主要模块

- [Web](../web/src/) 提供照片管理、对话、选题、图文工坊和导入管理界面，使用 Vue 3、TypeScript 与 NaiveUI。
- [Go 后端](../backend/internal/defaultService/) 管理照片元数据、原片与缩略图、EXIF、VLM、Embedding 代理及业务 API，使用 Kratos、GORM 与 SQLite。
- [Python Agent](../agent/README.md) 提供对话路由、检索、主题发现、创作、Runtime 和评估，通过 HTTP 与 Go 后端协作。
- [Windows 客户端](../client/) 使用 Wails 管理本地扫描、上传与同步，调用后端接口。
- [公共配置](../configs/config.yaml) 描述服务地址、存储及模型能力，个人配置位于 `.local/`。运行步骤见[部署指南](deploy.md)。

## Python 服务的职责与依赖

- 入口层为 [photo_agent.py](../agent/cli/photo_agent.py) 和 [server.py](../agent/cli/server.py)，分别承担 CLI 编排与 FastAPI 接线。
- 业务功能位于 `agent/internal/`，基础设施位于 `agent/infra/`。目录依赖按 `cli → internal → infra` 组织，具体边界见 [Python 服务说明](../agent/README.md#目录规范)。
- [chat](../agent/internal/chat/) 承担 RAG、Text-to-SQL 和会话存储，[context](../agent/internal/context/) 构造多轮上下文。
- [topics](../agent/internal/topics/) 承担聚类与选题提案，[posts](../agent/internal/posts/) 承担图文创作。
- [runtime](../agent/internal/runtime/) 组织开放目标执行，状态、预算、完成检查和恢复策略由独立模块维护，LangGraph 循环图负责串联。
- [evals](../agent/internal/evals/) 承担检索评估、规则评估与 Trace，基础设施封装后端 SDK、LLM、Chroma 与请求度量。

## 关键流程

- 照片导入后提取 EXIF、生成缩略图并保存元数据，VLM 产出描述与属性，Embedding 队列建立检索索引。
- Windows 客户端扫描和配对原片，先上传 JPG 到服务器暂存区。Go 后端计算本批次连拍组，客户端合并展示服务器预览并保存收藏或删除决定。确认留存后复用暂存 JPG，补传配对 NEF，经摘要核验后入库，按活动管理收藏及最近删除。Python Agent 定期清理已到期的向量索引。 [批次导入与回收](design-docs/2026-11-13-1-autocull-import-design.md)
- 图片管理从 Go 后端读取照片分页和分段导航，在 Web 端维护双向浏览窗口。时间线活动直接对应原片一级子目录，隐藏文件保存稳定 ID、时间与备注；后端同步目录改名并按活动和文件名组合访问路径。
- 对话入口分类后进入 SQL、RAG、工具或组合查询。已注册的开放目标进入 Runtime，多轮跟进通过上下文与任务快照继续。
- Runtime 按决定动作、执行能力、检查结果、归约状态和完成判断推进，约束、恢复次数与成本预算共同限定执行。
- 主题发现复用检索及模型能力生成提案，经 Web 审阅后可进入图文工坊。工坊由 Web 编排照片和编辑内容，Python Agent 生成或润色文案，Go 后端保存草稿并导出 ZIP。

## 修改时遵守的边界

- Go 数据访问、pgo 复用与测试要求见[项目 Go 规范](harness/styles/golang.md)，数据访问集中在 data 层，Service 承担业务编排。
- 表关联与真实数据、真实 LLM 回归限制见[项目 Agent 规则](../AGENTS.md)。
- Python 功能包的导入与复用方式见[Python 规范](harness/styles/python.md)，跨功能编排由入口层组织。

## 验证与证据入口

- [评估指南](harness/eval-guide.md)提供方法、项目工具与后端标准。
- [评估基线](eval/baseline.md)及[回归用例逻辑](eval/eval-test-logic.md)记录指标与测试口径。
- [项目上下文](harness/project-context.md#评估与运行证据)定位 Trace、回放及日志实现。
- [Agent 演进设计](design-docs/architecture/00-photo-agent-architecture.md)保存 V0–V5 的分阶段设计，具体实现与阶段状态按关联任务核对。
