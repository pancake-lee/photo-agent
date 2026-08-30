# AI 评估模式操作指南

> 本文档是 `work-modes.md` 评估模式的补充，定义 AI 在评估时如何按维度评分、收集证据、输出报告。
> 评估器是"判卷老师"：只判断好坏，不提出解决方案。

---

## 评分标准速查

各维度 1-10 分，评分锚点：

| 分数 | 含义 | 判断标准 |
|------|------|----------|
| 10 | 无可挑剔，超出预期 | 不仅满足所有要求，还有让人意外的亮点 |
| 8-9 | 良好，有小的改进空间 | 满足主要要求，边缘情况处理到位 |
| 6-7 | 可接受，有明显改进点 | 核心功能 OK，但存在技术债或覆盖不足 |
| 4-5 | 不足，影响使用 | 功能缺陷、代码质量问题明显，需要返工 |
| 1-3 | 严重缺陷，不可交付 | 核心功能不可用、安全问题、设计方案的预期行为未实现 |

后端专项评估使用 [后端代码质量评分标准](../eval/code-quality-rubric-backend.md)：按八项加权为 100 分，并换算为十分制写入通用报告。该标准明确区分独立功能单测、Service 集成测试和用户用例闭环；不以 100% 单元测试覆盖率作为目标。每轮先运行评估范围清单脚本，以其输出决定纳入文件。

---

## 评分维度

### 代码质量

