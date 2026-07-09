# Backend 重构方案

## 一、概述

### 1.1 重构目标

本次重构的核心目标有两个：

- **backend 项目本身**：将初版验证性代码重构为可维护性更好的结构，统一编码风格，引入代码生成减少手写样板
- **验证 pgo 封装合理性**：在实践中检验 pgo 的代码生成工具链，发现不足并同步改进

### 1.2 重构原则

- **对外接口通过 SDK 调用**：重构后不再要求 URL 与原来一致。标准 CRUD 直接使用 genCURD 生成的接口，agent 和 web 通过 Swagger/OpenAPI 生成对应语言的 SDK 来调用，避免代码中硬编码 URL 和字段名
- **业务逻辑复用**：原有 service 层的业务逻辑尽量保留，搬到新结构后统一风格重写，逻辑保持一致
- **生成 vs 手写分离**：生成代码（`*.gen.go`、`*.pb.go`）与手写代码严格分离，重新生成不影响手写逻辑
- **先工具链后业务**：先完善 pgo 的 genGORM/genCURD 对 SQLite3 的支持，再做 backend 代码迁移

### 1.3 当前 backend 结构速览

```
backend/
├── cmd/
│   ├── server/main.go          # 服务入口
│   ├── batch_vlm/main.go       # 批量 VLM CLI
│   └── init_dify/main.go       # Dify 知识库初始化 CLI
├── internal/
│   ├── api/                    # Gin HTTP handlers (12 个文件)
│   │   ├── routes.go           # 路由注册
│   │   ├── photo.go / upload.go / query.go / schema.go / timeline.go / tag.go / import.go / vlm.go / ...
│   ├── config/config.go        # TOML 配置
│   ├── model/                  # GORM 模型 (手写 struct)
│   │   ├── photo.go
│   │   └── import_job.go
│   ├── service/                # 业务逻辑层
│   │   ├── db.go               # SQLite 初始化 + AutoMigrate
│   │   ├── photo.go            # 照片 CRUD + 统计 + 过滤
│   │   ├── scanner.go / sync.go / dedup.go / descriptions.go
│   │   ├── vlm_queue.go / vlm_pipeline.go / processor.go
│   │   ├── query.go / storage.go / timeline.go
│   └── vlm/                    # VLM 客户端
│       ├── client.go / compress.go / dify.go
└── makefile
```

核心问题：

- GORM 模型手写，proto 类型手写，DO↔DTO 转换手写，DAO 手写，Service 样板代码手写 — 大量重复劳动
- Gin 路由手写注册，没有统一的 API 契约描述
- 缺少生成代码与手写代码的分离机制

---

## 二、目标架构

重构后的目录结构：

```
backend/
├── api/                        # 生成的 pb.go / http.go / grpc.go（由 make api 产出）
├── proto/                      # proto 定义文件
│   ├── photo_service.proto     # 照片 CRUD（由 genCURD 生成 z_ 前缀）
│   ├── import_service.proto    # 导入任务 CRUD
│   ├── vlm_service.proto       # VLM 队列 + 单张描述
│   ├── stats_service.proto     # 统计 + schema + 属性值
│   ├── query_service.proto     # SQL 查询
│   └── common.proto            # 公共类型
├── internal/
│   ├── db/                     # 数据库相关
│   │   ├── sql/                # DDL 定义（建表 SQL 文件）
│   │   │   └── photo.sql
│   │   ├── model/              # 生成的 GORM 模型（由 genGORM 产出）
│   │   └── query/              # 生成的类型安全查询代码（由 genGORM 产出）
│   ├── photo_service/          # 照片 CRUD 服务
│   ├── vlm_service/            # VLM 业务（手写为主，proto 定义接口）
│   ├── stats_service/          # 统计业务
│   ├── query_service/          # SQL 查询 + schema + 属性值
│   └── pkg/                    # 内部公共包
│       ├── config/             # 配置（保持现有）
│       ├── vlm/                # VLM 客户端（保持现有）
│       └── storage/            # 文件存储管理
├── cmd/
│   ├── batch_vlm/main.go
│   └── init_dify/main.go
├── makefile                    # 统一构建入口
└── go.mod
```

核心变化：

- **DDL 驱动**：表定义从 GORM struct tag 迁移到 SQL DDL 文件，genGORM 读取 SQLite 实例生成模型代码
- **proto 定义 API 契约**：所有接口用 proto 定义，生成请求/响应类型和 HTTP 路由
- **生成与手写分离**：`z_*.gen.go` 前缀标识生成文件，同名无 `z_` 前缀的文件为手写扩展

