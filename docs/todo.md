# TODO

> 按优先级分层排列，同层内按建议实施顺序排列。
> 详细方案论证见 [docs/task_3.md](task_3.md) / [docs/upgrade.md](upgrade.md) / [docs/expansion_directions.md](expansion_directions.md)。

---

## 近期重点（Top 3）

基于 RICE 评分（Reach × Impact × Confidence / Effort）+ 帕累托法则（抓关键 20%）筛选：

1. **Chroma 元数据过滤利用** — 0.5 天，低投入高回报，直接提升检索精度，为混合检索铺路
2. **LangGraph 路由融合 Function Calling** — 1-2 天，补齐当前 Agent 最大能力短板（无法调用 Go API）
3. **数据一致性保障（Chroma / Dify / SQLite）** — 2-3 天，死数据会随时间累积成技术债，越早治理成本越低

> 方法论依据：RICE 量化打分后，优先选「Confidence 高 + Effort 低」的项快速验证；同时用帕累托法则识别「投入小、覆盖核心场景广」的优化点，避免平均用力。

---

## 高优先级

- [ ] Chroma 元数据过滤利用
  - `photo_rag.py` 的 `_retrieve()` 增加 `where` 参数透传
  - 支持按 timeline / brand 等元数据过滤后再做向量检索
  - 为混合检索铺路，工作量约 0.5 天

- [ ] LangGraph 路由融合 Function Calling
  - 路由从 sql/rag 二分类扩展为三分类（sql / rag / tool）
  - `tool` 分支使用 `llm.bind_tools()` 让 LLM 自主调用 Go API
  - 补齐"列出时间线""按标签查照片"等查询的短板，工作量约 1-2 天

- [ ] 数据一致性保障（Chroma / Dify / SQLite）
  - description 更新后 Chroma 不会自动同步（需手动重跑 `index_photos.py`）
  - 照片删除后 Chroma 和 Dify 中残留死数据
  - 建立 `sync_state` 表或定期校验脚本，工作量约 2-3 天

- [ ] 照片去重检测
  - `batch_vlm` 会重复处理相同文件，浪费存储和 VLM 费用
  - 文件级：MD5 / 感知哈希（pHash / dHash）检测完全相同的文件
  - 内容级：利用已有 Embedding 向量计算余弦相似度
  - 在 `batch_vlm` 和 `AutoSync` 阶段自动跳过重复，工作量约 1-2 天

- [ ] VLM 描述结构化提取
  - description 是纯文本，Tags 字段空置，无法按维度精确检索
  - 使用 LLM 后处理提取：objects / colors / scene / lighting / mood / composition
  - 存入 SQLite `photo_attributes` 表，同时写入 Chroma metadata
  - 工作量约 2-3 天

- [ ] RAG 重排序（Rerank）
  - 向量检索后直接取 Top-K，没有二次精排
  - 引入轻量级 Cross-Encoder（如 `BAAI/bge-reranker-base`）本地部署
  - 流程：向量召回 Top-20 → Rerank 精排 → Top-5 送入 LLM
  - 工作量约 1-2 天

---

## 中优先级

- [ ] 真正的流式输出
  - `photo_rag.py` 设置了 `streaming=True` 但 `answer_question()` 直接 `invoke()`
  - CLI 聊天循环也没有流式打印
  - 接入 `chain.astream()` + PID 打印机实现打字机效果
  - 工作量约 0.5-1 天

- [ ] 自动降级策略
  - SQL 查询失败 → 自动降级到 RAG
  - RAG 检索结果为空 → 自动降级到 SQL 或直接回答"未找到"
  - 主模型调用失败 → 自动降级到 fallback 模型
  - 工作量约 0.5-1 天

- [ ] 配置热加载
  - 修改配置后必须重启 server 才能生效
  - 使用 `viper.WatchConfig()` 监听配置文件变化
  - VLM prompt / 并发数 / 日志级别等支持动态生效
  - 工作量约 0.5-1 天

- [ ] API 鉴权
  - 所有 API 和图片文件完全开放，局域网部署有安全隐患
  - 增加 Bearer Token 中间件，配置文件增加 `server.api_key`
  - Dify 工具配置同步配置 API Key
  - 工作量约 1 天

- [ ] GPS 反向地理编码
  - EXIF 中已有经纬度，但未转换为人类可读地名
  - 调用反向地理编码 API 转为省/市/区/景点名，存入 `location` 字段
  - 支持"我在北京拍的照片""故宫的照片"等查询
  - 工作量约 1-2 天

- [ ] 数据备份与恢复
  - SQLite / Chroma / descriptions.json 无备份机制
  - 提供 `backup` / `restore` 子命令，打包全部数据
  - 支持定时自动备份（保留最近 N 份）
  - 工作量约 1 天

