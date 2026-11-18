# 图片管理分段浏览文档试点记录

2026-11-14。按规划模式归纳既有功能，以 `9c6bcf54299a` 为源码核对基线。本轮证据来自旧文档、Git 历史和静态实现检查。

## 试点范围与资料去向

- `LB` 沿用专题编号。分段、窗口定位、浏览区及顶栏变化服务于同一用户流程，LB1–LB4、LB6–LB8 是功能的来源与验收历史。 [历史设计中枢](../_archives/photo-list-browsing/2026-08-20-1-photo-list-hub.md)
- 当前浏览页活动输入为照片库目录，2026-11-18 已由目录同步替代 LB5 的事件/散片重算流程。 [时间线规格](../product-specs/photo-agent.md#28-时间线管理) · [时间线归属设计](../design-docs/system-design.md#37-活动目录与时间线同步)
- 规格和详细设计分别从 [总规格](../product-specs/photo-agent.md#51-web-前端主要交互方式) 与 [系统设计](../design-docs/system-design.md#专题设计) 进入。原实施状态见 [v1.0.10](../version/v1.0.10.md)。
- LB1 原稿注明源自外部 AI 对话的需求总结。仓库中可追溯的最早文本是 `f6659db` 的首轮规划，直接对话缺少独立入口。 [LB1 原始设计](../_archives/photo-list-browsing/2026-08-20-1-photo-list-segmented-browse-design.md)

## 规格与实现差异

以下差异通过源码核对发现，浏览器运行结果仍待复验。规格中的验收条件引用历轮确定的行为。

- LB-A2 日期修改应即时刷新列表和导航。LB6 定稿要求改日期即触发筛选，当前日期选择器只写入值。搜索回车、活动选择及排序切换等其他操作会触发查询。单独修改日期时，现有列表和导航可能仍显示修改前的数据。 [LB6 原始设计](../_archives/photo-list-browsing/2026-08-21-1-photo-list-window-preload-design.md#93-lb6图片管理顶栏重排) · [顶栏事件](../../web/src/components/PhotoManagementToolbar.vue#L103) · [应用筛选](../../web/src/composables/usePhotos.ts#L417)
- LB-A5 月份导航和本地月份分割线应对应同一批照片。LB8 把前端分割线改为浏览器本地日期，Go 导航仍按 UTC 月份聚合。例如东八区 1 月 1 日 00:30 的照片归入本地 1 月分割线和后端 12 月导航，可能影响数量、定位和高亮。 [前端分段](../../web/src/utils/segment.ts#L32) · [后端分段](../../backend/internal/defaultService/data/dao_photo.go#L226) · [日期单测](../../web/src/utils/segment.spec.ts)
- LB-A4 连拍折叠时目标段可能只有被隐藏的组员。导航按全部照片计数，定位仅在窗口内查找可见卡，找不到时回到窗口顶部。折叠下的精准跳转和首屏续载均缺少专项运行时证据。 [折叠渲染](../../web/src/components/PhotoGrid.vue#L62) · [导航定位](../../web/src/components/PhotoListBrowser.vue#L78) · [历史验收](../_archives/photo-list-browsing/2026-08-20-1-photo-list-hub.md#4-v1010-归档时的验收状态)

## 已核对的历史取舍

- 导航点击由 LB1 的筛选重置改为 LB2 的窗口重定位。实际「回到最新」从 LB2 实现 `f701981` 起调用重置筛选，当前接线保持该行为。 [旧窗口设计](../_archives/photo-list-browsing/2026-08-21-1-photo-list-window-preload-design.md) · [当前接线](../../web/src/views/PhotoManagement.vue#L270)
- 排序入口收敛为拍摄时间升降序，后端仍提供已有其他排序键。 [决策记录](../note.md#15-照片列表排序收敛三键排序--仅拍摄时间升降序2026-08-20) · [后端排序](../../backend/internal/defaultService/data/dao_photo.go#L153)
- 2026-08-21 的 8.1/10 属于 LB1–LB6 的评估，当时的库为 1323 张。2000+ 张滚动和散片重算列为遗留验证。LB7–LB8 的拆分及单测由后续版本记录承接。 [评估报告](../eval/reports/2026-08-21-photo-list-lb-series.md) · [v1.0.10 验证记录](../version/v1.0.10.md#验证与遗留验证)

## 本轮验证

- `web/` 运行 `pnpm exec vitest run src/utils/segment.spec.ts`，两项日期分段测试通过。
- `backend/` 运行 `go test ./internal/defaultService/data -run '^TestListPhotoSegments' -count=1`，月份及活动分段测试通过。
- 检查 60 个新增本地链接与锚点，差异格式检查通过。浏览器联动及真实库历史遗留项仍待场景验证。

## 文档迁移

- DOC3 已完成。分段浏览由产品规格和 Feature 详细设计承接。LB5 的管理行为与验收补入总规格，重算契约补入系统设计。 [浏览规格](../product-specs/2026-08-20-photo-list-browsing.md) · [浏览设计](../design-docs/2026-08-20-lb-photo-list-browsing-design.md) · [时间线规格](../product-specs/photo-agent.md#28-时间线管理) · [时间线设计](../design-docs/system-design.md#37-活动目录与时间线同步)
- 四份旧稿按原名和原文移入 `docs/_archives/photo-list-browsing/`。版本快照及原稿中的旧相对路径随快照保留。 [历史设计归档索引](../version/design-archives.md)
- 旧 LB5 重算存在的同月散片合并问题，已随日期窗口分组退役；当前照片按所在目录归属。 [当前设计](../design-docs/system-design.md#37-活动目录与时间线同步)
- 迁移验证：四份归档与移动前逐字节一致，既有冻结文件保持原样，35 个新增链接与锚点通过检查。现行规格、设计和架构均可独立于旧稿读取。