---

## 三、工作流一：SQLite3 建表 → genGORM → genCURD

这是标准 CRUD 表的完整代码生成流水线。适用于 `photos` 等以数据库 CRUD 为核心的表。

### 3.1 整体流程

```
DDL (SQL 文件)
    ↓  make initDB    — 创建 SQLite 数据库，执行 DDL
SQLite 数据库实例
    ↓  make gorm      — pgo genGORM -db sqlite3 读取数据库，生成 GORM 模型 + Query 代码
Model (*.gen.go) + Query (*.gen.go)
    ↓  make curd      — pgo genCURD -db sqlite3 读取数据库，生成 Proto + DAO + Service
Proto (*.gen.proto) → genCURD 内部调用 make api → pb.go / http.go / grpc.go
DAO (*.gen.go) + Service (*.gen.go) + Server 注册
    ↓  make build
可执行文件
```

> 注：genGORM 和 genCURD 对 SQLite3 的支持已于 2026-07-08 在 pgo 中实现，详见 pgo `docs/design/sqlite.md`。

### 3.2 各步骤详解

#### Step 1: 定义 DDL（`internal/db/sql/*.sql`）

将当前 GORM struct tag 定义改写为标准 SQL DDL。以 `photos` 表为例：

- 当前：`internal/model/photo.go` 中 `Photo` struct + GORM tag
- 重构后：`internal/db/sql/photo.sql` 中 `CREATE TABLE photos (...)` 语句
- 字段类型、默认值、索引全部在 DDL 中体现
- 注释写在 SQL 注释中（`--`），genCURD 可读取作为字段说明

注意点：

- SQLite3 的 DDL 语法与 MySQL 有差异（如 `AUTOINCREMENT` vs `AUTO_INCREMENT`），DDL 文件需要针对目标数据库编写
- 如果未来需要切换数据库，DDL 需要分别维护（短期不做，仅 SQLite3）

#### Step 2: 初始化数据库（`make initDB`）

Makefile 目标：

```makefile
.PHONY: initDB
initDB:
    rm -f ./data/sqlite/photo_agent_orm.db
    # 用 sqlite3 CLI 或 Go 脚本执行 DDL 文件创建库表
    for file in ./internal/db/sql/*.sql; do \
        sqlite3 ./data/sqlite/photo_agent_orm.db < $$file; \
    done
```

为什么用独立的 `_orm` 库？genCURD 需要读取库中的所有表来生成代码。使用独立的临时库可以避免污染开发/生产数据库。

#### Step 3: 生成 GORM 代码（`make gorm`）

调用 `pgo genGORM`：

```makefile
.PHONY: gorm
gorm:
    rm -rf ./internal/db/model/
    rm -rf ./internal/db/query/
    pgo genGORM \
        -db sqlite3 \
        -dsn "./data/sqlite/photo_agent_orm.db" \
        -outPath ./internal/db/query/ \
        -outFile query.go \
        -modelPkgName github.com/pancake-lee/photo-agent/internal/db/model
```

产出：

- `internal/db/model/*.gen.go`：每个表一个文件，包含 GORM 结构体定义
- `internal/db/query/*.gen.go`：每个表一个文件 + `query.go`，包含类型安全的查询构建器

genGORM 底层使用 `gorm.io/gen`，自动从数据库列类型推导 Go 类型映射。

#### Step 4: 生成 CRUD 全套代码（`make curd`）

调用 `pgo genCURD`：

```makefile
.PHONY: curd
curd:
    pgo genCURD -db sqlite3 -dsn "./data/sqlite/photo_agent_orm.db"
```

这一步骤内部做了：

1. 读取数据库中各表的列信息和索引信息
2. 基于项目内的 `internal/abandonCodeService/` 模板（由 pgo 的 `initProj` 初始化项目时复制到本仓库），用 mark-pair 替换引擎填充各表信息
3. 依次生成：
   - `proto/z_<svc>_service.gen.proto`：CRUD 接口的 proto 定义
   - `internal/<svc>_service/data/z_dao_<tbl>.gen.go`：Data 层（DAO）标准 CRUD
   - `internal/<svc>_service/service/z_svc_<tbl>.gen.go`：Service 层标准 CRUD（含 DO↔DTO 转换）
   - `internal/<svc>_service/service/z_svr_<svc>.gen.go`：Server 注册（Reg 方法）
   - `internal/<svc>_service/<svc>_service.go`：服务 main 入口
4. 自动调用 `make api` 编译 proto 生成 pb.go

