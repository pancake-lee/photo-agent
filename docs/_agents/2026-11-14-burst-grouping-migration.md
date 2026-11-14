# 连拍分组文档迁移核对

2026-11-14。以 `f2c1b6f` 为源码基线，迁移 BG1 的识别、双档配置、重算、折叠浏览和封面维护。新稿沿用初稿日期 `2026-08-19`。

## 现行入口

- 产品规格从总产品规格进入。详细设计从系统设计的「专题设计」进入。分段浏览规格引用连拍规格，组级检索继续在其专题维护。 [产品规格](../product-specs/2026-08-19-burst-grouping.md) · [详细设计](../design-docs/2026-08-19-burst-grouping-design.md)
- 旧稿保留原名和字节内容，版本 README 通过历史设计归档索引定位。v1.0.10 快照保留原有相对路径。 [历史设计归档索引](../version/design-archives.md)

## 新旧口径核对

- 旧稿同时记有 YAML、单档位与双档配置。现行参数由设置页保存至数据库。ImageMagick 提取共享灰度矩阵，SSIM 在 Go 内计算。 [分组服务](../../backend/internal/defaultService/service/svc_burst_group.go)
- 旧稿称弹窗拉取全部成员。现行只请求首 100 张，取数失败与空组使用同一空状态。手选封面在重算时重置。 [弹窗取数](../../web/src/composables/usePhotos.ts#L482) · [初始封面](../../backend/internal/defaultService/service/svc_burst_group.go#L398)
- 重算先清旧组，再逐档保存。后台失败可能留下部分结果，状态响应无独立失败字段。图片管理收到停止状态会提示完成，并触发独立的组向量同步。 [重算实现](../../backend/internal/defaultService/service/svc_burst_group.go#L331) · [完成回调](../../web/src/views/PhotoManagement.vue#L203)

## 本轮验证

- 在 `backend/` 执行 `go test ./internal/defaultService/service -run '^(Test(SplitByTimeWindow|SplitBySimilarity_.*|SplitBurstGroups_.*|ValidateBurstConfig|DefaultBurstConfigUsesCurrentSettings|CalcSSIM|HammingDist|ParseGrayTxt))$' -count=1 -v`，10 项通过。覆盖时间窗、视觉切分、灰区、双档位、单张、默认值、非法阈值和灰度解析。
- 文档自评 · 核心区可独立核对触发入口、判定流程、清旧组的影响和封面边界。接口、存储、阈值读取与验证入口放在补充说明。规格与设计链接分别归属各自总入口，历史归档保留单独索引。
- 归档原稿与迁移前逐字节一致。本轮新增或修改的本地链接和锚点均可解析。
- 未执行浏览器和真实库全量重算。折叠、换封面、超长组的浏览器表现以源码核对。准确率、误归与漏归、全量耗时仍属于历史 P5 实机验证。 [版本验证记录](../version/v1.0.10.md#验证与遗留验证)
