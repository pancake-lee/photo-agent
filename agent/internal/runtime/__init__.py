"""
    Agent Runtime — 开放目标的状态化多步执行核心。

    分层:
        - state.py       TaskState + 显式归约规则（框架无关）
        - budget.py      步数/时长/成本预算（框架无关）
        - completion.py  确定性完成检查（框架无关）
        - registry.py    能力注册表 + 参数校验（框架无关）
        - capabilities/  能力包，按 LLM 参与方式分类（约束解析 / 检索 / 程序工具 / 创作）
        - progress.py    过程事件 → 用户过程快照（框架无关）
        - graph.py       LangGraph 编排外壳（decide 唯一 LLM 决策点 + 程序节点与程序路由）

    核心语义不依赖 LangGraph 与真实 LLM，可脱离编排框架直接单测。
"""

import internal.runtime.budget as budget
import internal.runtime.capabilities as capabilities
import internal.runtime.completion as completion
import internal.runtime.registry as registry
import internal.runtime.state as state

__all__ = ["budget", "capabilities", "completion", "registry", "state"]