#### Step 5: 手写扩展

生成的代码只覆盖标准 CRUD（Add/GetList/Update/Delete），项目特有的查询和统计逻辑写在手写文件中：

- `internal/<svc>_service/data/dao_<tbl>.go`：手写 DAO 扩展（如 `GetPhotosByTimeline`、`ListDistinctTags`）
- `internal/<svc>_service/service/svc_<tbl>.go`：手写 Service 扩展（如 `ListPhotos` 的复杂过滤逻辑）

生成代码会 import 同名手写文件中的扩展方法，所以手写文件可以自然地"挂载"到生成的结构体上。

> PS: 这部分其实在“四、工作流二”中展开

### 3.4 SDK 生成与调用

genCURD 内部的 `make api` 会产出 `openapi.yaml`（OpenAPI 3.0 规范），基于此文件可以自动生成各语言的调用 SDK。

**整体流程**：

```
make api (protoc + 插件)
    ↓
openapi.yaml (OpenAPI 规范)
    ↓  swagger-codegen / openapi-generator
├── Python SDK → agent/ 调用
└── TypeScript SDK → web/ 调用
```

**目标**：

- agent（Python）和 web（Vue 3 / TypeScript）不再手写 HTTP 请求代码（`fetch` / `requests`），不硬编码 URL 路径和参数名
- 调用方通过生成的 SDK 类和方法来访问后端 API，享受编译期类型检查和 IDE 自动补全
- 后端 URL 变更只需重新生成 SDK，调用方代码无需手动修改

**当前 Makefile 中的参考实现**（`api-cli` 目标）：

```makefile
.PHONY: api-cli
api-cli:
    java -jar ~/swagger-codegen-cli.jar generate \
        -i ./openapi.yaml \
        -l go \
        -o ./client/swagger \
        -D packageName=swagger
```

> 注：上述示例生成的是 Go SDK（供 CLI 工具使用），agent 和 web 各自选择对应语言生成器：
>
> - Python：`-l python`（swagger-codegen）或 `-g python`（openapi-generator）
> - TypeScript：`-l typescript-axios` 或 `-g typescript-axios`

**注意事项**：

- proto 通过 gnostic 生成的 `openapi.yaml` 不带 `required` 标识（所有字段都是可选），这会导致 openapi-generator 生成的 Go 代码中所有字段为指针类型。swagger-codegen 无此问题，目前 Makefile 已使用 swagger-codegen
- agent 和 web 的 SDK 生成命令可以在各自目录的构建脚本中维护，也可以统一在 backend 的 Makefile 中提供目标
- SDK 生成是纯增量流程，不影响后端自身的构建和运行

genCURD 生成的标准 CRUD 接口可直接覆盖以下场景：

- **照片列表查询**：genCURD 的 `GetPhotoList` 提供基础分页查询，复杂多条件过滤通过手写扩展补充
- **单张照片查询**：`GetPhotoByID`（genCURD 按主键查询）
- **照片删除**：`DelPhotoByIDList`，额外需要手写扩展处理磁盘文件删除
- **照片创建**：`AddPhoto`（genCURD 标准新增）

以下操作无法被 genCURD 覆盖，需要手写 proto + Service：

- **照片上传**：文件上传逻辑复杂，非标准 CRUD
- **标签更新**：只更新 tags 字段，非标准 CRUD
- **统计聚合**：聚合查询，非 CRUD

> 重构后 URL 路径由 proto 的 `google.api.http` 注解决定（genCURD 生成或手写定义），不再要求与旧 Gin 路由一致。agent 和 web 通过 OpenAPI 生成的 SDK 调用，URL 变更对调用方透明。

---

## 四、工作流二：非 CRUD API 的 Proto 定义

对于统计、VLM 队列控制、SQL 查询、文件上传等非标准 CRUD 接口，不使用 genCURD 自动生成，而是**手写 proto 定义** → **make api 生成 pb 代码** → **手写 Service/D AO 实现**。

### 4.1 流程

```
手写 proto 定义（RPC + Message）
    ↓  make api
生成 pb.go / http.go / grpc.go（到 api/ 目录）
    ↓  手写
internal/<svc>_service/service/svc_<xxx>.go（业务实现）
internal/<svc>_service/data/dao_<xxx>.go（数据访问）
    ↓  make build
可执行文件
```

### 4.2 Proto 定义示例

以 VLM 队列控制为例，在 `proto/vlm_service.proto` 中定义：