- [ ] 查询结果导出
  - Agent 返回的结果无法保存
  - 支持导出为 Markdown 相册 / PDF / 幻灯片
  - CLI 新增 `--export {format}` 参数
  - 工作量约 1-2 天

- [ ] 模型 A/B 测试框架
  - 可切换模型但无系统化效果对比
  - 扩展 `evaluation.py`，多模型运行同一评估集
  - 输出准确率 / 延迟 / 费用对比报告
  - 工作量约 1-2 天

- [ ] 负样本学习优化 Embedding
  - 评估集只有正样本，无法针对性优化
  - 增加 `irrelevant_photos` 标注，使用对比学习微调 Embedding
  - 工作量约 2-3 天（需先完成负样本标注）

---

## 低优先级

- [ ] 日志轮转与分级
  - 接入 pgo 日志体系，支持按大小/时间轮转
  - 增加日志级别配置
  - 工作量约 0.5 天

- [ ] 多语言支持
  - 配置 `vlm.language` 控制描述语言
  - 多语言 Embedding 模型
  - 工作量约 1-2 天

- [ ] 语音输入查询
  - CLI 增加 `--voice` 模式，Whisper 语音转文本
  - 工作量约 1 天

- [ ] 摄影参数智能推荐
  - 基于历史 EXIF 数据给出拍摄参数建议
  - 如"拍星空多用 ISO 3200 + 20s + f/2.8"
  - 工作量约 2-3 天

- [ ] 用户偏好学习（长期记忆）
  - 记录查询和点击行为，构建偏好画像（题材 / 色调 / 焦段）
  - 回答时融入偏好推荐
  - 工作量约 3-5 天

---

## 已有详细规划（见 task_3.md / upgrade.md）

以下方向已有完整方案，此处不展开：

- 混合检索（task_3 Phase 1.1）
- 多轮对话上下文感知（task_3 Phase 1.2）
- RAG 评估集扩充（task_3 Phase 1.3）
- 相似照片推荐（task_3 Phase 2.1）
- 智能相册自动生成（task_3 Phase 2.2）
- 摄影报告生成（task_3 Phase 2.3）
- 时间线关联分析（task_3 Phase 2.4）
- SQLite WAL 模式（task_3 Phase 3.1 / upgrade 1）
- 异步后台同步（task_3 Phase 3.2 / upgrade 4.1）
- 内存缓存层（task_3 Phase 3.3 / upgrade 4.2）
- 可观测性接入（task_3 Phase 3.4 / upgrade 2）
- 优雅关闭与限流（task_3 Phase 3.5 / upgrade 4.4）
- 本地 Embedding 模型（task_3 Phase 4.1 / upgrade 4.5）
- 图片格式自适应（task_3 Phase 4.2 / upgrade 4.2）
- proto-first 迁移评估（upgrade 3）

---

## 遗留事项

- [ ] pgo swagger：使用 pgo 的 proto 定义导出 swagger，避免 AI 输出不稳定导致文档不同步
- [ ] 匹配时间线的逻辑优化：支持更多日期格式（"2024.01.01"、"1月1日" 等），模糊匹配连续几天到同一活动
- [ ] 本地部署 embedding 模型

---

## 代码 TODO

- [ ] `agent/embedding/embedder.py:63`：Embedding URL 写死为 `{base_url}/v1/embeddings`，应支持配置灵活指定
- [ ] `backend/internal/api/routes.go:41-45`：import API 和 batch_vlm 逻辑重复，需合并统一

---

## 黄金测试集

评估脚本 `evaluation.py` 已就绪，但 `DEFAULT_EVAL_QUERIES` 中的 `relevant_photos` 字段是空的——需要你人工标注。

**操作步骤：**

1. 先确保 Go 后端和 Chroma 有数据，启动后进入 agent 目录
2. 运行一次空评估看看当前检索结果：

   ```bash
   python chain/photo_agent.py -c ../.local/my-config.yaml --eval
   ```

3. 对于每条查询，在返回的 `retrieved_ids` 中挑出你认为是"正确结果"的 photo_id，填入 `relevant_photos`
4. 可以扩充到 20~50 条查询，覆盖不同语义场景（物体/颜色/场景/情感/时间）
5. 填充后再次运行 `--eval`，得到基线指标（Precision@K / Recall@K / MRR）
6. 切换分块策略（修改配置中 `embedding.chunk_strategy` / `chunk_size` / `chunk_overlap`），重新索引后对比评估结果

**模板格式：**

```python
{
    "question": "有猫咪的照片吗？",
    "relevant_photos": ["photo_001", "photo_042", "photo_108"],  # ← 你手动标注
},
```
