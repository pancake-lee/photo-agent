# Photo Agent - 技术升级规划

> 本文档记录基于当前架构可引入的技术改进、优化方向及决策思考。原始 PRD 不作改动。

---

## 1. SQLite WAL 模式（高优先级）

**决策：不升级为 PostgreSQL，启用 WAL 模式优化并发性能。**

当前 SQLite 使用默认的 rollback journal 模式，在 server 启动时的 `AutoSync` 并发导入场景下，多 goroutine 同时写库会导致数据库级锁竞争。照片库量级在数万张以内时，SQLite 完全够用，迁移到 PostgreSQL 的收益不足以覆盖运维复杂度。

**具体措施：**
- 在 `service.InitDB()` 中执行 `db.Exec("PRAGMA journal_mode=WAL;")`
- WAL 模式下读操作不会阻塞写操作，写操作也不会阻塞读操作，`AutoSync` 的并发导入效率可提升数倍
- WAL 文件定期自动 checkpoint，无需额外维护

**不升级 PG 的理由：**
- 单机部署、轻量级运维是项目的核心约束
- GORM 换驱动虽简单，但引入 PG 容器后 Dify + PG + Go 三容器栈太重
- 当前最大并发写只是启动同步，WAL 足以解决

---

## 2. 可观测性（高优先级，参考 pgo 监控体系）

**想做，且已有现成基础设施可复用。**

`../pgo/deploy/docker/docker-compose.yaml` 中已经完整配置了 Prometheus + Grafana + Loki + Promtail + node-exporter + cAdvisor 的监控栈：

```yaml
# pgo 监控组件概览
prometheus      :29090  # 时序数据库，拉取 metrics
grafana         :23000  # 可视化仪表盘
loki            :23100  # 日志聚合存储
promtail        : --    # 日志采集器，读取 /opt/app_logs 上报 loki
node-exporter   :29100  # 宿主机系统指标（CPU/内存/磁盘/网络）
cAdvisor        :28081  # 容器指标（CPU/内存/网络/磁盘 I/O）
```

**Photo Agent 可直接接入的监控点：**

| 层级 | 接入方式 | 指标内容 |
|------|---------|---------|
| Go 应用指标 | Prometheus Client (`github.com/prometheus/client_golang`) | HTTP QPS/延迟/错误码、照片总量、导入任务状态、VLM API 调用次数与延迟 |
| 日志采集 | Promtail 读取 Go 日志文件 | 结构化日志（JSON 格式）直接入 Loki，支持在 Grafana 中按 trace_id 检索 |
| 系统监控 | 复用 node-exporter + cAdvisor | 宿主机和容器资源使用 |
| 告警 | Grafana Alerting | 磁盘空间不足、导入任务失败率过高、Dify 不可达 |

**实施方式：**
- Go server 暴露 `/metrics` 端点（非 `/api` 路径，避免被 Dify 工具调用）
- 日志输出到文件（或 stdout 由容器收集），Promtail 配置读取
- Grafana dashboard 可复用 pgo 的基础模板，只需增加 Photo Agent 业务面板

**暂不引入的：**
- Jaeger / Zipkin 分布式链路追踪（单服务，无跨服务调用链）
- 自定义告警通道（先走 Grafana 内置 alert）

---

## 3. 引入 pgo 的 proto-first 开发方式（待决策）

### 3.1 pgo 的 proto 工作流

pgo 项目中，API 接口以 `.proto` 文件为唯一数据源，通过 protoc 插件链自动生成全部框架代码：

```
手写 userService.proto（service + rpc + message + google.api.http 注解）
    ↓ protoc
    ├── *.pb.go          # Go struct + gRPC stub
    ├── *_http.pb.go     # kratos HTTP 路由注册 + 参数绑定
    ├── *_grpc.pb.go     # gRPC server interface
    └── openapi.yaml     # Swagger/OpenAPI 文档（由 gnostic 生成）
```

开发者只需：
1. 定义 proto 接口
2. 实现生成的 interface 中的业务方法
3. 框架代码（路由、中间件、错误处理、swagger 文档）全部自动生成

### 3.2 对应到 Photo Agent

当前 `docs/dify_tools_openapi.yaml` 是**手写维护**的 Dify 工具配置，与 Go 代码中的 Gin handler 是两套东西。如果改接口（如新增字段、调整路径），需要同时改 yaml + Go handler + routes 注册，容易遗漏不一致。

**迁移到 proto-first 后：**