```protobuf
syntax = "proto3";
package api;
import "google/api/annotations.proto";
import "common.proto";
option go_package = "github.com/pancake-lee/photo-agent/api;api";

service VLMService {
    // 启动 VLM 队列
    rpc StartVlmQueue (Empty) returns (Empty) {
        option (google.api.http) = {
            post: "/api/v1/vlm/queue/start"
            body: "*"
        };
    }
    // 停止 VLM 队列
    rpc StopVlmQueue (Empty) returns (Empty) {
        option (google.api.http) = {
            post: "/api/v1/vlm/queue/stop"
            body: "*"
        };
    }
    // 查询 VLM 队列状态
    rpc GetVlmQueueStatus (Empty) returns (GetVlmQueueStatusResponse) {
        option (google.api.http) = {
            get: "/api/v1/vlm/queue/status"
        };
    }
}

message VlmQueueStatus {
    bool running = 1;
    int32 queue_length = 2;
    int32 active_count = 3;
}

message GetVlmQueueStatusResponse {
    VlmQueueStatus status = 1;
}
```

关键点：

- `google.api.http` 注解定义 API 路径，重构后按 proto 规范重新设计，不要求与旧 Gin 路由一致
- HTTP 方法与操作语义匹配（POST/GET/PUT/DELETE）
- 请求/响应结构从当前 `gin.H` / 手写 struct 迁移到 proto message，获得强类型约束
- agent 和 web 通过生成的 SDK 调用，URL 变更对调用方透明

### 4.3 需要手写 proto 的服务清单

根据当前路由表整理：

| 服务                     | 接口                                                                           | 当前文件                   | 目标 proto                                                 |
| ------------------------ | ------------------------------------------------------------------------------ | -------------------------- | ---------------------------------------------------------- |
| **照片列表+详情**  | `GET /photos`, `GET /photos/:id`, `GET /photos/:id/image`                | `api/photo.go`           | 部分融入 genCURD，复杂过滤手写扩展                         |
| **照片上传**       | `POST /photos/upload`                                                        | `api/upload.go`          | `proto/photo_service.proto` 手写 RPC                     |
| **标签更新**       | `PUT /photos/:id/tags`                                                       | `api/photo.go`           | 手写扩展                                                   |
| **VLM 队列**       | `POST /vlm/queue/start`, `/stop`, `GET /status`                          | `api/vlm.go`             | `proto/vlm_service.proto`                                |
| **单张描述**       | `POST /photos/:id/describe`                                                  | `api/vlm.go`             | `proto/vlm_service.proto`                                |
| **SQL 查询**       | `POST /query/sql`                                                            | `api/query.go`           | `proto/query_service.proto`                              |
| **表结构**         | `GET /schema/photos`                                                         | `api/schema.go`          | `proto/query_service.proto`                              |
| **属性值**         | `GET /photos/attribute-values`                                               | `api/schema.go`          | `proto/query_service.proto` 或 stats                     |
| **统计**           | `GET /photos/stats`                                                          | `api/photo.go`           | `proto/stats_service.proto`                              |
| **时间线**         | `GET /timelines`, `GET /timelines/:name/photos`                            | `api/timeline.go`        | `proto/timeline_service.proto`                           |
| **标签**           | `GET /tags`, `GET /tags/:name/photos`                                      | `api/tag.go`             | `proto/tag_service.proto`                                |
| **Embedding 代理** | `POST /v1/embeddings`                                                        | `api/embedding_proxy.go` | 保持独立注册（纯代理，与业务 proto 分离）                  |

### 4.4 搬运业务代码的策略

从当前 `internal/api/xxx.go` + `internal/service/xxx.go` 到新的 proto + Kratos service 的迁移步骤：

1. **提取 proto 定义**：从当前 Gin handler 的 `c.Query()` / `c.Param()` / `c.ShouldBindJSON()` 反推请求结构，从 `c.JSON()` 反推响应结构
2. **生成 pb 代码**：`make api` 生成带类型的请求/响应 struct
3. **搬运 service 逻辑**：当前 `internal/service/photo.go` 中的函数逻辑，搬到对应 Service 结构体的方法中
   - 原来：`service.ListPhotos(params) ([]model.Photo, int64, error)`
   - 重构后：`(s *PhotoServer) GetPhotoList(_ctx context.Context, req *api.GetPhotoListRequest) (*api.GetPhotoListResponse, error)`
   - 函数体逻辑不变，只改签名和类型
4. **搬运 api 层逻辑**：原来 api 层做的参数解析/校验移到 Service 方法中（Kratos 模式下参数绑定由框架完成）
5. **删掉旧代码**

