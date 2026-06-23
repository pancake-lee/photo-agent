# ChromaDB 向量库 Metadata 存储设计

## 背景

ChromaDB 向量库存储照片描述文本的 Embedding 向量，用于 RAG 语义检索。在最初实现中，每个 chunk 的 metadata 冗余存储了大量 Go 后端 SQLite 已有的结构化数据。

## 两种架构路线

### 路线 A：ChromaDB 冗余存储 metadata

ChromaDB 的 `where` 过滤条件可直接在向量检索时过滤，一次查询完成"语义相似 + 结构化条件"。

```
用户提问 → LLM 意图识别
  ├─ 向量检索（ChromaDB where 过滤） → 直接返回结果
  └─ Text-to-SQL（结构化查询）        → 直接返回结果
两条路线独立、并行
```

**优点**：单次 ChromaDB 查询即可同时完成语义 + 结构化过滤，减少多工具编排

**缺点**：

- ChromaDB metadata 与 Go SQLite 数据冗余，需要复杂的同步机制确保一致性
- 冗余字段（file_path、shot_at、scene、lighting、mood 等）使每个 chunk 的 metadata 体积膨胀
- `get_embedded_photo_ids()` 需要全量加载 metadata 进行去重——数据量越大越慢
- 是 [批量 Embed 按钮点击延迟问题](../TASK.md) 的直接原因之一

### 路线 B：ChromaDB 只存向量 + 最小标识（✅ 选择）

ChromaDB 仅存储 photo_id 和 chunk_index，结构化过滤完全交给 Text-to-SQL。

```
用户提问 → LLM 意图识别
  ├─ 向量检索（ChromaDB 纯相似度）  → 返回 photo_id 列表
  ├─ Text-to-SQL（结构化查询）       → 返回 photo_id 列表
  └─ 结果合并/交集                   → 用 photo_id 从 Go 取完整数据
```

**优点**：

- 单一数据源，无冗余，无同步问题
- ChromaDB metadata 极小，`get_embedded_photo_ids()` 性能显著提升
- 修改结构化查询逻辑只需改 Text-to-SQL prompt，不涉及 ChromaDB schema 变更
- 哪里有问题就改哪里，优化效果直接挂钩，易于维护

**缺点**：

- 需要 LLM 编排多次工具调用（语义 + 结构化），增加一次 LLM 推理

## 决策

选择 **路线 B**。

理由：

1. 项目已有 Text-to-SQL 工具覆盖结构化查询，ChromaDB where 过滤是冗余能力
2. 路线 A 的 metadata 同步机制会随数据结构变化持续增加维护负担
3. 路线 B 架构边界清晰：向量库只管语义，SQL 只管结构化，Go 是唯一数据源
4. 路线 B 直接解决了当前 10-20 秒的批量 Embed 启动延迟问题

## 实现要点

### ChromaDB metadata 最小化

每个 chunk 只保留：

| 字段 | 用途 |
|------|------|
| `photo_id` | 关联 Go 照片、去重、清理孤立数据 |
| `chunk_index` | chunk 排序 |

移除的字段（均由 Go 后端 SQLite 提供）：

- `file_path` — Go 有
- `shot_at` — Go 有
- `objects`, `colors`, `scene`, `lighting`, `mood`, `composition` — Go 有
- `embed_model` — 配置文件已知
- `embedded_at` — 非关键信息

### RAG 检索链路

- `photo_rag.py` 移除 `where` 过滤参数和 `extract_filters_from_question()` LLM 提取逻辑
- `answer_question()` 简化为纯向量检索
- 若需结构化过滤，由 LLM 路由到 Text-to-SQL 路径，再与向量检索结果合并

### 不受影响的操作

- 按 `photo_id` 删除旧 Chroma 数据 → 保留（photo_id 是必须字段）
- `cleanup_orphans()` 清理孤立文档 → 保留
- `get_embedded_photo_ids()` 获取已嵌入 ID 集合 → 保留且更快

## 变更记录

- **2026-06-23**：决策采用路线 B，移除 ChromaDB 冗余 metadata
