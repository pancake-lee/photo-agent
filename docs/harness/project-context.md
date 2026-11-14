# Photo Agent 项目上下文

开始任务时先读取本页的项目约定，再按 Harness 总纲读取对应模式。

## 文档入口

- [产品规格](../product-specs/photo-agent.md)记录产品目标、行为与约束。
- [架构入口](../ARCHITECTURE.md)定位主要模块、依赖、数据流与稳定边界。
- [系统设计](../design-docs/system-design.md)提供专题设计索引、详细数据流、接口和模型约定。
- [当前任务](../backlog.md)记录规划、实施、状态和验收，设计门槛与数据约束见根部 Agent 规则。
- [版本记录](../version/README.md)提供版本快照和历史设计归档索引入口。
- 运行和部署按[部署指南](../deploy.md)，本地配置位于 `.local/`。
- 工作模式按[公共总纲](top/HARNESS.md)选择，项目运行证据入口见下节。

## 按任务加载的项目补充

- 修改 Go、DAO 或 Service 时读取 [Go 规范](styles/golang.md)的项目补充，保留 pgo 复用、数据访问层边界及测试约定。
- 修改 Python 时读取 [Python 规范](styles/python.md)的项目补充，保留显式包名导入与当前 uv 环境约定。
- 修改前端布局时读取 [Web 规范](styles/web.md)的项目补充及 [前端规则](FRONTEND.md#photo-agent-视觉与交互约定)。
- 评估时读取 [评估指南](eval-guide.md)的本项目工具箱与专项标准，以及 [评估基线](../eval/baseline.md)。
- 文档审阅读取 [文档审阅规范](styles/doc-review.md)的项目补充。`.local/learning/*` 继续作为个人学习笔记维护。

## 评估与运行证据

- 当前指标与回归口径见[评估基线](../eval/baseline.md)，普通回归的调用方式见[测试用例逻辑](../eval/eval-test-logic.md)。
- 启发式评估使用[评估配置](../../configs/evaluation.yaml)及[评估实现](../../agent/internal/evals/eval_engine.py)。
- Trace 记录与回放入口为[tracer.py](../../agent/internal/evals/tracer.py)和[trace_replay.py](../../agent/internal/evals/trace_replay.py)，日志接入见[app_logging.py](../../agent/infra/app_logging.py)。
- 项目专项评估工具、后端标准和回归限制继续由[评估指南](eval-guide.md#本项目专项photo-agent)承接。

## 既有协作补充

- **文案精炼与分工**：部署、使用说明和交付回复直接写操作、配置与必要预期，删去重复提醒和不影响执行的解释；方案取舍、实现原因与开发过程写入设计文档或 backlog，不混入操作步骤。必要前提与影响判断的边界简短保留

根部 Agent 规则中的真实数据与 LLM 回归约束适用于全部模式及工具示例。真实 LLM 调用按当轮明确授权执行，真实数据写入测试须恢复原貌。Go 命令沿用当前工具链配置。
