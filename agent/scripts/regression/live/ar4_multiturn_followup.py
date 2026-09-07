"""AR4 真实 LLM 多轮跟进识别与消解质量回归（只读）。

本脚本不属于日常 unittest discovery，必须在用户当轮明确授权后执行：

    cd agent
    .venv/bin/python scripts/regression/live/ar4_multiturn_followup.py -c ../.local/my-config.yaml

前置条件：Go 后端（默认 10004 端口）已启动且照片库可用；脚本启动时先探测后端，
不健康则直接退出，不消耗 LLM 调用。

消耗估算：4 轮真实会话，第 1/3 轮走 Runtime 全链路（多步决策 + 选片 + 文案），
第 2 轮局部续跑，第 4 轮单条 SQL 查询；按既往 live 回归经验约 2–7 元。

它只读取照片库并调用 LLM；会话历史与任务快照在内存中线程化（等价 server
send_message 接线），不写会话存储，不创建、更新或删除任何数据。

各轮断言逻辑为纯函数（输入轮次摘要字典，输出 failures 列表），
离线单测见 tests/test_ar4_live_assertions.py。
"""

from __future__ import annotations

import argparse
import json
import logging
import pathlib
import sys
import time
import urllib.error
import urllib.request


AGENT_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import cli.photo_agent as photo_agent
import infra.config as config
import internal.evals.tracer as tracer_mod


# 四轮真实多轮会话：首轮全链路 → 改文案（仅 copy 失效）→ 补选（selection_add）→ 负样本新问题
TURNS = (
    "找山西旅游第一天的照片并生成发布文案",
    "不要那么文艺",
    "再补两张不同场景的照片",
    "2026 年 5 月我拍了多少张照片",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="执行经授权的 AR4 真实多轮跟进回归")
    parser.add_argument("-c", "--config", required=True, help="本地 Agent YAML 配置")
    parser.add_argument("--llm-timeout", type=float, default=60.0, help="单次模型请求超时秒数")
    return parser.parse_args()


