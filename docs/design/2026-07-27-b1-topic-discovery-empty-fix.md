# B1 主题发现返回空结果 — 修复方案

> 日期：2026-07-27
> 关联：[[backlog#B1]] [[backlog#2.2]]

## 问题

调用 `POST /api/suggest/run`（或 CLI `--suggest`）返回"未发现候选选题方向"，三个分析维度（高频未成组、时间线规律、稀缺优质）均产出 0 个候选。

## 根因分析

### 数据现状

```
SQLite photos 表（1177 条）:
  description 有值: 1177 条 (100%)
  objects 有值:   0 条
  colors 有值:    0 条
  scene 有值:     0 条
  lighting 有值:  0 条
  mood 有值:      0 条

descriptions.json（1179 条）:
  VLM JSON 块完整，包含 subject/main_objects/color_palette/scene/lighting/mood/composition
```

### 因果链

1. VLM 批量处理生成了 descriptions.json，每条包含 `json` 结构化代码块
2. AutoSync 首次运行时，`parseVlmAttrs` 尚未实现（或未被调用），照片导入时仅写入 `description` 文本，**未解析结构化属性**
3. 后续 commit `1918d71` 在 `syncImportPhoto` 和 `syncUpdatePhoto` 中增加了 `parseVlmAttrs` 调用
4. **但 `syncUpdatePhoto` 的更新条件**（`svc_auto_sync.go:277-279`）是 description 或 timeline 发生变化。由于 description 已在首次同步时写入，再次运行 AutoSync 时 description 未变 → 直接返回 false，**永远不会触发 `parseVlmAttrs` 对已有照片的回填**
5. suggest.py 的三个分析函数完全依赖 objects/colors/scene/lighting/mood 五个字段，全空 → 所有维度产出 0 候选 → 最终返回"未发现候选选题方向"

### 为什么 task 2.2 的修复不够

task 2.2（聚类标题生成效果差）的方案关注：
- Go 后端新增 `parseVlmAttrs`，在导入/更新时调用 ✅ 已完成
- cluster.py 模板纳入 description 文本 ✅ 已完成

但 2.2 的方案没有解决**已有照片的回填问题**：`parseVlmAttrs` 只在新导入或 description 变化时触发，对于 1177 张已入库、description 未变的照片，结构化属性始终为空。

B1 和 2.2 共享同一个上游根因（属性字段为空），但 B1 的 suggest.py 没有类似 cluster.py 的 fallback（cluster.py 可以读 description 文本，suggest.py 只能读结构化属性）。

## 方案

### 改动 1：Go — `syncUpdatePhoto` 增加属性回填逻辑

**文件**：`backend/internal/defaultService/service/svc_auto_sync.go`

**现状**（line 277-279）：
```go
if existing.Description == newDesc &&
    existing.Timeline == newTimeline {
    return false
}
```

**改为**：增加一个判断分支，当 description 和 timeline 都未变，但结构化属性全空且 description 非空时，进入"仅回填属性"路径。

```go
descChanged := existing.Description != newDesc
timelineChanged := existing.Timeline != newTimeline
needAttrBackfill := newDesc != "" &&
    existing.Objects == "" && existing.Colors == "" &&
    existing.Scene == "" && existing.Lighting == "" &&
    existing.Mood == ""

if !descChanged && !timelineChanged && !needAttrBackfill {
    return false
}

updates := map[string]any{}
if descChanged {
    updates["description"] = newDesc
}
if timelineChanged {
    updates["timeline"] = newTimeline
}
// 解析结构化属性：description 有变化，或需要回填
if (descChanged || needAttrBackfill) && newDesc != "" {
    objects, colors, scene, lighting, mood := parseVlmAttrs(newDesc)
    updates["objects"] = objects
    updates["colors"] = colors
    updates["scene"] = scene
    updates["lighting"] = lighting
    updates["mood"] = mood
}
```

**关键点**：
- 回填条件用 AND 判断 5 个字段全空 + description 非空，避免无意义更新
- description 和 timeline 未变时不重复写入，只更新属性字段
- 如果某张照片的 VLM JSON 解析失败（`parseVlmAttrs` 返回空），下次 AutoSync 仍会再次尝试（属性仍为空 → `needAttrBackfill` 仍为 true）

### 改动 2：Go — 补充 `composition` 字段提取

**文件**：`backend/internal/defaultService/service/svc_auto_sync.go`

**现状**：`vlmJSON` 结构体缺少 `Composition` 字段，`parseVlmAttrs` 返回值也不含 composition。

VLM JSON 中实际包含：
```json
"composition": {
    "focus": "偏右",
    "depth": "浅景深",
    "symmetry": "非对称"
}
```

**改动**：
- `vlmJSON` 结构体新增 `Composition` 字段
- `parseVlmAttrs` 返回值新增 `composition`（拼接 focus/depth/symmetry）
- 所有调用处（`syncImportPhoto`、`syncUpdatePhoto`、`applyDescriptionToPhoto`）写入 composition

> 注意：suggest.py 不使用 composition，此改动不影响 B1 的直接修复，但补齐了数据完整性，且对后续可能用到 composition 的功能有益。

### 改动 3：Python — suggest.py 增加诊断日志

**文件**：`agent/chain/suggest.py`

在 `run_suggest()` 中 `_count_attribute_frequencies` 调用后，增加频率统计摘要日志：

```python
freq = _count_attribute_frequencies(photos)
# 新增诊断日志
for dim, values in freq.items():
    if values:
        top3 = sorted(values.items(), key=lambda x: -x[1])[:3]
        logger.info("属性维度 [%s]: %d 个不同值, top3=%s", dim, len(values), top3)
    else:
        logger.warning("属性维度 [%s]: 无数据", dim)
```

同时在三个分析函数各自返回后，如果返回空列表，加一条 warning 日志说明原因（如"高频未成组：频率表中无值 ≥ min_frequency"）。

> 诊断日志不改变行为，但能让后续排查时快速定位是"属性为空"还是"阈值不匹配"。

### 不改动的部分

- **suggest.py 阈值**：`min_frequency=3`、`max_frequency=5` 等参数在当前 300 张精选照片规模下是否为最优，需待属性回填后用真实数据验证。本次不调整，先让功能跑通。
- **API / Web 前端**：无需改动。回填后 suggest API 自然返回结果。
- **cluster.py**：task 2.2 已处理，本次不改。

## 验收

- [ ] AutoSync 后，SQLite 中 objects/colors/scene/lighting/mood 字段有值（≥ 90% 的照片）
- [ ] composition 字段有值（≥ 90% 的照片）
- [ ] suggest.py 日志中三个维度不再全空
- [ ] `POST /api/suggest/run` 返回 3-5 个选题建议，而非"未发现候选选题方向"
- [ ] CLI `--suggest` 输出正常的选题建议列表
- [ ] 已有照片无需重新 VLM（仅重新 AutoSync 即可）

## 实现步骤

1. 修改 `svc_auto_sync.go`：`syncUpdatePhoto` 回填逻辑 + `vlmJSON` 扩展 + `parseVlmAttrs` 扩展
2. 修改 `svc_vlm.go`：`applyDescriptionToPhoto` 适配 `parseVlmAttrs` 新返回值（composition）
3. 修改 `suggest.py`：增加诊断日志
4. 编译 Go 后端，重启服务，触发 AutoSync
5. 验证 DB 数据，运行 suggest 验收
