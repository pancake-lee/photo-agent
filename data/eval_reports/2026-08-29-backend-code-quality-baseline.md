# 后端代码质量基线评估

> 专题中枢：[后端代码质量治理专题中枢](../../docs/design/2026-08-30-1-backend-code-quality-hub.md)。后续复评见 [2026-08-30 后端代码质量复评](2026-08-30-backend-code-quality-reassessment.md)。

> 评估对象：`backend/` 的手写 Go 代码、人工维护的 Proto/SQL、后端配置和直接对应技术文档。
>
> 评估报告 ID：`2026-08-29-backend-code-quality-baseline`。
>
> 判卷依据：[后端代码质量评分标准](../../docs/eval/code-quality-rubric-backend.md)。pgo 生成的 `*.pb.go`、`*.gen.go`、`*.gen.proto`、生成的 API Client/OpenAPI 产物及 abandonCode 模板均未读取、未评分。

## 摘要

- **总体评分：57/100（5.7/10），不通过**。存在三项阻断项，按评分标准不得作为后续功能扩展的稳定基础。范围校正后，人工 Proto/SQL 的契约与建表语义得到确认，先前将 abandonCode 模板列为问题的判断已撤销。
- **阻断项**：启动迁移会删除存量列；默认服务跳过鉴权且可提交任意只读 SQL；完整配置被写入运行日志，日志中已出现敏感凭据。
- 静态与自动化证据良好：全量 Go 测试、`go vet` 和两个核心包的 race 测试均通过。照片筛选/分段的临时 SQLite 集成测试，以及连拍、时间线、VLM 解析与输入校验等独立逻辑均有单测。
- 当前运行进程监听三个预期端口，但从本评估环境发起的 HTTP 健康、embedding、storage 探测均在 5 秒内超时，不能将现有日志中的历史成功请求替代为本轮端到端闭环。

## 后端范围与闭环

- **范围**：
  - 入口和基础设施：`internal/defaultService/defaultService.go`、`internal/pkg/db/migrate.go`、`internal/pkg/db/db.go`。
  - Service：Photo、VLM、Timeline、Draft、Query、Embedding、Storage、Tag、Health 与 OpenAPI 调用层。
  - DAO：Photo、PhotoGroup、Draft、TimelineEvent、AppSetting 及相关查询调用层。
  - 人工 API 契约：`proto/common.proto`、`error_reason.proto`、`photo_service.proto`、`query_service.proto`、`tag_service.proto`、`timeline_service.proto`、`vlm_service.proto`。
  - 人工建表 SQL：`sql/photos.sql`、`photo_groups.sql`、`app_settings.sql`、`timeline_events.sql`。
  - 直接配置：`internal/defaultService/conf/conf.go`。
- **调用图**：
  - 人工 Proto 路由契约 → 生成 API 注册边界 → Photo/Timeline/Tag/VLM/Query Service → DAO/文件与 EXIF 工具/SQLite。
  - 手写 HTTP 路由 → Draft/Storage/Embedding/Health/OpenAPI Service → DAO、ZIP/文件系统、外部 Embedding API。
  - 启动入口 → 配置与日志初始化 → SQLite 初始化 → `Migrate` → Service 注册。
  - VLM Service → 队列状态机 → Photo DAO → VLM HTTP Client → 结果及 AI 处理履历。
- **关键用户用例证据**：
  - 照片列表筛选和分段：`dao_photo_test.go` 使用临时 SQLite 插入照片，验证散片 sentinel、NEF 排除、月/活动分段，PASS。
  - VLM 输入与结构化描述解析：`vlm_compress_test.go`、`vlm_parse_test.go` 覆盖正常、损坏、边界和异常描述，PASS。
  - 连拍分组与时间线：`svc_burst_group_test.go`、`svc_timeline_test.go` 覆盖阈值、跨年、空输入和非法日期，PASS。
  - 上传、删除、VLM 队列、迁移、草稿 HTTP/ZIP 导出没有本轮可执行的 API/CLI 用户用例闭环。
- **自动验证**：`GOTOOLCHAIN=local go test ./...`、`GOTOOLCHAIN=local go vet ./...`、`GOTOOLCHAIN=local go test -race ./internal/defaultService/service ./internal/defaultService/data` 均通过。
- **Proto 契约验证**：`protoc --descriptor_set_out=/dev/null` 校验七份人工 Proto 语法通过。
- **数据状态证据**：测试使用临时 SQLite 数据库，测试结束后清理；运行日志保留 PhotoService 读操作成功记录，但本轮直连 HTTP 请求超时，未把历史日志视为本轮闭环。
- **阻断项**：有，见摘要及 BQ2、BQ3、BQ4。

## 加权评分

### 功能正确性与数据完整性：10/18

得分点：

- `dao_photo_test.go` 在隔离 SQLite 中验证筛选和分段的用户可见结果，不只断言 mock。
- `svc_burst_group_test.go`、`svc_timeline_test.go` 覆盖分组和时间线的正常、边界与异常输入。
- VLM 输入预检、描述质量校验和临时压缩文件隔离均有独立测试。

失分点：

