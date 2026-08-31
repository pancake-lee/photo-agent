"""Agent 服务 JSONL 日志与请求级 Trace 上下文。"""

import contextvars
import datetime
import json
import logging
import pathlib


trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")


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
            "source": f"{record.pathname}:{record.lineno}",
            "trace_id": getattr(record, "trace_id", "") or trace_id_var.get(),
        }
        for field in ("method", "path", "status_code", "duration_ms"):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_service_logging(project_root: pathlib.Path) -> None:
    """配置服务唯一的应用日志出口，不触碰启动命令的控制台输出。"""
    log_path = project_root / "logs" / "agent.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(JsonLineFormatter())

    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
        target = logging.getLogger(name)
        target.handlers.clear()
        target.addHandler(handler)
        target.setLevel(logging.INFO)
        target.propagate = False
