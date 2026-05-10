# Dify 配置指南

> 本指南说明如何配置 Dify，使其与 Photo Agent Go 后端协同工作。
> 配置分为两部分：代码化（知识库初始化脚本 + DSL 文件）和 手动（模型供应商、工具授权）。

## 前置条件

- Go 后端已启动并运行（`./server`）
- Dify 容器已启动（`cd dify && docker compose up -d`）
- 照片已导入 SQLite 数据库（通过 `/api/import/jobs`）

## 步骤一：启动 Dify

```bash
cd dify
cp .env.example .env
# 编辑 .env，修改 SECRET_KEY 为一个随机字符串
docker compose up -d
```

访问 `http://localhost`，注册管理员账户。

## 步骤二：配置模型供应商

在 Dify UI 中：

- 右上角头像 → 设置 → 模型供应商
- 添加你使用的 LLM（如 OpenAI GPT-4o-mini 或火山引擎）
- 配置 API Key 和模型参数
- 设置系统推理模型和 Embedding 模型

## 步骤三：代码化初始化知识库

运行初始化脚本，自动创建知识库并上传照片描述：

```bash
cd backend
go run cmd/init_dify/main.go \
  --email    "你的Dify邮箱" \
  --password "你的Dify密码" \
  --dify-url "http://localhost"
```

脚本会：
- 登录 Dify 获取 auth token
- 创建名为"照片描述库"的知识库（或复用已有）
- 读取 SQLite 中所有照片描述
- 批量上传到知识库
- 等待 Embedding 索引完成
- 输出 Dataset ID（后续步骤需要）

## 步骤四：创建 Agent 应用

### 方式 A：导入 DSL（推荐，用于版本控制）

项目中维护了 `dify/dsl/photo-agent.yml`，包含完整的 Agent 配置：

- 系统提示词
- 模型参数
- 知识库引用
- 工具绑定

导入步骤：

1. Studio → 创建空白应用 → 导入 DSL 文件
2. 选择 `dify/dsl/photo-agent.yml`
3. Dify 会自动重建 Agent 配置

导入后需要补充的操作：
- 在"上下文"区域绑定知识库（选择步骤三创建的知识库）
- 检查工具绑定是否正确（工具需先完成步骤五）

### 方式 B：手动创建

如果不使用 DSL 导入，按以下步骤手动创建：

1. Studio → 创建空白应用 → 选择 Agent
2. 应用名称：Photo Agent

#### 系统提示词

在"提示词编排"中粘贴：

```
你是 Photo Agent，一位个人摄影资产助手。你帮助用户通过自然语言检索照片、回顾拍摄经历、分析摄影主题。

可用能力：
1. 通过知识库检索照片描述（语义搜索）
2. 通过工具查询时间线和标签
3. 基于历史作品提供创作建议
4. 通过工具导入本地照片文件夹

回答时：
- 如果提到具体照片，使用 Markdown 图片语法展示照片，格式：![描述](http://host.docker.internal:8080/api/photos/{photo_id}/image)
- 时间线查询使用 list_timelines / get_photos_by_timeline 工具
- 标签查询使用 get_photos_by_tags 工具
- 导入照片使用 import_photos 工具
- 模糊描述检索使用知识库 RAG（自动）
```

#### 模型配置

- Agent 模式：Function Calling
- 系统推理模型：选择你配置的 LLM（如 GPT-4o-mini）
- 最大迭代次数：5

#### 绑定知识库

- 在"上下文"区域添加知识库
- 选择步骤三中创建的知识库（照片描述库）
- 检索设置：Top-K = 5，分数阈值 = 0.5

## 步骤五：导入自定义工具

自定义工具（OpenAPI Schema）在 Dify 中是**工作空间级别**的配置，需要在导入 DSL 之前完成：

1. 工具 → 自定义 → 创建自定义工具
2. 上传文件：`docs/dify_tools_openapi.yaml`
3. 服务器地址确认：`http://host.docker.internal:8080`
4. 保存

然后在 Agent 应用的"工具"区域启用需要的工具：
- list_timelines
- get_photos_by_timeline
- get_photos_by_tags
- get_photo_detail
- import_photos
- get_import_status

## 步骤六：发布应用

- 点击右上角"发布"
- 选择"运行"
- 在聊天界面中测试：
  - "列出所有时间线"
  - "帮我找云南的雪山照片"
  - "导入 ~/Photos/"

## DSL 版本控制

`dify/dsl/photo-agent.yml` 纳入 Git 管理，变更流程：

```
在 Dify UI 中修改 Agent 配置
        ↓
导出 DSL 文件，覆盖项目中的 photo-agent.yml
        ↓
Git diff 审查变更
        ↓
提交到版本库
```

这样 Agent 的每次迭代都有版本记录，可回滚、可迁移。

**DSL 包含的内容**：系统提示词、模型参数、知识库引用、工具绑定。
**DSL 不包含的内容**：模型 API Key、工具认证信息、知识库实际数据（这些通过其他方式管理）。

## 常见问题

**Q: Go Backend 的地址为什么是 host.docker.internal:8080？**
A: Dify 运行在 Docker 容器内，需要通过 `host.docker.internal` 访问宿主机的 Go 后端。如果部署在不同机器上，请替换为实际可访问的 IP 地址。

**Q: 图片在 Dify 聊天中无法显示？**
A: 确保图片 URL 可被 Dify 容器访问。宿主机部署时使用 `host.docker.internal:8080`，远程部署时替换为公网地址。

**Q: 知识库检索结果不准确？**
A: 检查 VLM 生成的描述质量。描述越详细，检索效果越好。可在 Dify 知识库设置中调整检索参数（Top-K、分数阈值）。

**Q: 导入 DSL 后工具绑定丢失？**
A: 自定义工具是工作空间级别的配置。导入 DSL 前，需要先在当前工作空间中导入 `docs/dify_tools_openapi.yaml`。如果工具名称与 DSL 中引用的不一致，需要手动重新绑定。
