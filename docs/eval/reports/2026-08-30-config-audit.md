# 配置项全量评估报告

## 摘要

- **报告 ID**：`2026-08-30-config-audit`
- **评估目标**：项目自有配置文件及其加载/消费关系
- **综合评分**：5.2/10
- **结论**：不通过。核心运行链路能够读取并使用主要配置，但模板同时承载两套历史配置结构；部分配置项没有消费者，部分脚本使用了配置类中不存在的属性，命名和职责边界不够清晰。
- **范围**：`configs/config.yaml`、`configs/evaluation.yaml`、`configs/prices.yaml`、`agent/config.py`，以及项目维护的 `client/wails.json`、`web/vite.config.ts`、`web/tsconfig*.json`。
- **排除**：Dify 官方 Docker Compose、Dify 官方模板/运行环境变量、OpenAPI/SDK 和其他生成文件；它们不是 Photo Agent 当前核心配置契约。Dify 作为可选历史路径，仅记录与核心配置的交界问题。

## 评分

- **正确性：5/10**
  - 得分点：Go 后端的 `Log.Level`、`Http.*`、`Sqlite.Path` 和大写 `Storage/VLM/Embedding/Burst` 有实际读取路径；Python Agent 的 LLM、Embedding、RAG、会话、评估目录配置能够进入运行代码。
  - 失分点：`agent/scripts/index_photos.py`、`agent/embedding/demo_embedding.py`、相关旧脚本读取 `cfg.descriptions_path`，但 `Config` 没有定义或加载该属性；模板中的 `db.sqlite_path` 也没有进入 `Config`。
- **健壮性：5/10**
  - 得分点：必填段使用 `_require`；路径统一经过 `project_root` 解析；缺失评估配置时回归脚本会报错。
  - 失分点：数值、枚举、URL 和地址没有统一范围/格式校验；可选配置大量使用静默默认值；`prices.yaml` 的价格结构没有校验，未知模型会被按零成本记录。
- **可维护性：4/10**
  - 得分点：评估规则已从代码中抽出到 YAML，连拍参数按 `Fine/Coarse` 分组，Python 配置读取集中在一个模块。
  - 失分点：同一文件同时维护 Go 大写键和 Python 小写键；同一语义出现 `VLM`/`vlm`、`Embedding`/`embedding`、`PhotoSrc`/`photo_src`、`Path`/`*_path` 两套命名；配置类中还保留了旧脚本所需但实际不存在的契约缺口。
- **简洁性：4/10**
  - 得分点：核心配置文件数量不多，评估规则和价格表职责相对单一。
  - 失分点：Dify 配置仍占据公共模板，但当前核心代码没有消费者；小写 `vlm` 段也没有 Python 消费者；`db.sqlite_path` 与 Go 使用的 `Sqlite.Path` 重复表达数据库路径。
- **功能效果：6/10**
  - 得分点：LLM 调用、Embedding 分块、RAG 检索、评估规则、连拍默认参数和 Token 价格均能影响对应功能。
  - 失分点：配置“改动后谁生效”不直观；连拍参数运行时优先级由数据库设置覆盖，模板注释虽有说明，但其他重复段没有同等清晰的优先级说明。
- **一致性：3/10**
  - 得分点：Python 段大多使用 snake_case，Go 段遵循结构体字段命名。
  - 失分点：一个公共模板混用两种大小写和两种职责模型；端口在 Go/Python/Web/Wails 配置和 Makefile 中多处独立定义；模板默认值、Go struct default 和 Python 默认值未形成单一来源。

## 逐项审计

### `configs/config.yaml`

#### Go/PGo 段

