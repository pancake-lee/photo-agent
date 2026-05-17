"""
    LLM 工厂：创建带重试和降级的 ChatOpenAI 实例。

    使用 LangChain 原生的 Runnable.with_retry() 和 with_fallbacks()，
    不依赖 tenacity（仅保留依赖声明作备用）。

    用法:
        from utils.llm_factory import create_llm

        llm = create_llm(cfg, temperature=0.5, streaming=True, callbacks=[...])
"""

import typing

import langchain_core.callbacks as lc_callbacks
import langchain_openai as lc_openai

import config


def create_llm(
    cfg: config.Config,
    model: str = "",
    temperature: float = 0.0,
    streaming: bool = False,
    callbacks: list[lc_callbacks.BaseCallbackHandler] | None = None,
) -> typing.Any:
    """创建带重试 + 可选降级的 LLM 实例。

    重试：LangChain 原生 with_retry，指数退避 + 抖动，3 次尝试。
    降级：主模型失败时自动切换到 fallback_model。
    """
    llm = lc_openai.ChatOpenAI(
        model=model or cfg.llm_model,
        api_key=cfg.llm_api_key,  # type: ignore[arg-type]
        base_url=cfg.llm_base_url,
        temperature=temperature,
        streaming=streaming,
        callbacks=callbacks,
    )

    if cfg.retry_enabled:
        try:
            llm = llm.with_retry(
                stop_after_attempt=cfg.retry_max_attempts,
                wait_exponential_jitter=True,
            )
        except Exception:
            pass  # with_retry 不可用不阻塞

    if cfg.llm_fallback_model:
        fallback_llm = lc_openai.ChatOpenAI(
            model=cfg.llm_fallback_model,
            api_key=cfg.llm_api_key,  # type: ignore[arg-type]
            base_url=cfg.llm_base_url,
            temperature=temperature,
            streaming=streaming,
            callbacks=callbacks,
        )
        print(f"fallback: {cfg.llm_model} → {cfg.llm_fallback_model}")
        try:
            llm = llm.with_fallbacks([fallback_llm])
        except Exception:
            pass

    return llm
