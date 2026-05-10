# Excalidraw 维护经验（项目补充）

> 本文件记录 `diagram-excalidraw` skill 未覆盖、但在本项目实际踩坑的 Excalidraw JSON 维护经验。
> Skill 已覆盖的硬约束（无菱形、标签绑定、箭头格式、边缘定位等）不再重复，见 `.claude/skills/diagram-excalidraw/`。

---

## 1. index 用来管理层叠关系，注意取值范围

**问题**：新增元素使用 `a0`/`a1`/`aa`/`ab` 混合风格，或截断 ID 前 4 字母作为 index，导致文件打不开。

**原因**：Excalidraw 按 `index` 字段排序渲染元素，不同 index 值决定层叠顺序。index 不必每个元素都不一致，多个元素可以是同一个值。但如果使用了 Excalidraw 不支持的 index 格式，文件可能打不开。

**已知安全的 index 格式**：
- 两个字母组合：第一个字母为 `0-9` 或 `a`，第二个字母为 `0-9` 或 `a-y`
- 三个字母及以上也安全（如 `ay0`）
- 未穷举所有可能，可能有例外

**正确做法**：
- 先查看现有文件中 index 的编码风格（如 `a0-a9` → `aa-ay`）
- 新增元素的 index 可以使用已有index，如果有层叠关系，再考虑新增，保持同一套编码规则
- 文件打不开时，优先怀疑 index 是否使用了新值或非常规格式，可以叫用户协助验证

---

## 2. shape-text 双向绑定必须完整

**问题**：矩形 `boundElements` 中引用了 text，但 text 的 `containerId` 为 null，文件打不开。

**原因**：Excalidraw 要求 shape ↔ text 双向引用。单向引用会导致渲染器在计算文本位置时崩溃。

**正确做法**：
- 每个带标签的矩形必须有：`boundElements: [{type: "text", id: "xxx-text"}]`
- 对应的文本元素必须有：`containerId: "xxx"`
- 修改后用脚本验证所有 shape-text 对的双向一致性

---

## 3. boundElements 引用必须存在

**问题**：矩形 `boundElements` 中引用了箭头的 ID，但该箭头在修改过程中被删除了，文件打不开。

**原因**：残留的悬引用（dangling reference）导致 Excalidraw 遍历时找不到目标元素。

**正确做法**：
- 删除元素时，同步扫描所有其他元素的 `boundElements`，清理对该 ID 的引用
- 新增元素时，确保 `boundElements` 中引用的所有 ID 都在当前 elements 列表中
- 修改后用脚本验证所有 boundElements / startBinding / endBinding / containerId 的引用有效性

---

## 4. 坐标调整要保持几何一致性

**问题**：移动了某个矩形的位置，但没有同步更新连接它的箭头坐标，导致箭头悬浮或指向空白。

**原因**：Excalidraw 的箭头 `points` 是相对坐标，但 `x`/`y` 是起点绝对坐标。startBinding/endBinding 只负责视觉吸附，实际坐标不匹配时渲染会错位。

**正确做法**：
- 移动矩形时，同步重新计算所有连接箭头的 `x`/`y` 和 `points`
- 箭头的 `x` = startBinding 元素边缘的 x 坐标
- 箭头的 `y` = startBinding 元素边缘的 y 坐标
- 优先让箭头绑定到形状边缘（fixedPoint），而非硬编码坐标

---

## 5. 验证脚本（修改后必跑）

```python
import json

with open("docs/xxx.excalidraw") as f:
    d = json.load(f)

ids = {e["id"] for e in d["elements"]}

# 1. 检查所有引用
for e in d["elements"]:
    for ref in e.get("boundElements", []):
        assert ref["id"] in ids, f"悬引用: {e['id']} -> {ref['id']}"
    for key in ["startBinding", "endBinding"]:
        b = e.get(key)
        if b:
            assert b["elementId"] in ids, f"悬绑定: {e['id']} -> {b['elementId']}"
    if e.get("containerId"):
        assert e["containerId"] in ids, f"悬容器: {e['id']} -> {e['containerId']}"

# 2. 检查 shape-text 双向绑定
for e in d["elements"]:
    if e["type"] in ("rectangle", "ellipse"):
        for ref in e.get("boundElements", []):
            if ref.get("type") == "text":
                text = next(x for x in d["elements"] if x["id"] == ref["id"])
                assert text.get("containerId") == e["id"], f"绑定缺失: {e['id']}"

# 3. 检查 index 格式安全（可选，未穷举）
# index 不必唯一，相同值用于管理层叠关系

print("验证通过")
```

---

## 6. 与 Obsidian Excalidraw 插件的兼容性

- 本项目使用 Obsidian Excalidraw 插件管理 `.excalidraw` 文件
- 插件版本差异可能导致兼容性问题，修改后必须在 Obsidian 中实际打开验证
- 不要依赖纯 JSON 验证通过就认为文件可用
