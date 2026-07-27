# AI 评估模式操作指南

> 本文档是 `work-modes.md` 评估模式的补充，定义 AI 在评估时如何利用脚手架工具收集证据、验证修复效果。
> 工具设计原则：AI 是判断者，工具只提供原始数据，不做业务判断。

---

## 评估流程

当用户说"评估 XXX"时，AI 按以下流程执行：

### 第一步：确认评估目标

1. 读 `docs/backlog.md`，找到对应条目及其验收条件（AC）
2. 如果 AC 不够具体，向用户澄清后再继续
3. 对于已修复待验证的条目（状态=已开发），目标是逐条验证 AC

### 第二步：确认服务状态

```
make status
```

确认 backend（10004）、agent（10005）、web（10006）三个服务全部 HTTP 健康。如果服务未运行或需要重新编译，执行：

```
make stop && make start
```

`make start` 内部已含编译（`make dev`），无需单独编译。

### 第三步：逐条验证 AC

根据 AC 类型选择对应的检查工具（见下方工具箱）。每条 AC 收集证据后立即判断通过/失败，不等所有检查跑完。

### 第四步：保存评估报告

将检查结果写入 `data/eval_reports/eval-{backlog_id}-{date}.json`，格式：

```json
{
  "report_id": "eval-{uuid12}",
  "backlog_id": "B1",
  "created_at": "2026-07-27T...",
  "checks": [
    {"ac": "AC1: ...", "tool": "sqlite3", "result": "passed", "evidence": "objects 97% (1141/1177), ..."},
    {"ac": "AC2: ...", "tool": "curl", "result": "passed", "evidence": "返回 4 个建议，无 error"}
  ],
  "overall_passed": true,
  "notes": "AI 判断：全部 AC 通过"
}
```

### 第五步：更新文档

- 评估通过 → 更新 `docs/backlog.md` 条目状态为 Done
- 评估失败 → 在条目「分析」字段记录失败原因，状态保持「已开发」
- 首次为某维度建立基线 → 更新 `docs/eval/baseline.md`

---

## 工具箱

### 服务管理

| 操作 | 命令 |
|------|------|
| 检查状态 | `make status`（含 HTTP 健康检查） |
| 停止服务 | `make stop` |
| 启动服务（含编译） | `make start` |

### 数据库检查

SQLite 数据库路径：`data/sqlite/photo_agent.db`

直接使用 `sqlite3` CLI 查询：

```bash
# 统计属性非空率
sqlite3 data/sqlite/photo_agent.db \
  "SELECT COUNT(*) AS total,
    ROUND(100.0*SUM(CASE WHEN objects!='' THEN 1 END)/COUNT(*),1) AS objects_pct,
    ROUND(100.0*SUM(CASE WHEN colors!='' THEN 1 END)/COUNT(*),1) AS colors_pct,
    ROUND(100.0*SUM(CASE WHEN scene!='' THEN 1 END)/COUNT(*),1) AS scene_pct,
    ROUND(100.0*SUM(CASE WHEN lighting!='' THEN 1 END)/COUNT(*),1) AS lighting_pct,
    ROUND(100.0*SUM(CASE WHEN mood!='' THEN 1 END)/COUNT(*),1) AS mood_pct,
    ROUND(100.0*SUM(CASE WHEN composition!='' THEN 1 END)/COUNT(*),1) AS composition_pct
   FROM photos;"
```

```bash
# 查看特定照片的属性值（抽样）
sqlite3 data/sqlite/photo_agent.db \
  "SELECT id, objects, colors, scene, lighting, mood FROM photos LIMIT 5;"
```

### API 检查

Agent API 基址：`http://localhost:10005`

```bash
# suggest API
curl -sX POST http://localhost:10005/api/suggest/run | python3 -m json.tool

# 聚类结果
curl -s http://localhost:10005/api/cluster/results | python3 -m json.tool

# 评估报告列表
curl -s http://localhost:10005/api/eval/reports | python3 -m json.tool
```

### 日志检查

日志目录：`logs/`

