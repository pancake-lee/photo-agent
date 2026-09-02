# agent/ — Python AI 服务

Photo Agent 的 AI 侧服务：LangChain + Chroma + LangGraph，负责照片 RAG 检索、Text-to-SQL、主题发现、图文工坊与 Agent Runtime 多步执行。通过 HTTP 与 Go 后端交互，由 Go 侧统一对外提供页面 API。

## 运行入口

- `make dev`：创建/复用 `.venv` 并启动 Agent Server（`cli/photo_agent.py --serve`）
- `make venv`：显式重建 `.venv`（注意：重建后需重新安装 backend-sdk，见下文「backend-sdk/」）
- 常用 CLI（在 agent 目录执行，配置指向 `../.local/*.yaml`；入口文件已带路径引导，从其他目录直接 `python cli/photo_agent.py` 也可运行）：
  - `cli/photo_agent.py -c <config> --serve`：启动 FastAPI 服务（正式入口）
  - `cli/photo_agent.py -c <config> --suggest`：选题建议管线
  - `cli/photo_agent.py -c <config> --eval`：RAG 检索评估
  - `scripts/eval_regression.py -c <config>`：三层检索回归（L0 数据态 / L1 函数 / L2 HTTP）

## 目录规范

按功能分包（package by feature）+ 三层金字塔，依赖方向必须单向：

- `cli/（入口）→ internal/（业务功能包）→ infra/（基础设施）`
- `internal/` 内各功能包（chat / topics / posts / runtime / evals）之间不互相 import：跨功能复用的实现下沉到 `infra/`，跨功能的编排放在入口层
- `infra/` 不 import `internal/` 与 `cli/`，只被依赖
- 顶层只放工程管理文件（makefile / pyproject.toml / uv.lock / README）与测试、脚本、SDK、退役目录
- import 风格遵循 Go 式限定调用（详见 `docs/handbook/coding-conventions.md` 导入规范）：`import internal.chat.photo_rag as photo_rag`，调用点 `photo_rag.answer_question(...)`；禁止 `from xxx import <符号>` 导入项目内模块

## 目录与文件职责

> 目录与文件均按字符串排序，与 VSCode 文件树顺序一致；`__init__.py` 为空包标记，不单独列出。

### 根文件（工程管理，不放源码）

- `makefile`：venv 重建与服务启动
- `pyproject.toml` / `uv.lock`：依赖声明与锁定，uv 管理

### backend-sdk/ — Go 后端 Swagger SDK（生成代码）

- `setup.py`：editable 安装所需（`.venv` 中以 `uv pip install -e ./backend-sdk` 装入）
- `swagger_client/`：swagger-codegen 生成的 Go 后端客户端，运行时代码经 `infra/backend_sdk.py` 引用
- 注意：`make venv` 重建环境后不会自动重装本 SDK，需手动执行上述安装命令，否则 `import swagger_client` 失败

### bak/ — 已退役文件（待手动删除）

- 2026-08-31 目录整理移入：学习性 demo（`demo/` 全目录，含其配套 `tests/test_query_router.py`）、一次性调试脚本（`scripts/debug_pid.py`）、过期 smoke 测试（`chain/test_suggest_smoke.py`）、backend-sdk 的 codegen 自带测试与 CI 脚手架（`test/`、`tox.ini`、`.travis.yml`、`git_push.sh`、`test-requirements.txt`）
- 保留原相对路径，确认无用后可整目录删除；需要恢复时按原路径移回即可

### cli/ — 入口层（类 Go cmd/）

- `demo.py`：全链路场景演示（`--demo` 触发，跑固定查询列表）
- `photo_agent.py`：CLI 入口与 PhotoAgent 编排，按类别路由到 SQL / RAG / Runtime 分支
- `server.py`：FastAPI 服务，对外暴露 Agent HTTP API（会话、检索、选题、图文工坊、trace 端点）

### infra/ — 基础设施（被 internal 与 cli 单向依赖）

- `backend_sdk.py`：Go Backend SDK 共享工厂，统一管理 swagger_client 配置与 API 实例
- `chroma_client.py`：ChromaDB 客户端封装（集合管理、写入、检索）
- `config.py`：全局配置加载（YAML），各模块统一从这里取配置
- `embed_queue.py`：照片 Embedding 异步队列，由 `/api/embed/*` 端点驱动
- `embedding/` — 文本向量化
  - `chunking.py`：描述文本分片策略（按字数、按 Markdown 标题等），`chunk_text` 统一分发
  - `embedder.py`：调用 Embedding 模型生成向量
