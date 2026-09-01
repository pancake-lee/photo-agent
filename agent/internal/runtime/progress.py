"""将 Runtime 的内部事件归约为可安全展示给用户的过程快照。"""

import copy


_ACTION_TITLES = {
    "resolve_trip": "确认候选范围",
    "sql_search": "查询照片",
    "rag_search": "查找相似照片",
    "hybrid_search": "综合查询照片",
    "fetch_photo_details": "确认照片信息",
    "select_photos": "挑选代表照片",
    "write_post": "生成发布文案",
}


def _title_for(action: str) -> str:
    return _ACTION_TITLES.get(action, "处理任务")


class RuntimeProgressTranslator:
    """消费真实 Runtime 事件，输出轻量、无内部日志的步骤快照。"""

    def __init__(self):
        self._steps: dict[int, dict] = {}

    def consume(self, event: str, data: dict) -> list[dict]:
        """归约一条 runtime.* 事件，返回当前完整步骤列表。"""
        step_no = int(data.get("step") or 0)
        if step_no <= 0 or event == "runtime.trace_summary":
            return self.snapshots()

        step = self._steps.setdefault(step_no, {
            "step": step_no,
            "title": _title_for(str(data.get("action") or "")),
            "status": "进行中",
            "decision": "",
            "result": "",
            "facts": [],
            "details": {},
        })
        action = str(data.get("action") or "")
        if action:
            step["title"] = _title_for(action)

        if event == "runtime.decide":
            step["decision"] = str(data.get("reason") or "正在确定下一步。")
            step["status"] = "准备执行"
        elif event == "runtime.execute":
            step["status"] = "正在执行"
            step["details"].update(data.get("details") or {})
        elif event == "runtime.observe":
            step["result"] = str(data.get("summary") or "已得到执行结果。")
            step["status"] = "已完成"
            step["facts"] = list(data.get("facts") or [])
            step["details"].update(data.get("details") or {})
        elif event == "runtime.check":
            if data.get("stop_reason") or data.get("terminal_reason"):
                step["status"] = "已停止"
            elif data.get("complete"):
                step["status"] = "已完成"

        return self.snapshots()

    def snapshots(self) -> list[dict]:
        """按步骤号返回可 JSON 序列化的深拷贝。"""
        return [copy.deepcopy(self._steps[key]) for key in sorted(self._steps)]
