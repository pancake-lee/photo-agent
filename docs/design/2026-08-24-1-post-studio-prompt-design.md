### 图文工坊提示词结构 — 设计文档

关联：[图文工坊设计文档](2026-08-23-post-studio-design.md) · backlog 条目 PS6

### 1. 问题现象

用户在图文工坊选了 3 张照片，点击"生成文案"，得到的文案与照片内容无关，明显是泛泛而谈的模板话术。

### 2. 根因分析

#### 2.1 主因：照片描述根本没进提示词

`agent/chain/server.py` 的 `_fetch_photo_descriptions` 按顶层字段读取 Go 后端响应：

```python
data.get("filename", "")      # 实际位置：data["photo"]["filename"]
data.get("description", "")   # 实际位置：data["photo"]["description"]
```

而 Go 的 `GetPhotoDetail`（`backend/internal/defaultService/service/svc_photo.go:228`）返回结构是：

```json
{ "photo": { "filename": "...", "description": "..." }, "image_url": "...", "description_model": "...", "description_time": "..." }
```

描述嵌在 `photo` 对象里。取顶层同名 key 恒为空字符串，于是拼出来的照片上下文是：

```
照片1（）：（无描述）
照片2（）：（无描述）
照片3（）：（无描述）
```

LLM 拿到三个空壳，只能靠用户输入的提示词硬凑，所以文案与照片无关。这一条足以解释全部现象。

#### 2.2 次因：描述字段是 VLM 原始 JSON，不适合直接入提示词