---

## 五、pgo 需要补充和优化的功能

以下是在本次重构中发现 pgo 需要改进的地方，按优先级排列。

### P1（本次重构阻塞项）

#### 5.1 genGORM/genCURD 对 SQLite3 的完整支持

**描述**：重构依赖 genGORM + genCURD 读取 SQLite3 数据库生成代码，需要两个工具完整支持 SQLite3 作为数据源。

**决策**：pgo 的 Makefile 硬编码 MySQL 只是 pgo 自身项目的默认值，在 photo-agent 项目的 Makefile 中直接使用 `-db sqlite3` 参数即可，无需改动 pgo 的 Makefile。需要做的是：pgo 增加 `pdb.InitSqlite()`、genGROM/genCURD 增加 `-db sqlite3` 参数路由、驱动层增加纯 Go 驱动支持和 WAL 模式。

**执行状态：[已完成]** — 2026-07-08，详见 pgo commit `6e688e9` 及 `docs/design/sqlite.md`：

- genGORM、genCURD 均已支持 `-db sqlite3` 参数，dispatch 到 `pdb.InitSqlite()`
- `pdb.InitSqlite()` 已创建（使用 `gorm.io/driver/sqlite`），统一 pgo 内部 DB 初始化模式
- 驱动层面：genGORM/genCURD 在代码生成阶段使用 CGO 驱动无影响（开发者机器有 CGO），运行时 photo-agent 继续使用 glebarez/sqlite 纯 Go 驱动，两者各司其职
- WAL 模式：代码生成用的临时 `_orm.db` 不需要 WAL，运行时 WAL 已由 photo-agent 自行在 `service/db.go` 中设置

#### 5.2 genCURD 的 `inferServiceName` 改为可配置

**描述**：`inferServiceName()` 函数硬编码返回 `"default"`，所有表归入同一个 service。对于多表分服务的项目，需要按表名前缀映射到不同 service。

**决策**：暂缓。photo-agent 表数量少（photos + import_jobs），归入同一个 default service 完全够用，不需要分服务。

**执行状态：[暂缓]** — 已记录到 pgo `docs/backlog.md` #14。

#### 5.3 genCURD 模板与目标项目解耦

**描述**：genCURD 的模板文件原来固定在 pgo 仓库的 `internal/abandonCodeService/` 中，不同项目使用时依赖 pgo 仓库内的模板。

**决策**：经验证，pgo 已有的 `initProj` + `workDir` 机制已充分解决此问题：

- `initProj` 将模板文件（`internal/abandonCodeService/`、`proto/abandonCode.proto`、`Makefile`）复制到目标项目
- genCURD 通过 `-workDir` 参数 chdir 到目标项目后，使用相对路径读取项目内的模板
- 无需额外代码改动

**执行状态：[已验证]** — 2026-07-08 确认方案可行。

### P2（重构中需要，可并行）

#### 5.4 pdb 统一 DB 访问模式

**描述**：pgo 内部使用 `db.GetQuery().<Table>` 模式（依赖 genGORM 生成的 query 代码），而 photo-agent 当前直接用 `db.Where(...)`，两种模式不统一。

**决策**：重构后的代码统一使用 pgo 的编码规范，用 genGORM 生成的类型安全 query 代码。复杂聚合/统计场景可以混合使用 `pdb.GetGormDB().Raw(...)`。

**执行状态：[编码规范]** — 非 pgo 代码改动，在 backend 重构时遵循此规范即可。

#### 5.5 papp.AppCtx 增加更多中间件能力

**描述**：`AppCtx` 包含 `UserId`、`Log`、缓存 map，但没有 request-scoped 的 trace ID、请求计时等。

**决策**：暂缓。当前 photo-agent 是单用户本地服务，不紧急。等项目实际需要时再扩展。

**执行状态：[暂缓]** — 已记录到 pgo `docs/backlog.md` #15。

#### 5.6 make api 命令的可配置化

**描述**：`make api` 的 proto 路径、输出路径在 Makefile 中硬编码。genCURD 内部调用 `make api` 也依赖 Makefile 的存在。

**决策**：拒绝。一个项目的文件结构一般很稳定，提供过多变量反而让日常使用变复杂。稳定的参数写死在 Makefile 即可。

**执行状态：[拒绝]** — 已记录到 pgo `docs/note.md` 设计决策记录。

### P3（后续优化）

#### 5.7 genCURD 支持多主键表