- `Log.Level`：**有效**。由 pgo `InitFromConfig` 读取，影响后端日志级别。命名与 pgo 契约一致。
- `Http.Addr`：**有效**。由 pgo HTTP 服务读取，决定监听地址；与下方 `server.addr` 表达同一端口，但不是同一消费者。
- `Http.Timeout`：**有效**。由 pgo HTTP 服务读取；模板值 `1000` 的单位和用户可理解性不明确，且本地配置改为 `60000`，存在单位/量级认知风险。
- `Sqlite.Path`：**有效**。由 pgo SQLite 初始化读取，是 Go 后端实际数据库路径。
- `Storage.PhotoSrc`：**有效**。Go 服务用于原图、上传、EXIF、VLM 输入和删除。
- `Storage.PhotoPath`：**有效**。Go 服务用于压缩图/展示图和连拍图像读取；名称含义偏泛，实际是 compressed/display storage。
- `Storage.TimelineWindowDays`：**有效**。Go 时间线关联使用。
- `VLM.MaxImageSizeMB`：**有效**。Go 上传/处理流程用于压缩阈值。
- `VLM.Prompt`：**有效**。Go VLM 客户端读取提示词文件；模板、本地配置和 Python 小写段重复表达同一路径。
- `Embedding.APIKey`：**有效**。Go Embedding 代理读取；Go 的 Model/BaseURL 可由 struct default 提供，本地配置实际补齐了它们。
- `Burst.Fine.TimeWindowSec`：**有效**。作为 fine 档数据库无记录时的初始默认。
- `Burst.Fine.HashThreshold`：**有效**。作为 fine 档初始默认。
- `Burst.Fine.SsimThreshold`：**有效**。作为 fine 档初始默认。
- `Burst.Fine.SsimGrayMin`：**有效**。作为 fine 档初始默认。
- `Burst.Fine.SsimGrayMax`：**有效**。作为 fine 档初始默认。
- `Burst.Coarse.TimeWindowSec`：**有效**。作为 coarse 档初始默认。
- `Burst.Coarse.HashThreshold`：**有效**。作为 coarse 档初始默认。
- `Burst.Coarse.SsimThreshold`：**有效**。作为 coarse 档初始默认。
- `Burst.Coarse.SsimGrayMin`：**有效**。作为 coarse 档初始默认。
- `Burst.Coarse.SsimGrayMax`：**有效**。作为 coarse 档初始默认。
- `Burst.*` 整体：**结构合理但存在优先级复杂度**。网页设置写入 `app_settings` 后覆盖文件值，模板只负责初始默认；该行为与其他配置段的静态配置模型不一致。

#### Python/统一段

- `server.addr`：**有效**。Python 侧转换为 Go 后端 URL；名称实际是 backend endpoint，且会把 `0.0.0.0` 转成 `127.0.0.1`。
- `storage.project_root`：**有效**。Python 相对路径解析的根；名称和职责清楚，但 Go 不读取它。
- `storage.photo_src`：**模板中有效但 Python 当前不消费**。Go 消费的是同名大写键；Python 通过 API 使用照片，不直接访问该路径。
- `storage.photo_path`：**模板中有效但 Python 当前不消费**。与 `storage.photo_src` 相同，属于跨服务重复配置。
- `db.sqlite_path`：**未发现当前消费者**。Go 使用 `Sqlite.Path`，Python Agent 使用 `agent.data_dir` 派生自己的 SQLite；该键当前是误导性的重复配置。
- `agent.data_dir`：**有效**。Chroma、Agent SQLite、Trace、聚类和历史数据的根目录。
- `chat.db_path`：**有效**。会话 CLI 路径读取使用；服务端会话路径由同一配置对象使用。名称合理。
- `evaluation.reports_dir`：**有效但仅部分路径约束**。配置对象加载它，报告相关代码同时存在直接使用 project root 下固定目录的路径，需警惕配置与实际落盘位置漂移。
- `evaluation.config_path`：**有效**。聚类规则 API 和三层回归脚本读取。
- `llm.base_url`：**有效**。LangChain LLM 使用。
- `llm.api_key`：**有效且敏感**。LLM 使用；模板占位符本身安全，但配置规范没有统一说明密钥来源和禁止日志输出。
- `llm.model`：**有效**。LLM 主模型使用。
- `llm.fallback_model`：**有效可选**。配置后建立 fallback；空值表示不启用。
- `llm.retry_enabled`：**有效**。控制 LangChain 重试包装。
- `llm.retry_max_attempts`：**有效**。控制重试次数，但没有正数校验。
- `llm.request_timeout`：**有效**。传给 LangChain；没有非负/上限校验。
- `llm.tool_max_rounds`：**有效**。限制工具循环；没有正数校验。
- `vlm.base_url`：**Python 当前未消费**。实际 VLM 调用在 Go 服务，使用大写 `VLM.BaseURL`。
- `vlm.api_key`：**Python 当前未消费**。实际 VLM 密钥在 Go 大写段。
- `vlm.model`：**Python 当前未消费**。实际 VLM 模型在 Go 大写段。
- `vlm.concurrency`：**Python 当前未消费**。VLM 队列并发由 Go 代码/队列实现控制。
- `vlm.retry`：**Python 当前未消费**。Go VLM 代码没有从该小写键读取重试次数。
- `vlm.max_image_size_mb`：**Python 当前未消费**。实际压缩阈值为 Go `VLM.MaxImageSizeMB`。
- `vlm.max_tokens`：**Python 当前未消费**。Go VLM 请求没有从 Python 配置读取该值；模板把它写成了“配置项”，但当前无效。
- `vlm.prompt`：**Python 当前未消费**。实际提示词为 Go `VLM.Prompt`。
- `embedding.base_url`：**有效**。Python 的 Embedding SDK 连接到 Go `/v1/embeddings` 代理时使用模型字段；实际外部 URL 由 Go 大写配置决定。
- `embedding.api_key`：**被加载但当前 Embedding 客户端不直接使用**。Python 通过 Go 代理，API Key 在 Go 侧使用；保留它会造成“Python 是否直连外部 Embedding”的误解。
- `embedding.model`：**有效**。Python 生成向量时使用，并传给 Go 代理；Go 侧外部模型还有自己的大写配置。
- `embedding.context_size`：**仅参与默认计算**。只有缺省 `chunk_size` 时用于计算默认块大小；模板同时显式给了 `chunk_size`，因此当前值实际不影响分块结果。
- `embedding.chunk_strategy`：**有效**。控制 `none`、`fixed_size`、`markdown_heading`。
- `embedding.chunk_size`：**有效但条件性**。仅在 `fixed_size` 策略下生效；当前默认策略 `none` 时不生效。
- `embedding.chunk_overlap`：**有效但条件性**。仅在 `fixed_size` 策略下生效；没有校验其小于 `chunk_size`。
- `embedding.heading_level`：**有效但条件性**。仅在 `markdown_heading` 策略下生效。
- `rag.auto_distance_ratio`：**有效**。进入 RAG 检索截断逻辑；名称基本合理，含义依赖距离排序规则。
- `rag.distance_threshold`：**有效**。进入 RAG 距离过滤；可为空时由代码表示“不设固定阈值”，模板的默认浮点值则改变行为。
- `dify.base_url`：**核心路径未消费**。仅历史 Dify 路径文档仍描述该配置。
- `dify.api_key`：**核心路径未消费**。模板仍要求放置敏感凭据。
- `dify.dataset_id`：**核心路径未消费**；当前模板注释声称由 `init_dify` 自动填入，但仓库当前没有对应核心初始化入口。
- `dify.email`：**核心路径未消费**，且是敏感凭据相关字段。
- `dify.password`：**核心路径未消费**，且是敏感凭据字段。
- `dify.dataset_name`：**核心路径未消费**。
- `dify.db_path`：**核心路径未消费**，且重复表达 `Sqlite.Path`。
- `prices.path`：**有效**。TokenTracker 读取价格文件；路径命名清楚，但价格单位与实际供应商报价是否一致没有机器校验。

