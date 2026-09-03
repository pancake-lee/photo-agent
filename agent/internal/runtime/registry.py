"""
    Agent Runtime 能力注册表（框架无关纯 Python）。

    能力的工具描述回答「何时使用」，参数声明让程序能校验「如何使用」。
    一个能力的全部信息聚合在 Capability 定义处（实现、用户标题、决策提示、
    过程细节），具体能力在 capabilities/ 包中定义，本模块只负责登记与校验。
"""

import dataclasses
import typing

import internal.runtime.state as rt_state


# 参数声明允许的类型（用于提示词描述与程序校验）
_PARAM_TYPES = ("str", "int", "float", "bool", "list", "dict")


@dataclasses.dataclass
class RunContext:
    """能力执行的上下文，由编排外壳在每步执行前构造。

    cfg            配置对象（类型为 config.Config，核心层不 import 具体实现）
    granularity    检索粒度 photo/fine/coarse
    cost_hook      LLM 成本上报回调（用于预算的 cost 维度）
    question       本次任务的原始用户请求
    state          当前 TaskState 快照，能力只读（写入必须经归约）
    llm_callbacks  能力内创建 LLM 时附带的回调（Token 追踪等）
    """

    cfg: typing.Any
    granularity: str = "photo"
    cost_hook: typing.Callable[[float], None] | None = None
    question: str = ""
    state: typing.Any = None
    llm_callbacks: list = dataclasses.field(default_factory=list)
    tracer: typing.Any = None


@dataclasses.dataclass
class Capability:
    """一项可被 decide 选中执行的能力，全部信息聚合在此定义处。

    name              能力名（decide 返回的 action）
    title             用户过程面板的步骤标题
    description       何时使用该能力（写入决策提示词的能力清单）
    parameters        参数声明 {参数名: {"type", "description", "required"}}
    run               执行函数 (params, ctx) -> Observation
    decide_hint       注入决策提示词的选择规则（能力自带的排序约束，可选）
    progress_details  受控过程细节提取 (params) -> dict，只放可进用户面板的字段（可选）
    repairable_reasons 能力侧可通过带反馈修复重执行解决的前置失败 terminal_reason 清单（可选）；
                      清单外的 invalid_input 视为决策侧问题，反馈给 decide 再决策
    evaluator         语义质量门 (ctx, observation) -> QualityVerdict（可选），
                      guardrail 在确定性检查通过后触发；返回对象需带 passed / feedback
    """

    name: str
    title: str
    description: str
    parameters: dict[str, dict]
    run: typing.Callable[[dict, RunContext], rt_state.Observation]
    decide_hint: str = ""
    progress_details: typing.Callable[[dict], dict] | None = None
    repairable_reasons: tuple[str, ...] = ()
    evaluator: typing.Callable[[RunContext, rt_state.Observation], typing.Any] | None = None

    def spec(self) -> dict:
        """输出给决策提示词的能力描述。"""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


class CapabilityRegistry:
    """能力登记与参数校验。"""

    def __init__(self) -> None:
        self._capabilities: dict[str, Capability] = {}

    def register(self, capability: Capability) -> None:
        if capability.name in self._capabilities:
            raise ValueError(f"能力重复注册: {capability.name!r}")
        for param_name, param in capability.parameters.items():
            if param.get("type") not in _PARAM_TYPES:
                raise ValueError(
                    f"能力 {capability.name!r} 参数 {param_name!r} 类型必须是 {_PARAM_TYPES}"
                )
        self._capabilities[capability.name] = capability

    def get(self, name: str) -> Capability | None:
        return self._capabilities.get(name)

    def names(self) -> list[str]:
        return list(self._capabilities)

    def specs(self) -> list[dict]:
        return [capability.spec() for capability in self._capabilities.values()]

    def decide_hints(self) -> list[str]:
        """按登记顺序收集能力自带的选择规则（去重，多个能力可共享同一条）。"""
        hints: list[str] = []
        for capability in self._capabilities.values():
            hint = capability.decide_hint
            if hint and hint not in hints:
                hints.append(hint)
        return hints

    def validate_params(self, name: str, params: typing.Any) -> list[str]:
        """校验 decide 返回的参数，返回错误清单（空列表表示通过）。"""
        capability = self._capabilities.get(name)
        if capability is None:
            return [f"未知能力: {name!r}，可用: {', '.join(self._capabilities) or '无'}"]
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return [f"参数必须是对象，实际为 {type(params).__name__}"]

        errors: list[str] = []
        for param_name, param in capability.parameters.items():
            value = params.get(param_name)
            if value is None:
                if param.get("required"):
                    errors.append(f"缺少必填参数: {param_name}")
                continue
            expected = param.get("type")
            if not _type_matches(value, expected):
                errors.append(
                    f"参数 {param_name} 类型应为 {expected}，实际为 {_describe_type(value)}"
                )
        for param_name in params:
            if params[param_name] is not None and param_name not in capability.parameters:
                errors.append(f"未声明的参数: {param_name}")
        return errors


def _type_matches(value: typing.Any, expected: str) -> bool:
    if expected == "str":
        return isinstance(value, str)
    if expected == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "bool":
        return isinstance(value, bool)
    if expected == "list":
        return isinstance(value, list)
    if expected == "dict":
        return isinstance(value, dict)
    return False


def _describe_type(value: typing.Any) -> str:
    return type(value).__name__