- `internal/pkg/db/migrate.go:101-109` 在每次启动中检查后直接执行 `ALTER TABLE photos DROP COLUMN`，会不可逆删除四个存量状态列的数据。
- 上传文件、缩略图、照片行及删除清理的多资源一致性没有自动用户用例证据。

### 分层与职责边界：10/14

得分点：

- 传输注册集中于各 Service 的 `Reg`，主要业务入口位于 Service，照片和时间线查询大多通过 DAO 收敛。
- 文件写入、EXIF、VLM 客户端、连拍和时间线算法已有可识别边界。

失分点：

- `svc_storage.go`、`ai_quality.go` 和部分 Service 直接使用 GORM/pdb，绕开 DAO 层，数据访问边界不一致。
- `svc_photo.go` 同时承担 HTTP 适配、上传冲突处理、文件操作、记录写入与展示 DTO 组装，职责聚集。

### 风格一致性与可读性：7/10

得分点：

- 业务函数和日志前缀大多语义明确；时间线、VLM 和连拍算法的注释能解释规则和边界。
- 全量 `go vet` 通过。

失分点：

- `svc_photo.go` 约 700 行，`svc_burst_group.go` 约 600 行，单文件混合多类职责，阅读和变更定位成本高。
- `internal/pkg/perr/err.go` 未通过 `gofmt`，仍保留 CRLF 格式。

### 抽象、复用与复杂度控制：8/10

得分点：

- 连拍/时间线的阈值决策拆为独立函数；VLM 输入校验与压缩输出路径独立，避免同名临时文件冲突。
- DAO 侧照片列表筛选使用共享 scope，测试已覆盖主要筛选语义。

失分点：

- VLM 与 Embedding 的外部客户端各自依赖包级全局配置和 HTTP Client，缺少统一、可替换的外部客户端边界。
- `svc_query.go` 的 SQL 值和类型转换标记为待迁移到 pgo，当前仍以局部 helper 维护。

### 健壮性、并发与可观测性：5/12

得分点：

- VLM、连拍和时间线的运行状态有互斥锁保护；定向 race 测试通过。
- VLM 请求使用 60 秒超时，队列、单张描述和描述质量失败路径均有阶段日志与处理履历。

失分点：

- `svc_embedding.go:221` 使用 `http.DefaultClient` 调外部 Embedding 服务，没有显式超时，也未传递 HTTP 请求的取消上下文；批量输入按条串行等待。
- 启动时 `pconfig.Log()` 会输出配置值。实际运行日志中已含敏感凭据，日志既不能安全共享，也扩大了凭据泄露面。
- VLM 队列和 Embedding 失败/超时恢复没有集成或用户用例测试。

### API、安全与兼容性：3/10

得分点：

- `QueryServer.ExecuteSQL` 通过只读数据库连接执行，代码没有拼接用户输入构造 SQL。
- 上传文件名通过 `sanitizeFilename` 清洗，后续文件操作以数据库中的相对路径为来源。

失分点：

- `defaultService.go:51` 全局调用 `papp.SetIgnoreAuth()`；同一入口注册 `QueryServer`，而 `svc_query.go:40-61` 接收调用方提交的任意 SQL。当前进程监听 `[::]:10004`，无鉴权的数据库读访问构成阻断项。
- 自动迁移删除列不具备存量数据兼容性，且违反项目不删除数据库结构的约束。
- 配置凭据泄露到日志，违反敏感配置不得进入日志的安全要求。

### 测试策略与用户用例闭环：7/16

得分点：

- 测试粒度合理地覆盖了独立算法和 DAO+SQLite 集成：共 40 个手写 Go 测试函数，未为了薄路由机械堆叠单测。
- 全量 Go 测试、vet、核心 Service/DAO race 测试全部通过。

失分点：

- `Migrate`、上传和删除的文件/数据库一致性、VLM 队列启停及错误回写、Embedding 超时、草稿 HTTP CRUD 与 ZIP 导出均没有自动闭环。
- 当前进程直连 HTTP 请求超时，因此本轮不能证明任何 HTTP/API 用户路径在当前环境可用。

### 废弃代码与文档同步：7/10

得分点：

- 人工 Proto 的 HTTP 路由、字段序号与 Service 注册相互对应；`protoc` 语法校验通过。
- 人工 SQL 的 photos、photo_groups、app_settings、timeline_events 基表默认值与当前手写迁移的目标结构相符，且表关联保持普通列而非外键。

失分点：

- `internal/pkg/perr/err.go` 未通过 `gofmt`，保留 CRLF 格式差异。
- SQL 初始化脚本含 `DROP TABLE IF EXISTS`；默认目标是独立的 ORM 生成数据库，未作为本轮缺陷计分，但该 DDL 的执行范围必须持续与实际业务 SQLite 数据库隔离。

## 已登记问题

- BQ2：启动迁移会删除存量列值。
- BQ3：跳过鉴权的服务暴露任意只读 SQL。
- BQ4：敏感配置被写入日志。
- BQ5：Embedding 外部调用没有受控超时和取消边界。
- BQ6：高风险用户路径缺少自动化闭环，当前环境 HTTP 探测未通过。
- BQ8：一份手写 Go 文件未格式化。
