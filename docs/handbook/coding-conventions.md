# 编码规范

> 按语言/模块分节。AI 在对应目录下工作时读取相关节。

---

## 通用规范

### Markdown 输出

- **减少**使用表格，**优先**使用标题层级（`##` / `###`）+ 无序列表（`-`）+ 缩进组织内容
  - 长文本内容会把表格撑得很宽，阅读体验差
  - 仅在数据对比（如配置参数对照）等真正适合表格的场景使用表格

### 文本类文件输出

- 尽量不使用破折号 `--` 或 `——` 来展开，大部分情况下都可以改成 `,` 或 `，`
- 写文章时，避免"下定义"口吻，保持平和的个人叙述：
  - 去掉绝对化措辞：本质上、其实很简单、极其、没有任何、就是
  - 加上个人限定：我觉得、我理解、我目前的看法是、试着
  - 比喻用于辅助理解，不要写成"这就是真理"的句式
  - 结论写成阶段性认识，而非终极答案

### 文档设计原则

- **设计文档只描述当前方案**：设计迭代中的中间产物不留痕迹
- **否决方向记录到 `docs/note.md`**：经审议明确否决的方向，记录拒绝理由，避免未来重复提出
- **设计文档不写否定性叙述**：不包含"曾考虑 X 但未采用"或"不需要 Y"

---

## Go（backend/）

### 优先复用 pgo 代码库

- `/root/code/pgo` 是本人维护的 Go 代码库，`pkg/` 下包含大量日常封装
- 本项目通过 `go.work` 直接引用本地 pgo，而非 import GitHub 版本
- 优先使用已有封装：`pconfig`（配置管理）、`plogger`（日志）、`putil`（HTTP/字符串/路径/时间工具）、`papp`（Runner 模式）
- 如发现 `pgo` 封装有缺陷或需扩展，可以同步维护 `pgo`

### 命名规范

- **列表/切片**：后缀 `List`（如 `userRoleList`、`permissionList`）
- **Map 结构**：后缀 `Map`（如 `roleIDMap`、`permissionMap`），更清晰时用 `keyToValueMap`（如 `idToUserMap`）
- **函数命名**：统一用"动宾"结构
  - C: `add` — 新增，尽量让一种数据的创建入口尽可能少
  - U: `edit` — 主动修改；`update` — 被动更新
  - R: `get` — 查询
  - D: `del` — 删除
  - 关联关系：`addXxxToYyy` / `delXxxFromYyy`
- **HTTP method**：GET（查询）、POST（创建）、PUT（全量更新）、PATCH（部分更新）、DELETE（删除）

### 格式化

- 逻辑修改后统一用 `gofmt -w <file>` 处理，不纠结缩进对齐

### 代码组织

- 避免 `if` 中使用 `;`（如 `if d, ok := data["k"]; ok`），易造成长代码
- 入口函数放在 `internal/<module>/<module>.go`，而非 `cmd/`
- 非复杂场景优先用基础类型组合，仅在复用明显或封装语义明确时抽象 `type`
- **接口代理模式**：基础类通过接口代理支持子类覆盖，子类初始化后调用 `BindProvider(self)`

### 数据访问边界

- ORM、生成查询对象、原始 SQL 和只读数据库连接只允许出现在 `internal/defaultService/data/`；Service 负责业务编排，不直接查表或写表
- `data` 层函数必须表达业务意图，而非暴露通用 ORM 操作。单表操作按明确动作命名，例如 `GetPhotoByID`、`UpdatePhotoDescription`；跨表、聚合或组装结果按返回的业务对象命名，例如 `GetUserInfo`
- 不为减少少量重复而新增泛化 DAO、可传入任意条件的查询接口或由 Service 拼接查询条件。字段投影、筛选和排序由 `data` 层以已知业务用法收敛
- 新增或调整数据访问时，同步为有业务规则的 DAO 行为补充临时 SQLite 测试；Service 测试只通过公开行为断言结果

### 测试

- 编写集成测试验证 Service 层逻辑
- 使用 `defer` + 清理函数移除测试数据
- **禁止**在测试中修改表结构，差异应正常报错以提醒升级注意

### 禁忌

- 不要直接 `go build` 到根目录
- `bootCheck` 的 MySQL 检查不允许执行 `DROP`、`TRUNCATE`、`ALTER ... MODIFY/CHANGE/RENAME`、删索引、删主键等危险 SQL
- 数据库结构不能 drop，仅代码层面废弃，实际数据清理由用户自行操作

### Go 工具链

- Always set `GOTOOLCHAIN=local` before running any `go` command
- 当 `go.mod` 的 `go` directive 高于系统 Go 版本时，不要依赖 auto-download，修复 go.mod directive 或更新系统 Go

---

## Python（agent/）

### 导入规范

- 使用**显式包名导入**（Go 风格限定调用）：`import langchain_openai as lc_openai`，调用时 `lc_openai.ChatOpenAI(...)`；项目内模块同样如此，`import chat.photo_rag as photo_rag`，调用点 `photo_rag.answer_question(...)`
- **禁止** `from xxx import <符号>` 导入项目内模块的类或函数（如 `from chat.session_store import SessionStore`），符号来源必须在调用点可见
- 例外：标准库与第三方包按 Python 惯例允许 `from` 导入，如 `from typing import Literal`、`from dataclasses import dataclass`、fastapi 的路由与模型导入、`from __future__ import annotations`
- 包名过长时允许简写别名，但至少保留一个单词方便阅读，如 `import langchain.schema as lc_schema`、`import langchain_core.prompts as lc_prompts`
- 别名与原名一致时写裸导入（`import photo_agent`），不要写 `import photo_agent as photo_agent` 式冗余别名
- 存量 `from import` 已于 2026-08-31（TIDY6）全部转换为限定调用，新增代码不得回退

### 环境管理（uv）

```
curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.12.4
uv python pin 3.12
uv venv
source .venv/bin/activate
uv init
uv sync
deactivate
```

---

## Web 前端（web/）

- 编写或修改前端布局前，先读 `docs/ui-rules.md`，检查设计方案是否符合基本的规则。仅逻辑修改则无需关心这个文档
- 优先使用 pnpm，而不是 npm，除非用户指定或目录/代码明显不是使用 pnpm
- 无需为验证改动而启动 Dev Server 并抓取页面检测，消耗太多 token
