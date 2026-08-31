"""Agent 服务 JSONL 日志与请求级 Trace 上下文。"""

import contextvars
import datetime
import json
import logging
import pathlib


trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")


def _format_source(record: logging.LogRecord) -> str:
    """将源码位置收敛为最后一级目录和文件名，避免暴露机器绝对路径。"""
    path = pathlib.Path(record.pathname)
    if path.parent.name:
        return f"{path.parent.name}/{path.name}:{record.lineno}"
    return f"{path.name}:{record.lineno}"


class JsonLineFormatter(logging.Formatter):
    """把应用和 HTTP 日志收敛为可检索的统一 JSONL 字段。"""

    def format(self, record: logging.LogRecord) -> str:
        now = datetime.datetime.now(datetime.timezone.utc)
        payload = {
            "ts": now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z",
            "level": record.levelname,
            "module": record.name,
            "event": getattr(record, "event", "log"),
            "message": record.getMessage(),
            "source": _format_source(record),
            "trace_id": getattr(record, "trace_id", "") or trace_id_var.get(),
        }
        for field in ("method", "path", "status_code", "duration_ms"):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class ConsoleFormatter(logging.Formatter):
    """开发控制台的紧凑文本日志，保留定位所需的模块与 Trace。"""

    def format(self, record: logging.LogRecord) -> str:
        trace_id = getattr(record, "trace_id", "") or trace_id_var.get()
        trace_text = f" trace={trace_id}" if trace_id else ""
        prefix = f"{self.formatTime(record, '%H:%M:%S')} {record.levelname:<7} [{record.name}]{trace_text}"
        message = record.getMessage()
        if record.exc_info:
            message += "\n" + self.formatException(record.exc_info)
        return f"{prefix} {message} [{_format_source(record)}]"


def configure_service_logging(project_root: pathlib.Path, console: bool = False) -> None:
    """写入生产 JSONL；传入 console 时额外挂载开发用文本控制台输出。"""
    log_path = project_root / "logs" / "agent.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(JsonLineFormatter())
    console_handler = logging.StreamHandler() if console else None
    if console_handler is not None:
        console_handler.setFormatter(ConsoleFormatter())

    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
        target = logging.getLogger(name)
        target.handlers.clear()
        target.addHandler(handler)
        if console_handler is not None:
            target.addHandler(console_handler)
        target.setLevel(logging.INFO)
        target.propagate = False
