# LB 系列整体评估报告

- **报告 ID**：eval-lb-series-20260821
- **日期**：2026-08-21
- **对象**：LB 系列（照片列表浏览专题）：LB1 分段浏览 / LB2 滑动窗口预加载 / LB3 高度链修复 / LB4 导航精度 / LB5 散片时间线+管理页 / LB6 顶栏重排
- **提交**：LB1 f19b2e4 · LB2 f701981 · LB3 70aac52 · LB4/LB5/LB6 c3720ec

## 摘要

**总分 8.1/10 ✅ 通过**（阈值 6.0）。分条目：LB1 8.3 · LB2 7.9 · LB3 7.7 · LB4 8.5 · LB5 7.9 · LB6 8.4。

一句话总结：核心数据链路（分段 offset/count/窗口拉取/导航跳转/高亮）经运行时实测全部精确对齐，LB4 修复实测有效、LB6 顶栏与设计定稿一致；主要扣分在 PhotoManagement.vue 1030 行的可维护性债与 LB5 散片运行时效果悬置（重算未执行）。

评估方式：三路并行代码审查 + 运行时实测（API/sqlite3/Playwright）。子代理曾报三项「高严重」问题（offset 不随排序方向 / 排序 UI 残留 / 气泡无延迟），经复测全部排除（首项因 curl 误传 camelCase 参数走进 default 分支）。

## 分维度评分

### 代码质量

**正确性 8.5**

得分点：

- ListPhotoSegments offset 实测跟随排序方向：desc 首段 2026-08 offset=0 / 末段 2025-03 offset=1280，asc 正确反转
- 导航 count 与 SQL 实测完全一致：月分段 145/51/136/18/265 与 DB 聚合逐项吻合
- offset 与窗口拉取对齐：SearchPhotos desc 首页首张 2026-08-08 与 segments[0].offset=0 同口径；asc 下 2025-03 offset=2 正确跳过 2 张零值照片（dao_photo.go:228 IsZero 排除）
- timeline=none sentinel 运行时验证：API total=190 与 DB 空标签数完全一致
- LB4 运行时验证：点击「2026 年 2 月」导航项后窗口重定位、active 高亮与目标一致
- LB5 JSON 一次性迁移已实际发生：timeline_events 29 条、created_at 同批次 2026-08-21 14:45:08，ListEvents 返回 photoCount/isScattered 完整
- LB6 顶栏单行实测文案与设计定稿完全一致
- photoListScope（dao_photo.go:87-180）作为列表与分段导航的共享筛选排序入口，落实设计 3.2 节关键承诺
- 气泡修复：PhotoCard.vue:79 `:delay="300" :to="false"`

失分点：

- 分段日期/月份键全链路 UTC（dao_photo.go:235 与 segment.ts:35），东八区凌晨 0-8 点拍摄照片按天分段归前一天；实测当前库月首日凌晨影响 0 张，理论瑕疵
- 散片生成与重算的运行时效果未验证：DB 散片组 0 条、timeline_manual 全 0（用户未执行重算，非代码缺陷）

**健壮性 7.5**

得分点：

- DAO 层全参数绑定（rawCond + ? 占位）无 SQL 注入面；错误处理无吞错
- 窗口 offset 越界收敛（usePhotos.ts:222）、noMoreUp/noMoreDown 边界标志完整
- RecomputeTimelines 复用 burstGroupManager 成熟模式，already_running 双重检查（svc_timeline.go:319-344）
- 管理页重算轮询 1500ms、!running 停止、onUnmounted 清理
- 表单校验：日期/活动名空值 message.warning 拦截

失分点：

- fetchPage 无请求去重：loading 标志只防重入，快速滚动同一页可能重复请求（usePhotos.ts:180-203）
- 窗口淘汰未检测锚点元素是否在被淘汰页内，极端滚动下视口可能跳变（usePhotos.ts:306-324）
- fetchSegments/统计获取失败仅 console.warn，用户无感知