### `configs/evaluation.yaml`

- `cluster_theme`：**有效**。`eval_engine` 和评估 API 读取整个规则列表。
- `cluster_theme[].id`：**有效**。作为报告规则 ID；未校验唯一性。
- `cluster_theme[].description`：**有效**。用于报告展示和错误消息。
- `cluster_theme[].severity`：**有效**。报告记录使用；没有统一枚举校验。
- `cluster_theme[].check.field`：**有效**。选择簇字段。
- `cluster_theme[].check.op`：**有效**。当前支持 `length_between`、`not_contains_any`、`min_length`、`all_unique`。
- `cluster_theme[].check.min/max`：**有效但只在对应操作下生效**；没有按操作校验必填关系。
- `cluster_theme[].check.values`：**有效但只在 `not_contains_any` 下生效**。
- `cluster_theme[].scope`：**有效**。`all_clusters` 控制跨簇规则；命名清楚。
- `attribute_availability`：**有效**。规则执行器读取。
- `attribute_availability[].id/description/severity`：**有效**。分别用于报告标识、消息和严重级别。
- `attribute_availability[].check.field/op/min`：**有效**。当前非空率检查使用；结构与 `cluster_theme` 一致性较好。
- `retrieval_regression.golden_cases`：**有效**。回归 CLI 使用标记的黄金用例。
- `golden_cases[].id`：**有效**。与运行数据黄金用例 ID 关联；关联不存在时会报错。
- `golden_cases[].name`：**有效**。回归失败消息使用。
- `golden_cases[].levels.L0.covers`：**有效**。验证 fine/coarse 连拍封面。
- `golden_cases[].levels.L1.expected_photo_ids`：**有效**。验证未分组照片召回。
- `golden_cases[].levels.L1.expected_group_ids`：**有效**。验证连拍组召回。
- `golden_cases[].levels.L2.expected_chat_filenames`：**有效**。验证对话 API 返回的照片。
- 整体：**结构有效但契约偏隐式**。规则操作名、字段名和层级字段均由执行器字符串解释，配置文件缺少 schema 或启动时完整校验。

### `configs/prices.yaml`

