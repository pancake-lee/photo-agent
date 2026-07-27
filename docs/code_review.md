# 代码审查报告

> 审查日期：2026-06-26
> 审查范围：Go 后端 (backend/)、Python AI 服务层 (agent/)、Web 前端 (web/)
> 审查维度：代码整洁度、风格一致性、AI 开发最佳实践对齐

---

## 总体评价

项目代码整体质量**中上**，三层的职责边界清晰，核心架构设计合理。Go 后端遵循标准 Gin + GORM 模式，Python AI 层正确使用了 LangGraph StateGraph 编排，Web 前端 Vue 3 Composition API + TypeScript 使用得当。

主要问题集中在三个方面：

1. **代码重复**：三层都存在不同程度的重复逻辑
2. **错误处理**：静默吞错过多，缺少统一的错误处理策略
3. **测试覆盖**：生产级 LangGraph 图没有自动化测试，Go 后端零单元测试

---

## Go 后端 (backend/)

### 代码量：~6,583 行，34 个 Go 文件

### 架构评分：良好

`cmd/internal` 分离干净。`cmd/` 是薄入口，业务逻辑在 `internal/service/`，HTTP 在 `internal/api/`，数据模型在 `internal/model/`，外部集成在 `internal/vlm/`。

### G3. 🟡 高 — 依赖膨胀严重

通过 `pgo` 模块间接引入了大量不必要的框架和驱动：iris、kratos、tidb parser、redis、rabbitmq、jwt、mysql driver、postgres driver 等。对于一个只使用 HTTP 助手和日志封装的简单后端，这些依赖显著增加了二进制体积和构建时间。

**建议**：审查 `pgo` 模块，裁剪不需要的依赖，或将实际使用的少量工具内联到项目中。

### G4. 🟡 高 — 手写 OpenAPI 规范

**位置**：`backend/internal/api/openapi.go`（184 行）

所有路由和 schema 定义通过手写 `gin.H` 维护。路由变更时容易忘记同步更新。**建议**：使用 `swaggo/swag` 等工具从代码注释自动生成。

### G5. 🟡 高 — 废弃依赖

- `github.com/rwcarlsen/goexif`：最后更新 2019 年
- `github.com/satori/go.uuid`：已归档/废弃，应换为 `github.com/google/uuid`

### G6. 🟡 中 — VLM 输出的中文映射耦合

**位置**：`backend/internal/service/descriptions.go`

`mapScene()`、`mapLighting()`、`mapMood()` 函数直接检查中文子串（如 `"室内"`、`"夜"`、`"温暖"`、`"忧郁"`）。如果 VLM prompt 改为英文输出，这些映射全部静默失效（返回空字符串）。应增加 fallback 机制或至少 warn 日志。

方案：需要配合prompt一起处理，由提示词提供准确的枚举值，让vlm输出准确的值，这些值可以由用户在web配置。

---

## Python AI 服务层 (agent/)

### 代码量：~4,500 行，25+ 个 Python 文件

### 架构评分：良好

LangGraph StateGraph 编排清晰（6 节点 + 条件路由），Combined 查询的降级策略设计优秀。API 使用 FastAPI 应用工厂模式，Pydantic 模型定义完整。

### P5. 🟡 高 — 所有 Prompt 硬编码在 Python 源码中

9 个提示词变量全部以字符串常量形式写在代码里，无配置文件化、无版本管理、无 A/B 测试能力。建议抽到 YAML 或独立 prompt 文件中。

### P13. 🟢 低 — 缺少 API 认证和速率限制

对于本地工具可接受，但需在文档中明确说明。

---

## AI 开发最佳实践对齐评估

### 做得好的 ✅

- ✅ 查询路由（LangGraph StateGraph）：4 类路由 + Combined 交集策略，设计优秀
- ✅ 降级策略：Combined 5 层降级（SQL 异常/过宽/空/交集空/整体异常 → RAG）
- ✅ Temperature 控制：classify/SQL 用 0.0，RAG 用 0.5，主题生成用 0.7
- ✅ Few-shot 示例：Text-to-SQL 有 6 个精心设计的 NL→SQL 示例
- ✅ 结构化输出解析：3 层 fallback 策略（JSON → regex → 中文模式匹配）
- ✅ Token 追踪：LangChain Callback 自动记录，按模型和日期分组
- ✅ 动态属性值注入：从 DB 获取 distinct 值拼入 prompt，避免 LLM 幻觉值
- ✅ VLM prompt 外置：通过配置文件引用外部 prompt 文件
- ✅ ChromaDB 元数据最小化：Route B 策略，Go SQLite 是唯一数据源

