# Photo Agent - 前端 UI 设计文档

> 状态：草案 | 2026-06-18

## 1. 总体架构

### 1.1 三层架构

```
Vue 前端 (Web UI)  :10000/dev
    │
    ├──→ Go 基建后端 (:10000)
    │       ├── 照片元数据 CRUD（已有）
    │       ├── 文件存储与读取（已有）
    │       ├── 图片上传接收 + 存储
    │       ├── VLM 图片描述生成（已有，抽象为 service）★
    │       ├── EXIF 解析 + 去重判断
    │       └── 缩略图 / 统计
    │
    └──→ Python Agent 后端（后续启用）
            ├── LLM 对话编排
            ├── Chroma 向量检索（RAG）
            ├── Text-to-SQL
            └── Function Calling → Go API
```

**核心原则**：

- **VLM 图片预处理属于基建能力，归 Go 后端**，不涉及 Agent 编排。现有 `batch_vlm` 和 `vlm.DescribeImage()` 逻辑应抽象为 service，同时服务 CLI 和 Web 两种入口。
- **Python Agent 后端只负责 LLM 编排**（对话、RAG、Text-to-SQL、Function Calling），所有数据/文件操作通过 Go API 完成。
- **前端直接调用 Go API** 完成图片上传、VLM 预处理；对话功能后续再接入 Python 后端。

### 1.2 VLM 预处理的两种入口

现有 `batch_vlm` 是纯 CLI 工具，需要将其核心逻辑下沉到 `internal/service` 包，让 CLI 和 Web API 共享同一套处理管线：

```
internal/service/vlm_pipeline.go（新增，抽象）
    ├── ScanImages(dir) → []string
    ├── ProcessImages(images, concurrency, retry) → map[relPath]DescriptionEntry
    │      内部循环: compress → VLM describe → EXIF → save descriptions.json
    └── SaveDescriptions(path, result)

cmd/batch_vlm/main.go（CLI 入口，精简为参数解析 + 调用 service）
api/photo.go（Web 入口，新增 upload + batch_vlm handler）
```

**Web 上的两种处理方式**：

| 方式 | 适用场景 | 流程 |
|------|---------|------|
| **方式 1：服务器目录批量处理** | 原图已在服务器上（如 `/root/project/photos/`），用户熟悉技术 | Web 配置源目录 → Go 后台异步扫描 + 批量 VLM → 前端轮询进度 → 完成后刷新图片列表 |
| **方式 2：Web 交互上传** | 原图在用户本地电脑，用户不熟悉技术 | 前端选择文件 → 前端压缩 → 上传到 Go → Go 存储 + 触发 VLM 描述（单张同步或小批量异步） |

两者共享同一套 `service.VlmPipeline`，差异仅在于：方式 1 读本地文件，方式 2 接收前端传来的压缩文件。

---

## 2. 技术选型

参考 `/root/code/pflow/web/` 的技术栈：

- **框架**：Vue 3.5 + TypeScript
- **构建**：Vite 8.x
- **组件库**：Naive UI 2.x（暗色主题）
- **图标**：`@vicons/ionicons5`
- **图片压缩**：`browser-image-compression`，在浏览器端将原图压缩后上传
- **EXIF 读取**：`exifr`，读取原始文件拍摄时间用于去重
- **路由**：当前阶段不引入 vue-router，用状态变量切换视图

---

## 3. 页面布局

### 3.1 整体框架

```
┌──────────────────────────────────────────────────┐
│  Top Nav Bar（项目名 + 版本，可选）                  │
├─────────┬────────────────────────────────────────┤
│ 功能列表 │                                        │
│         │         主内容区                        │
│ 📷 图片  │                                        │
│   管理   │                                        │
│         │                                        │
│ (后续    │                                        │
│  扩展)   │                                        │
├─────────┴────────────────────────────────────────┤
```

- **左侧边栏**（`NLayoutSider`，宽度 ~200px）：功能导航列表，当前仅"图片管理"
- **主内容区**（`NLayoutContent`）：根据选中功能渲染对应页面，当前渲染图片管理页面
- **默认暗色主题**（`NConfigProvider` + `darkTheme`），与 pflow 一致

### 3.2 组件树

