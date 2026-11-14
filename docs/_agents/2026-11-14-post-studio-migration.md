# 图文工坊文档迁移核对

2026-11-14。以 `f0f36f1` 为源码核对基线，按图文工坊从编排到导出的完整流程迁移 PS1–PS6，并纳入 PS10 的草稿恢复。

## 现行入口

- 产品规格维护创作入口、模式、草稿、导出与验收。详细设计维护模块职责、文案契约和保存边界。文件名沿用首轮设计日期 `2026-08-23`。 [产品规格](../product-specs/2026-08-23-post-studio.md) · [详细设计](../design-docs/2026-08-23-post-studio-feature-design.md)
- 共享选图控件、Agent 候选收缩和草稿清空等未来项继续在各自文档维护。工坊补图当前使用页面内的搜索弹窗。 [工坊页面](../../web/src/views/PostStudio.vue#L584) · [未来需求](../future-requirements.md#fr-8-草稿字段清空能力)
- 两份旧稿保留原名与字节内容。 [历史设计归档索引](../version/design-archives.md)

## 实现边界

- 工坊生成请求和单张下载展开连拍组。草稿保存组引用，ZIP 将组引用解析为封面 ID。先做连拍精选可将选中成员变为独立条目。 [工坊实现](../../web/src/views/PostStudio.vue) · [ZIP 导出](../../backend/internal/defaultService/service/svc_draft.go#L243)
- 更新草稿时，空标题和正文保留原值，提示词和初稿输入允许清空。 [草稿更新](../../backend/internal/defaultService/service/svc_draft.go#L151)
- 润色事实边界由提示词约束。历史评估的实际生成样本支持画面与 EXIF 的使用，拖拽后叙事、四风格差异、润色事实边界和完整导出交互待专项复验。 [历史评估](../eval/reports/2026-08-25-post-studio-ps-series.md)

## 本轮验证

- `agent/` 运行 `.venv/bin/python -m internal.posts.test_post_studio_smoke`，6 项通过。
- `backend/` 运行 `go test ./internal/defaultService/service -run '^TestDraftDO2ResponsePreservesEditingInput$' -count=1`，通过。
- 首稿核心区可定位入口、顺序、事实边界、保存和导出口径。按需区承接契约、代码定位和验证依据。现行规格与设计分别从总规格和系统设计进入。
- 33 个新增本地链接及锚点检查通过。两份归档与移动前逐字节一致。功能验证采用现有离线用例，浏览器与真实模型效果仍按对应场景复验。
