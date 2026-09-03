"""
    Agent Runtime 能力共享辅助（跨能力复用，不含具体能力）。

    - capability_run        执行护栏装饰器：能力异常按类型归类为六态观察，不炸循环
    - classify_exception    异常 → 恢复状态归类（网络超时类 temporary，其余 permanent）
    - retrieval_status      检索类观察的空结果/有结果状态
    - invoke_structured_llm 能力内 LLM 调用的统一入口（提示词驱动，返回原始文本）
    - extract_json_dict     从模型输出提取首个 JSON 对象
    - fetch_photos_batch    并行批量拉取照片详情（Go 后端，按传入顺序返回）
    - cached_photos         按顺序取详情：优先 TaskState 缓存，缺失部分批量补拉
"""

import functools
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx
import langchain_core.messages as lc_messages

import infra.http_client as http_utils
import infra.llm_factory as llm_factory
import internal.runtime.registry as rt_registry
import internal.runtime.state as rt_state

logger = logging.getLogger(__name__)


# --------------------------------------------------
# 执行护栏
# --------------------------------------------------

# 瞬时异常族：网络传输/超时类（httpx.TransportError 覆盖连接失败与读写超时）。
# SDK、LLM、解析等其余异常默认按 permanent 归类，宁可正确停止也不盲目重试。
_TEMPORARY_EXCEPTION_TYPES = (httpx.TransportError, TimeoutError)


def classify_exception(exc: Exception) -> str:
    """异常 → 恢复状态：网络/超时类 temporary_error，其余默认 permanent_error。"""
    if isinstance(exc, _TEMPORARY_EXCEPTION_TYPES):
        return rt_state.STATUS_TEMPORARY_ERROR
    return rt_state.STATUS_PERMANENT_ERROR


def retrieval_status(ids: list[str]) -> str:
    """检索类观察的状态：范围内的空结果是合法空观察（候选由权威范围兜底）。"""
    return rt_state.STATUS_EMPTY if not ids else rt_state.STATUS_SUCCESS


def capability_run(fn):
    """能力执行护栏：异常转为带恢复状态的失败观察，不让单次能力失败炸掉整个循环。"""

    @functools.wraps(fn)
    def wrapped(params: dict, ctx: rt_registry.RunContext) -> rt_state.Observation:
        try:
            return fn(params or {}, ctx)
        except Exception as exc:
            logger.exception("[runtime] 能力 %s 执行失败", fn.__name__)
            return rt_state.Observation(
                rt_state.OBS_ERROR,
                f"{fn.__name__} 执行失败: {exc}",
                {"terminal_reason": "capability_execution_failed"},
                status=classify_exception(exc),
            )

    return wrapped


# --------------------------------------------------
# 能力内 LLM 调用（提示词驱动，与 decide 节点的 LLM 决策相互独立）
# --------------------------------------------------

def invoke_structured_llm(
    ctx: rt_registry.RunContext,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
) -> str:
    """能力内 LLM 调用：System/Human 两条消息，返回原始文本。

    JSON 提取与字段校验由调用方负责，本入口只统一 LLM 构造与回调挂载。
    """
    llm = llm_factory.create_llm(
        ctx.cfg, temperature=temperature, callbacks=ctx.llm_callbacks or None,
    )
    response = llm.invoke([
        lc_messages.SystemMessage(content=system_prompt),
        lc_messages.HumanMessage(content=user_prompt),
    ])
    response_text = str(response.content)
    if ctx.tracer is not None:
        payload_ref = ctx.tracer.save_payload(
            "runtime-llm.json",
            json.dumps({"system": system_prompt, "user": user_prompt, "response": response_text}, ensure_ascii=False),
        )
        ctx.tracer.emit("runtime.llm", {"payload_ref": payload_ref}, module="runtime")
    return response_text


def extract_json_dict(text: str) -> dict | None:
    """从模型输出中提取首个 JSON 对象，失败返回 None。"""
    text = (text or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


# --------------------------------------------------
# 照片详情获取（批量拉取 + 状态缓存）
# --------------------------------------------------

def fetch_photos_batch(cfg, photo_ids: list[str]) -> list[dict]:
    """批量获取照片详情（并行请求 Go 后端，按传入顺序返回）。"""
    if not photo_ids:
        return []

    results: list[dict] = []

    def _fetch(pid: str) -> dict | None:
        try:
            with http_utils.create_client(timeout=5.0) as client:
                resp = client.get(f"{cfg.go_backend_url}/api/v1/photos/{pid}")
                resp.raise_for_status()
                payload = resp.json()
                photo = payload.get("photo") if isinstance(payload, dict) else None
                if not isinstance(photo, dict) or not photo.get("id"):
                    logger.warning("[runtime] 照片详情响应缺少 photo.id: id=%s", pid)
                    return None
                return photo
        except Exception as exc:
            logger.warning("[runtime] 获取照片详情失败: id=%s, error=%s", pid, exc)
            return None

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_fetch, pid): pid for pid in photo_ids}
        for future in as_completed(futures):
            data = future.result()
            if data:
                results.append(data)

    id_order = {pid: i for i, pid in enumerate(photo_ids)}
    results.sort(key=lambda x: id_order.get(x.get("id", ""), 999))
    return results


def cached_photos(ctx: rt_registry.RunContext, photo_ids: list[str]) -> list[dict]:
    """按 photo_ids 顺序取详情：优先状态缓存，缺失部分批量补拉。"""
    state = ctx.state
    cache: dict[str, dict] = state.artifacts.photo_cache if state is not None else {}
    missing = [pid for pid in photo_ids if pid not in cache]
    fetched = {p.get("id"): p for p in fetch_photos_batch(ctx.cfg, missing)}
    photos = []
    for pid in photo_ids:
        if pid in cache:
            photos.append(cache[pid])
        elif pid in fetched:
            photos.append(fetched[pid])
    return photos
