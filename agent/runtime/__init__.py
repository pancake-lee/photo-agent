"""
    Agent Runtime — 开放目标的状态化多步执行核心。

    分层:
        - state.py      TaskState + 显式归约规则（框架无关）
        - budget.py     步数/时长/成本预算（框架无关）
        - completion.py 确定性完成检查（框架无关）
        - registry.py   能力注册表 + 参数校验（框架无关）
        - capabilities.py 具体能力实现（依赖 chain 现有实现）
        - graph.py      LangGraph 编排外壳（decide/execute/reduce/check 循环）

    核心语义不依赖 LangGraph 与真实 LLM，可脱离编排框架直接单测。
"""

import runtime.budget as budget
import runtime.capabilities as capabilities
import runtime.completion as completion
import runtime.registry as registry
import runtime.state as state

__all__ = ["budget", "capabilities", "completion", "registry", "state"]
