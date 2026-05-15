# Photo Agent 部署与操作手册

> 从零到可聊天的完整操作流程。

---

## 前置准备

### 1. 准备配置文件

复制公共配置模板到个人目录并编辑：

```bash
cp ./configs/config.yaml .local/my-config.yaml
# 编辑 .local/my-config.yaml，填入你的 API Key、照片路径等
```

**说明**：

- `./configs/config.yaml` 是脱密的公共模板，**不要直接编辑**，避免敏感信息意外提交到 Git
- 复制到 `.local/`（已加入 `.gitignore`）后按需修改
- `storage.timeline_path` 指向一个 Markdown 表格文件，记录活动时间线（见下方格式）
- `vlm.*` 配置三选一：volcengine / openai / qwen

### 2. 准备时间线文件

创建 `data/timeline.md`，格式如下：

```markdown
| 时间 | 活动 | like | post |
|------|------|------|------|
| 2024-02-01 ~ 2024-02-05 | 云南旅游 | | |
| 2024-03-07 | 生日 | | |
```

支持单日、日期范围（`~` 分隔）、月份精度。程序根据照片 EXIF 拍摄时间匹配对应活动。

### 3. 准备照片

将原始照片放入任意目录（如 `/root/project/photos/`），不约束目录结构。

---

## 第一步：编译后端

```bash
cd /root/code/photo-agent
make backend
```

产出四个可执行文件到 `bin/`：

- `server` — Go 后端服务
- `batch_vlm` — 批量 VLM 预处理脚本
- `init_dify` — Dify 知识库初始化脚本
- `backendTest` — E2E 测试程序

---

## 第二步：图片预处理（VLM 描述生成）

所有照片必须先经此步骤生成描述，server 导入时不再实时调用 VLM。

```bash
cd /root/code/photo-agent
./bin/batch_vlm \
  -c ./configs/config.yaml \
  -input /root/project/photos/
```

参数说明：

- `-c` — 配置文件路径
- `-input` — 照片根目录
- `-force` — 强制重新处理（可选）
- `-dry-run` — 仅验证配置，不实际调用（可选）

脚本会自动：

- 扫描所有图片（jpg / png / jpeg / webp）
- 压缩超大图片（ImageMagick，512x512，质量 85）
- 调用 VLM API 生成描述
- 输出到 `storage.descriptions_path`（默认 `./data/descriptions.json`）
- 已有描述和压缩图会自动跳过

---

## 第三步：启动 Go 后端

```bash
./bin/server -c ./configs/config.yaml
```

server 启动后会**自动执行一次同步**：

- 扫描 `storage.photo_path` 目录下所有图片
- 读取 `descriptions.json` 中的预生成描述
- 对比 SQLite `photos` 表，执行增量导入
  - **新照片**：读取 EXIF、匹配时间线、写入 SQLite
  - **已有照片**：如 `descriptions.json` 中描述有变化，自动更新
  - **无变化**：跳过
- 如已配置 `dify.api_key` 和 `dify.dataset_id`，自动同步到 Dify 知识库

同步在后台 goroutine 中执行，不阻塞 server 启动。日志中会输出同步结果：

```
AutoSync: 45 images scanned, 0 existing in DB
AutoSync done: new=45, updated=0, skipped=0
```

**后续新增照片**：只需把新照片放入原目录，重新运行 `batch_vlm`（会自动跳过已有描述），然后重启 server 即可自动同步增量。

**手动触发同步**：如需立即重新同步（不重启 server），可调用 import API：

```bash
curl -X POST http://localhost:10000/api/import/jobs \
  -H "Content-Type: application/json" \
  -d '{"source_path":"/your/photo/path","recursive":true}'
```

验证健康检查：

```bash
curl http://localhost:10000/api/health
# {"status":"ok"}
```

---

## 第四步：启动 Dify

```bash
cd dify
cp .env.example .env
# 编辑 .env，修改 SECRET_KEY 为一个随机字符串
docker compose up -d
```

访问 `http://localhost`，注册管理员账户。

---

## 第五步：配置模型供应商

在 Dify UI 中：

