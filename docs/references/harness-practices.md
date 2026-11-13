<!-- harness:begin -->
# Harness 配套规则的参考依据

[HumanOnly]

查阅日期：2026-11-04。本文供规则审阅与来源追溯使用；各项“本地采用”是本次综合判断，仍按候选规则审批。

## 结构与上下文

[OpenAI：Harness engineering](https://openai.com/index/harness-engineering/)介绍以短入口导航、仓库文档和工程检查支持 Agent 工作的经验。

本地采用：入口负责定位，模式负责流程，专题负责判据，styles 负责写法。保留常见专题名称；执行任务使用 backlog，完成记录使用 version，具体组织服从已确认的本地工作流。没有照搬其自动化程度或发布策略。

## 设计与代码审查

[Design Docs at Google](https://www.industrialempathy.com/posts/design-docs-at-google/)由 Malte Ubl 总结设计文档经验，涉及背景、目标、方案与取舍；这是实践分享，不是 Google 官方制度。

[Google 工程实践：代码审查内容](https://google.github.io/eng-practices/review/reviewer/looking-for.html)关注设计适配、行为、复杂度及测试有效性，强调测试本身也需要审查。

本地采用：概要与详细设计保留决策理由；测试检查真实行为和契约。Epic/Feature 的固定对应、具体模板与个人排版是本地选择，不能由上述来源直接推出。

## 反馈与效果验证

[Anthropic：Demystifying evals for AI agents](https://www.anthropic.com/research/demystifying-evals-for-ai-agents)区分轨迹、最终结果与评分器，并讨论人工校准及多种验证手段。

[Harness engineering](https://martinfowler.com/articles/harness-engineering.html)由 Birgitta Böckeler 讨论引导、反馈和检查机制，提供理解外环的参考。

本地采用：结果与证据对应，检查按成本和影响选择；规则获批后继续观察行为收益。10 分制、0.5 分步长和 Git 暂存审批来自用户约定，不是社区推荐的统一评分法。

## 语言与交互

[Effective Go](https://go.dev/doc/effective_go)提供 Go 格式、命名和错误处理惯例；[PEP 8](https://peps.python.org/pep-0008/)说明 Python 风格以及项目一致性的重要性。

本地采用：沿用项目工具配置。Go 的 `List/Map` 命名、80 字符目标和分行错误判断，以及 Python 项目模块限定导入，来自旧版偏好，单独标明，未宣称是语言标准。

[W3C：表单通知](https://www.w3.org/WAI/tutorials/forms/notifications/)提供识别错误和表达反馈的依据；[OWASP：授权检查](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html)支持最小权限、默认拒绝和服务端校验。

本地采用：UI 写行为与可访问性要求，视觉参数由项目确定；安全要求按实际边界选择。没有将固定配色比例、间距或企业部署清单设为跨项目规则。

## 旧版经验与适配结果

保留结构化交接、用户验收状态、真实路径测试、按问题复评和反馈追溯。修订设计中排除取舍理由的绝对要求、无成本边界的验证要求，以及依赖具体私有架构的通用规定。

来源只提供方向，规则是否减少误解和负担，需要实际任务继续检验。
<!-- harness:end -->