| 维度 | 评分要点 | 证据来源 |
|------|----------|----------|
| 正确性 | 是否实现设计方案的预期行为，边界情况处理如何 | 对比 design/*.md 与代码实现，跑相关测试/黄金用例 |
| 健壮性 | 错误处理、空值防护、异常路径覆盖 | 检查 error/err 处理模式，空值检查，边界输入 |
| 可维护性 | 命名、结构、注释、与项目编码规范的一致性 | 对比 `docs/handbook/coding-conventions.md`，检查函数长度、嵌套深度 |
| 简洁性 | 是否存在冗余代码、过度抽象、dead code | 检查是否有未使用的函数/导入，是否有过度设计 |

### 功能效果

| 维度 | 评分要点 | 证据来源 |
|------|----------|----------|
| 准确性 | 输出是否匹配预期，误判/遗漏程度 | curl/CLI 调功能，对比预期输出 |
| 完整性 | 覆盖度是否充分，有无遗漏维度或场景 | 对比设计文档中的功能范围 |
| 一致性 | 风格/格式与项目其他部分是否统一 | 对比现有功能的输出格式、UI 风格 |

### 用户价值

从用户视角评估输出是否有用，而非仅验证格式正确性。惊喜度、可用性、交互体验三项对所有面向用户的功能必评；AI 增量仅对依赖 AI/LLM 的功能启用。

| 维度 | 评分要点 | 证据来源 |
|------|----------|----------|
| 惊喜度 | 输出是否揭示了用户自己不会发现的关联？是否让人感到"这个角度我没想到"？ | 人工审视输出内容，判断每个结果的意外程度和创意质量 |
| 可用性 | 用户能否直接基于输出采取行动（如直接发布）？还是需要大量二次加工？ | 审视输出的标题/描述/角度，判断是否具体可操作 |
| 交互体验 | 操作流程是否顺畅？等待时间是否可接受？状态反馈是否及时清晰？结果呈现是否易于扫读？ | 实际操作功能流程，记录等待时间、加载状态、结果布局 |
| AI 增量 | 可选。这个输出需要 AI 才能产生吗？还是简单脚本 + LLM 润色就能得到？ | 理解功能的内部实现逻辑，判断 AI 在哪个环节真正增加了价值 |

---

## 评估流程

### 第零步：理解产品定义

在评分之前，先理解功能对用户的承诺：

1. 读取功能的 PRD 定义（`docs/prd.md` 对应章节）、设计方案（`docs/design/`）、或 backlog 条目中的背景描述
2. 提炼出功能解决什么用户问题、提供什么价值——这是用户价值评分的基准
3. 如果 PRD 中缺少该功能的定义，在评估报告的 `findings_for_backlog` 中记录

### 第一步：确认评估目标

1. 明确评估对象：用户指定的功能/代码/PR、或 backlog 中状态 = 「已开发」的条目
2. 读取相关上下文：设计文档（`docs/design/`）、验收条件、编码规范
3. 确定评分重点：代码质量为主、功能效果为主、还是两者兼顾
4. 若目标为 `backend/`：运行 `GOTOOLCHAIN=local go run ./tools/go/main.go --self-check`，以输出列明评估文件、数据状态和至少一条关键用户用例。

### 第二步：确认服务状态

```
make status
```

确认 backend（10004）、agent（10005）、web（10006）三个服务全部 HTTP 健康。如果服务未运行或需要重新编译，执行：

```
make stop && make start
```

`make start` 内部已含编译（`make dev`），无需单独编译。

### 第三步：逐维度评分

根据评估目标选择合适的维度（不必每次都评全部维度），每个维度：

1. **收集证据**：使用下方工具箱中的命令收集原始数据
2. **判断打分**：对照评分标准速查表给出分数
3. **列出得分点**：具体指出哪里做得好（引代码行、贴输出片段）
4. **列出失分点**：具体指出哪里不够好（同样要有具体证据）

后端专项评估必须覆盖《后端代码质量评分标准》的八项维度，并记录加权总分、阻断项、测试分层选择及用户用例闭环。发现废弃代码、过期配置或文档时，只记录现象和影响并写入 backlog；不得在评估模式中直接删除。

代码质量维度还可以用 Git diff 辅助：

```bash
# 查看最近一次提交的代码变更
git diff HEAD~1
# 或查看特定提交
git show <commit>
```

### 第四步：输出评估报告

按读者拆分双格式（规范详见 [2026-07-26-1-harness-design.md](../design/2026-07-26-1-harness-design.md)「2026-08-21 评估报告双格式规范」节），两个文件同目录同名：

**命名**：`{date}-{topic}.json` + `{date}-{topic}.md`，如 `2026-08-21-photo-list-lb-series`。topic 优先取对应 design 文档的主题名（design 与 report 尽量对应），无对应 design 时以 backlog 序号兜底（如 `2026-07-28-b10`）

**JSON**（面向程序：通过判定、基线更新、趋势追踪）只保留结构化字段：

```json
{
  "report_id": "2026-08-21-photo-list-lb-series",
  "backlog_id": "LB1-LB6",
  "created_at": "2026-08-21T23:30:00+08:00",
  "target": "LB 系列整体评估",
  "overall": 8.1,
  "per_task": { "LB1": 8.3, "LB2": 7.9 },
  "dimension_scores": { "正确性": 8.5, "健壮性": 7.5 },
  "findings_for_backlog": ["问题描述，可直接导入 backlog"],
  "verification_runtime": ["go test PASS", "Playwright 导航跳转实测"],
  "verification_commits": { "LB1": "f19b2e4" }
}
```

**Markdown**（面向人工：复盘、代码审查参考）完整承载描述性内容：

- 摘要：总分 + 通过结论 + 一句话总结
- 分维度评分：每个维度得分 + 得分点/失分点（JSON 中移除的 strengths/weaknesses 全部在此）
- per_task 评分与简评（多任务报告）
- 执行证据：运行时验证、commits 完整证据链
- 下一步建议：由 findings_for_backlog 提炼方向

### 第五步：更新文档

- 评估通过（总分 ≥ 6 且无 1-3 分的维度）→ 更新 `docs/backlog.md` 条目状态为 Done
- 评估不通过 → 在 backlog 中新增条目（**只描述问题现象和严重程度，不写方案**），状态 = 待规划
- 首次为某维度建立基线 → 更新 `docs/eval/baseline.md`
- **回写评估分数到 backlog**：在任务总览表的「评估」列填入综合总分；在任务详情区增加 `- **评估**：<总分>（<维度1> <分> <维度2> <分> ...），详见 [报告文件名](../data/eval_reports/<报告文件名>)` 一行。各维度得分横向展开不换行，不写得分解
- **回写方案验收列表**：评估过程必然对照验收标准逐项检查，结果应回写到验收清单中。如果任务有独立 design 文档，勾选 `docs/design/` 对应文档的验收项；如果任务方案直接记录在 backlog 中，则勾选 backlog 条目自身的验收清单。代码审查可验证的直接勾选，需运行时验证的标注「需运行时」后留待用户确认

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
.venv/bin/python3 chain/photo_agent.py -c ../.local/my-config.yaml --suggest

# RAG 评估
.venv/bin/python3 chain/photo_agent.py -c ../.local/my-config.yaml --eval

# 运行 suggest 单元测试
.venv/bin/python3 chain/test_suggest_smoke.py
```

### Web 页面检查

通过 Playwright CLI 自动化 Web 页面交互：

```bash
node tools/node/web_check.mjs \
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

### 代码检查

```bash
# 查看 Git diff（最近的代码变更）
git diff HEAD~1

# 查看特定提交
git show <commit>

# 查看某文件的变更历史
git log --oneline -5 -- <file>
```

---

## 维度 → 工具映射

| 维度 | 首选工具 | 示例 |
|------|---------|------|
| 正确性 | `curl` + 对比设计文档，`sqlite3` 验证数据 | "API 返回了 5 条建议与设计预期一致" |
| 健壮性 | 读代码（error 处理、nil 检查）| "parseVlmAttrs 在 JSON 解析失败时返回空字符串，调用方未判断" |
| 可维护性 | 读代码 + 对比 coding-conventions.md | "函数命名符合规范，但 syncUpdatePhoto 已超过 80 行" |
| 简洁性 | 读代码（Git diff 或完整文件）| "新增的 needAttrBackfill 变量实际只在 if 条件中使用一次" |
| 准确性 | `curl` + 手动检查 JSON | "5 条建议中 4 条合理，1 条推荐的'雪山之峰'照片实际不是雪山" |
| 完整性 | `grep` / `Read` 日志 + 对比设计文档 | "三个分析维度中两个维度有产出，时间线规律维度为空" |
| 一致性 | `curl` + `Read` 对比现有输出格式 | "输出 JSON 结构与 cluster API 格式一致" |
| 惊喜度 | 人工审视输出 + 对比产品定义 | "5 条建议中 0 条有跨场景关联，均为同场景相似照片组合" |
| 可用性 | 人工审视输出 + 判断可操作性 | "建议标题泛化，'静谧时光集'可套在任何安静照片组上" |
| 交互体验 | 实际操作功能流程 + Web 检查 | "点击按钮后 30s 才出结果且无进度提示，用户不知道是否卡死" |
| AI 增量 | 读代码理解实现逻辑（可选） | "核心逻辑是频率统计 + LLM 润色，AI 未做发现层面的智能工作" |
| 逻辑推导 | AI 基于已有证据推理 | "已有照片无需重新 VLM，仅 AutoSync 即可完成回填" |

---

## 常见评估场景速查

### 评估代码修复质量

1. `make status` 确认服务运行
2. `git diff HEAD~1` 查看代码变更
3. 按代码质量维度评分（正确性/健壮性/可维护性/简洁性）
4. 调用 API/CLI 验证功能效果
5. 查日志确认无 WARNING/ERROR
6. 保存报告，更新 backlog

### 评估功能效果（非 Bug 修复）

1. 理解产品定义（第零步），明确功能对用户的承诺
2. 触发功能，收集输出
3. 对比设计文档中的预期行为
4. 按功能效果维度评分（准确性/完整性/一致性）
5. 按用户价值维度评分（惊喜度/可用性/交互体验，AI 增量可选）
6. 识别亮点和不足
7. 对于不足：写入 backlog（只描述问题，不写方案）

### 回归检查（改代码后）

1. 运行已有评估脚本（如 `--eval`）
2. 对比 `docs/eval/baseline.md` 中的历史指标
3. 标记显著下降的维度（P@10/MRR 下降 > 10%）

### 后端基线评估（功能开发前或治理复评）

1. 运行评估范围清单脚本，人工确认其输出后再明确关键用户用例
2. 从清单中的 Proto/API 建立到 Service → DAO/外部客户端的调用图
3. 在 `backend/` 下运行 `GOTOOLCHAIN=local go test ./...`，为高风险独立逻辑补单测，为关键用户路径执行 API/CLI 闭环
4. 逐项给出八项加权分数；阻断项或总分低于 60 时，创建只描述问题现象的 backlog 条目
5. 由规划模式决定废弃代码清理、重构和测试补充的具体方案，完成后以同一用户用例复评

---

## 注意事项

- 评估不修改代码，只收集信息和判断。需要修改时路由到规划/生成模式
- 评估不提出"应该怎么改"，只指出"哪里不够好"。改进方案由规划模式产出
- 数据库查询是只读操作，不要执行 INSERT/UPDATE/DELETE
- API 调用可能触发 LLM 费用（如 `/api/suggest/run`），运行前告知用户
- 服务启动后 AutoSync 可能阻塞（同步扫描 1177 张照片），`make status` 等待 HTTP 健康后再继续
- Web 页面检查耗时较长（等待 LLM 响应），超时设置建议 120s+
