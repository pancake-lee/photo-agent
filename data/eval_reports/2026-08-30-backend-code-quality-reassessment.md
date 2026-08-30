# 后端代码质量问题修复后复评

> 专题中枢：[后端代码质量治理专题中枢](../../docs/design/2026-08-30-1-backend-code-quality-hub.md)。
>
> 评估对象：2026-08-29 基线报告所列 BQ2–BQ6、BQ8 的后续规划与生成结果，以及仍暂缓的 BQ3。
>
> 评估报告 ID：`2026-08-30-backend-code-quality-reassessment`。
>
> 判卷依据：[后端代码质量评分标准](../../docs/eval/code-quality-rubric-backend.md)。评估范围由 `tools/go/main.go` 自检后确定，共 57 个文件。

## 摘要

- **总体评分：59/100（5.9/10），不通过。** 按八项维度的未封顶分数为 79/100；BQ3 保留的未鉴权任意 SQL 查询属于阻断项，评分标准要求总分最高为 59。
- BQ2、BQ4、BQ5、BQ8 已由代码、活动 SQLite 与自动验证证实关闭。BQ4 的旧运行日志仍应按历史凭据泄露事件处理；当前 backend 进程来自修复前的启动，未为本次评估重启服务，因此本轮只确认当前启动代码不再输出完整配置，不重复记录任何敏感值。
- BQ6 的草稿 HTTP、上传删除、VLM 写回和 Embedding 超时/取消已有可重复自动证据，但其测试夹具违反表结构测试约定，且 VLM 队列没有端到端自动闭环，因此 BQ6 不能维持 Done。
- 运行中的 backend 对 `/v1/embeddings/health`、`/v1/openapi.json` 返回 HTTP 200；根路径不是健康接口，返回 404，`make status` 的根路径探测不能作为失败的业务用例证据。

## 后端范围与闭环

- **范围**：清单脚本自检通过，纳入 41 个手写 Go、7 个人工 Proto、4 个人工 SQL、3 个后端配置和 2 份直接技术文档。
- **调用链复核**：人工 Proto/API 注册仍收敛到各 Service；本轮迁移的照片审核、VLM 写回/履历、存储最新同步时间、只读 SQL 与照片 schema 读取均经 `data` 层调用。生产 Service 中未检出直接 `pdb`、GORM 或生成查询对象调用。
- **关键用户用例**：草稿进程内 HTTP 的创建、更新、列表、导出 ZIP 与删除均通过；JPG/NEF 上传删除、缩略图失败清理、VLM 合格/待复核/失败履历写回均通过；Embedding 的输入顺序、失败中止、超时和取消均通过。
- **数据状态证据**：活动 SQLite 的四个旧 AI/VLM 状态列计数为 0；手写后端迁移代码未含这些列的 `DROP COLUMN`。
- **自动验证**：`GOTOOLCHAIN=local go test -count=1 ./...`、`GOTOOLCHAIN=local go vet ./...`、`GOTOOLCHAIN=local go test -count=1 -race ./internal/defaultService/service ./internal/defaultService/data`、纳入手写 Go 的 `gofmt` 检查、手工 Proto 的 `protoc` 语法校验均通过。
- **阻断项**：有。`defaultService.go:50` 仍调用 `papp.SetIgnoreAuth()`，同时 `QueryServer.ExecuteSQL` 接收调用方 SQL 并交给只读连接执行；FR-11 已记录其仅限开发阶段的接受边界，但不改变评分标准中的阻断性质。

## 加权评分

### 功能正确性与数据完整性：16/18

得分点：

- `migrate.go` 已移除四个旧状态列的删除分支，活动库中这些列也不存在。
- `TestDraftHTTPCRUDAndExport` 覆盖草稿 HTTP CRUD 与 ZIP 内容；`TestPhotoUploadDeleteAndVlmWriteback` 覆盖 JPG、NEF、缩略图失败清理和 VLM 写回后的数据库/文件状态。

失分点：

- `user_paths_test.go:25-44` 自行创建表结构，未证明真实迁移后的表结构与用户用例相容，见 BQ10。

### 分层与职责边界：13/14

得分点：

