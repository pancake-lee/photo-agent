"""
    LLM 工厂：创建带重试和降级的 ChatOpenAI 实例。

    使用 LangChain 原生的 Runnable.with_retry() 和 with_fallbacks()，
    不依赖 tenacity（仅保留依赖声明作备用）。

    用法:
        import infra.llm_factory as llm_factory

        llm = llm_factory.create_llm(cfg, temperature=0.5, streaming=True, callbacks=[...])
"""

import typing

import langchain_core.callbacks as lc_callbacks
import langchain_openai as lc_openai

import infra.config as config


def create_llm(
    cfg: config.Config,
    model: str = "",
    temperature: float = 0.0,
    streaming: bool = False,
    callbacks: list[lc_callbacks.BaseCallbackHandler] | None = None,
    tools: list[typing.Any] | None = None,
) -> typing.Any:
    """创建带重试 + 可选降级的 LLM 实例。

    重试：LangChain 原生 with_retry，指数退避 + 抖动，3 次尝试。
    降级：主模型失败时自动切换到 fallback_model。

    注意：bind_tools 必须在 with_retry / with_fallbacks 之前调用，
    因为 RunnableRetry 没有 bind_tools 方法。
    """
    llm = lc_openai.ChatOpenAI(
        model=model or cfg.llm_model,
        api_key=cfg.llm_api_key,  # type: ignore[arg-type]
        base_url=cfg.llm_base_url,
        temperature=temperature,
        request_timeout=cfg.llm_request_timeout,
        streaming=streaming,
        callbacks=callbacks,
    )

    # bind_tools 必须在 with_retry 之前，否则 RunnableRetry 没有此方法
    if tools:
        llm = llm.bind_tools(tools)

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
            request_timeout=cfg.llm_request_timeout,
            streaming=streaming,
            callbacks=callbacks,
        )
        if tools:
            fallback_llm = fallback_llm.bind_tools(tools)
        print(f"fallback: {cfg.llm_model} → {cfg.llm_fallback_model}")
        try:
            llm = llm.with_fallbacks([fallback_llm])
        except Exception:
            pass

    return llm
