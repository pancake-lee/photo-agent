# 3.4 评估报告

- **报告 ID**：eval-3d4e2v2-20260727
- **日期**：2026-07-27T22:30:00
- **对象**：3.4 主题发现选题相似度过高 — 衍生问题修复后重新评估（B4/B5/B6/R5 修复后）

## 摘要

**总分 5.8/10 ❌ 不通过**（阈值 6.0）。

B4/B5/B6/R5 四个修复整体提升了代码质量（从 4.2→5.8），基础设施改善显著：B6 修复使照片采样池从 300 恢复到 1177，B5 健康检查避免了 token 浪费，R5 消除了 JSON 解析重复代码。但存在一个阻塞性部署问题：.local/pancake.yaml 的 Go 配置段缺少 Embedding.APIKey 字段（且 VLM 回退的 APIKey/Model/BaseURL 在 Go 段也为空），导致 getEmbeddingConfig() 两次回退后 BaseURL 仍为空字符串，三阶段编辑视角主路径仍无法运行。用户实际看到的选题建议与改进前完全一致——5 条「高频未成组」类建议，均为按单一情绪属性值归类的同质化照片组合。代码层面的修复是扎实的，但水龙头拧开之前（配置补齐），用户无法感知到任何改善。score 5.8/10，评估不通过。

## 分维度评分

### 代码质量

#### 正确性 7

得分点：

- B6 PageSize 规范化正确：_fetch_all_photos 现在返回 1177 张照片（之前仅 300 张），Stage 1 采样池完整恢复
- B5 健康检查正确：_check_embedding_health 在 Stage 1 之前调用 Go 后端 /v1/embeddings/health，不可用时跳过整个三阶段流程，节省了 LLM token
- B4 错误处理改善：handleEmbedding 在 BaseURL 为空时返回明确错误信息（不再发必然失败的 HTTP 请求），callVolcengineEmbedding 的错误信息包含火山引擎响应体
- R5 JSON 解析重构正确：_parse_llm_json_response 统一了解析逻辑，两个 wrapper 函数行为与原实现一致

失分点：

- B4 修复不完整：configs/config.yaml 模板新增了 Embedding.APIKey: ''，但 .local/pancake.yaml（实际运行配置）Go 段未添加此字段，且 VLM 回退的 APIKey/Model/BaseURL 在 Go 段也为空，导致 getEmbeddingConfig() 两次回退后 BaseURL 仍为 ''，三阶段主路径仍无法运行
- B4 的 embedding 代理接口（POST /v1/embeddings）因配置缺失无法端到端验证，代码正确性只能通过 code review 判断
- _check_embedding_health 中 except httpx.HTTPStatusError 分支是死代码：httpx.get() 不会主动 raise_for_status()，HTTP 错误码会走到 resp.json() 然后由 except Exception 兜底

#### 健壮性 7

得分点：

- 三阶段主路径前置检查完整：embedding 不可用时不仅跳过 RAG 调用，而是跳过整个三阶段（含 Stage 1 LLM），彻底避免了 token 浪费
- 健康检查失败不会导致 suggest API 崩溃：_check_embedding_health 捕获了 httpx.RequestError 和通用 Exception
- Go 后端 handleEmbedding 在构造 HTTP 请求前检查 BaseURL 为空，前置防御避免了无意义的网络调用
- Go callVolcengineEmbedding 正确 defer resp.Body.Close()，无资源泄漏风险

失分点：

- _check_embedding_health 中 resp.json() 调用前未检查 resp.status_code，若后端返回非 JSON 错误页（如 502 HTML），json() 抛异常后只能由 except Exception 兜底，HTTP 状态码信息丢失
- 健康检查无重试机制（单次 5s 超时），网络抖动可能导致误判为不可用
- Go callVolcengineEmbedding 使用 http.DefaultClient.Do，未设置独立的请求超时 context

#### 可维护性 8

得分点：

- R5 消除了约 45 行重复的 JSON 解析代码，_parse_intuitions_response 和 _parse_legacy_response 从各 40 行缩减为 2 行委托调用
- B5 health endpoint 是标准 RESTful 风格（GET /v1/embeddings/health），返回结构化 JSON，与现有 API 风格一致
- 日志信息完整：pipeline 路由决策、embedding 不可用原因、Stage 失败原因均有明确日志锚点
- 新增代码改动范围克制（4 个文件，+100/-65 行），未引入新的依赖或抽象层

失分点：

- import re 仍在 suggest.py 两处函数体内联（_parse_llm_json_response 和 _parse_proposal_response），未在 R5 重构中提升到模块顶部（已记录为 R6 待规划）
- 新代码（health endpoint、health check 函数、PageSize 规范化）均无对应测试覆盖

#### 简洁性 8

得分点：

- R5 净减少约 50 行重复代码，保留两个语义清晰的 2 行 wrapper
- B4 config 模板改动极简（2 行），Model/BaseURL 复用 Go struct default tag，不重复默认值
- _check_embedding_health 约 15 行，单一职责，易于理解
- handleEmbeddingHealth 约 10 行，逻辑直白

失分点：

- _check_embedding_health 中 except httpx.HTTPStatusError 分支永远不会触发，属于冗余代码（约 2 行）
- callVolcengineEmbedding 混用了两种 HTTP 调用风格：putil.NewHttpRequestJson 构造请求 + http.DefaultClient.Do 执行，putil.HttpDo 的封装被绕过以读取响应体


### 功能效果

#### 准确性 5

得分点：

