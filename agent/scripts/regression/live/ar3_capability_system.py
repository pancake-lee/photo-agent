"""AR3 真实数据与真实 LLM 的只读 Runtime 回归。

本脚本不属于日常 unittest discovery，必须在用户当轮明确授权后执行：

    cd agent
    .venv/bin/python scripts/regression/live/ar3_capability_system.py -c ../.local/my-config.yaml

它只读取照片库、向量库并调用 LLM；不会创建、更新或删除照片、标签、草稿或主题历史。
"""

from __future__ import annotations

import argparse
import logging
import pathlib
import sys
import time


AGENT_DIR = pathlib.Path(__file__).resolve().parents[3]
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import infra.config as config
import internal.evals.tracer as tracer_mod
import internal.runtime.graph as rt_graph
import internal.runtime.state as rt_state


CASES = (
    (
        "comparison",
        "对比 2025 年春天和 2026 年春天的照片，总结我的拍摄进步",
        rt_state.GOAL_PHOTO_COMPARISON,
    ),
    (
        "topics",
        "在 2026 年 5 月拍摄的照片中发现值得发布的主题候选",
        rt_state.GOAL_TOPIC_DISCOVERY,
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="执行经授权的 AR3 只读真实 Runtime 回归")
    parser.add_argument("-c", "--config", required=True, help="本地 Agent YAML 配置")
    parser.add_argument("--case", choices=("comparison", "topics", "all"), default="all")
    parser.add_argument("--llm-timeout", type=float, default=30.0, help="单次模型请求超时秒数")
    return parser.parse_args()


def _print(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def run_case(cfg: config.Config, name: str, question: str, goal_type: str) -> list[str]:
    tracer = tracer_mod.Tracer(cfg.project_root, cfg.agent_data_dir)
    previous_steps = ""

    def report_progress(event: str, data: dict) -> None:
        nonlocal previous_steps
        steps = data.get("steps") or []
        snapshot = " | ".join(
            f"{item.get('title', '处理任务')}：{item.get('status', '进行中')}"
            for item in steps
        )
        if snapshot and snapshot != previous_steps:
            previous_steps = snapshot
            _print(f"[{name}] 进度：{snapshot}")

    _print(f"[{name}] 开始，目标={goal_type}，trace={tracer.trace_file_ref()}，trace_id={tracer.trace_id}")
    started_at = time.perf_counter()
    result = rt_graph.run_runtime(
        cfg, question, goal_type=goal_type, tracer=tracer, progress_callback=report_progress,
    )
    _print(f"[{name}] Runtime 返回，耗时 {time.perf_counter() - started_at:.1f}s")
    print(f"[{name}] 问题：{question}", flush=True)
    print(f"[{name}] 终态：{result['terminal_reason'] or '无'}", flush=True)
    print(f"[{name}] 停止原因：{result['stop_reason'] or '无'}", flush=True)
    print(f"[{name}] 照片数：{len(result['photos'])}", flush=True)
    print(f"[{name}] 回答摘要：{result['answer'][:240].replace(chr(10), ' ')}", flush=True)
    failures = []
    if result["terminal_reason"]:
        failures.append(f"{name} 出现终态：{result['terminal_reason']}")
    if result["stop_reason"]:
        failures.append(f"{name} 出现停止原因：{result['stop_reason']}")
    if name == "comparison" and "照片依据：" not in result["answer"]:
        failures.append("comparison 未交付带照片依据的报告")
    if name == "topics" and "# 主题候选" not in result["answer"]:
        failures.append("topics 未交付主题候选")
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
    _print(f"真实回归请求超时={cfg.llm_request_timeout:.1f}s，模型重试已关闭")
    failures = []
    for name, question, goal_type in CASES:
        if args.case not in ("all", name):
            continue
        failures.extend(run_case(cfg, name, question, goal_type))
    if failures:
        print("FAIL：" + "；".join(failures))
        return 1
    print("PASS：AR3 真实只读 Runtime 回归完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
