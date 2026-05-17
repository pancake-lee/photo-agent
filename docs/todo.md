# TODO

- [ ] pgo swagger：使用 pgo 的 proto 定义导出 swagger，避免 AI 输出不稳定导致文档不同步
- [ ] 匹配时间线的逻辑要优化，时间线只记录了单个日期，但是照片是连续几天，也匹配到同一个活动中
  - 支持更多日期格式（如 "2024.01.01"、"1月1日" 等）
  - 模糊匹配：照片日期落在时间线区间内即匹配
- [ ] 本地部署embedding模型

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
