"""
    PID 参数调试脚本。

    用真实日志数据反推的 chunk 序列，模拟不同 PID 参数下的速度曲线。

    用法:
        cd agent
        python scripts/debug_pid.py --kp 0.1 --ki 0.0 --kd 0.0 --window 5
"""

import sys
import pathlib
import argparse

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from utils.streaming_printer import PIDController


# 从用户日志反推的 chunk 序列：(字符数, 到达间隔秒)
# 日志原文：
#   巷 → [10.87] → [21.09] → [994.15] → 口 → [16.77] → [1900.89] → [896.60]
#   → 的旧书店 → [7.05] → 亮着暖黄的灯，空气里飘着旧书页的 → [2.59]
CHUNK_SEQUENCE = [
    (1, 0.000),   # chunk 1: "巷", 首次 feed 无 speed 更新
    (1, 0.092),   # chunk 2: observed=10.87  (=1/0.092)
    (1, 0.047),   # chunk 3: observed=21.09  (=1/0.047)
    (50, 0.050),  # chunk 4: observed=994.15 (=50/0.050)  大 chunk
    (1, 0.060),   # chunk 5: observed=16.77  (=1/0.060)
    (50, 0.026),  # chunk 6: observed=1900.89(=50/0.026)  大 chunk
    (20, 0.022),  # chunk 7: observed=896.60 (=20/0.022)
    (5, 0.709),   # chunk 8: observed=7.05   (=5/0.709)   LLM 停顿
    (17, 6.560),  # chunk 9: observed=2.59   (=17/6.560)  LLM 大停顿
]


def simulate(kp: float, ki: float, kd: float, window_size: int,
             default_cps: float, min_cps: float, max_cps: float) -> None:
    pid = PIDController(kp=kp, ki=ki, kd=kd, output_min=min_cps, output_max=max_cps)
    current_cps = default_cps

    speed_samples: list[tuple[int, float]] = []

    print(f"参数: Kp={kp} Ki={ki} Kd={kd} window={window_size}")
    print(f"{'Step':>4} {'Chars':>5} {'Elapsed':>8} {'Observed':>10} {'New CPS':>10}  {'Notes'}")
    print("-" * 60)

    notes_map = {
        4: "大 chunk",
        6: "大 chunk",
        8: "LLM 停顿",
        9: "大停顿",
    }

    for i, (chars, elapsed) in enumerate(CHUNK_SEQUENCE, 1):
        note = notes_map.get(i, "")

        if i == 1:
            print(f"{i:>4} {chars:>5} {'-':>8} {'-':>10} {current_cps:>10.2f}  {note}")
            continue

        # 滑动窗口平均
        speed_samples.append((chars, elapsed))
        if len(speed_samples) > window_size:
            speed_samples.pop(0)

        total_chars = sum(c for c, _ in speed_samples)
        total_elapsed = sum(e for _, e in speed_samples)
        observed_cps = total_chars / total_elapsed if total_elapsed > 0 else 0.0

        current_cps = pid.update(
            setpoint=observed_cps,
            measurement=current_cps,
            dt=elapsed,
        )

        print(f"{i:>4} {chars:>5} {elapsed:>8.3f} {observed_cps:>10.2f} {current_cps:>10.2f}  {note}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PID 速度控制参数调试")
    parser.add_argument("--kp", type=float, default=0.1, help="比例系数")
    parser.add_argument("--ki", type=float, default=0.0, help="积分系数")
    parser.add_argument("--kd", type=float, default=0.0, help="微分系数")
    parser.add_argument("--window", type=int, default=5, help="滑动窗口大小")
    parser.add_argument("--default-cps", type=float, default=5.0, help="初始速度")
    parser.add_argument("--min-cps", type=float, default=5.0, help="最小速度")
    parser.add_argument("--max-cps", type=float, default=300.0, help="最大速度")
    args = parser.parse_args()

    simulate(
        kp=args.kp,
        ki=args.ki,
        kd=args.kd,
        window_size=args.window,
        default_cps=args.default_cps,
        min_cps=args.min_cps,
        max_cps=args.max_cps,
    )