### 需要改进的 ⚠️

- ⚠️ Prompt 管理：所有 prompt 硬编码在 Python 源码中，无版本控制、无 A/B 测试能力
- ⚠️ 流式输出：仅 CLI 支持，API 端点不支持 SSE 流式
- ⚠️ Prompt 注入防护：Chat API 无任何输入过滤或 guardrails
- ⚠️ API 安全：无认证、无速率限制，LLM 预算暴露给网络
- ⚠️ 评估体系：黄金查询用例管理已建立，但评估脚本未接入 CI，缺少自动化回归
- ⚠️ 可观测性：无 LLM 调用的 latency/error rate 监控，无 tracing

### 架构模式评价

```
当前架构：
  Web 前端 ←→ Python Agent ←→ Go Backend ←→ SQLite
                ↓                  ↓
            ChromaDB          VLM API / Embedding API
```

这个三栈划分是合理的：

- **Go 负责数据和文件**：照片存储、EXIF 解析、SQL 执行、Embedding 代理 — 这是正确的，Go 擅长 IO 密集型操作
- **Python 负责 AI 编排**：LangGraph、ChromaDB、Text-to-SQL — 这是正确的，AI 生态 Python 最完整
- **Vue 负责 UI**：照片管理、对话界面、聚类浏览 — 这是正确的，现代 SPA 框架

**无需改变架构。** 当前模式已经合理利用了每层的最佳能力。

---

## 已处理

> 以下问题已修复，保留原文供回溯。

---

### Go 后端 (backend/)

#### G1. 🔴 严重 — timeline.go 中 panic 会导致服务崩溃

**位置**：`backend/internal/service/timeline.go:38`

```go
if os.IsNotExist(err) {
    plogger.Errorf("Timeline file not found: %s", path)
    panic(fmt.Sprintf("timeline file not found: %s", path))
}
```

timeline 文件是**可选功能**，文件不存在不应导致整个 server 崩溃。应改为返回 error，由调用方决定如何处理。

方案：不处理，timeline配置可以设置为空，则不使用该功能，如配置了，则应该解析成功，否则panic明确告知用户，否则用户容易忽略，需要在后续功能回头排查，路径很长。

#### G2. 🔴 严重 — 硬编码 `/root/project/` 路径

**位置**：`backend/internal/service/storage.go:32` 和 `backend/internal/vlm/compress.go:74`

```go
const projectPrefix = "/root/project/"
```

这是开发机特有的路径，换个机器就会出问题。应通过配置文件或环境变量指定。

方案：代码去掉projectPrefix常量，直接使用配置`storage.photo_src`和`storage.photo_path`足够

#### G7. 🟡 中 — `activeCount()` 永远返回 0

**位置**：`backend/internal/service/vlm_queue.go:232`

注释写明 `WaitGroup doesn't provide a read counter`，但这个函数仍在 `Stop()` 日志中被调用，永远显示 `active=0`，具有误导性。

#### G8. 🟢 低 — `max_tokens: 500` 硬编码

**位置**：`backend/internal/vlm/client.go:150`

应移至配置文件。

---

### Python AI 服务层 (agent/)

#### P1. 🔴 严重 — `sys.path` 操作泛滥

**12+ 个文件**开头都有：

```python
import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
```

这是明显的包结构问题。**解决方案**：将项目安装为可编辑包（`pip install -e .`），移除所有 `sys.path` 操作。

#### P2. 🔴 严重 — Text-to-SQL 和 RAG 绕过 LLM 工厂

**位置**：`chain/text_to_sql.py:331` 和 `chain/photo_rag.py:233`

这两个模块直接实例化 `lc_openai.ChatOpenAI`，而不是通过 `llm_factory.create_llm()`。这意味着：

- SQL 生成和 RAG 回答生成**没有重试逻辑**
- **没有 fallback 模型**
- **Token 用量不会被追踪**

#### P3. 🟡 高 — 无 LLM 调用超时

所有 `ChatOpenAI` 实例化都没有设置 `request_timeout`。如果网络阻塞，API 会无限等待。