```
App.vue
├── NConfigProvider (darkTheme)
│   └── NLayout
│       ├── NLayoutSider（左侧）
│       │   └── NMenu / 自定义列表
│       └── NLayoutContent
│           └── PhotoManagement.vue
│               ├── 工具栏（"开始自动VLM预处理" + 进度指示器 + 上传按钮）
│               ├── PhotoGrid.vue
│               │   └── PhotoCard.vue × N（含描述状态按钮）
│               ├── 分页器
│               ├── PhotoDetail.vue（NDrawer，含描述展示 + 重新生成按钮）
│               ├── DescriptionModal.vue（NModal，描述内容查看）
│               ├── UploadModal.vue
│               │   ├── UploadDropZone.vue
│               │   └── FileList.vue
│               └── ConflictModal.vue
```

---

## 4. 图片管理页面

### 4.1 页面结构

```
┌──────────────────────────────────────────────────┐
│  图片管理    [开始自动VLM预处理] [上传图片]         │  ← 队列空闲
│  图片管理    [开始自动VLM预处理] [3/20] [上传图片]  │  ← 队列运行中
├──────────────────────────────────────────────────┤
│  共 X 张 | 含描述 X 张 | 待处理 X 张               │
├──────────────────────────────────────────────────┤
│ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐             │
│ │      │ │      │ │      │ │      │             │
│ │ 缩略图│ │ 缩略图│ │ 缩略图│ │ 缩略图│             │
│ │      │ │      │ │      │ │      │             │
│ │文件名 │ │文件名 │ │文件名 │ │文件名 │             │
│ │有描述✓│ │无描述 │ │有描述✓│ │有描述✓│             │
│ └──────┘ └──────┘ └──────┘ └──────┘             │
│ ┌──────┐ ┌──────┐ ...                            │
│ │ ...  │ │ ...  │                                │
│ └──────┘ └──────┘                                │
│                                                   │
│          分页器 < 1 2 3 ... >                      │
└──────────────────────────────────────────────────┘
```

### 4.2 网格展示

- **响应式网格**：根据窗口宽度自适应（3~6 列），使用 CSS Grid 或 Naive UI `NGrid`
- **卡片（NCard）**：
  - 缩略图：`GET /api/v1/photos/:id/image?size=thumb`
  - 文件名
  - 描述状态按钮（卡片右下角）：
    - 有描述 → 绿色实心按钮（✓ 图标），点击打开描述内容弹窗（含"重新生成"按钮，见 §6.5）
    - 无描述 → 灰色虚线按钮，点击触发单张 VLM 生成（调用 `POST /api/v1/photos/:id/describe`，加入后端队列）
    - 处理中 → spinner 动画
  - 悬停 Tooltip：拍摄时间、相机、镜头、ISO 等
- **加载中**：`NSpin` 包裹
- **空状态**：图标 + "还没有照片，点击上方按钮开始"
- **错误状态**：`NAlert` + 重试按钮

### 4.3 查看大图

- 点击卡片 → 右侧滑出 `NDrawer`
- 展示：
  - 完整图片（压缩后）
  - EXIF 详情表（`NDescriptions`）
  - VLM 描述文本
  - 时间线标签、结构化标签
- 描述区域：
  - 已有描述 → 展示完整 VLM 描述文本，底部有 [重新生成] 按钮（调用 `POST /api/v1/photos/:id/describe`，加入后端队列）
  - 暂无描述 → 展示占位文案 + [生成描述] 按钮（同上）

---

## 5. 上传流程（方式 2：Web 交互上传）

### 5.1 上传弹窗

点击"上传图片"按钮 → `NModal`：

```
┌──────────────────────────────────────────────────┐
│  上传图片                                   [✕]   │
├──────────────────────────────────────────────────┤
│                                                   │
│   ┌───────────────────────────────────────────┐  │
│   │                                           │  │
│   │     拖拽图片到此处，或点击选择文件          │  │
│   │                                           │  │
│   │     支持 JPG / PNG / HEIC / TIFF          │  │
│   │                                           │  │
│   └───────────────────────────────────────────┘  │
│                                                   │
│  ── 已添加的文件 ──                               │
│  ┌───────────────────────────────────────────┐  │
│  │ 📷 IMG_001.jpg  3.2MB→320KB  ✅ 已压缩     │  │
│  │ 📷 IMG_002.png  1.8MB→280KB  ⏳ 压缩中     │  │
│  │ 📷 IMG_003.jpg  4.1MB        等待压缩      │  │
│  └───────────────────────────────────────────┘  │
│                                                   │
│          [取消]           [开始上传 (3)]           │
└──────────────────────────────────────────────────┘
```

### 5.2 交互细节

