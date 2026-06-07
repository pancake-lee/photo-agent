| 状态 | 排名 | 类别 | 优化点 |
|------|------|------|--------|
| ⬚ | 1 | 检索 | VLM 描述结构化提取（P1-核心） |
| ⬚ | 2 | 检索 | Chroma 元数据过滤利用（P1-检索） |
| ⬚ | 3 | 质量 | 评估基线建立 |
| ⬚ | 4 | 检索 | GPS 反向地理编码 |
| ⬚ | 5 | 工程 | SQLite WAL 模式 |
| ⬚ | 6 | 工程 | 日志轮转与分级 |
| ✔ | - | 检索 | Chroma 元数据过滤利用（已有基础） |

---

## Phase 1 — 让照片「可被多维检索」

> 当前周期。目标：可以按色调/光线/构图/情绪/主体筛选照片，为选题提供素材维度。

### VLM 描述结构化提取

- description 是纯文本，Tags 字段空置，无法按维度精确检索
- 新建 `extract_attributes.py`：LLM 提取 objects/colors/scene/lighting/mood/composition
- 属性存入 `attributes.json`，`index_photos.py` 同步写入 Chroma metadata（配合 where 过滤）
- Go 新增 `PUT /api/v1/photos/:id/tags` API，支持将结构化标签回写 SQLite
- **期望**：用户可用多维度精确查询，如"找蓝色调、室外、有人物的照片"
- 工作量约 2-3 天，**提升**：检索精度从文本模糊匹配到结构化匹配

### Chroma 元数据过滤利用

- `photo_rag.py` 已有 `where` 参数支持
- 补全 `index_photos.py` 写入的 metadata 字段（shot_at, colors, lighting, mood, subject）
- `answer_question()` 支持从用户查询中自动提取过滤条件
- 示例："蓝调时刻的街拍" → `where={"lighting": "blue_hour"}` + RAG 检索
- **提升**：从纯语义模糊匹配升级为语义+结构化联合过滤

### 评估基线建立

- `evaluation.py` 的 `DEFAULT_EVAL_QUERIES` 中 `relevant_photos` 字段为空，需人工标注
- 扩充到 20 条黄金查询，覆盖：物体/场景/光线/情绪/组合查询
- 运行评估记录基线 P@10 / R@10 / MRR
- 对比两种分块策略（none vs fixed_size），选优固定
- **提升**：后续每个 Phase 有量化标准验证效果

### GPS 反向地理编码

- EXIF 中已有经纬度，但未转换为人类可读地名
- 调用反向地理编码 API 转为省/市/区/景点名，存入 `location` 字段
- 支持"我在北京拍的照片"等查询
- **提升**：地名成为直观的检索维度，选题时可按地点筛选

## 工程小改进

### SQLite WAL 模式

- `service.InitDB()` 中执行 `PRAGMA journal_mode=WAL;`
- **提升**：WAL 模式下读写不互锁，AutoSync 并发导入效率提升

### 日志轮转与分级

- 接入 pgo 日志体系，支持按大小/时间轮转
- 增加日志级别配置
- **提升**：长期运行不占用过多磁盘空间

---

## 遗留事项

- [ ] `agent/embedding/embedder.py:63`：Embedding URL 写死为 `{base_url}/v1/embeddings`，应支持配置灵活指定
- [ ] `backend/internal/api/routes.go:41-45`：import API 和 batch_vlm 逻辑重复，需合并统一
- [ ] 匹配时间线的逻辑优化：支持更多日期格式，模糊匹配连续几天到同一活动

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
