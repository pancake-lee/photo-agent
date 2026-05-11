# Photo Agent 部署与操作手册

> 从零到可聊天的完整操作流程。

---

## 前置准备

### 1. 准备配置文件

复制 `backend/configs/` 下的示例配置，按需修改：

```toml
[server]
addr = ":8080"

[db]
sqlite_path = "./data/sqlite/photo_agent.db"

[storage]
photo_path = "./data/photos"
descriptions_path = "./data/descriptions.json"
timeline_path = "./data/timeline.md"

[vlm]
provider = "volcengine"
api_key = "your-vlm-api-key"
model = "doubao-vision-pro"
base_url = "https://ark.cn-beijing.volces.com/api/v3"
concurrency = 3
retry = 3
max_image_size_mb = 1

[dify]
base_url = "http://localhost"
email = "your-dify-email"
password = "your-dify-password"
dataset_name = "照片描述库"
```

**说明**：

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
cd /root/code/photo-agnet
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
cd /root/code/photo-agnet
./bin/batch_vlm \
  -c backend/configs/server.toml \
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
./bin/server -c backend/configs/server.toml
```

验证健康检查：

```bash
curl http://localhost:8080/api/health
# {"status":"ok"}
```

---

## 第四步：导入照片到数据库

```bash
curl -X POST http://localhost:8080/api/import/jobs \
  -H "Content-Type: application/json" \
  -d '{"source_path":"/root/project/photos/","recursive":true}'
```

返回导入任务 ID，异步处理。查询进度：

```bash
curl http://localhost:8080/api/import/jobs/{job_id}
```

导入流程：扫描目录 → 复用已压缩图片 → 读取 `descriptions.json` → 匹配时间线 → 写入 SQLite。无预描述时以空描述入库。

---

## 第五步：启动 Dify

```bash
cd dify
cp .env.example .env
# 编辑 .env，修改 SECRET_KEY 为一个随机字符串
docker compose up -d
```

访问 `http://localhost`，注册管理员账户。

---

## 第六步：配置模型供应商

在 Dify UI 中：

1. 右上角头像 → 设置 → 模型供应商
2. 添加你使用的 LLM（如火山引擎 Doubao / OpenAI GPT-4o-mini）
3. 配置 API Key 和模型参数
4. 设置系统推理模型和 Embedding 模型
   1. 火山的embedding要用openai的兼容api
   2. 还要写一个代理 `http//127.0.0.1:10000/v1`
   3. openai-api-compatible插件会帮你在加上 `/embeddings`
      1. 也正因如此，所以火山的url `https://ark.cn-beijing.volces.com/api/v3/embeddings/multimodal`无法直接配置，需要代理
   4. doubao-embedding-vision-251215
      1. doubao-embedding文档没有接入指引，url也不知道，模型id对不对也不知道，只能用vision版本

---

## 第七步：初始化知识库

运行 Go 脚本，自动登录 Dify、创建知识库、上传照片描述：

```bash
./bin/init_dify -c backend/configs/server.toml
```

脚本执行完成后输出知识库 ID，后续步骤需要用到。

---

## 第八步：导入自定义工具

自定义工具是工作空间级别的配置，需在导入 DSL 之前完成：

1. Dify UI → 工具 → 自定义 → 创建自定义工具
2. 上传文件：`docs/dify_tools_openapi.yaml`
3. 服务器地址：`http://host.docker.internal:8080`
4. 保存

工具列表：

- `list_timelines` — 列出所有时间线
- `get_photos_by_timeline` — 按时间线查照片
- `get_photos_by_tags` — 按标签查照片
- `get_photo_detail` — 获取单张照片详情
- `import_photos` — 创建照片导入任务
- `get_import_status` — 查询导入任务进度

---

## 第九步：导入 Agent DSL

1. Studio → 创建空白应用 → 导入 DSL
2. 选择 `dify/dsl/photo-agent.yml`

导入后补充操作：

- 在"上下文"区域绑定知识库（选择第七步创建的知识库）
- 检查"工具"区域是否已启用全部 6 个自定义工具
- 如工具绑定丢失，先在第八步确认工具已导入，再重新绑定

---

## 第十步：发布并开始聊天

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

**Q: Go Backend 的地址为什么是 `host.docker.internal:8080`？**
A: Dify 运行在 Docker 容器内，需要通过 `host.docker.internal` 访问宿主机的 Go 后端。如果部署在不同机器上，请替换为实际可访问的 IP 地址。

**Q: 图片在 Dify 聊天中无法显示？**
A: 确保图片 URL 可被 Dify 容器访问。宿主机部署时使用 `host.docker.internal:8080`，远程部署时替换为公网地址。

**Q: 知识库检索结果不准确？**
A: 检查 VLM 生成的描述质量。描述越详细，检索效果越好。可在 Dify 知识库设置中调整检索参数（Top-K、分数阈值）。

**Q: 导入 DSL 后工具绑定丢失？**
A: 自定义工具是工作空间级别的配置。导入 DSL 前，需要先在当前工作空间中导入 `docs/dify_tools_openapi.yaml`。如果工具名称与 DSL 中引用的不一致，需要手动重新绑定。

**Q: 导入 DSL 后查看应用详情报错 `InFailedSqlTransaction`？**
A: 之前的导入尝试损坏了 PostgreSQL session。执行 `cd dify && docker compose down && docker compose up -d` 重启容器后重试。