- **添加文件**：点击拖拽区 → 系统文件选择器 / 拖拽文件到区域内 / 粘贴剪贴板图片
- **去除文件**：列表每项右侧有 ✕ 按钮
- **压缩**：文件加入列表后自动开始前端压缩，显示原始大小 → 压缩后大小
- **上传**：用户点击"开始上传"后，逐文件 `POST /api/v1/photos/upload`（限制并发数 3）
- **去重冲突**：后端返回 `conflict` 时暂停，弹出 ConflictModal 让用户选择（见 §6）
- **VLM 处理**：上传成功后，图片元数据写入数据库，`has_description` 默认为 false。用户可通过工具栏的"开始自动 VLM 预处理"批量生成描述，也可在图片卡片上逐张触发。VLM 处理流程见 §6。

### 5.3 前端压缩参数

- 最大宽度/高度：2048px
- 格式：统一 JPEG
- 质量：0.85
- 最大文件大小：~500KB
- 库：`browser-image-compression`

（保留足够细节供 VLM 分析，同时减少传输和存储成本）

### 5.4 EXIF 预读

- 前端使用 `exifr` 读取原始文件的 DateTimeOriginal
- 随上传请求一并发送，供后端去重判断（见 §6）
- 读取失败时传空，后端以文件 mtime 作为 fallback

---

## 6. VLM 异步处理队列

### 6.1 设计思路

VLM 调用耗时长（每张数秒到数十秒）、消耗 API Token，不适合同步等待。后端维护一个 VLM 任务队列，前端提供**全局开关**和**单张触发**两种粒度。

关键约束：
- 每个图片的 VLM 描述状态**独立标识**，可单独操作
- 全局"开始自动 VLM 预处理"将所有未描述图片入队
- 用户可随时**中止**：清空队列，但已发出的请求正常完成（不浪费 Token）
- 中止后的"扫尾"结果静默写入，前端不展示进度，用户下次刷新自然可见

### 6.2 后端队列模型

```
internal/service/vlm_queue.go（新增）
    ├── VlmQueue 结构体（单例，跟随 server 生命周期）
    │   ├── pending chan string         # 待处理 photo_id 队列（带缓冲）
    │   ├── running bool                # 是否正在消费队列
    │   ├── total / completed / failed  # 本轮进度计数
    │   ├── ctx / cancel                # 取消上下文（控制队列消费循环）
    │   ├── active sync.WaitGroup       # 正在执行的 VLM 请求计数
    │   └── mu sync.RWMutex             # 状态读写锁
    ├── Start(photoIDs []string)        # 填充队列、启动消费循环
    ├── Stop()                          # cancel context → 清空 pending chan → 返回
    │                                     不等待 active（让已发出的请求自然完成）
    ├── Enqueue(photoID string)         # 单张追加到 pending
    └── Status() QueueStatus            # 查询当前进度
```

**Worker 消费循环**（伪代码）：

```
for {
    select {
    case <-ctx.Done(): return          // 被中止，退出循环
    case photoID := <-pending:
        active.Add(1)
        go func() {
            defer active.Done()
            // VLM 调用不传 ctx（或传独立的 ctx），确保不被 cancel 中断
            desc, model, err := vlm.DescribeImage(photoPath)
            if err == nil {
                saveResult(photoID, desc, model)
            }
            updateProgress()
        }()
    }
}
```

**中止语义（Stop）**：
1. `cancel()` → Worker 循环退出，不再从 pending 取新任务
2. 排空 pending channel 中剩余项并丢弃
3. **不等待** `active.WaitGroup`——已发出 HTTP 请求的 goroutine 不受 cancel 影响（它们不依赖队列 ctx）
4. 已发出的请求正常完成 → `saveResult()` 写入 descriptions.json + 更新数据库
5. 前端不需要展示这些"扫尾"结果——下次用户刷新列表或打开详情时自然可见
6. `Stop()` 返回后，`running=false`，`total/completed/failed` 清零

### 6.3 全局控制

图片管理页面工具栏（§4.1）：

```
队列空闲：
  图片管理    [开始自动VLM预处理]

队列运行中：
  图片管理    [开始自动VLM预处理] [3/20 ⏸]    ← hover 时文案变为"点击中止"

队列完成（短暂展示后自动恢复）：
  图片管理    [开始自动VLM预处理]
```

**"开始自动VLM预处理"按钮**（`NButton`，primary 类型）：
- 队列空闲时可见
- 点击 → `POST /api/v1/vlm/queue/start`，查询所有 `has_description=false` 的图片 ID，全部入队
- 可带 `force=true` 参数，将已有描述的图片也纳入重新处理（配合二次确认弹窗）
- 请求返回后，按钮旁边出现进度指示器，开始轮询

