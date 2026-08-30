"""
    Trace 重放模块：从 data/agent/execution-traces/*.jsonl 中按 trace_id 重建管线步骤。

    用法:
        import chain.trace_replay as trace_replay

        steps = trace_replay.replay_trace(project_root, trace_id)
        for step in steps:
            print(step["event"], step["data"])
"""

import json
import pathlib
import datetime
import logging
import dataclasses
import typing

logger = logging.getLogger(__name__)

# trace 文件保留天数（与 tracer.py 的 _RETENTION_DAYS 一致）
_RETENTION_DAYS = 7

# 管线步骤定义：事件名 → 展示信息
_PIPELINE_STEPS = [
    {"event": "suggest.decision.pipeline",  "stage": 0, "label": "管线选择",        "group": "决策"},
    {"event": "suggest.stage1.sample",      "stage": 1, "label": "随机采样",        "group": "Stage 1 灵感发现"},
    {"event": "suggest.stage1.llm.start",   "stage": 1, "label": "LLM 输入",        "group": "Stage 1 灵感发现"},
    {"event": "suggest.stage1.llm.end",     "stage": 1, "label": "LLM 输出（直觉）", "group": "Stage 1 灵感发现"},
    {"event": "suggest.stage1.intuitions",  "stage": 1, "label": "主题直觉汇总",    "group": "Stage 1 灵感发现"},
    {"event": "suggest.stage2.rag.start",   "stage": 2, "label": "RAG 查询",        "group": "Stage 2 扩展选片"},
    {"event": "suggest.stage2.rag.end",     "stage": 2, "label": "RAG 匹配结果",    "group": "Stage 2 扩展选片"},
    {"event": "suggest.stage2.diversity",   "stage": 2, "label": "多样性过滤",      "group": "Stage 2 扩展选片"},
    {"event": "suggest.stage3.llm.start",   "stage": 3, "label": "LLM 输入",        "group": "Stage 3 选题提案"},
    {"event": "suggest.stage3.llm.end",     "stage": 3, "label": "LLM 输出（提案）", "group": "Stage 3 选题提案"},
    {"event": "suggest.stage3.proposal",    "stage": 3, "label": "提案解析",        "group": "Stage 3 选题提案"},
    {"event": "suggest.stage3.validation",  "stage": 3, "label": "ID 校验",         "group": "Stage 3 选题提案"},
    {"event": "suggest.stage3.time_span",   "stage": 3, "label": "时间跨度",        "group": "Stage 3 选题提案"},
    {"event": "suggest.complete",           "stage": 3, "label": "管线完成",        "group": "汇总"},
]


@dataclasses.dataclass
class PipelineStepSnapshot:
    """单个管线步骤的快照数据。"""
    event: str
    label: str
    group: str
    stage: int
    timestamp: str
    data: dict
    payload_content: str = ""  # 关联的 payload 文件内容（如有）
    payload_ref: str = ""      # payload 文件路径引用


def _traces_dir(project_root: pathlib.Path) -> pathlib.Path:
    return project_root / "data" / "agent" / "execution-traces"


def _find_trace_events(project_root: pathlib.Path, trace_id: str) -> list[dict]:
    """在 data/agent/execution-traces/*.jsonl 中搜索指定 trace_id 的所有事件，按时间排序。"""
    traces_dir = _traces_dir(project_root)
    if not traces_dir.exists():
        return []

    events: list[dict] = []
    for fp in sorted(traces_dir.glob("*.jsonl")):
        try:
            with open(fp, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("trace_id") == trace_id:
                        events.append(obj)
        except OSError:
            continue

    events.sort(key=lambda e: e.get("ts", ""))
    return events


def _load_payload(project_root: pathlib.Path, payload_ref: str) -> str:
    """加载 payload 文件内容。"""
    if not payload_ref:
        return ""
    fp = project_root / payload_ref
    if not fp.exists():
        return ""
    try:
        return fp.read_text(encoding="utf-8")
    except OSError:
        return ""


def _is_trace_expired(project_root: pathlib.Path, trace_id: str) -> bool:
    """判断 trace 数据是否已过期（所有相关 JSONL 文件的日期均超过保留天数）。"""
    traces_dir = _traces_dir(project_root)
    if not traces_dir.exists():
        return True

    cutoff = datetime.date.today() - datetime.timedelta(days=_RETENTION_DAYS)
    has_any = False

    for fp in traces_dir.glob("*.jsonl"):
        try:
            with open(fp, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("trace_id") == trace_id:
                        has_any = True
                        date_str = fp.stem
                        file_date = datetime.date.fromisoformat(date_str)
                        if file_date >= cutoff:
                            return False
        except OSError:
            continue

    # 没找到任何事件 → 视为过期
    return not has_any


def _get_step_defs(events: list[dict]) -> list[dict]:
    """返回管线步骤定义列表。统一使用三阶段编辑视角提案步骤。"""
    return _PIPELINE_STEPS


def replay_trace(
    project_root: str | pathlib.Path,
    trace_id: str,
) -> tuple[list[PipelineStepSnapshot], bool]:
    """从 trace 文件重建指定 trace_id 的管线步骤列表。

    参数:
        project_root: 项目根目录
        trace_id:     要重放的 trace ID

    返回:
        (steps, expired): 步骤快照列表和是否过期的标志
    """
    root = pathlib.Path(project_root)

    if _is_trace_expired(root, trace_id):
        logger.info("trace_replay: trace_id=%s 数据已过期", trace_id)
        return [], True

    events = _find_trace_events(root, trace_id)
    if not events:
        logger.info("trace_replay: trace_id=%s 无事件记录", trace_id)
        return [], True

    step_defs = _get_step_defs(events)

    # 构建 event → step_def 映射
    event_map: dict[str, dict] = {sd["event"]: sd for sd in step_defs}

    # 按事件出现顺序构建步骤快照
    steps: list[PipelineStepSnapshot] = []
    for ev in events:
        event_name = ev.get("event", "")
        sd = event_map.get(event_name)
        if sd is None:
            # 跳过未定义的步骤（如 suggest.stage3.skip_empty, suggest.decision.skip 等）
            continue

        data = ev.get("data", {})
        payload_ref = data.get("payload_ref", "")
        payload_content = _load_payload(root, payload_ref) if payload_ref else ""

        steps.append(PipelineStepSnapshot(
            event=event_name,
            label=sd["label"],
            group=sd["group"],
            stage=sd["stage"],
            timestamp=ev.get("ts", ""),
            data=data,
            payload_content=payload_content,
            payload_ref=payload_ref,
        ))

    return steps, False


def list_available_trace_dates(
    project_root: str | pathlib.Path,
) -> list[str]:
    """列出所有可用的 trace 日期（用于判断某 trace_id 是否有数据）。"""
    root = pathlib.Path(project_root)
    traces_dir = _traces_dir(root)
    if not traces_dir.exists():
        return []
    dates: list[str] = []
    for fp in sorted(traces_dir.glob("*.jsonl")):
        dates.append(fp.stem)
    return dates