```proto
// photo_agent.proto（示意）
syntax = "proto3";
package api;
import "google/api/annotations.proto";

service PhotoAgent {
    rpc ListTimelines(ListTimelinesRequest) returns (ListTimelinesResponse) {
        option (google.api.http) = { get: "/api/timelines" };
    }

    rpc GetPhotosByTimeline(GetPhotosByTimelineRequest) returns (GetPhotosByTimelineResponse) {
        option (google.api.http) = { get: "/api/timelines/{name}/photos" };
    }

    rpc GetPhotosByTags(GetPhotosByTagsRequest) returns (GetPhotosByTagsResponse) {
        option (google.api.http) = { get: "/api/photos" };
    }

    rpc GetPhotoDetail(GetPhotoDetailRequest) returns (Photo) {
        option (google.api.http) = { get: "/api/photos/{id}" };
    }

    rpc ImportPhotos(ImportPhotosRequest) returns (ImportJob) {
        option (google.api.http) = { post: "/api/import/jobs" body: "*" };
    }

    rpc GetImportStatus(GetImportStatusRequest) returns (ImportJob) {
        option (google.api.http) = { get: "/api/import/jobs/{id}" };
    }
}
```

运行 `make api` 后：
- 自动生成 `photo_agent.pb.go`（所有 struct 定义）
- 自动生成 `photo_agent_http.pb.go`（kratos HTTP server 注册，替代 Gin + 手写 routes.go）
- 自动生成 `openapi.yaml`（替代手写的 `docs/dify_tools_openapi.yaml`）

### 3.3 是否值得迁移？

**支持的点：**
- 接口定义单一数据源，yaml + Go 代码永远一致
- 省去 `routes.go`、Gin handler 参数绑定、swagger 维护等框架代码
- 未来如需 gRPC 调用（如 VLM 服务拆出去）可直接复用 proto
- 错误码体系可标准化（配合 `protoc-gen-go-errors`）
- 项目虽小，但 proto-first 是"一次投入、长期受益"的基础设施

**顾虑的点：**
- 当前 API 数量很少（7 个工具 API + 图片服务 + health + embedding proxy），手写成本本身不高
- 需要引入 kratos 框架替换 Gin，增加依赖重量
- 团队/个人对 kratos 的熟悉度 vs Gin
- 图片端点 `/api/photos/:id/image` 是文件流式响应，kratos HTTP 对文件下载的支持需要验证
- `EmbeddingProxy` 是纯代理转发，用 proto 定义意义不大

**迁移路径（如果决定做）：**

```
Step 1: 在 photo-agent 中建立 proto/ 目录，引入 third_party（google/api, validate 等）
Step 2: 将当前所有 API 翻译为 .proto 定义
Step 3: 复制 pgo 的 Makefile api 目标，配置 protoc 插件链
Step 4: 用生成的 kratos HTTP server 替换 Gin，实现 service interface
Step 5: 删除手写 routes.go、手写的 dify_tools_openapi.yaml
Step 6: 图片文件服务端点和 embedding proxy 可作为"非 proto 路由"单独挂载
```

**决策结论：暂不实施，但保留为中期优化方向。** 当前 API 数量少，迁移的即时收益有限。待 API 增长到 15+ 或需要引入 gRPC 时，再一次性切到 proto-first。

---

## 4. 异步任务队列及后续优化（待定）

以下内容已识别为有价值的优化方向，但尚未形成具体实施计划，先原文记录，后续再决策：

### 4.1 异步任务队列（高优先级）

当前 `AutoSync` 仅在 server 启动时执行一次，失败无重试、无进度可见性、server 重启即丢失中间状态。

**未来可引入：**
- 持久化任务队列（`github.com/hibiken/asynq` 基于 Redis，或 SQLite 轻量队列）
- 后台定时扫描（cron），无需重启 server 即可增量同步
- 导入任务支持断点续传、实时进度查询

### 4.2 缓存与性能

- 内存 LRU 缓存（缩略图路径、照片元数据）
- API 响应缓存（`go-cache`， timelines/tags 缓存 5 分钟）
- HTTP 缓存头（ETag / Last-Modified）用于图片端点
- 图片格式自适应（WebP/AVIF 根据 Accept 头自动返回）

### 4.3 搜索能力增强

- SQLite FTS5 全文搜索（Dify 不可用时兜底）
- 本地向量库 `sqlite-vec`（Embedding 本地化）
- 感知哈希相似图片搜索（重复照片检测）
- 多模态 Embedding（以图搜图）

### 4.4 API 工程化

- 优雅关闭（Graceful Shutdown）
- 限流与熔断（VLM API 保护）
- 统一错误响应格式
- API Key 认证
- 配置热加载（viper WatchConfig）

### 4.5 EXIF / 地理信息

- GPS 坐标提取与反向地理编码
- 地图聚合展示
- 相机参数分析（摄影报告）

### 4.6 Dify 侧增强

- Dify DSL 版本控制 + 自动同步（配置即代码）
- Embedding 代理多 provider 自动降级
- 多 Agent 协作工作流

---

## 附录：已明确的近期行动项

| 序号 | 事项 | 优先级 | 状态 |
|------|------|--------|------|
| 1 | 启用 SQLite WAL 模式 | 高 | 待实施 |
| 2 | 接入 Prometheus + Grafana 监控（复用 pgo 基础设施） | 高 | 待实施 |
| 3 | 评估 proto-first 迁移价值 | 中 | 暂不实施，保留 |
| 4 | 异步任务队列 | 高 | 待定 |
| 5+ | 其余优化项 | 中/低 | 待定 |