**进度指示器**（`NButton` + `NTooltip`）：
- 文案：`{completed}/{total}`
- 悬停 Tooltip："点击中止处理"
- 悬停时按钮文案从 `3/20` 变为 `点击中止`（或始终显示 `3/20`，仅 tooltip 提示中止——具体交互后续确定）
- 点击 → `POST /api/v1/vlm/queue/stop`
  - 后端清空队列、停止消费
  - 前端停止轮询，进度指示器消失，恢复为"开始自动VLM预处理"
- 完成时：`completed === total`，进度指示器自动消失，按钮恢复

**轮询频率**：`GET /api/v1/vlm/queue/status`，间隔 1~2s。

### 6.4 单张控制

**PhotoCard 描述状态按钮**（见 §4.2 卡片布局）：
- 有描述（`has_description=true`） → 绿色实心按钮（checkmark 图标）→ 点击弹出 DescriptionModal（§6.5）
- 无描述（`has_description=false`）→ 灰色虚线按钮 → 点击调用 `POST /api/v1/photos/:id/describe`，按钮变为 spinner
- 单张触发不受全局队列运行状态影响——Enqueue 追加到 pending 末尾即可

**PhotoDetail 抽屉**（见 §4.3）：
- 已有描述 → 描述文本 + [重新生成] 按钮（调用 `POST /api/v1/photos/:id/describe`）
- 暂无描述 → 占位提示 + [生成描述] 按钮

### 6.5 描述内容弹窗（DescriptionModal）

点击"有描述"按钮 → `NModal` 展示描述内容：

```
┌──────────────────────────────────────────────────┐
│  图像描述 - IMG_001.jpg                      [✕]  │
├──────────────────────────────────────────────────┤
│                                                   │
│  模型：doubao-vision-pro-32k                      │
│  生成时间：2026-06-18 14:30:22                    │
│                                                   │
│  ┌───────────────────────────────────────────┐   │
│  │                                           │   │
│  │  这是一张户外风景照片，画面中央是...         │   │
│  │  主体：山脉、湖泊                          │   │
│  │  色调：冷色调，以蓝绿为主                   │   │
│  │  ...                                      │   │
│  │                                           │   │
│  └───────────────────────────────────────────┘   │
│                                                   │
│                [重新生成]    [关闭]                │
└──────────────────────────────────────────────────┘
```

- "[重新生成]" → 调用 `POST /api/v1/photos/:id/describe`，关闭弹窗，对应 PhotoCard 按钮切换为 spinner

### 6.6 服务器目录批量导入（方式 1，后续 Phase 实现）

与 VLM 队列独立。`BatchVlmModal` 仅做"扫描服务器目录 → 导入图片元数据到数据库"，**不再直接触发 VLM**：

```
BatchVlmModal（简化版）：
  源目录：[________________] [浏览...]
  并发导入数：[5]
  ☐ 跳过 MD5 去重

  ── 导入进度 ──
  进度条：[████████░░░░░░░░] 45/120
  新增: 43  |  跳过: 2

  [开始导入]
```

导入完成后，图片 `has_description=false`，用户通过"开始自动VLM预处理"统一触发描述生成。

---

## 7. 去重逻辑

### 7.1 触发时机

- **方式 1（批量处理）**：已有 MD5 去重（`dedup_hashes.json`），不涉及用户交互
- **方式 2（Web 上传）**：后端收到上传文件后，检查 `storage.photo_path` 中是否已有同名文件

### 7.2 判断逻辑

```
同名文件在 photo_path 中？
  ├── 否 → 直接存储 + 调用 VLM
  └── 是 → 对比 EXIF 拍摄时间
            ├── 拍摄时间不同 → 自动加序号后缀存储（IMG_001-2.jpg）
            ├── 拍摄时间相同 → 返回 conflict，前端弹窗展示两张图片
            │                   用户选择：覆盖 / 跳过 / 保留两者
            └── 无法判断任一拍摄时间 → 降级为"拍摄时间相同"的冲突处理
```

### 7.3 冲突 UI