- 照片审核、VLM 写回与履历、只读 SQL、schema 反射和存储最新同步时间已迁入 `data`；静态搜索未发现生产 Service 直接使用 ORM、`pdb` 或生成查询对象。
- `svc_query.go` 仅保留请求限额、DAO 调用和 Proto 响应转换，数据访问职责清楚。

失分点：

- `svc_photo.go` 仍为 864 行，上传、删除、冲突处理、DTO 转换等职责聚集，定位成本较高。

### 风格一致性与可读性：7/10

得分点：

- 纳入手写 Go 的 `gofmt` 检查通过；`perr/err.go` 已统一格式。
- 本轮新增 DAO 与测试命名能表达业务动作和断言目标。

失分点：

- `svc_photo.go`（864 行）与 `svc_burst_group.go`（662 行）仍是较大的多职责文件；这一可读性风险没有随本轮治理消失。

### 抽象、复用与复杂度控制：8/10

得分点：

- SQL 结果规范化与 schema 类型推导有单一实现，Service 不再复制这些转换。
- Embedding 请求构造、上下文控制和结果聚合收敛到可独立测试的函数。

失分点：

- VLM 与 Embedding 外部调用仍各自使用包级客户端/配置边界，外部客户端的可替换性和生命周期策略不一致。

### 健壮性、并发与可观测性：10/12

得分点：

- Embedding 使用入站上下文和 15 秒时限；超时、取消、非成功响应和失败后停止后续输入均有本地 HTTP 测试。
- VLM 队列状态受互斥锁保护；目标包 race 检查通过，失败可回写处理履历。

失分点：

- VLM 队列的真实 worker 路径未被本地替身驱动验证，无法从测试证实并发成功、失败和停止后的最终状态，见 BQ11。

### API、安全与兼容性：4/10

得分点：

- 当前启动入口已无完整配置日志调用；Embedding 健康与 OpenAPI 端点在运行中服务上返回 200。
- 旧 AI/VLM 列删除行为已移除，照片 API 仍由实时描述推导状态。

失分点：

- 默认服务仍忽略鉴权并接受任意 SQL 文本。即使数据库连接只读，任何可达调用方仍可读取可访问表和元数据。这是 BQ3/FR-11 的已知阻断项。

### 测试策略与用户用例闭环：12/16

得分点：

- 全量测试、vet、race、Proto 语法与格式化检查均通过；新增测试没有依赖真实外网或真实 LLM。
- 草稿 HTTP 与上传/删除/VLM 写回已从用户动作断言到 ZIP、文件和数据库最终状态；Embedding 的失败路径也有可重复证据。

失分点：

- `setupUserPathTest` 通过 `Migrator().CreateTable` 和原始 `CREATE TABLE` 初始化测试库，违反项目“测试不修改表结构”约定，且绕过迁移。
- `TestVlmQueueLifecycle` 只调用 `vlmQueueManager`，并未调用 `StartVlmQueue` 或 `runVlmQueue`，所以无法证明队列的本地 VLM 成功/失败、停止与最终处理履历闭环。

### 废弃代码与文档同步：9/10

得分点：

- BQ2 的一次性迁移分支、BQ4 的完整配置日志入口和 BQ8 的 Service 数据访问遗留均已清除；评分标准、编码规范和 backlog 记录一致。
- 人工 Proto 以正确的 `--proto_path` 完成语法校验，人工 SQL 仍保持普通列关联。

失分点：

- `backend/sql/` 仍含仅限独立初始化库的 `DROP TABLE IF EXISTS`。本轮未发现它与业务 SQLite 混用的证据，因此不作为阻断项；其执行边界仍需持续保持明确。

## 已登记问题

- BQ3：开发阶段接受的未鉴权任意 SQL 查询仍是阻断项，未进入当前开发队列。
- BQ10：关键用户路径测试夹具直接创建表结构，违反测试约定且未覆盖实际迁移路径。
- BQ11：VLM 队列缺少从公开启动入口到本地 VLM 响应、最终状态和处理履历的自动化闭环。

## 结论

自动化证据和已完成治理将未封顶质量从基线的 57/100 提升到 79/100；但 BQ3 的安全阻断项使本轮结论仍为不通过，且 BQ10、BQ11 说明 BQ6 需重新进入规划。当前后端可继续在受信任的本地开发边界内维护，不可作为共享或生产服务发布。