**描述**：检测到多主键时直接 `tbl.PriCol = nil` 跳过，生成代码不含 Update/Delete。photo-agent 当前表均使用 UUID 单主键，不受影响。

**执行状态：[P3 后续]** — 已记录到 pgo `docs/backlog.md` #16。

#### 5.8 genGORM 与 genCURD 合并为一个命令

**描述**：分两步执行 `make gorm` 再 `make curd`，各自连接一次数据库。可考虑合并为一个命令减少连接开销。

**决策**：暂时不合并。分开生成有利于排查问题，生成量太多时难以定位根源。

**执行状态：[P3 后续]** — 已记录到 pgo `docs/backlog.md` #17。

#### 5.9 pconfig 支持 SQLite 路径的自动目录创建

**描述**：`pconfig` 负责加载配置，但不负责创建目录。photo-agent 的 `config.Init()` 中手写了 `ensureDir`。

**决策**：拒绝。这种重要的运维逻辑，报错/崩溃/停止才是更好的方式。项目在 `config.Init()` 中自行处理。

**执行状态：[拒绝]** — 已记录到 pgo `docs/note.md` 设计决策记录。

#### 5.10 pgo 增加 Proto-only 生成模式（不依赖 Kratos）

**描述**：`make api` 使用 Kratos 的 protoc 插件生成 HTTP + gRPC 代码。如果项目不需要 Kratos，只想用 proto 做类型定义，当前没有现成命令。

**决策**：拒绝。只使用 proto 类型定义的话，用户自己执行 `protoc` 命令即可，不需要 pgo 提供额外封装。

**执行状态：[拒绝]** — 已记录到 pgo `docs/note.md` 设计决策记录。

---

## 六、编码规范（重构统一标准）

### 6.1 目录与命名

#### 目录结构

```
internal/<name>_service/       # 每个 service 一个独立目录
├── <name>_service.go          # package main，服务入口
├── data/                      # DAO 层（Data Access Object）
│   ├── z_dao_<tbl>.gen.go     # 生成的 DAO
│   └── dao_<tbl>.go           # 手写扩展
└── service/                   # Service 层（业务逻辑）
    ├── z_svr_<svc>.gen.go     # 生成的 Server 注册
    ├── z_svc_<tbl>.gen.go     # 生成的标准 CRUD Service
    └── svc_<tbl>.go           # 手写扩展
```

#### 文件命名

- **生成文件**：`z_` 前缀 + `.gen.go` 后缀。如 `z_dao_photo.gen.go`。这些文件会被 genCURD 的 `rmAllGenFile()` 在重新生成时清除
- **手写文件**：无 `z_` 前缀，无 `.gen` 后缀。如 `dao_photo.go`
- **proto 文件**：生成的有 `z_` 前缀和 `.gen.proto` 后缀；手写的只有 `.proto` 后缀
- **DDL 文件**：`<table_name>.sql`，存放于 `internal/db/sql/`

#### 命名约定

- **Go 变量**：`camelCase`，List 后缀表示切片（`photoList`），Map 后缀表示映射（`idToPhotoMap`）
- **Go 类型**：`UpperCamelCase`，保持 `ID` 全大写（`PhotoID` 而非 `PhotoId`），保持 `URL` 全大写
- **Proto field**：`snake_case`，如 `photo_id`、`created_at`
- **Service 名**：与表名的关联由 `inferServiceName` 或配置文件决定
- **HTTP 路径**：kebab-case，如 `/api/v1/vlm-queue/status`，由 proto 的 `google.api.http` 注解决定

### 6.2 分层职责

```
┌─────────────────────────────┐
│  proto/*.proto              │  API 契约定义
│  api/*.pb.go (生成)          │  Request/Response 类型
├─────────────────────────────┤
│  service/svc_*.go           │  业务逻辑编排
│  service/z_svc_*.gen.go     │  标准 CRUD（生成）
├─────────────────────────────┤
│  data/dao_*.go              │  数据访问（GORM 操作）
│  data/z_dao_*.gen.go        │  标准 CRUD DAO（生成）
├─────────────────────────────┤
│  internal/db/model/*.gen.go │  GORM 模型（生成）
│  internal/db/query/*.gen.go │  类型安全查询（生成）
├─────────────────────────────┤
│  internal/db/sql/*.sql      │  DDL 定义（手写，事实来源）
└─────────────────────────────┘
```

**Service 层**：负责业务逻辑编排。包括参数校验、权限判断、调用 DAO、组装响应。不直接写 SQL。