DB 里 `photos.description` 存的是 VLM 返回的原始 JSON 字符串，带 ` ```json ` 围栏，单张 1000+ 字符，包含 `composition.symmetry`、`lighting.contrast`、`background.blur`、`foreground.overlaps_main` 等对文案毫无价值的字段。即使把 2.1 的取值修对，整段塞进提示词也会污染 LLM 的语气，写出"技术参数报告"味道的文字。

#### 2.3 次因：润色模式看不到照片

`/api/post-studio/refine` 只接收 `content` 和 `style`，不接收 `photo_ids`。润色时 LLM 完全没有照片信息，无法补充画面细节，也无法校正草稿里与照片不符的表述。

#### 2.4 次因：输出解析靠首行

现在用 `raw.split("\n", 1)` 把首行当标题。LLM 输出"好的，以下是为您创作的文案："这类寒暄、或用 `**标题**`、`标题：xxx` 格式时，标题和正文都会错位。

#### 2.5 次因：通用要求写在前端输入框

前端 `DEFAULT_PROMPT` 预填了"1. 语言为中文；2. 适合社交媒体发布；3. 文字简洁有趣；4. 适当加入表情符号"。这些是每次生成都一样的平台约束，属于系统提示词的职责。放在用户输入框里有三个问题：占掉用户写真实需求的位置、每次请求重复传输、与后端系统提示词潜在冲突。

### 3. 提示词四层结构

确定的整体结构：

```
L1 系统提示词（后端固定）        角色 + 输入说明 + 平台默认约束 + 防幻觉约束 + 输出契约
L2 风格层（下拉选择/自定义）      文艺 / 纪实 / 轻松 / 攻略 / 用户自定义文本
L3 照片上下文层（后端拼接）       时间跨度汇总 + 照片 1..N 摘要，按用户拖拽顺序
L4 用户要求层（前端输入，可留空）  本次的具体诉求
```

消息组装：L1 + L2 进 `SystemMessage`，L3 + L4 进 `HumanMessage`。这样切分是因为 L1/L2 在同一风格下稳定不变，L3/L4 每次请求都不同，未来若接入 prompt caching 边界天然对齐。

#### 3.1 L1 系统提示词（生成模式）

内容要点：

- 角色定位：摄影帖子文案创作者
- 输入说明：会收到一组按发布顺序排列的照片客观描述，描述来自视觉模型，是事实记录而非文案素材
- 平台默认约束：中文；面向社交媒体；标题 10 到 20 字；正文 150 到 400 字；段落短，2 到 4 句一段；可用少量 emoji 但不堆砌
- 防幻觉约束：
  - 只能基于照片描述和用户要求写作，不得虚构描述中不存在的地点、人物、事件
  - 地名、店名、具体日期若描述中没有，就不要编造，用模糊表述带过
  - 不要用"照片1""图2"这类编号指代，把画面自然融入叙事
  - 照片的排列顺序就是叙事顺序，按这个顺序推进
- 反寒暄约束：不要输出"以下是为您生成的文案"之类的开场白或结尾说明
- 输出契约：严格输出 JSON 对象 `{"title": "...", "content": "..."}`，不要加代码围栏，`content` 内用 `\n` 分段

#### 3.2 L2 风格层

`STYLE_MAP` 从 `generate` 和 `refine` 两处重复定义收敛为模块级单一常量，措辞从"某某风格"改写为可执行的语气指令：

- `literary` 文艺：语言优美细腻，多用意象和通感，重意境与情绪流动，少用感叹号
- `documentary` 纪实：客观克制，重细节和事件本身，按时间或空间线索推进，不抒情
- `casual` 轻松：口语化，像跟朋友分享，可用网络语和 emoji，节奏跳脱
- `guide` 攻略：实用优先，给出可复用的信息，如机位、时段、光线条件、注意事项

用户自定义文本原样透传（保持现有 `STYLE_MAP.get(style, style)` 行为）。

#### 3.3 L3 照片上下文层

从 VLM JSON 做**提取式摘要**，只保留对文案有用的字段。

单张照片渲染格式：

```
### 照片 1
拍摄时间：2026-05-02 白天
主体：年轻女性、竹筏、喀斯特山峰
动作：身体前倾，面带微笑看向镜头
场景：室外，喀斯特地貌河畔
天气：晴
光线：自然光，明亮
色调：暖色
氛围：轻松
画面文字：阳朔竹筏漂流
概述：女子在漓江竹筏上回头微笑
```

字段映射：

- 拍摄时间：日期取 `photo.shot_at`（复用 `suggest.py` 的 `_parse_shot_date`，它已兼容 Unix 时间戳和 ISO 两种格式），时段取 VLM 的 `scene.time_of_day`
- 主体：`subject.main_objects`，逗号连接
- 动作：`subject.attributes["pose/action"]`
- 场景：`scene.environment` + `scene.setting`
- 天气：`scene.weather`
- 光线：`lighting.source` + `lighting.brightness`
- 色调：`color_palette.overall_tone`
- 氛围：`mood`
- 画面文字：`text_and_symbols`，这个字段常能捞到路牌店招，对定位地点有用
- 概述：`overall_summary`

明确丢弃：`image_type`、`subject.count`、`composition.*`、`lighting.contrast`、`background.*`、`foreground.*`、`color_palette.dominant_colors`。这些描述的是摄影技术属性，对文案生成是纯噪音。

其他规则：

- 空值跳过：字段为 `null`、空字符串或字符串 `"null"` 时整行不输出，不写"未知"占位
- 解析降级：`description` 不是合法 JSON 时（老数据或换过 VLM 提示词），用原始文本截断 300 字兜底，而不是丢弃
- 攻略风格补 EXIF：仅当 `style == "guide"` 时追加一行 `参数：<brand> <model> / <lens> / <focal_length> / <aperture> / ISO <iso>`。其他风格不加，避免干扰语气
- 照片较多时精简：超过 20 张时每张只保留 拍摄时间 / 主体 / 概述 三行，控制上下文长度

列表前置汇总：

```
## 照片素材（共 3 张，按发布顺序排列）
拍摄时间跨度：2026-05-02 至 2026-05-04，跨 3 天
```

全部同一天时写成 `拍摄日期：2026-05-02`。游记类文案需要知道这是一天之内还是一次多日行程，这个信息单看每张照片是拼不出来的。

#### 3.4 L4 用户要求层

```
## 本次的额外要求
重点写第二天爬山那段
```

用户输入为空时整段不输出。用二级标题做边界分隔，避免用户输入被当作正文素材吞掉。

#### 3.5 润色模式的提示词结构

同样四层，差异在：

- L1 改为文案编辑角色，强调保留原文结构、段落数和核心意图，只改善表达
- L3 照片上下文照常拼接，前置一句说明：以下照片是这篇草稿的配图，润色时可参考画面细节，但不要新增草稿里没有的事实
- L4 换成草稿正文，用 `## 待润色的草稿` 分隔
- 输出契约与生成模式一致

因此 `PostStudioRefineRequest` 需要新增 `photo_ids: list[str] = []` 字段，前端润色请求带上当前照片列表。

### 4. 输出解析

要求 LLM 返回 JSON，复用 `suggest.py` 已有的 `_parse_llm_json_response` 容错解析（能剥 markdown 围栏、正则截取首个 JSON 对象）。

解析失败时不静默返回空，抛 500 并在 detail 里说明"AI 返回格式异常，请重试"，同时 `logger.warning` 记录原始响应前 300 字。这比返回一段错位的文案让用户困惑要好。

### 5. 无描述照片的处理

不做静默降级，按根因优先原则直接暴露问题：

- 全部照片都没有描述：返回 400，detail 为"所选 N 张照片都还没有 AI 描述，请先在图片管理中生成描述后再来生成文案"
- 部分照片没有描述：正常生成，响应体新增 `warnings` 字段返回 `["N 张照片缺少 AI 描述，未参与文案生成"]`，前端用 `message.warning` 提示

`PostStudioGenerateResponse` 新增 `warnings: list[str] = []`。

### 6. 数据获取改用 SDK