#### P4. 🟡 高 — CORS 配置错误

**位置**：`chain/server.py`

```python
allow_origins=["*"],
allow_credentials=True,
```

当 `allow_credentials=True` 时，`Access-Control-Allow-Origin` 不能是 `*`。浏览器会拒绝此 CORS 响应。本项目中前端通过 Vite 代理访问所以不会触发此问题，但直接浏览器访问时会失效。

#### P10. 🟡 中 — AutoEmbed 定义但从未使用

**位置**：`chain/auto_embed.py`

文档字符串说 "used by photo_agent.py automatically"，但 `photo_agent.py` 从未导入或调用 `AutoEmbed`。

方案：自动运行已经被废弃，现在是web上通过按钮触发，所以自动执行相关代码可以删除，注意不要删了复用的代码。

#### P11. 🟢 低 — 未使用的依赖

- `tenacity`：`pyproject.toml` 中声明但从未 import（项目使用 LangChain 的 `with_retry`）
- `python-dotenv`：声明但从未 import（配置全部来自 YAML）

#### P12. 🟢 低 — `datetime.utcnow()` 已废弃

**位置**：`chain/session_store.py`

Python 3.12+ 中 `datetime.utcnow()` 已废弃，应使用 `datetime.now(datetime.UTC)`。

#### P6. 🟡 高 — 聚类 API 同步阻塞

**位置**：`chain/server.py` — `POST /api/cluster/run`

UMAP + HDBSCAN 计算可能需要数分钟。在 FastAPI handler 中同步执行会阻塞事件循环。应使用 `run_in_executor` 或改为后台任务。

方案：改为后台任务模式。POST /api/cluster/run 启动后台线程执行聚类，立即返回 task_id；前端通过 GET /api/cluster/status/{task_id} 查询进度，或轮询 GET /api/cluster/results 查看新结果。

#### P7. 🟡 中 — 全局可变状态

模块级单例 `_graph_app`、`_tracker`、`_callbacks`、`_tool_clients`、`_GOLDEN_QUERIES_DIR`、`_CLUSTER_DIR` 增加了耦合度和测试难度。

方案：目录路径全局变量（`_GOLDEN_QUERIES_DIR`、`_CLUSTER_DIR`）迁移到 `app.state`，函数通过参数接收路径。其余单例（`_graph_app` 等）保留并在注释中说明设计权衡——这些在 PhotoAgent 初始化时创建一次，进程生命周期内复用，是单进程 FastAPI 的务实选择。

#### P8. 🟡 中 — HTTP 请求无重试

所有对 Go 后端的 HTTP 调用都没有重试逻辑。Go 后端短暂不可用时 Python Agent 会直接报错。

方案：创建 `utils/http_client.py` 共享工厂，使用 `httpx.HTTPTransport(retries=3)` 配置重试。所有 HTTP 调用点（sqlite_client、openapi_client、embed_queue、embedder 及内联 httpx.Client）统一使用该工厂。

#### P9. 🟡 中 — Error detail 泄露内部信息

**位置**：`chain/server.py` — `send_message` 端点

```python
raise fastapi.HTTPException(status_code=500, detail=str(exc))
```

`str(exc)` 可能包含堆栈跟踪、SQL 查询等内部信息。

方案：HTTPException 的 detail 改为通用提示（"处理请求时发生内部错误"），完整异常信息通过 `logger.exception()` 记录到日志。用户聊天消息也同步改为通用提示。

---

### Web 前端 (web/)

### 代码量：~3,000 行，9 个组件，6 个 composables，4 个视图

### 架构评分：良好

Vue 3 Composition API + TypeScript + NaiveUI，项目结构清晰。Composable 模式做状态管理（模块级单例 ref），适合当前规模。零 `any` 使用，TypeScript 覆盖率优秀。

#### W1. 🔴 严重 — `onUnmounted` 在单例 composable 中无效

**位置**：`src/composables/useVlmQueue.ts` 和 `useEmbedQueue.ts`

```typescript
export function useVlmQueue() {
    // module-level state...
    onUnmounted(() => stopPolling())  // BUG: 永远不执行
}
```

因为 composable 使用模块级单例模式，`onUnmounted` 只在首次调用 `useVlmQueue()` 的组件 `setup` 时注册。当用户导航离开使用了该 composable 的视图后，轮询 interval **继续运行**（直到 SPA 完全刷新）。这是一个真实的资源泄漏 bug。