```bash
# 搜索 agent 日志
grep "属性维度" logs/agent.log
grep "高频未成组\|时间线规律\|稀缺优质" logs/agent.log

# 查看最近的后端日志
tail -30 logs/backend.log

# 搜索 backend 日志中的 AutoSync 信息
grep "AutoSync" logs/backend.log
```

也可以使用 `Read` 工具完整读取日志文件（按需分页）。

### CLI 检查

部分功能支持 CLI 模式，无需通过 HTTP API：

```bash
cd agent

# 选题建议（需要 venv）
.venv/bin/python3 chain/photo_agent.py -c ../.local/pancake.yaml --suggest

# RAG 评估
.venv/bin/python3 chain/photo_agent.py -c ../.local/pancake.yaml --eval

# 运行 suggest 单元测试
.venv/bin/python3 chain/test_suggest_smoke.py
```

### Web 页面检查

通过 Playwright CLI 自动化 Web 页面交互：

```bash
node tools/web_check.mjs \
  --url "http://localhost:10006/#/suggest" \
  --click "button:has-text('生成选题建议')" \
  --wait-selector ".n-card, .n-empty" \
  --extract ".n-card .n-card-header__main" \
  --screenshot "data/eval_reports/web-{ts}.png" \
  --timeout 120000
```

参数说明：
- `--url`：页面地址（注意 hash 路由用 `/#/path`）
- `--click`：点击按钮的选择器（可选，不传则仅截图）
- `--wait-selector`：等待出现的 CSS 选择器，逗号分隔，任一出现即继续
- `--extract`：提取文本的 CSS 选择器（可选）
- `--screenshot`：截图路径，`{ts}` 替换为时间戳
- `--timeout`：超时毫秒数（默认 30000，LLM 调用场景建议 120000+）

输出 JSON 到 stdout。Playwright 未安装时 exit 2（跳过）并打印安装指引。

---

## AC 类型 → 工具映射

| AC 类型 | 首选工具 | 示例 |
|---------|---------|------|
| 数据库字段有值/非空率 | `sqlite3` 直接查询 | "objects 字段 ≥ 90% 非空" |
| API 返回特定结构/数量 | `curl` + 手动检查 JSON | "API 返回 3-5 个建议" |
| API 返回的 error 字段为空 | `curl` + 检查 `error` 字段 | "不返回'未发现候选选题方向'" |
| 日志含特定输出 | `grep` / `Read` 日志文件 | "agent.log 中三个维度不再全空" |
| CLI 输出正常 | `cd agent && .venv/bin/python3 ... --suggest` | "CLI --suggest 正常输出" |
| Web 页面展示正确 | `node tools/web_check.mjs` | "页面显示建议卡片而非空状态" |
| 文件存在/内容正确 | `Read` 或 `cat` | "data/clusters/ 下有结果文件" |
| 逻辑推导类 | AI 基于已有证据推理 | "已有照片无需重新 VLM" |

---

## 常见评估场景速查

### 验证 Bug 修复

1. `make status` 确认服务运行
2. 查 DB/API/日志确认修复生效
3. 对照 AC 逐条判断
4. 保存报告，更新 backlog

### 评估功能效果（非 Bug）

1. 触发功能，收集输出
2. 检查启发式规则（如有，通过 `POST /api/cluster/results/{id}/evaluate-themes`）
3. 检查日志中是否有 WARNING/ERROR
4. 人工或 LLM 判断输出质量

### 回归检查（改代码后）

1. 运行已有评估脚本（如 `--eval`）
2. 对比 `docs/eval/baseline.md` 中的历史指标
3. 标记显著下降的维度（P@10/MRR 下降 > 10%）

---

## 注意事项

- 评估不修改代码，只收集信息和判断。需要修改时路由到生成模式
- 数据库查询是只读操作，不要执行 INSERT/UPDATE/DELETE
- API 调用可能触发 LLM 费用（如 `/api/suggest/run`），运行前告知用户
- 服务启动后 AutoSync 可能阻塞（同步扫描 1177 张照片），`make status` 等待 HTTP 健康后再继续
- Web 页面检查耗时较长（等待 LLM 响应），超时设置建议 120s+
