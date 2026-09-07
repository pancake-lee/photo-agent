"""一次聊天请求内的 LLM 用量归集。

LLM 工厂在创建模型时自动附加当前请求的回调，调用方无需把回调逐层传递。
"""

import contextvars
import dataclasses
import threading

import langchain_core.callbacks as lc_callbacks


@dataclasses.dataclass
class RequestUsage:
    """与一个 trace 对应的 LLM Token 和成本累计值。"""

    prices: dict[str, dict[str, float]] | None
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    calls: int = 0
    _lock: threading.Lock = dataclasses.field(default_factory=threading.Lock)

    def record(self, model: str, input_tokens: int, output_tokens: int) -> None:
        price = (self.prices or {}).get(model) or {}
        cost = (
            input_tokens / 1_000_000.0 * price.get("input", 0.0)
            + output_tokens / 1_000_000.0 * price.get("output", 0.0)
        )
        with self._lock:
            self.input_tokens += input_tokens
            self.output_tokens += output_tokens
            self.cost += cost
            self.calls += 1

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "cost": round(self.cost, 6),
                "llm_calls": self.calls,
                "cost_tracked": self.prices is not None,
            }


_usage_var: contextvars.ContextVar[RequestUsage | None] = contextvars.ContextVar(
    "request_usage", default=None,
)


class RequestUsageCallback(lc_callbacks.BaseCallbackHandler):
    """把 LangChain 返回的标准 token_usage 累加至当前请求。"""

    def __init__(self, usage: RequestUsage):
        super().__init__()
        self._usage = usage

    def on_llm_end(self, response, **kwargs) -> None:
        llm_output = getattr(response, "llm_output", None) or {}
        token_usage = llm_output.get("token_usage", {})
        input_tokens = int(token_usage.get("prompt_tokens", 0) or 0)
        output_tokens = int(token_usage.get("completion_tokens", 0) or 0)
        if not (input_tokens or output_tokens):
            return
        model = (
            llm_output.get("model_name", "")
            or getattr(response, "model_name", "")
            or "unknown"
        )
        self._usage.record(str(model), input_tokens, output_tokens)


def begin_request(prices: dict[str, dict[str, float]] | None) -> tuple[RequestUsage, contextvars.Token]:
    """创建当前同步调用链的请求用量上下文。"""
    usage = RequestUsage(prices)
    return usage, _usage_var.set(usage)


def end_request(token: contextvars.Token) -> None:
    """清除当前请求用量上下文。"""
    _usage_var.reset(token)


def current_callbacks() -> list[lc_callbacks.BaseCallbackHandler]:
    """返回当前请求的回调；非聊天调用没有上下文时返回空列表。"""
    usage = _usage_var.get()
    return [RequestUsageCallback(usage)] if usage is not None else []