**修复**：在 `stopPolling`/`stopQueue` 中主动清理 interval，而非依赖 `onUnmounted`。当前已通过 usageCount 引用计数实现，最后一个组件卸载时停止轮询。

#### W2. 🟡 高 — 照片缩略图渲染代码大量重复

**位置**：`GoldenQueryManagement.vue` 和 `ClusterView.vue`

两个文件各自实现了 ~80 行的 `h()` 函数渲染照片缩略图。`GoldenQueryManagement`: `renderPhotoList(photos, emptyText)`；`ClusterView`: `renderPhotoThumbs(photos, showAll)`。

**修复**：提取为共享的 `components/PhotoThumbList.vue` 组件。支持 `photos`、`maxPreview`（默认 3，设为 0 展示全部）、`emptyText` 属性，emit `preview` 事件。同时替换了 `GoldenQueryManagement.vue` 详情弹窗中的内联缩略图渲染。

#### W3. 🟡 高 — 照片预览 Modal 重复 3 次

**位置**：`ChatView.vue`、`GoldenQueryManagement.vue`、`ClusterView.vue`

完全相同的 `NModal + img` 结构重复 3 次，CSS 也重复。ChatView 还额外有下载按钮。

**修复**：提取为共享的 `components/PhotoPreviewModal.vue` 组件。支持 `show`（v-model）、`imageUrl`、`title`、`showDownload`、`downloadFilename` 属性。内置下载逻辑（fetch→blob→download，失败时 fallback 到 `window.open`）。

#### W4. 🟡 中 — 14+ 处静默错误吞没

14+ 处 `catch { }` 不输出任何日志，排查问题时无从下手。

**修复**：为所有静默 catch 添加错误日志。CRUD 操作使用 `console.warn`（带上下文描述），轮询操作使用 `console.debug`（Agent 未启动时 404 属预期）。涉及文件：`useChat.ts`、`usePhotos.ts`、`useVlmQueue.ts`、`useEmbedQueue.ts`、`useUpload.ts`、`ChatView.vue`、`GoldenQueryManagement.vue`、`ClusterView.vue`。

#### W7. 🟡 中 — 上传冲突回调的 Promise 泄漏风险

**位置**：`PhotoManagement.vue` 和 `useUpload.ts`

用户关闭冲突弹窗而不做选择时，`onConflict` 回调返回的 Promise 永远不 resolve，upload 循环永久阻塞。

**修复**：在 `PhotoManagement.vue` 中添加 `watch(showConflictModal)`，当弹窗关闭但 `conflictResolver` 未消费时，自动以 `'skip'` resolve，确保上传循环能继续执行。

#### W5. 🟡 中 — 日期格式化重复 ~15 次

```typescript
new Date(t).toLocaleString('zh-CN')
```

散落在各组件中，格式不统一。

**修复**：已提取为 `utils/format.ts` 中的 `formatDate()` 函数，所有组件统一导入使用。

#### W6. 🟡 中 — `UploadDropZone` 使用字符串 `$refs`

```html
@click="($refs.fileInput as HTMLInputElement).click()"
```

模板字符串 refs 类型推断不佳。

**修复**：已改为 `const fileInput = ref<HTMLInputElement>()` 模板 ref。

#### W8. 🟢 低 — `NImage` 导入但未使用

**位置**：`GoldenQueryManagement.vue:16`、`ClusterView.vue:16`

**修复**：已移除未使用的 `NImage` 导入。

#### W9. 🟢 低 — `marked.parse({ async: false })` 已弃用

**位置**：`ChatView.vue:162`

**修复**：已升级 marked 到 v18，使用新版 API `marked.parse(text)`（无 options 参数时同步返回 string）。

#### W10. 🟢 低 — `/photos` 路由非懒加载

**修复**：所有 5 个路由均已改为 `() => import(...)` 懒加载。

#### W11. 🟢 低 — 无 ESLint/Prettier 配置

代码风格依赖开发者编辑器设置，无项目级约束。

**修复**：已添加 `.prettierrc` 配置文件（semi: false, singleQuote: true, trailingComma: all, printWidth: 100）。ESLint 按评审方案不引入，仅使用 Prettier。