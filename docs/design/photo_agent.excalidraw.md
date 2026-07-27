# photo_agent.excalidraw — 架构图维护说明

## 概述

> `docs/archive/photo_agent.excalidraw` 是AI初步绘制的图，已归档，不维护

`photo_agent.excalidraw` 是项目全貌架构兼流程图，展示从用户浏览器到 AI 服务的完整链路。可在 Excalidraw 桌面版 / excalidraw.com / VS Code 插件中打开编辑。

文件路径：`docs/photo_agent.excalidraw`

## MCP CRUD 操作指南

### 配置

已通过 `claude mcp add` 配置到项目级别（`/root/.claude.json`），命令为：

```sh
node /root/.claude/mcp-servers/node_modules/@cmd8/excalidraw-mcp/dist/index.js --diagram /root/code/photo-agent/docs/photo_agent.excalidraw
```

### 可用工具

1. **getFullDiagramState** — 获取整个图表的 Markdown 表示（只读，不修改文件）
2. **createNode** — 创建新节点
   - `label`: 标签文本（支持 `\n` 换行）
   - `shape`: `rectangle` | `ellipse` | `diamond`（默认 rectangle）
   - `color`: 13 种预设色（见上表）
   - `x`, `y`: 坐标（不提供时自动排在最后节点下方）
   - `width`, `height`: 尺寸（不提供时自动适配文本）
3. **createEdge** — 创建连线
   - `from`: 源节点 ID 或**精确标签文本**
   - `to`: 目标节点 ID 或精确标签文本
   - `label`: 可选连线标签
   - `style`: `solid` | `dashed`（默认 solid）
4. **deleteElement** — 删除节点或连线（通过 ID 或精确标签文本）

### 新增节点示例

在 MCP 会话中（新会话启动时工具会自动加载）：

```txt
创建节点: createNode { label: "新功能模块\n详细描述", color: "light-green", x: 100, y: 500 }
创建连线: createEdge { from: "LangGraph 查询路由", to: "新功能模块\n详细描述", label: "调用" }
```

### 修改现有节点

该 MCP 不支持直接"修改"节点。操作方式：

1. `deleteElement` 删除旧节点
2. `createNode` 创建新节点（使用相同的 x/y 坐标）
3. 如有连线指向旧节点，需重建连线

### 注意事项

- `createEdge` 的 `from`/`to` 按**精确标签文本**匹配（大小写不敏感，但多行文本需完全匹配含 `\n`）
- 推荐使用节点 ID 进行连线（通过 `getFullDiagramState` 无法获取 ID，需直接读取 JSON 文件查找）
- **不要并发修改**：MCP 工具的底层实现在读写文件时无锁，并发调用会导致数据丢失

## MCP 补丁

npm 包 `@cmd8/excalidraw-mcp@1.2.0` 的 dist 文件存在 ESM 导入扩展名缺失问题，需在首次安装后执行补丁：

```bash
bash /root/.claude/mcp-servers/patch-excalidraw-mcp.sh
```

该补丁修复：

1. 相对导入缺少 `.js` 扩展名 → 自动添加
2. TypeScript `@/` 路径别名未解析 → 转为相对路径

## 直接编辑 JSON

如需批量修改，可直接编辑 `.excalidraw` 文件（它是标准 JSON）：

```python
import json
with open('docs/photo_agent.excalidraw') as f:
    data = json.load(f)
# data['elements'] 是所有元素的列表
# 每个元素有 type, id, x, y, width, height, backgroundColor 等属性
```

注意：修改后务必验证 JSON 有效性。