```
┌──────────────────────────────────────────────────────┐
│  文件名冲突：IMG_001.jpg                              │
├──────────────────────────────────────────────────────┤
│                                                       │
│   已有图片                    新上传图片               │
│  ┌──────────────┐          ┌──────────────┐          │
│  │  [缩略图]     │          │  [缩略图]     │          │
│  │              │          │              │          │
│  │ 拍摄: 2024-02│          │ 拍摄: 2024-02│          │
│  │ Canon EOS R5 │          │ Canon EOS R5 │          │
│  │ 大小: 280 KB │          │ 大小: 320 KB │          │
│  └──────────────┘          └──────────────┘          │
│                                                       │
│   两张图片的拍摄时间相同，可能是重复文件。              │
│                                                       │
│   ○ 覆盖已有图片（删除旧图，保留新图）                 │
│   ○ 跳过（保留旧图，丢弃新图）                        │
│   ○ 保留两者（新图加序号后缀另存）                     │
│                                                       │
│                        [确认]                         │
└──────────────────────────────────────────────────────┘
```

用户选择后，前端在 upload 请求中带 `conflict_resolution` 参数重传，后端执行对应操作。

---

## 8. API 设计

### 8.1 新增 Go 后端 API

```
# ── 图片上传（方式 2：Web 交互上传）──

POST   /api/v1/photos/upload
       表单字段：
         file                  压缩后的 JPEG（multipart）
         original_name         原始文件名
         original_shot_at      前端读取的 EXIF 拍摄时间（RFC 3339，可选）
         conflict_resolution   冲突处理策略（可选，"overwrite"|"skip"|"keep_both"）
       响应 200：
         status: "stored" | "conflict"
         photo_id: "..."
         conflict: {                       # 仅 status="conflict" 时存在
           existing_photo_id: "..."
           existing_thumbnail_url: "..."
           new_shot_at: "..."
           existing_shot_at: "..."
         }

# ── VLM 队列控制 ──

POST   /api/v1/vlm/queue/start
       请求体：{ force?: bool }    # 是否强制重新处理已有描述的图片（默认 false）
       响应 200：{ task_id, total }

POST   /api/v1/vlm/queue/stop
       响应 200：{ stopped: true }

GET    /api/v1/vlm/queue/status
       响应 200：{
         running: bool,
         total: int,
         completed: int,
         failed: int,
         current_file?: string,     # 当前正在处理的文件名
       }

# ── 单张 VLM 处理 ──

POST   /api/v1/photos/:id/describe
       将指定图片加入 VLM 队列。如果队列未运行，自动启动消费循环。
       响应 200：{ queued: true }
```

### 8.2 已有 API（不变）

```
GET    /api/v1/photos              照片列表（分页 + 多条件过滤）
                                   列表项增加 has_description: bool 字段
GET    /api/v1/photos/stats        照片统计
GET    /api/v1/photos/:id          照片详情（增加 description 字段）
GET    /api/v1/photos/:id/image    图片文件（?size=thumb）
PUT    /api/v1/photos/:id/tags     更新标签
```

### 8.3 服务器目录批量导入 API（后续 Phase）

```
POST   /api/v1/photos/batch-import
       请求体：{ source_dir, concurrency?, no_dedup? }
       响应 200：{ task_id, total }
       # 仅做扫描 + 导入，不触发 VLM

GET    /api/v1/photos/batch-import/:task_id
       响应 200：{ status, total, added, skipped, logs[] }
```

### 8.4 Python Agent 后端 API（后续设计）

本阶段不涉及。后续对话功能设计时补充。

---

## 9. 前端项目结构

参考 pflow 结构：

```
web/
├── index.html
├── package.json
├── vite.config.ts               # dev 代理 /api → Go :10000
├── tsconfig.json
├── tsconfig.app.json
├── tsconfig.node.json
└── src/
    ├── main.ts
    ├── App.vue                  # NConfigProvider + 左侧边栏 + 视图切换
    ├── config/
    │   └── index.ts             # API 地址、压缩参数等常量
    ├── types/
    │   ├── photo.ts             # Photo 类型
    │   └── upload.ts            # Upload 相关类型
    ├── composables/
    │   ├── usePhotos.ts         # 照片列表数据
    │   ├── useUpload.ts         # 上传状态管理
    │   └── useVlmQueue.ts       # ★ VLM 队列状态轮询（§6）
    ├── components/
    │   ├── PhotoCard.vue        # 照片卡片（含描述状态按钮）
    │   ├── PhotoGrid.vue        # 照片网格
    │   ├── PhotoDetail.vue      # 照片详情 NDrawer（含描述 + 重新生成）
    │   ├── DescriptionModal.vue # ★ VLM 描述内容弹窗
    │   ├── UploadModal.vue      # 上传弹窗容器
    │   ├── UploadDropZone.vue   # 拖拽/选择区域
    │   ├── FileList.vue         # 待上传文件列表
    │   ├── ConflictModal.vue    # 去重冲突弹窗
    │   └── SideMenu.vue         # 左侧功能导航
    ├── views/
    │   └── PhotoManagement.vue  # 图片管理页面
    └── assets/
```

