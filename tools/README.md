# 开发工具

`tools/` 存放跨模块的开发、验证和仓库治理工具，不放业务服务的内部脚本。只服务单个模块的脚本仍放在其所属模块中，例如 `agent/scripts/`。

## 目录约定

每种语言占用一个一级目录，语言依赖、锁文件和可执行程序均放在该目录内：

```text
tools/
├── go/       # Go 工具
└── node/     # Node 与 Playwright 工具
```

每种语言对外只保留一个命令入口。新增功能通过入口的子命令或参数选择，不新增并列的可执行文件。Go 工具功能增长后，参考 `/root/code/pgo/cmd/pgo/main.go` 的单入口命令框架承载多个子命令；其他语言沿用相同的「入口 + 功能参数」交互形式。

当前 Go 工具只有后端评估范围一项功能，因此以 `go/main.go` 作为唯一入口，暂不引入命令框架：

```sh
GOTOOLCHAIN=local go run ./tools/go/main.go --self-check
```

## Node 迁移过渡

本次按最小迁移保留两个既有 Node 脚本的调用方式，不改变其逻辑：

```sh
node tools/node/web_check.mjs <参数>
node tools/node/golden_query_ui_regression.mjs
```

它们是单入口约定的临时例外。下次为 Node 工具增加功能时，应先合并为 `tools/node/main.mjs <功能>`，再添加新能力；Node 依赖与锁文件只维护在 `tools/node/`，运行产物 `node_modules/` 不提交。
