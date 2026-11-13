<!-- harness:begin -->
# Go 代码规范

修改 Go 代码时，与[通用代码规范](code.md)一起读取。下列命名和排版包含个人偏好；采用前与目标项目约定核对。

## 命名

列表与切片使用 `List` 后缀；Map 使用 `Map` 后缀，映射方向重要时使用 `keyToValueMap`。

业务操作使用动宾结构：`add` 新增、`edit` 主动修改、`update` 被动更新、`get` 查询、`del` 删除；关系操作使用 `addXxxToYyy`、`delXxxFromYyy`。公共协议、框架接口和已有公开 API 保持其约定。

## 排版

修改文件后使用 `gofmt`。手写代码原则上每行不超过 80 字符，按语义换行；不拆坏名称或字符串含义。

长函数签名的参数列表能单行表达时保留一行；仍过长时逐个参数换行。长函数调用从左括号后换行，逐个参数排列。最终格式服从 `gofmt`。

赋值或调用与错误判断分行编写；函数内按校验、准备、执行与收尾等实际阶段留空行。

## 结构与资源

优先使用基础类型组合；接口与新类型依据真实的替换、复用或语义封装需要建立。入口位置、存储分层与第三方库沿用项目结构。

错误及时返回并保留原因；文件、连接与并发任务有明确的结束和释放方式。测试使用隔离资源与清理机制，不修改用户数据。

工具链使用遵循环境与全局约束，不通过切换 `GOTOOLCHAIN` 绕过版本要求或触发工具链下载。

## 命名规范

- **列表/切片**：后缀 `List`（如 `userRoleList`、`permissionList`）
- **Map 结构**：后缀 `Map`（如 `roleIDMap`、`permissionMap`），更清晰时用 `keyToValueMap`（如 `idToUserMap`）
- **函数命名**：统一用"动宾"结构
  - C: `add` — 新增，尽量让一种数据的创建入口尽可能少
  - U: `edit` — 主动修改；`update` — 被动更新
  - R: `get` — 查询
  - D: `del` — 删除
  - 关联关系：`addXxxToYyy` / `delXxxFromYyy`
- **HTTP method**：GET（查询）、POST（创建）、PUT（全量更新）、PATCH（部分更新）、DELETE（删除）

## 格式化

- 逻辑修改后统一用 `gofmt -w <file>` 处理，不纠结缩进对齐
- 手写代码单行原则上不超过 80 个字符；函数签名、调用参数、结构体字面量和长字符串按语义换行，不为压缩行数牺牲扫读性
- 函数签名超过 80 个字符时，按参数列表长度选择换行方式：
  - 参数列表本身可在 80 个字符内完整展示时，参数保持在同一行，在最后一个参数后加逗号再换行，不提前拆成一参数一行
  - 参数列表本身也超过 80 个字符时，将每个参数独立放在一行
- 函数调用的右括号后没有返回值声明，不使用“参数保持同一行、右括号单独一行”的形式：
  - 完整调用不超过 80 个字符时，所有参数与右括号保持在同一行
  - 完整调用超过 80 个字符时，从左括号后换行，每个参数独立一行，最后再单独写右括号

```go
func readResult(ctx context.Context, path string,
) (Result, error) {
	// 参数列表本身未超过 80 个字符。
}

func runStage(
	ctx context.Context,
	config Config,
	preparer Preparer,
) error {
	// 参数列表本身超过 80 个字符。
}

result, err := readResult(ctx, path)

result, err = runStage(
	ctx,
	config,
	preparer,
)
```

- 一行只表达一个主要行为。赋值、函数调用与错误判断分行编写，不使用 `if err := run(); err != nil` 或 `if err = run(); err != nil` 形式
- 函数内不同阶段之间留一个空行，例如参数校验、资源准备、核心执行、结果处理与清理，让每个步骤可以独立扫读

## 代码组织

- 入口函数放在 `internal/<module>/<module>.go`，而非 `cmd/`
- 非复杂场景优先用基础类型组合，仅在复用明显或封装语义明确时抽象 `type`
- **接口代理模式**：基础类通过接口代理支持子类覆盖，子类初始化后调用 `BindProvider(self)`

## 测试

- 编写集成测试验证 Service 层逻辑
- 使用 `defer` + 清理函数移除测试数据
- **禁止**在测试中修改表结构，差异应正常报错以提醒升级注意

## Go 工具链

- 沿用当前的 `GOTOOLCHAIN` 配置，不在每条 `go` 命令前重复设置，也不改为指定版本或启用自动下载
- 当 `go.mod` 的 `go` directive 高于系统 Go 版本时，不要依赖 auto-download，修复 go.mod directive 或更新系统 Go

---
<!-- harness:end -->

---

## Go（本项目补充）

### 优先复用 pgo 代码库

- `/root/code/pgo` 是本人维护的 Go 代码库，`pkg/` 下包含大量日常封装
- 本项目通过 `go.work` 直接引用本地 pgo，而非 import GitHub 版本
- 优先使用已有封装：`pconfig`（配置管理）、`plogger`（日志）、`putil`（HTTP/字符串/路径/时间工具）、`papp`（Runner 模式）
- 如发现 `pgo` 封装有缺陷或需扩展，可以同步维护 `pgo`

### 数据访问边界

- ORM、生成查询对象、原始 SQL 和只读数据库连接只允许出现在 `internal/defaultService/data/`；Service 负责业务编排，不直接查表或写表
- `data` 层函数必须表达业务意图，而非暴露通用 ORM 操作。单表操作按明确动作命名，例如 `GetPhotoByID`、`UpdatePhotoDescription`；跨表、聚合或组装结果按返回的业务对象命名，例如 `GetUserInfo`
- 不为减少少量重复而新增泛化 DAO、可传入任意条件的查询接口或由 Service 拼接查询条件。字段投影、筛选和排序由 `data` 层以已知业务用法收敛
- 新增或调整数据访问时，同步为有业务规则的 DAO 行为补充临时 SQLite 测试；Service 测试只通过公开行为断言结果

### 禁忌

- 不要直接 `go build` 到根目录
- `bootCheck` 的 MySQL 检查不允许执行 `DROP`、`TRUNCATE`、`ALTER ... MODIFY/CHANGE/RENAME`、删索引、删主键等危险 SQL
- 数据库结构不能 drop，仅代码层面废弃，实际数据清理由用户自行操作

---