**Data 层（DAO）**：负责数据访问。封装 GORM 操作，一个方法一个数据库操作。不包含业务逻辑。简单查询使用生成的类型安全 query，复杂查询使用 `db.Raw()` 或 GORM 链式调用。

### 6.3 Service 方法签名规范

所有 Service 方法统一使用 Kratos 生成的签名：

```go
func (s *PhotoServer) GetPhotoList(
    _ctx context.Context,
    req *api.GetPhotoListRequest,
) (resp *api.GetPhotoListResponse, err error) {
    ctx := papp.NewAppCtx(_ctx)
    // 业务逻辑 ...
}
```

要点：

- `_ctx` 前缀下划线表示原始 context，不直接使用
- 通过 `papp.NewAppCtx(_ctx)` 创建项目级 context，包含 logger、userID、cache 等
- 返回值 `resp` 和 `err` 使用命名返回值，方便 defer 中做统一处理

### 6.4 错误处理

- **DAO 层**：错误直接向上抛，用 `ctx.Log.LogErr(err)` 包装日志输出后返回
- **Service 层**：区分业务错误和系统错误。业务错误（如"照片不存在"）返回明确的 error 信息；系统错误（如"数据库连接失败"）打日志后返回通用错误码
- 使用 pgo 的 `perr` 包（如果存在）或 Kratos 的 error handler 做统一错误码映射
- **禁止**用 `try-catch` 风格的宽泛 `recover` 掩盖错误，必须逐层处理

### 6.5 日志规范

```go
ctx.Log.Debugf("GetPhotoList: page=%d, pageSize=%d", req.Page, req.PageSize)
ctx.Log.Infof("photo created: id=%s", photoID)
ctx.Log.Warnf("auto sync partial failure: %v", err)
```

- Debug：调试信息，生产环境默认不输出
- Info：关键操作节点（创建/删除/状态变更）
- Warn：非致命错误（单张照片处理失败但继续批量处理）
- Error：需要人工介入的错误（数据库连接失败）
- 日志中**不输出**敏感信息（API key、密码等）

### 6.6 配置管理

保持当前 `internal/pkg/config/` 的模式，使用 `pconfig` 的 `Scan` + `default` tag：

```go
type ServerConfig struct {
    Addr string `json:"addr" toml:"addr" default:":8080"`
}
```

- 配置从 TOML 文件加载，路径由 `-c` 参数指定
- `default` tag 定义默认值，无需配置文件即可运行
- 需要创建目录的路径，在 `Init()` 中统一处理

### 6.7 DO↔DTO 转换

```go
// DO: Data Object（GORM 模型，数据库直接映射）
// DTO: Data Transfer Object（proto 生成的 API 类型）

func DO2DTO_Photo(do *model.Photo) *api.PhotoInfo {
    if do == nil { return nil }
    return &api.PhotoInfo{
        Id:          do.ID,
        Filename:    do.Filename,
        // ...
        ShotAt:      do.ShotAt.Unix(),  // time.Time → int64
    }
}

func DTO2DO_Photo(dto *api.PhotoInfo) *model.Photo {
    if dto == nil { return nil }
    return &model.Photo{
        ID:       dto.Id,
        Filename: dto.Filename,
        // ...
    }
}
```

- 生成的标准转换由 genCURD 产出
- 手写字段的转换在手写文件中补充
- 时间类型：DO 用 `time.Time`，DTO 用 `int64`（Unix timestamp）

### 6.8 并发处理

保持当前项目良好的并发模式，统一规范：

- **信号量控制并发数**：`sem := make(chan struct{}, concurrency)`
- **Channel 通信**：异步队列用 buffered channel
- **原子操作计数**：`sync/atomic` 用于计数器，`sync.Mutex`/`sync.RWMutex` 用于共享状态
- **Context 传播**：所有长时间操作接受 `context.Context`，支持取消

---

## 七、迁移策略

### 7.1 建议分阶段执行

#### 阶段 0：pgo 工具链完善（在 pgo 项目中进行）

- [X] genGORM + genCURD 支持 `-db sqlite3` 参数（pgo commit `6e688e9`）
- [X] `pdb.InitSqlite()` 创建（`gorm.io/driver/sqlite`）
- [X] genCURD 模板解耦方案确认（initProj + workDir 已够用）
- [X] genCURD `inferServiceName` → 暂缓（backlog #14，photo-agent 用 default 即可）
- [X] genCURD 对 SQLite3 的端到端测试（用 photo-agent 的表结构验证生成质量）

#### 阶段 1：DDL + 数据库层（不影响运行）

