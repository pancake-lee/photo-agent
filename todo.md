| 状态 | 排名 | 类别 | 优化点 |
|------|------|------|--------|
| ✔ | 1 | 检索 | VLM 描述结构化提取（P1-核心） |
| ✔ | 2 | 检索 | Chroma 元数据过滤利用（P1-检索） |
| ⬚ | 3 | 质量 | 评估基线建立 |
| ⬚ | 4 | 检索 | GPS 反向地理编码 |
| ⬚ | 5 | 工程 | SQLite WAL 模式 |
| ⬚ | 6 | 工程 | 日志轮转与分级 |

---

## Phase 1 — 让照片「可被多维检索」

> 当前周期。目标：可以按色调/光线/构图/情绪/主体筛选照片，为选题提供素材维度。

### ✅ VLM 描述结构化提取（已完成）

- `agent/scripts/extract_attributes.py`：LLM 提取 objects/colors/scene/lighting/mood/composition → `attributes.json`
- `agent/scripts/index_photos.py`：增量索引时自动读取 `attributes.json`，写入 Chroma metadata（scene/lighting/mood/colors/objects/composition）

### ✅ Chroma 元数据过滤利用 — 自动 where 提取（已完成）

- `agent/chain/photo_rag.py`：
  - 新增 `METADATA_SCHEMA`：定义 scene/lighting/mood 三个维度的允许值
  - 新增 `FILTER_PROMPT`：LLM prompt，将自然语言映射为预定义值
  - 新增 `extract_filters_from_question()`：从用户问题自动提取 Chroma `where` 过滤条件
  - 扩展 `answer_question()`：新增 `auto_filter` 参数
- `agent/chain/photo_agent.py`：`_rag_node` 调用 `extract_filters_from_question()` 提取过滤条件，传给 RAG 检索
- **效果**："蓝调时刻的街拍" → `where={"lighting": "dim", "scene": "street"}` + RAG 语义检索

---

### 🧪 阶段 1 测试指引

> 以下在新环境重新部署后执行。

#### 部署步骤

```bash
# ===== 1. Go 后端 =====
cd /root/code/photo-agent/backend
# 确保 .local/pancake.yaml 中 server.addr、db.sqlite_path、storage.* 路径正确
# 确保照片源目录存在（storage.photo_src）
./server &
# 验证：curl http://localhost:10000/api/v1/health

# ===== 2. VLM 批量预处理（生成 descriptions.json） =====
# 如果已有 descriptions.json 可跳过
cd /root/code/photo-agent/backend
./batch_vlm

# ===== 3. 结构化属性提取 =====
cd /root/code/photo-agent/agent
.venv/bin/python scripts/extract_attributes.py -c ../.local/pancake.yaml
# 输出：data/attributes.json（按 photo_id 索引，每个含 objects/colors/scene/lighting/mood/composition）

# ===== 4. 照片描述入库 Chroma =====
.venv/bin/python scripts/index_photos.py -c ../.local/pancake.yaml
# 如重新索引：加 --clear 全量重建
# 验证：查看输出中 metadata 是否包含 scene/lighting/mood 等字段

# ===== 5. 启动聊天测试 =====
.venv/bin/python chain/photo_agent.py -c ../.local/pancake.yaml
```

#### 测试用例

在聊天中输入以下查询，观察 `[过滤条件: {...}]` 和检索结果：

| 测试查询 | 预期过滤条件 | 说明 |
|----------|-------------|------|
| `"蓝调时刻的街拍"` | `{"lighting": "dim", "scene": "street"}` | 光线+场景联合过滤 |
| `"日落时分的风景照"` | `{"lighting": "golden_hour", "scene": "nature"}` | 光线+场景联合过滤 |
| `"室内温馨的家庭照"` | `{"scene": "indoor", "mood": "warm"}` | 场景+情绪联合过滤 |
| `"找蓝色调、室外、有人物的照片"` | `{"scene": "outdoor"}` | 仅有 scene 能映射到允许值 |
| `"有猫咪的照片吗？"` | （无过滤条件） | 纯语义查询，不受影响 |
| `"夜景照片"` | `{"scene": "night"}` | 单维度过滤 |

**判断标准**：
- ✅ 过滤条件提取正确 → 检索结果范围缩小、相关度提升
- ✅ 纯语义查询不提取过滤条件 → 原有能力不受影响
- ❌ 过滤条件映射错误 → 调整 `FILTER_PROMPT` 中的映射示例
- ❌ 有明确结构化信息但输出空过滤 → 补充 prompt 映射规则

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