- `models`：**有效**。TokenTracker 读取模型价格映射。
- `models.<model-name-1/2>.input`：**模板占位示例，当前无效用**。示例模型名不对应默认模型，实际调用会得到零成本。
- `models.<model-name-1/2>.output`：**模板占位示例，当前无效用**。同上。
- `input/output` 的单位注释：**存在准确性风险**。代码按每 1K token 计算，但模板写“元”，实际 `.local/prices.yaml` 使用的供应商价格单位未由代码声明或校验。

### `agent/config.py`

- `Config` 的基础属性：**可用但存在未消费属性**。`embedding_api_key`、`embedding_base_url` 被加载，但核心 Python Embedding 走 Go 代理；`embedding_context_size` 只参与块大小默认计算。
- `_require`：**方向正确但校验不足**。只检查存在和非空，不检查类型、范围、枚举和占位符。
- `_optional`：**简洁但容易隐藏拼写/废弃键**。未知键不会报错，配置文件中多余项可长期存在。
- `project_root` 与 `resolve_path`：**有效**。是当前 Python 路径治理的核心。
- `go_backend_url`：**有效**，但由 `server.addr` 重新拼接 URL，配置名称没有直接表达“后端 URL”。
- `chat_db_path`：**有效**，但读取默认值和服务/CLI 的实际使用路径需要保持同一契约。
- `agent_data_dir`、`eval_reports_dir`、`evaluation_config_path`：**有效且必填**。这三项是当前 Agent 运行和评估链路的核心路径配置。
- `descriptions_path`：**缺失**。多个旧索引/演示脚本直接访问，`Config` 初始化没有该属性；这是可复现的配置类与脚本契约不一致。

### 项目维护的前端/客户端配置

- `client/wails.json.$schema`、`name`、`outputfilename`：**有效**。Wails 构建元数据。
- `client/wails.json.frontend:*`：**部分有效**。当前前端目录、安装、构建命令为空，而 `frontend:dev:serverUrl` 有效；正式构建通过根 Makefile 完成，职责分散。
- `client/wails.json.author.*`：**非运行配置**。作者邮箱为空，不影响功能。
- `web/vite.config.ts.server.host/port`：**有效**。开发服务器监听和端口；端口与 `makefile`、Wails 配置重复。
- `web/vite.config.ts.server.proxy.*`：**有效**。各 API 前缀代理到 Agent/Backend；代理目标地址和端口硬编码，未复用统一配置。
- `web/tsconfig*.json`：**有效的构建配置**。`noUnused*`、类型和项目引用能约束构建；`tsBuildInfoFile` 为工具缓存配置，不是业务配置。

## 关键问题（供 backlog 交接）

1. **P1：配置模板存在两套重复且互不联动的结构**。同一文件同时包含 Go/PGo 大写段与 Python 小写段，VLM、Embedding、存储、数据库和端口等语义分别由不同消费者读取，用户无法仅凭键名判断哪个值实际生效。
2. **P1：配置类与脚本契约不一致**。索引和演示脚本读取 `cfg.descriptions_path`，但 `agent/config.py` 没有定义或加载该配置项。
3. **P1：核心模板保留无消费者的 Dify 配置和 Python `vlm` 配置**。这些键仍带有 API Key、密码或模型等敏感/高影响字段，容易造成错误配置和秘密扩散。
4. **P2：数据库与运行目录配置职责重叠或隐式派生**。`Sqlite.Path`、`db.sqlite_path`、`agent.data_dir`、`chat.db_path` 之间没有统一的所有权说明。
5. **P2：配置值校验不完整**。重试次数、工具轮数、超时、分块参数、RAG 阈值、连拍阈值、评估规则操作和 Token 价格缺少统一的类型/范围/枚举校验。
6. **P2：模板价格文件是占位示例且单位未形成契约**。默认模型不在模板价格表中，未配置实际价格时成本静默按零计算。
7. **P2：服务端口和代理目标分散在配置、Makefile、Vite 和 Wails 文件中**，缺少单一可追踪来源。

## 自动验证证据

- `agent/.venv/bin/python -m unittest discover -s agent/tests -p 'test_eval*.py'`：14/14 通过。
- 配置模板和 `.local/my-config.yaml` 均可被 YAML 解析；本地敏感值未写入本报告。
- 静态引用扫描确认 Go/Python 配置消费者及上述未消费项。
- `agent/.venv/bin/python -m unittest discover -s agent/tests -p 'test_config*.py'`：没有匹配到配置测试，返回“0 tests”，因此不能作为配置加载正确性的通过证据。
- 未启动服务；本轮目标是静态配置契约评估，且评估模式要求不修改代码。
