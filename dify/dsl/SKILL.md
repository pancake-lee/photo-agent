---
name: dify-dsl-dev
description: Dify DSL 开发踩坑补充。与开源 skill `dify-dsl-generator` 配合使用，覆盖其未涉及的 Agent 模式陷阱、自定义 API 工具 UUID 问题、数据库事务错误等实战经验。
---

# Dify DSL 开发踩坑补充

> 本文档是开源 skill `dify-dsl-generator` 的补充，仅记录该 skill 未覆盖的、实际踩过的坑。DSL 基础结构、节点类型、edges 连接等通用知识请参考该 skill。

---

## 核心原则

- **AI 可自主处理**：提示词（`pre_prompt`）、模型参数（`completion_params`）、图标、名称等纯文本/数值字段的修改
- **必须人工介入**：自定义 API 工具的首次创建、工具 UUID 的获取、模型插件的安装
- **遇到不确定时**：停下来汇报，不要猜测或尝试

---

## 第一步：判断当前任务类型

当用户要求创建或修改 DSL 时，先按以下逻辑判断：

```
任务是否涉及自定义 API 工具（provider_type: api）？
  ├─ 是 → 继续判断：
  │       当前是否有已包含正确 provider_id（UUID）的基准 DSL？
  │       ├─ 是 → AI 可基于此基准修改提示词/参数等
  │       └─ 否 → 【STOP】必须人工介入获取基准 DSL（见下方"人工介入：创建自定义工具 Agent"）
  │
  └─ 否 → AI 可自主完成 DSL 修改
```

**如何判断是否有基准 DSL**：检查 `photo-agent.yml`（或目标 DSL 文件）中的 `agent_mode.tools`：
- 如果每个工具的 `provider_id` 是 UUID 格式（如 `6549e9fe-4b0d-45bb-992d-5c6d45fe7007`）→ 有基准 DSL
- 如果 `tools: []` 或 `provider_id` 是字符串名（如 `photo_agent`）→ 无基准 DSL

---

## 人工介入节点 1：创建自定义工具 Agent（首次）

**触发条件**：用户要创建一个包含自定义 API 工具的 Agent 应用，且当前没有含正确 UUID 的基准 DSL。

**AI 操作**：
1. 向用户汇报：
   > "当前需要创建含自定义 API 工具的 Agent 应用。由于 Dify 为每个工具分配 UUID 作为 provider_id，我无法手写正确的 tools 配置。需要您完成以下 4 步人工操作："
2. 给出具体操作步骤：

   **步骤 1**：确保 `photo_agent` 自定义工具 Provider 已创建
   - 打开 Dify → 工具 → 自定义 → 导入 `docs/dify_tools_openapi.yaml`
   - 如果已创建，跳过此步

   **步骤 2**：AI 生成无 tools 的 DSL 并保存
   - AI 将 `agent_mode.tools` 设为空数组 `[]`
   - AI 生成其余配置（提示词、模型等）
   - 保存为 `dify/dsl/photo-agent.yml`

   **步骤 3**：用户在 Dify UI 中导入并绑定工具
   - Studio → 创建空白应用 → 导入 DSL 文件
   - 进入 Agent 编排 → 添加工具 → 选择 `photo_agent` → 勾选所有工具
   - 发布

   **步骤 4**：用户导出完整 DSL 发回给 AI
   - 应用设置 → 导出 DSL
   - 将文件内容发回给 AI，或保存到 `dify/dsl/photo-agent.yml`
   - 此即为**基准 DSL**，后续 AI 修改都基于此文件

3. **等待用户完成**。在用户返回基准 DSL 之前，不要继续生成 tools 配置。

---

## 人工介入节点 2：修改工具配置

**触发条件**：用户要求增删工具、修改工具参数，且当前 DSL 可能不是最新基准版本。

**AI 操作**：
1. 向用户汇报：
   > "修改工具配置需要基于最新导出的基准 DSL，因为工具的 provider_id 或参数结构可能已变化。请确认以下问题："
2. 询问用户：
   - "当前 `dify/dsl/photo-agent.yml` 是否是从 Dify 最新导出的？"
   - 如果用户不确定，或回答是"否"：
     > "请从 Dify 导出最新 DSL 发给我，我再进行修改。"
3. **等待用户提供最新 DSL**。不要基于可能过期的文件修改工具配置。

---

## 人工介入节点 3：导入后报错（InFailedSqlTransaction）

**触发条件**：用户反馈导入 DSL 后查看应用详情时报错，错误包含 `InFailedSqlTransaction`。

**AI 操作**：
1. 向用户汇报：
   > "检测到数据库事务错误。这通常是因为之前的 DSL 导入尝试（尤其是 tools 配置有误时）损坏了 PostgreSQL session。当前 session 中的事务已失败，后续所有查询都被拒绝。"
2. 给出解决方案：
   > "需要重启 Dify 容器以清除损坏的 session。请执行："
   ```bash
   cd dify && docker compose down && docker compose up -d
   ```
3. 询问：
   > "重启完成后请告诉我，我们再重新导入。"
4. **等待用户确认重启完成**。不要假设用户已经重启了。

---

## 人工介入节点 4：模型 Provider 变更

**触发条件**：用户要求切换模型（如从 gpt-4o 换为 doubao），或 DSL 中的 `model.provider` 与目标 Dify 已安装的插件不匹配。

**AI 操作**：
1. 向用户汇报当前 DSL 使用的模型和 provider：
   > "当前 DSL 配置的模型是 `{name}`，provider 是 `{provider}`。"
2. 询问：
   > "您的 Dify 实例是否已安装并配置了对应的模型插件？如果未安装，请先安装该插件（设置 → 模型供应商），然后告诉我已就绪。"
3. **等待用户确认**。不要尝试导入可能因缺少插件而失败的 DSL。

---

## Agent 模式工具配置速查

### Agent 模式必填字段

```yaml
agent_mode:
  enabled: true
  strategy: function_call   # 或 react
  max_iteration: 5
  prompt: null
  tools: []                 # 空数组或完整工具数组
```

### 工具数组完整字段（仅用于已有基准 DSL 时参考）

```yaml
tools:
  - enabled: true
    notAuthor: false
    provider_id: 6549e9fe-4b0d-45bb-992d-5c6d45fe7007   # UUID！仅基准 DSL 中可用
    provider_name: photo_agent
    provider_type: api
    tool_label: list_timelines
    tool_name: list_timelines
    tool_parameters:
      name: null
    type: api
```

**自定义 API 工具 vs Marketplace 插件工具的区别**：
- 自定义 API 工具：`provider_type: api`，`provider_id` 是 UUID，**不需要**在 `dependencies` 中声明
- Marketplace 插件工具：`provider_type: builtin/plugin`，`provider_id` 是插件标识符（如 `langgenius/json_process/json_process`），**需要**在 `dependencies` 中声明对应的 `marketplace_plugin_unique_identifier`

---

## 已知限制（踩坑记录）

- 导入/导出 DSL **不会**包含知识库绑定信息（`dataset_configs.datasets` 始终为空数组），知识库需导入后在 UI 中手动绑定
- `annotation_reply` / `tags` 等字段在查看详情时触发数据库查询，若事务已损坏会导致级联报错
- DSL 中的 `app.icon` 使用 emoji 时，`icon_type` 必须为 `emoji`
- 导入路径**不验证** `agent_mode.tools` 的内容，配置错误不会立即暴露，会在查看详情时触发事务错误
