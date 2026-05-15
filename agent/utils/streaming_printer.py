"""
    自适应速度流式文本打印机（PID 速度控制版）。

    根据 LLM chunk 的到达频率动态调整逐字打印速度，
    用 PID 控制器平滑跟踪服务端生成节奏。

    用法:
        from utils.streaming_printer import StreamingPrinter

        with StreamingPrinter() as printer:
            for chunk in llm.stream(...):
                printer.feed(chunk.content)
"""

import threading
import time
from typing import Optional


# --------------------------------------------------------------------------- #
# PID 控制器 — 纯算法封装，与业务无关
# --------------------------------------------------------------------------- #

class PIDController:
    """
    PID（比例-积分-微分）控制器。

    控制目标：让 process_variable（当前测量值）平滑跟踪 setpoint（目标值）。

    输出公式（采样间隔无关版，微分先行）：
        output = measurement + Kp * error + Ki * integral + Kd * derivative
        其中 error = setpoint - measurement
        微分项 derivative = -(measurement - last_measurement)

    换算到 1s 间隔：所有系数均在"1秒标准间隔"下标定，
    算法内部消除了 dt 对积分/微分项的影响。
    语义：Kp=1, Ki=0, Kd=0 → 输出直接等于 setpoint（完全跟踪）。

    参数:
        kp: 比例系数，越大响应越快，但可能振荡
        ki: 积分系数，消除稳态误差，过大易累积过冲
        kd: 微分系数，抑制超调和振荡
        output_min, output_max: 输出限制（anti-windup）
    """

    def __init__(
        self,
        kp: float,
        ki: float,
        kd: float,
        output_min: float,
        output_max: float,
    ):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.output_min = output_min
        self.output_max = output_max

        self._integral: float = 0.0
        self._last_measurement: float = 0.0
        self._first: bool = True

    def reset(self) -> None:
        """重置积分和历史测量值（如切换控制对象时调用）。"""
        self._integral = 0.0
        self._last_measurement = 0.0
        self._first = True

    def update(self, setpoint: float, measurement: float, dt: float) -> float:
        """
        执行一次 PID 计算（采样间隔无关版，微分先行）。

        参数:
            setpoint:    目标值
            measurement: 当前测量值
            dt:          采样间隔（秒），保留在接口中供扩展，
                         当前实现已消除 dt 对三因子的影响

        返回:
            控制输出值（已 clamp 到 [output_min, output_max]）
        """
        error = setpoint - measurement

        # 比例项
        p = self.kp * error

        # 积分项：采样间隔无关（不乘 dt）
        self._integral += error
        i = self.ki * self._integral

        # 微分先行：作用于测量值变化，抑制输出突变。
        # 标准微分（对误差求导） 在 setpoint 突变时会助推。
        #   d = Kd * (error - last_error)
        # 微分先行（对测量值求导） 只在输出变化快时刹车。
        #   d = -Kd * (measurement - last_measurement)
        if self._first:
            d = 0.0
            self._first = False
        else:
            d = -self.kd * (measurement - self._last_measurement)
        self._last_measurement = measurement

        # 基准线为当前测量值，语义：Kp=1 时 output = setpoint
        output = measurement + p + i + d

        # 输出限制 + 积分饱和回滚（anti-windup）
        if output > self.output_max:
            excess = output - self.output_max
            if self.ki != 0:
                self._integral -= (excess / self.ki)
            output = self.output_max
        elif output < self.output_min:
            deficit = self.output_min - output
            if self.ki != 0:
                self._integral += (deficit / self.ki)
            output = self.output_min

        return output


# --------------------------------------------------------------------------- #
# StreamingPrinter — 基于 PID 的自适应速度打印器
# --------------------------------------------------------------------------- #