- B6 修复后 _fetch_all_photos 返回 1177 张照片（运行时验证 confirmed），采样池完整
- Legacy 回退路径仍能产出 5 条格式正确的选题建议，覆盖高频未成组和稀缺优质两个维度
- meta.pipeline 字段正确反映实际执行路径（legacy_three_dimension），便于排查

失分点：

- 运行时仍 100% 走回退路径，实际输出与改进前完全一致：5 条建议中 4 条是高频情绪词归类（静谧 2 条/轻松 1 条/闲适 1 条/雪山 1 条），选题相似度问题未得到改善
- 5 条建议的 photo_ids 均为同一属性值的同组照片，不满足设计文档验收标准中的「时间跨度 > 7 天」
- 「稀缺优质」维度仅返回 2 张照片的选题（庄重），不满足验收标准「至少包含 5 张照片」
- 三阶段编辑视角提案的正确性无法评估：Stage 1/2/3 的代码逻辑虽通过 code review，但运行时从未执行

#### 完整性 6

得分点：

- 设计文档 B4/B5/B6/R5 四个任务全部按方案实现，无遗漏的功能点
- B5 补上了设计方案中「Stage 2 基础设施故障降级策略」的缺口：embedding 不可用时跳过三阶段，而非让 Stage 1 消耗 token 后 Stage 2 逐个失败
- 三阶段工作流代码层面完整：随机采样→RAG 扩展→LLM 提案，每个阶段函数可独立测试
- meta['pipeline'] 字段正确区分 editorial_three_stage 和 legacy_three_dimension 两种执行路径

失分点：

- 设计方案步骤 3.6 验收标准中「照片时间跨度 > 7 天」仅在 Stage 2 日志中输出天数，未在最终 TopicSuggestion 结构体中携带，API 消费者无法获取
- 设计方案中「照片顺序按叙事逻辑排列」因 Stage 3 从未成功执行而无法验证
- 设计方案中提到的「至少包含 5 张照片」验收标准：稀缺优质维度产出 2 张照片的选题，不满足此标准
- B4 修复在代码层面完成，但部署层面（.local/pancake.yaml Go 段添加 Embedding.APIKey）未完成，导致主路径仍不可用


### 用户价值

#### 惊喜度 3

得分点：

- （无）实际输出与修复前完全一致，未带来任何惊喜度的改善

失分点：

- 实际呈现给用户的输出 100% 来自回退路径的「高频未成组」类选题（静谧时光集、蓝调静谧时、雪域秘境、闲适生活录、轻松一刻），本质上仍是按单一情绪/场景属性值归类的同质化照片组合
- 用户看到的选题建议与功能改进前完全一致，没有感受到任何编辑视角或跨上下文连接的惊喜
- Stage 1 的 LLM 编辑直觉能力因 embedding 不可用而被跳过，AI 真正的惊喜发现能力从未对用户展示

#### 可用性 5

得分点：

- 输出格式与之前一致（title/angle/rationale/photo_ids/category），API 消费者无需改动
- meta 中 pipeline 字段告知调用了哪个路径，便于运维排查
- 响应时间较三阶段路径更短（跳过 Stage 1 LLM 调用 + 多次 RAG 检索），用户体验的等待时间约 10-20s

失分点：

- 选题建议中的 photo_ids 是后端 SDK 的内部 ID，前端展示需要额外拼接图片 URL，用户无法直接从 JSON 判断照片内容
- angle 描述泛化（如「捕捉日常生活中的平静瞬间，制作沉浸式放松主题合集」），可套用在任何一组生活照片上，缺乏针对性的可执行建议
- 5 条建议中 2 条围绕「静谧」情绪（静谧时光集、蓝调静谧时），选题角度重叠明显

#### AI 增量 4

得分点：

- Stage 1 的「随机采样 → LLM 编辑直觉」流程是真正的 AI 增量（随机性引入偶然发现，LLM 做编辑视角的模式识别），设计正确但未激活
- Stage 3 的「按叙事逻辑排列照片序列 + 为每张照片赋予叙事角色」也是 LLM 独有能力，设计正确但未激活

失分点：

- 运行时实际走的回退路径中，AI 增量仅停留在 LLM 润色：将统计出的属性值分组（「静谧 45 次」→「静谧时光集」）包装成选题标题，核心发现工作由简单频率统计完成
- 该功能的 AI 增量设计优秀但未生效，属于「有图纸没盖房」的状态——B4/B5 堵住了漏水，但水管还没接上（config 缺失）

## 下一步建议

- .local/pancake.yaml Go 配置段缺少 Embedding.APIKey：当前 Go 段仅声明了 VLM.MaxImageSizeMB，缺少 Embedding.APIKey（且 VLM 段的 APIKey/Model/BaseURL 也未声明），导致 getEmbeddingConfig() 两次回退后 BaseURL 为空，三阶段主路径不可用。需用户手动在 .local/pancake.yaml 的 Go 段添加 Embedding 配置
- _check_embedding_health 的 except httpx.HTTPStatusError 分支是死代码：httpx.get() 不会主动 raise_for_status()，HTTP 错误码会走到 resp.json() 然后由 except Exception 兜底，建议移除或修正
- legacy 回退路径产出「稀缺优质」维度选题仅 2 张照片（庄重寺院印象），不满足设计方案「至少 5 张照片」的验收标准
- legacy 回退路径产出的 5 条建议中 2 条围绕「静谧」情绪（静谧时光集、蓝调静谧时），选题角度重叠——回退路径本身也存在选题相似度问题，只是严重程度低于修复前的三阶段主路径