- `http_client.py`：HTTP 请求封装（重试、超时）
- `llm_factory.py`：LLM 实例工厂，统一模型参数
- `openapi_client.py`：从 Go 后端 `/v1/openapi.json` 解析接口定义，转为 LLM Function Calling 工具并代理执行
- `sqlite_client.py`：SQLite 访问封装，供会话等本地数据使用
- `streaming_printer.py`：流式输出打印（含 PID 平滑速度控制）
- `token_tracker.py`：Token 用量统计（按天持久化）

### internal/ — 业务功能包（类 Go internal/）

- `chat/` — 对话查询线
  - `photo_rag.py`：RAG 分支，基于 Chroma 向量检索照片描述
  - `session_store.py`：会话持久化（SQLite），多轮对话上下文
  - `text_to_sql.py`：Text-to-SQL 分支，自然语言转 SQL 查询照片库
- `evals/` — 评估与观测
  - `eval_engine.py`：聚类主题启发式规则评估引擎，报告落 data 目录
  - `evaluation.py`：RAG 检索质量评估（黄金查询集 + MRR/P@K）
  - `trace_replay.py`：按 trace_id 重放管线步骤，问题回溯用
  - `tracer.py`：结构化 Trace 日志（JSONL，按天拆分，大 payload 落独立文件）
- `posts/` — 图文工坊线
  - `post_studio.py`：图文工坊文案生成（VLM 描述组织为四层提示词）
  - `test_post_studio_smoke.py`：图文工坊 smoke 测试（直接 `python` 执行）
- `runtime/` — Agent Runtime（AR1，框架无关）
  - `budget.py`：执行预算（步数 / 超时 / 成本），配置键落在 Agent 段
  - `capabilities/` — 能力包，按 LLM 参与方式分类；每个能力的实现、工具描述、用户标题、决策提示、过程细节聚合在同一代码块，新增能力只加代码块并登记
    - `common.py`：跨能力共享辅助（执行护栏 / 能力内 LLM 调用入口 / JSON 提取 / 照片详情缓存）
    - `resolve_trip.py`：约束解析类，能力内 LLM（提示词抽取硬约束）+ 程序物化权威范围
    - `retrieval.py`：检索类（sql / rag / hybrid），能力自身不调 LLM（SQL 生成封装在 text_to_sql 内）
    - `photo_tools.py`：程序工具类（Go 后端 HTTP 工具），全程无 LLM
    - `creation.py`：创作类（select_photos / write_post），能力内 LLM，含 CQ4 迁移来的连拍折叠与两级收缩
  - `completion.py`：任务完成检查
  - `graph.py`：LangGraph 编排外壳，decide → execute → reduce → check 循环图；decide 是唯一 LLM 决策点（能力清单经提示词提供），其余节点与流转均为程序行为
  - `progress.py`：Runtime 过程事件归约为用户过程快照（标题由能力定义随事件携带）
  - `registry.py`：能力注册表（Capability 含 name/title/description/parameters/run/decide_hint/progress_details）
  - `state.py`：TaskState 任务状态与归约规则，开放目标任务的唯一事实源
- `topics/` — 选题发现线
  - `cluster.py`：照片向量聚类（UMAP 降维 + HDBSCAN），主题发现的聚类基础
  - `suggest.py`：选题建议三阶段管线（直觉生成 / 扩选 / 提案）

### scripts/ — 运维与回归脚本

- `eval_regression.py`：三层检索回归 CLI，评估与验收的标准入口

### tests/ — 单元测试

- `test_*.py`：与各模块对应的 unittest 用例，`.venv/bin/python -m unittest discover -s tests` 全量执行

## notes

@dataclasses.dataclass 自动生成几个数据类的通用方法 `__init__`初始化 `__repr__`打印 `__eq__`比较

dataclasses.field 确保每个实例的列表是独立，而不是共享同一个

@capability_run 本项目自己写的装饰器（位于 `internal/runtime/capabilities/common.py`），
  所有能力被执行时都由try包住，不要炸掉runtime

@functools.wraps(fn)
  capability_run里用wrapped函数调用传递进来的fn，打印`fn.__name__`时会变成wrapped，
  所以 @functools.wraps(fn) 是为了保住`fn.__name__`依然指向原来的函数。