class StreamingPrinter:
    """
    后台线程按 PID 自适应速度逐字打印文本。
    PS: 本来这里是用了EMA算法的，但是速度突变还是存在
        学生时代用过PID搞过平衡车，就拿来玩玩
        然后工业控制的dt是固定的，但是LLM的chunk到达是随机的
        所以dt不固定，改了一下算法，直接把dt消掉了，换算成1s标准间隔了

    核心控制回路：
    1. 观测环节：记录每个 chunk 的到达时间和字符数
    2. 计算环节：滑动窗口平均速度 = 窗口内总字符数 / 总时间
       （消除单个大 chunk 导致的观测速度突变）
    3. 控制环节：PID（采样间隔无关版）以平均观测速度为目标，调整当前打印速度
    4. 执行环节：后台线程按当前速度逐字输出

    PID 参数语义（已消除 dt 影响，换算为 1s 标准间隔）：
        - Kp=1, Ki=0, Kd=0 → 输出直接等于观测速度（完全跟踪）
        - Kp 大 → 跟踪更灵敏，但 chunk 抖动时打印速度波动也大
        - Ki 大 → 最终打印速度更接近平均观测速度，但响应变慢
        - Kd 大 → 抑制速度突变，让打印更平滑（微分先行，只在输出变化快时刹车）

    该设计将"服务端生成速度"与"客户端打印速度"解耦，
    后续迁移到 SSE API 时只需复用 PIDController，
    外层替换为 async 事件循环即可。
    """

    def __init__(
        self,
        default_cps: float = 5.0,
        min_cps: float = 5.0,
        max_cps: float = 300.0,
        kp: float = 0.03,
        ki: float = 0.0,
        kd: float = 0.03,
        speed_window_size: int = 5,
    ):
        self.default_cps = default_cps
        self.min_cps = min_cps
        self.max_cps = max_cps

        # PID 控制器：目标 = 服务端观测速度，测量值 = 当前打印速度
        self._pid = PIDController(
            kp=kp,
            ki=ki,
            kd=kd,
            output_min=min_cps,
            output_max=max_cps,
        )
        self._current_cps = default_cps

        self._last_feed_time: Optional[float] = None
        self._last_feed_chars = 0

        # 滑动窗口：消除单个大 chunk 导致的观测速度突变
        self._speed_samples: list[tuple[int, float]] = []  # (chars, elapsed)
        self._speed_window_size = speed_window_size

        self._buffer = ""
        self._lock = threading.Lock()
        self._running = True
        self._closing = False
        self._has_data = threading.Event()
        self._thread = threading.Thread(target=self._print_loop, daemon=True)
        self._thread.start()

    def _update_speed(self, now: float) -> None:
        """根据滑动窗口平均观测速度，用 PID 更新当前打印速度。"""
        if self._last_feed_time is None or self._last_feed_chars == 0:
            return

        elapsed = now - self._last_feed_time
        if elapsed < 0.001:
            return

        # 记录本次样本到滑动窗口
        self._speed_samples.append((self._last_feed_chars, elapsed))
        if len(self._speed_samples) > self._speed_window_size:
            self._speed_samples.pop(0)

        # 窗口平均速度：消除单个大 chunk 导致的观测突变
        total_chars = sum(c for c, _ in self._speed_samples)
        total_elapsed = sum(e for _, e in self._speed_samples)
        if total_elapsed <= 0:
            return

        observed_cps = total_chars / total_elapsed
        self._current_cps = self._pid.update(
            setpoint=observed_cps,
            measurement=self._current_cps,
            dt=elapsed,
        )

    def _print_loop(self) -> None:
        """后台打印线程：按当前速度从缓冲区逐字输出。"""
        while True:
            self._has_data.wait(timeout=0.05)
            self._has_data.clear()

            with self._lock:
                text = self._buffer
                self._buffer = ""

            for ch in text:
                print(ch, end="", flush=True)
                time.sleep(1.0 / self.current_cps)

            # 关闭信号且缓冲区已空时才真正退出，防止末尾字符丢失
            with self._lock:
                if self._closing and not self._buffer:
                    break

    def feed(self, text: str) -> None:
        """
        喂入新文本 chunk，触发 PID 速度更新并加入打印队列。

        参数:
            text: LLM 返回的文本 chunk
        """
        if not text:
            return

        now = time.time()
        self._update_speed(now)

        with self._lock:
            self._buffer += text

        self._last_feed_time = now
        self._last_feed_chars = len(text)
        self._has_data.set()

    def close(self) -> None:
        """关闭打印机，等待后台线程完成剩余内容。"""
        self._closing = True
        self._has_data.set()
        self._thread.join()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    @property
    def current_cps(self) -> float:
        """当前打印速度（字符/秒）。"""
        return self._current_cps