**可维护性 7**

得分点：

- 组件职责分离清晰：PhotoSegmentDivider / PhotoSegmentNav / segment.ts 纯函数；后端 segmentLabel 与前端 segLabelOf 文案口径对齐
- 散片分组 splitScatteredPhotos 为 64 行纯函数；timeline_events 表遵循无外键约定
- svc/dao 分层与既有代码一致；LB1 旧「筛选重置式跳转」dead code 清理干净

失分点：

- PhotoManagement.vue 已达 1030 行，LB1-LB6 全部叠加于此，与 W12（ImportWorkflow.vue 1010 行拆分）同级技术债
- LB3 高度链修复依赖 naive-ui 内部类名 .n-layout-scroll-container / .n-layout-content，组件库升级时可能静默失效（已知取舍）
- evictTop/evictBottom 对称重复（usePhotos.ts:306-324）

**简洁性 8**

得分点：

- LB1 分页组件与 page+追加模型移除彻底，无残留分页状态
- 类型安全良好，无 any 滥用
- 散片判定/分组/JSON 解析均为短纯函数

失分点：

- .pagination-wrapper 空样式残留（PhotoManagement.vue:1011-1013）
- TIMELINE_NONE 常量已导出但 PhotoManagement.vue:170 硬编码 'none' 字面量

### 功能效果

**准确性 9**：导航 count 16 个月份项与 SQL 逐项一致；导航跳转落点与高亮实测一致；ListEvents photoCount 与 DB 匹配；sentinel 过滤 190=190 精确。失分：散片命名与重算保留人工值语义仅有单测证据，无运行时证据。

**完整性 8**：六条目设计承诺全部落地（三种分段方式、双向滚动+预加载+淘汰、窗口重定位、高度链、导航精度、timeline_events CRUD+重算+管理页、顶栏单行收纳）；「保留 sentinel 兼容未重算存量照片」已实现；LB2 对 LB1 4.2 节决策的反转在代码层执行彻底。失分：散片单测缺跨年边界与单月多段序号递增断言；「2000+ 张滚动流畅」未验证（库仅 1323 张）。

**一致性 9**：前后端分段文案口径统一（「2026 年 8 月」「未分类」「未知时间」）；管理页 NaiveUI 风格一致，散片组区分样式+空态提示；顶栏遵循 ui-rules.md。无失分点。

### 用户价值

**交互体验 8**：导航跳转→窗口重定位→高亮全链路 4 秒内完成，流连续不锁死（对比 LB1 筛选重置式是质变）；管理页信息密度合理一屏可扫读；顶栏从三行收敛为单行。失分：图片异步加载时滚动补偿理论上有跳变风险（PhotoCard aspect-ratio:1 固定卡片尺寸，实际风险低，未实测到跳变）。

## 执行证据

**运行时验证**：

- `make status` 三服务健康；`go test ./internal/defaultService/service/...` PASS（0.133s）
- `GET /api/v1/photos/segments?sortBy=shot_at&sortOrder=desc|asc`：offset 随方向正确反转
- `GET /api/v1/photos?timeline=none`：total=190 = DB 空标签数
- `GET /api/v1/timeline-events`：29 事件含 photoCount/isScattered；recompute/status running=false
- Playwright 实测 `/#/photos`：顶栏单行文案、分割线「2026 年 8 月 114 张」渲染、导航 16 项 count 与 SQL 一致、点击 2026-02 后 active 高亮与落点正确
- Playwright 实测 `/#/timelines`：29 事件渲染、散片组空态提示正确
- sqlite3：timeline_events 29 条（JSON 已迁移）、photos timeline_manual 全 0、散片组 0 条（重算未执行）

## 下一步建议

- （用户）在 /timelines 页执行一次「重算时间线」，闭环 LB5 散片验收
- LB7 PhotoManagement.vue 拆分（建议在 LB5 运行时验证后）
- LB8 四项低危小项可搭车 LB7 处理或明确接受