def _print(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def backend_reachable(base_url: str) -> bool:
    """探测 Go 后端是否在线：收到任何 HTTP 响应（含 404）即视为在线。"""
    request = urllib.request.Request(f"{base_url.rstrip('/')}/api/v1/photos/__probe__")
    try:
        with urllib.request.urlopen(request, timeout=5):
            return True
    except urllib.error.HTTPError:
        return True
    except (urllib.error.URLError, OSError):
        return False


def selected_ids_from_dump(dump_json: str) -> list[str]:
    """从 Runtime 任务快照 JSON 中取入选照片 ID 列表（无快照或无字段时为空）。"""
    if not dump_json:
        return []
    data = json.loads(dump_json)
    artifacts = data.get("artifacts") or {}
    return [str(pid) for pid in artifacts.get("selected_ids") or []]


def summarize_turn(turn_no: int, question: str, result: dict) -> dict:
    """把 route 结果压成可断言、可序列化打印的轮次摘要。"""
    return {
        "turn": turn_no,
        "question": question,
        "followup": bool(result.get("followup")),
        "query_type": str(result.get("query_type") or ""),
        "affected": list(result.get("runtime_affected") or []),
        "answer": str(result.get("answer") or ""),
        "selected_ids": selected_ids_from_dump(str(result.get("runtime_task_dump") or "")),
        "clarification": bool(result.get("runtime_clarification")),
        "terminal_reason": str(result.get("runtime_terminal_reason") or ""),
    }


def assert_first_turn(summary: dict) -> list[str]:
    """首轮：非跟进，走 Runtime 全链路并交付选片与文案。"""
    failures = []
    if summary["followup"]:
        failures.append("首轮无历史却被判为跟进")
    if summary["query_type"] != "runtime":
        failures.append(f"首轮应路由 runtime，实际 {summary['query_type'] or '空'}")
    if not summary["selected_ids"]:
        failures.append("首轮未产生选片集合")
    if not summary["answer"]:
        failures.append("首轮未交付回答")
    if summary["clarification"]:
        failures.append("首轮出现待澄清，场景问题应可直接执行")
    if summary["terminal_reason"]:
        failures.append(f"首轮出现终态：{summary['terminal_reason']}")
    return failures


def assert_copy_followup(prev: dict, summary: dict) -> list[str]:
    """第二轮「不要那么文艺」：跟进、仅 copy 受影响、选片不变、文案变化。"""
    failures = []
    if not summary["followup"]:
        failures.append("「不要那么文艺」未被识别为跟进")
    if summary["query_type"] != "runtime":
        failures.append(f"第二轮应续跑 runtime，实际 {summary['query_type'] or '空'}")
    if "copy" not in summary["affected"]:
        failures.append(f"第二轮受影响部分应含 copy，实际 {summary['affected']}")
    unexpected = sorted(set(summary["affected"]) & {"scope", "selection", "selection_add"})
    if unexpected:
        failures.append(f"改文案不应失效 {unexpected}")
    if summary["selected_ids"] != prev["selected_ids"]:
        failures.append(
            f"选片集合应不变：前轮 {prev['selected_ids']}，本轮 {summary['selected_ids']}"
        )
    if summary["answer"] and summary["answer"] == prev["answer"]:
        failures.append("第二轮文案与首轮完全相同，改写未生效")
    if summary["terminal_reason"]:
        failures.append(f"第二轮出现终态：{summary['terminal_reason']}")
    return failures


def assert_selection_add(prev: dict, summary: dict) -> list[str]:
    """第三轮「再补两张」：跟进、声明补选、旧入选程序性保留且有新增。"""
    failures = []
    if not summary["followup"]:
        failures.append("「再补两张不同场景的照片」未被识别为跟进")
    if summary["query_type"] != "runtime":
        failures.append(f"第三轮应续跑 runtime，实际 {summary['query_type'] or '空'}")
    if "scope" in summary["affected"]:
        failures.append("补选不应失效范围")
    if "selection_add" not in summary["affected"]:
        failures.append(
            f"第三轮应声明补选 selection_add，实际 {summary['affected']}"
            + ("（声明重选 selection 会丢用户已确认照片）" if "selection" in summary["affected"] else "")
        )
    missing = [pid for pid in prev["selected_ids"] if pid not in summary["selected_ids"]]
    if missing:
        failures.append(f"补选后旧入选未被保留，丢失：{missing}")
    if len(summary["selected_ids"]) <= len(prev["selected_ids"]):
        failures.append(
            f"补选未新增照片：前轮 {len(prev['selected_ids'])} 张，本轮 {len(summary['selected_ids'])} 张"
        )
    if summary["terminal_reason"]:
        failures.append(f"第三轮出现终态：{summary['terminal_reason']}")
    return failures


def assert_negative_sql(summary: dict) -> list[str]:
    """第四轮负样本：全新事实问题不应误判为跟进，应路由 sql。"""
    failures = []
    if summary["followup"]:
        failures.append(
            f"新问题「{summary['question']}」被误判为跟进，受影响部分 {summary['affected']}"
        )
    if summary["query_type"] != "sql":
        failures.append(f"照片计数问题应路由 sql，实际 {summary['query_type'] or '空'}")
    return failures


_TURN_ASSERTIONS = (
    lambda _prev, summary: assert_first_turn(summary),
    assert_copy_followup,
    assert_selection_add,
    lambda _prev, summary: assert_negative_sql(summary),
)


def run_scenario(cfg: config.Config) -> list[str]:
    """跑四轮真实会话并逐轮断言，返回全部失败项。"""
    agent = photo_agent.PhotoAgent(cfg)
    history: list[dict] = []
    snapshot = ""
    summaries: list[dict] = []
    failures: list[str] = []

    for index, question in enumerate(TURNS):
        tracer = tracer_mod.Tracer(cfg.project_root, cfg.agent_data_dir)
        _print(
            f"[第{index + 1}轮] {question}"
            f"（trace={tracer.trace_file_ref()}，trace_id={tracer.trace_id}）"
        )
        started_at = time.perf_counter()
        result = agent.route(
            question,
            tracer=tracer,
            history=history or None,
            prior_runtime_task_json=snapshot or None,
        )
        summary = summarize_turn(index + 1, question, result)
        summaries.append(summary)
        _print(
            f"[第{index + 1}轮] 返回，耗时 {time.perf_counter() - started_at:.1f}s，"
            f"followup={summary['followup']}，路径={summary['query_type'] or '空'}，"
            f"受影响={summary['affected'] or '无'}，选片={len(summary['selected_ids'])} 张"
        )
        _print(f"[第{index + 1}轮] 回答摘要：{summary['answer'][:200].replace(chr(10), ' ')}")

        # 会话层线程化（等价 server send_message）：历史追加、快照仅在无待澄清时更新
        history.append({"role": "user", "content": question})
        history.append({
            "role": "assistant",
            "content": summary["answer"],
            "photos": list(result.get("photos") or []),
        })
        if result.get("runtime_task_dump") and not result.get("runtime_clarification"):
            snapshot = str(result["runtime_task_dump"])

        turn_failures = _TURN_ASSERTIONS[index](
            summaries[index - 1] if index else {}, summary,
        )
        for item in turn_failures:
            _print(f"[第{index + 1}轮] 断言失败：{item}")
        failures.extend(turn_failures)

    return failures


def main() -> int:
    args = parse_args()
    cfg = config.Config(args.config)
    cfg.check_api_key()
    cfg.llm_request_timeout = args.llm_timeout
    cfg.retry_enabled = False
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if not backend_reachable(cfg.go_backend_url):
        print(f"FAIL：Go 后端不可达（{cfg.go_backend_url}），未消耗 LLM 调用。请先启动后端。")
        return 1
    _print(f"后端 {cfg.go_backend_url} 在线，真实回归请求超时={cfg.llm_request_timeout:.1f}s，模型重试已关闭")

    failures = run_scenario(cfg)
    if failures:
        print("FAIL：" + "；".join(failures))
        return 1
    print("PASS：AR4 真实多轮跟进识别与消解回归完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
