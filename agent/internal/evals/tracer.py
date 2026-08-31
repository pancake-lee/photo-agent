"""
    结构化追踪日志模块。

    统一输出 JSON 结构日志到 data/agent/execution-traces/YYYY-MM-DD.jsonl，
    大体积 payload（LLM prompt/response 全文）写入独立文件，
    日志行中只记路径引用。

    用法:
        import internal.evals.tracer as tracer

        t = tracer.Tracer(project_root="/path/to/project")
        t.emit("cluster.theme.start", {"cluster_id": 5, "photo_count": 8})
        # ... do work ...
        t.emit("llm.call.start", {"model": "gpt-4o"})
        payload_ref = t.save_payload("llm_request.txt", prompt_text)
        t.emit("llm.call.end", {"duration_ms": 1200, "payload_ref": payload_ref})
"""

import json
import uuid
import time
import pathlib
import datetime
import threading
import logging
import typing

logger = logging.getLogger(__name__)

# 日志文件保留天数
_RETENTION_DAYS = 7


class Tracer:
    """结构化追踪器，每个实例绑定一个 trace_id。"""

    def __init__(self, project_root: str | pathlib.Path, agent_data_dir: str = "./data/agent"):
        self.project_root = pathlib.Path(project_root)
        self.agent_data_dir = pathlib.Path(agent_data_dir)
        if not self.agent_data_dir.is_absolute():
            self.agent_data_dir = self.project_root / self.agent_data_dir
        self.trace_id = uuid.uuid4().hex[:12]
        self._lock = threading.Lock()

    # ── 路径工具 ──

    def _today_str(self) -> str:
        return datetime.date.today().isoformat()

    def _trace_log_path(self) -> pathlib.Path:
        d = self.agent_data_dir / "execution-traces"
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{self._today_str()}.jsonl"

    def _payload_dir(self) -> pathlib.Path:
        d = self.agent_data_dir / "execution-traces" / "payloads" / self._today_str()
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _relative(self, p: pathlib.Path) -> str:
        """返回相对于 project_root 的路径字符串。"""
        try:
            return str(p.relative_to(self.project_root))
        except ValueError:
            return str(p)

    # ── 核心 API ──

    def emit(self, event: str, data: dict | None = None, level: str = "INFO", module: str = "") -> str:
        """写入一条 trace 事件到 JSONL 日志文件。

        参数:
            event:  事件名（如 "llm.call.start"）
            data:   事件附带的键值对
            level:  日志级别
            module: 模块名（如 "cluster.generate_theme"）

        返回:
            写入的 JSON 字符串
        """
        now = datetime.datetime.now()
        line = json.dumps({
            "ts": now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z",
            "level": level,
            "trace_id": self.trace_id,
            "module": module,
            "event": event,
            "data": data or {},
        }, ensure_ascii=False, default=str)

        with self._lock:
            fp = self._trace_log_path()
            try:
                with open(fp, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError as e:
                logger.warning("tracer: 写入 trace 日志失败 %s: %s", fp, e)

        return line

    def save_payload(self, filename: str, content: str) -> str:
        """将大体积内容写入独立文件，返回相对路径引用。

        参数:
            filename: 文件名（如 "llm-req-abc123.txt"）
            content:  文件内容

        返回:
            相对于 project_root 的文件路径
        """
        payload_dir = self._payload_dir()
        # 文件名加 trace_id 前缀避免冲突
        safe_name = f"{self.trace_id}-{filename}"
        fp = payload_dir / safe_name
        try:
            fp.write_text(content, encoding="utf-8")
        except OSError as e:
            logger.warning("tracer: 写入 payload 失败 %s: %s", fp, e)
            return ""
        return self._relative(fp)

    # ── 工具 ──

    def new_trace_id(self) -> None:
        """重新生成 trace_id（用于子操作）。"""
        self.trace_id = uuid.uuid4().hex[:12]

    @staticmethod
    def now_iso() -> str:
        return datetime.datetime.now().isoformat()

    @staticmethod
    def cleanup_old(days: int = _RETENTION_DAYS, project_root: str | pathlib.Path = ".") -> int:
        """清理超过指定天数的 trace 日志和 payload 文件。返回删除的文件数。"""
        root = pathlib.Path(project_root)
        traces_dir = root / "data" / "agent" / "execution-traces"
        if not traces_dir.exists():
            return 0

        cutoff = datetime.date.today() - datetime.timedelta(days=days)
        removed = 0

        # 清理 JSONL 日志文件
        for fp in traces_dir.glob("*.jsonl"):
            try:
                date_str = fp.stem  # YYYY-MM-DD
                file_date = datetime.date.fromisoformat(date_str)
                if file_date < cutoff:
                    fp.unlink()
                    removed += 1
            except (ValueError, OSError):
                pass

        # 清理 payload 目录
        payloads_root = traces_dir / "payloads"
        if payloads_root.exists():
            for d in payloads_root.iterdir():
                if not d.is_dir():
                    continue
                try:
                    dir_date = datetime.date.fromisoformat(d.name)
                    if dir_date < cutoff:
                        import shutil
                        shutil.rmtree(d)
                        removed += 1
                except (ValueError, OSError):
                    pass

        return removed