- [X] 使用`pgo`的`initProj`功能初始化项目
- [X] 编写 `sql/photo.sql` 和 `import_job.sql`
- [X] 配置 `make initDB` / `make gorm` / `make curd` 目标，改成基于sqlite3
- [X] 跑通 genGORM → genCURD 流程，检查生成代码质量
- [X] 对比生成代码与当前手写代码，确认覆盖度

#### 阶段 2：照片 CRUD 服务迁移

- [X] 创建 `photo_service.proto`，跑通生成代码
- [X] 手写扩展：复杂过滤查询（`ListPhotos`）的 Service + DAO 逻辑
- [X] 手写扩展：统计（`GetPhotoStats`）的逻辑
- [X] 手写扩展：标签更新（`UpdatePhotoTags`）
- [X] 手写扩展：上传（`UploadPhoto`）+ 文件管理
- [ ] 从 `openapi.yaml` 生成 Python SDK 和 TypeScript SDK，验证 SDK 可用性
- [ ] 切换到新服务，删除旧 `internal/api/photo.go` + `internal/api/upload.go`

#### 阶段 3：其余服务逐一迁移

- [X] 导入任务服务 — 已删除（业务上与 batch_vlm + Web 上传重叠，废弃 import_jobs 表）
- [X] VLM 服务 — proto 定义 + 脚手架 done（svc_vlm.go stub），业务逻辑待迁移
- [X] 统计/查询/Timeline/Tag 服务 — proto 定义 + 脚手架 done，统计已在阶段 2 融入 photo_service
  - [X] `vlm_service.proto` — VLM 队列控制 + 单张描述
  - [X] `timeline_service.proto` — 时间线列表 + 按时间线查照片
  - [X] `tag_service.proto` — 标签列表 + 按标签查照片
  - [X] `query_service.proto` — SQL 查询 + 表结构 + 属性值
- [ ] Embedding 代理（保持特殊处理，不纳入 proto）

#### 阶段 4：SDK 集成 + 清理 + 文档

- [ ] 删除旧的 `internal/api/`、`internal/service/`（业务逻辑全部搬完后）
- [ ] agent（Python）改用生成的 Python SDK 调用后端，移除手写的 HTTP 请求代码
- [ ] web（Vue 3）改用生成的 TypeScript SDK 调用后端，移除手写的 fetch/axios 代码
- [ ] 更新 `CLAUDE.md`、`README.md`
- [ ] 端到端联调验证所有 API

### 7.2 验证方式

- 每个阶段迁移完成后，用当前 `test/backendTest.go` 做回归测试（测试文件需随 URL 变更同步更新）
- 生成 SDK 后，在 agent 和 web 中验证 SDK 调用是否正常
- 在迁移过程中，新旧代码可以暂时共存（通过路由前缀区分），逐步切换

---

## 八、风险与注意事项

- **框架切换成本**：当前是 Gin 直接写 handler，重构后是 proto → Kratos。Service 层业务逻辑可复用，但 api 层的参数解析/响应渲染需要改写。估时约 2-3 天完成全部迁移
- **genCURD 的局限性**：只生成单表的简单 CRUD，复杂查询仍需手写。不要期望 genCURD 覆盖所有场景，它解决的是 80% 的样板代码
- **GORM 类型映射差异**：genGORM 从 SQLite3 列类型推导 Go 类型，可能与当前手写 struct 的类型不同（如 TEXT 映射为 `string` vs `sql.NullString`），需要逐字段验证。SQLite 柔性类型系统的注意事项见 pgo `docs/design/sqlite.md` 的「类型映射注意事项」章节
- **OpenAPI 生成 SDK 的字段可选问题**：proto 通过 gnostic 生成的 `openapi.yaml` 不带 `required` 标识，可能导致某些语言生成器的产出代码中所有字段为指针/可选类型。Makefile 中已选用 swagger-codegen 规避此问题，但切换到其他语言生成器时需验证
- **SDK 生成流程的维护成本**：每次 proto 变更后需要重新生成 SDK 并同步到 agent 和 web 项目。建议在各项目的构建流程中集成 SDK 生成步骤，或在 backend Makefile 中提供统一入口
- **Embedding 代理**：当前是纯反向代理（OpenAI 格式 → 火山引擎格式），与业务 proto 无关。建议保持特殊处理，不纳入 proto 生成体系
- **batch_vlm 和 init_dify CLI**：这两个 CLI 工具不对外暴露 HTTP API，不涉及 proto 定义。保持 `cmd/` 下的独立入口，只迁移它们引用的 service 层代码到新位置