### 9.1 Vite 代理配置

```ts
// vite.config.ts
export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:10000',   // Go 基建后端
        changeOrigin: true,
      },
      // Python Agent 后端（后续启用）
      // '/agent': {
      //   target: 'http://localhost:8000',
      //   changeOrigin: true,
      // },
    },
  },
})
```

---

## 10. 组件状态设计

### 10.1 图片管理页面

```
photoManagement:
  photos: Photo[]             # 当前页列表
  total: number               # 总数
  page: number                # 当前页
  pageSize: number            # 每页数（默认 24）
  loading: boolean
  error: string | null

  selectedPhoto: Photo | null  # 详情抽屉
  showDetail: boolean

  showUploadModal: boolean     # 上传弹窗
  showBatchVlmModal: boolean   # 批量处理弹窗
```

### 10.2 上传弹窗

```
uploadModal:
  files: UploadFile[]          # 已添加文件列表
  uploading: boolean
  conflictQueue: ConflictItem[] # 待处理冲突队列

UploadFile:
  id: string                  # 前端临时 ID
  originalFile: File
  originalName: string
  originalSize: number
  compressedBlob: Blob | null
  compressedSize: number | null
  compressStatus: 'pending' | 'compressing' | 'done' | 'error'
  uploadStatus: 'pending' | 'uploading' | 'done' | 'conflict' | 'error'
  shotAt: string | null       # 前端读取的 EXIF 拍摄时间
```

### 10.3 VLM 队列状态（全局，useVlmQueue composable）

```
vlmQueue:
  running: boolean               # 队列是否运行中
  total: number                  # 本轮总任务数
  completed: number              # 已完成数
  failed: number                 # 失败数
  currentFile: string | null     # 当前处理中的文件名
  polling: boolean               # 是否正在轮询
```

---

## 11. 分阶段计划

### Phase 1（当前）：图片上传与管理 + VLM 队列

1. 初始化 Vue 项目（Vite + Naive UI + TypeScript）
2. 主页面框架（左侧边栏 + 内容区）
3. 图片管理页面（网格展示 + 分页 + 描述状态按钮）
4. 图片详情抽屉（含描述展示 + 单张触发 VLM）
5. DescriptionModal（描述内容弹窗 + 重新生成）
6. 上传弹窗（文件选择 + 拖拽 + 前端压缩 + 上传）
7. 去重冲突弹窗
8. **Go 后端：抽象 VLM 处理管线为 service**（batch_vlm 和 Web API 共用）
9. Go 后端：上传 API + 去重逻辑 + 冲突处理
10. **Go 后端：VLM 队列服务**（vlm_queue.go + start/stop/status/enqueue API）
11. **前端：useVlmQueue 轮询 + 全局开关 + 进度指示器 + 中止按钮**

### Phase 2（后续）：服务器目录批量导入

1. Go 后端：batch-import API（扫描目录 + 导入元数据，不触发 VLM）
2. BatchImportModal（源目录配置 + 导入进度）
3. 导入完成后自动衔接 VLM 队列

### Phase 3（后续）：智能对话

1. 对话页面
2. Python Agent 后端接入
3. 流式输出

### Phase 4（后续）：高级功能

1. VLM 描述展示与编辑
2. 标签管理
3. 搜索与多维过滤
4. 批量操作

---

## 12. 待决策项

1. **前端压缩参数**：最大 2048px / 质量 0.85 / 最大 500KB 是否合理？（影响 VLM 分析精度 vs 带宽/存储）
2. **前端压缩库**：用 `browser-image-compression` 还是 `compressorjs`？
3. **前端 EXIF 库**：`exifr`（轻量，推荐）还是 `exif-js`？
4. **HEIC 支持**：在前端转 JPEG（可用 `heic2any`）还是后端处理？
5. ~~上传后 VLM 处理方式~~ → 已确定：后端 VLM 任务队列 + 全局开关 + 单张触发（§6）。
6. **批量导入 source_dir 范围限制**：是否限制为 `config.yaml` 中 `storage.photo_src` 的子目录？安全考虑。（Phase 2 再议）
