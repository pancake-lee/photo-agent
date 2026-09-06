"""真实数据与真实 LLM 的只读 Runtime 回归。

本脚本不属于日常 unittest discovery，必须获得当轮用户明确授权后才可执行：

    cd agent
    python scripts/regression/live/shanxi_day4.py -c ../.local/my-config.yaml

它只调用照片库的读取接口、向量检索和 LLM；不会创建、更新或删除照片库数据。
"""

from __future__ import annotations

import argparse
import pathlib
import sys


AGENT_DIR = pathlib.Path(__file__).resolve().parents[1]
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import infra.config as config
import internal.runtime.graph as rt_graph


QUESTION = "找山西旅游第4天的照片并生成发布文案"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="执行经授权的山西第 4 天真实 Runtime 回归")
    parser.add_argument("-c", "--config", required=True, help="本地 Agent YAML 配置")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = config.Config(args.config)
    cfg.check_api_key()
    result = rt_graph.run_runtime(cfg, QUESTION)

    print(f"问题：{QUESTION}")
    print(f"终态：{result['terminal_reason'] or '无'}")
    print(f"停止原因：{result['stop_reason'] or '无'}")
    print(f"照片数：{len(result['photos'])}")
    print(f"恢复计数：{result['recovery_used']}")

    failures = []
    if result["terminal_reason"]:
        failures.append(f"出现终态：{result['terminal_reason']}")
    if result["stop_reason"]:
        failures.append(f"出现停止原因：{result['stop_reason']}")
    if not result["photos"]:
        failures.append("未交付照片")
    if not result["answer"].lstrip().startswith("# "):
        failures.append("未交付标题和文案")
    if failures:
        print("FAIL：" + "；".join(failures))
        return 1
    print("PASS：完整交付照片、标题和文案。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