1. 右上角头像 → 设置 → 模型供应商
2. 添加你使用的 LLM（如火山引擎 Doubao / OpenAI GPT-4o-mini）
3. 配置 API Key 和模型参数
4. 设置系统推理模型和 Embedding 模型
   - 系统推理模型：选择你添加的 LLM（如 Doubao-seed-1.6）
   - Embedding 模型：如需使用火山引擎多模态 Embedding，需通过 Go 后端代理（地址为 `http://host.docker.internal:10000/v1`），选择 openai-api-compatible 插件配置

---

## 第六步：初始化知识库（首次或补同步）

server 启动时的自动同步需要 `dify.api_key` 和 `dify.dataset_id`。首次部署时知识库尚未创建，需要运行 init_dify 脚本初始化：

```bash
./bin/init_dify -c ./configs/config.yaml
```

脚本会自动：

- 登录 Dify Console
- 查找或创建知识库（按 `dify.dataset_name` 匹配）
- 获取知识库 API Key
- 从 SQLite 读取照片描述并批量上传到知识库

执行完成后输出知识库 ID，将其写入配置文件 `dify.dataset_id` 字段。后续 server 重启时会自动使用该配置同步增量数据。

**非首次**：如已配置 `dataset_id` 且 server 已自动同步，此步骤可跳过。仅用于知识库重建或批量补同步。

---

## 第七步：导入自定义工具

自定义工具是工作空间级别的配置，需在导入 DSL 之前完成：

1. Dify UI → 工具 → 自定义 → 创建自定义工具
2. 上传文件：`docs/dify_tools_openapi.yaml`
3. 服务器地址：`http://host.docker.internal:10000`
4. 保存

工具列表：

- `list_timelines` — 列出所有时间线
- `get_photos_by_timeline` — 按时间线查照片
- `get_photos_by_tags` — 按标签查照片
- `get_photo_detail` — 获取单张照片详情
- `import_photos` — 创建照片导入任务
- `get_import_status` — 查询导入任务进度

---

## 第八步：导入 Agent DSL

1. Studio → 创建空白应用 → 导入 DSL
2. 选择 `dify/dsl/photo-agent.yml`

导入后补充操作：

- 在"上下文"区域绑定知识库（选择第六步创建的知识库）
- 检查"工具"区域是否已启用全部 6 个自定义工具
- 如工具绑定丢失，先在第七步确认工具已导入，再重新绑定

---

## 第九步：发布并开始聊天

1. 点击右上角"发布"
2. 选择"运行"
3. 在聊天界面中测试：
   - "列出所有时间线"
   - "帮我找云南的雪山照片"
   - "导入 ~/Photos/"

---

## DSL 版本控制

`dify/dsl/photo-agent.yml` 纳入 Git 管理。变更流程：

```
在 Dify UI 中修改 Agent 配置
        ↓
导出 DSL 文件，覆盖项目中的 photo-agent.yml
        ↓
Git diff 审查变更
        ↓
提交到版本库
```

---

## 常见问题

**Q: Go Backend 的地址为什么是 `host.docker.internal:10000`？**
A: Dify 运行在 Docker 容器内，需要通过 `host.docker.internal` 访问宿主机的 Go 后端。如果部署在不同机器上，请替换为实际可访问的 IP 地址。

**Q: 图片在 Dify 聊天中无法显示？**
A: 确保图片 URL 可被 Dify 容器访问。宿主机部署时使用 `host.docker.internal:10000`，远程部署时替换为公网地址。

**Q: 知识库检索结果不准确？**
A: 检查 VLM 生成的描述质量。描述越详细，检索效果越好。可在 Dify 知识库设置中调整检索参数（Top-K、分数阈值）。

**Q: 导入 DSL 后工具绑定丢失？**
A: 自定义工具是工作空间级别的配置。导入 DSL 前，需要先在当前工作空间中导入 `docs/dify_tools_openapi.yaml`。如果工具名称与 DSL 中引用的不一致，需要手动重新绑定。

**Q: 导入 DSL 后查看应用详情报错 `InFailedSqlTransaction`？**
A: 之前的导入尝试损坏了 PostgreSQL session。执行 `cd dify && docker compose down && docker compose up -d` 重启容器后重试。