`_fetch_photo_descriptions` 现在用裸 httpx 手拼 URL 再手取 dict key，2.1 的 bug 正是这种写法的必然产物。改为走已有的 SDK：

```python
import utils.backend_sdk as backend_sdk
api = backend_sdk.get_photo_api(cfg.go_backend_url)
detail = api.photo_service_get_photo_detail(pid)
photo = detail.photo   # 结构化对象，字段拼错会直接 AttributeError
```

与 `suggest.py` 的 `_fetch_all_photos` 保持一致。返回顺序严格按传入的 `photo_ids` 顺序，因为这个顺序承载了用户在前端拖拽出的叙事意图。

Go 后端没有按 ID 批量查照片的接口，保持逐张请求。图文工坊场景下照片数在几张到几十张量级，逐张 HTTP 的开销远小于一次 LLM 调用，不值得为此新增后端接口。

### 7. 代码组织

新建 `agent/chain/post_studio.py`，与 `suggest.py`、`cluster.py` 的组织方式对齐。`server.py` 只保留路由、参数校验和调用。

模块内容：

- `STYLE_MAP` 风格常量，生成与润色共用
- `SYSTEM_PROMPT_GENERATE` / `SYSTEM_PROMPT_REFINE` 系统提示词常量
- `_summarize_vlm_description(desc)` VLM JSON 解析为摘要字段字典，含降级分支
- `_render_photo_block(idx, photo, style, brief)` 渲染单张照片段落
- `build_photo_context(photos, style)` 拼接汇总行 + 全部照片段落
- `_parse_post_response(raw)` JSON 解析为 `(title, content)`
- `generate_post(cfg, photos, style, user_prompt)` 生成模式主流程
- `refine_post(cfg, photos, style, content)` 润色模式主流程

日志：`logger.info` 记录照片数、缺描述数、最终提示词字符数；`logger.debug` 打完整提示词。以后排查这类问题不用再靠猜。

### 8. 前端改动

`web/src/views/PostStudio.vue`：

- `DEFAULT_PROMPT` 置空，`promptText` 初始为空字符串
- 提示词模式的 placeholder 改为"补充本次的具体要求，可留空。例如：重点写第二天爬山那段"
- 润色请求体加上 `photo_ids`
- 生成/润色成功后，若响应带 `warnings` 则逐条 `message.warning` 提示

### 9. 关键决策记录

**决策：照片上下文用提取式摘要，不用 VLM 原始 JSON**

- VLM JSON 单张 1000+ 字符，其中构图、对比度、景深、前景遮挡等字段对文案生成是噪音，会把 LLM 带向技术性描述
- 摘要后单张约 80 到 120 字符，信息密度显著提升
- 代价是多一层解析代码，且 VLM 提示词若改字段名需要同步维护，通过降级分支兜底

**决策：不采用多模态直接传图**

- 主 LLM（deepseek）是纯文本模型，多模态要改用 vlm 配置的 doubao 视觉模型，与现有 llm 配置分叉
- 需要新增图片编码链路，成本明显更高
- VLM 描述已经是项目的既有资产，先把它用好再评估是否需要视觉直连

**决策：输出用 JSON 契约而非首行标题**

- 首行解析对 LLM 输出格式漂移零容忍，寒暄一句就全错位
- 项目已有 `_parse_llm_json_response` 容错解析可复用，边际成本接近零

**决策：通用要求下沉到系统提示词**

- 中文、社交媒体、简洁、emoji 这类约束每次生成都相同，属于系统职责
- 输入框腾出来给用户写真正专属于本次的诉求，提示词的信噪比更高
- 代价是用户不能再直接改动这些通用约束，若后续有需求可在设置页开放系统提示词编辑

**决策：无描述照片直接报错而非静默生成**

- 静默生成会产出与照片无关的文案，用户以为是 AI 能力不行，实际是数据没准备好
- 明确报错并指引到图片管理生成描述，把问题暴露在正确的位置

### 10. 验收标准

- [ ] 选 3 张有描述的照片生成文案，正文能准确提到照片里的具体主体和场景
- [ ] 调整照片拖拽顺序后重新生成，叙事推进顺序随之改变
- [ ] 切换风格（文艺/纪实/轻松/攻略），文案语气有可辨识的差异
- [ ] 攻略风格的文案包含相机参数相关的实用信息
- [ ] 用户要求留空可正常生成；填写"重点写某某"时文案确实有所侧重
- [ ] 润色模式能参考照片内容，且不新增草稿里没有的事实
- [x] 所选照片全部无描述时返回明确错误提示，而非生成无关文案
- [x] 部分照片无描述时正常生成并弹出警告提示
- [x] LLM 返回带 markdown 围栏或寒暄时，标题和正文仍能正确拆分
- [x] 服务端日志能看到照片数、缺描述数和提示词长度
