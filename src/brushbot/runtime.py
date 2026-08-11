"""Runtime 集成: 时钟世界的执行组件。

设计: docs/superpowers/specs/2026-08-05-runtime-integration-design.md
本模块当前只有 Clock 部分 (§3.1); TactileExecutor/TickLog 按 spec 后续补齐。

Clock 契约: tick() 阻塞到下一拍边界, 返回 (t_now_s, overrun)。
- 首拍立即返回 (0.0, 0), 同时建立时间原点 t0。
- t 是相对 t0 的秒数。
- overrun = 本拍迟到的整周期数 (只记不停, 是健康指标不是错误)。
"""
import math
import time
from typing import Protocol

import numpy as np

from brushbot import config
from brushbot.types import Command


class Clock(Protocol):
    def tick(self) -> tuple[float, int]: ...


class NullClock:
    """离线时钟: 立即返回理想时间轴 i*dt。用于与 run_loop 的逐位对齐测试。"""

    def __init__(self, fs: float):
        self.dt = 1.0 / fs
        self._i = 0

    def tick(self) -> tuple[float, int]:
        t = self._i * self.dt
        self._i += 1
        return (t, 0)


class RealClock:
    """真时钟: 按 t0 + i*dt 绝对节拍 sleep-until-next。

    绝对边界而非相对 sleep(dt): 每拍干活耗时不吃进节拍, 无漂移累积。
    迟到超过整周期时记 overrun 并重新对齐到下一个未来边界。
    monotonic/sleep 可注入, 测试用假时间源确定性验证。
    """

    def __init__(self, fs: float, monotonic=time.monotonic, sleep=time.sleep):
        self.dt = 1.0 / fs
        self._monotonic = monotonic
        self._sleep = sleep
        self._t0 = None
        self._i = 0

    def tick(self) -> tuple[float, int]:
        if self._t0 is None:
            self._t0 = self._monotonic()
            return (0.0, 0)
        self._i += 1
        target = self._t0 + self._i * self.dt
        now = self._monotonic()
        overrun = 0
        if now > target:
            overrun = int((now - target) / self.dt)
            if overrun:
                # 重对齐到下一个未来边界 (简单 self._i += overrun 可能仍指向过去)
                self._i = math.ceil((now - self._t0) / self.dt)
                target = self._t0 + self._i * self.dt
        while True:
            now = self._monotonic()
            if now >= target:
                break
            self._sleep(target - now)
        return (now - self._t0, overrun)


class TactileSensor(Protocol):
    def read_new(self) -> list:
        """自上次调用以来的新样本, 每个 (3,) µT, 按到达顺序; 可为空列表(空拍)。"""


class TickLog:
    """每拍一行的全量飞行记录 (spec §3.4)。内存累积, save() 落 CSV。"""

    COLUMNS = ("t_s", "dBx_uT", "dBy_uT", "dBz_uT", "dBf_norm_uT", "g_d_uT",
               "x_m", "y_m", "z_cmd_m", "frozen", "n_new", "overrun")

    def __init__(self, fs: float):
        self.fs = fs
        self._rows = []
        self._abort = None

    def append(self, t, raw, dBf_norm, g_d, x, y, z_cmd, frozen, n_new,
               overrun) -> None:
        rx, ry, rz = (float("nan"),) * 3 if raw is None else map(float, raw)
        self._rows.append((float(t), rx, ry, rz, float(dBf_norm), float(g_d),
                           float(x), float(y), float(z_cmd), bool(frozen),
                           int(n_new), int(overrun)))

    def set_abort(self, reason: str, tick: int) -> None:
        self._abort = {"reason": reason, "tick": int(tick)}

    def __getitem__(self, col: str):
        i = self.COLUMNS.index(col)
        dtype = {"frozen": bool, "n_new": int, "overrun": int}.get(col, float)
        return np.array([r[i] for r in self._rows], dtype=dtype)

    def summary(self) -> dict:
        n = len(self._rows)
        overruns = int(self["overrun"].sum()) if n else 0
        jitter = 0.0
        if n > 1:
            dt_actual = np.diff(self["t_s"])
            jitter = float(np.abs(dt_actual - 1.0 / self.fs).max())
        return {"n_ticks": n, "overrun_total": overruns,
                "overrun_rate": overruns / n if n else 0.0,
                "max_jitter_s": jitter, "abort": self._abort}

    def save(self, path) -> None:
        with open(path, "w") as f:
            f.write(",".join(self.COLUMNS) + "\n")
            for r in self._rows:
                f.write(",".join(
                    str(int(v)) if isinstance(v, bool) else repr(v)
                    if isinstance(v, float) else str(v) for v in r) + "\n")


class PlantLink:
    """彩排注入件: 同一 sim_loop.Plant 的 sensor+backend 两面 (spec §3.5)。

    write(cmd) → plant.step(z) 存入缓冲; read_new() 取走。
    首拍预热: 以 z0 (= ctrl.z_surface) 初始化, 首拍 read_new 返回 plant.step(z0)
    —— 与 run_loop 首迭代逐语句一致, 杜绝对齐测试 off-by-one。
    """

    def __init__(self, plant, z0: float):
        self._plant = plant
        self._pending = [plant.step(z0)]

    def read_new(self) -> list:
        out = self._pending
        self._pending = []
        return out

    def write(self, cmd) -> None:
        self._pending.append(self._plant.step(cmd.tcp_pose[2]))


class TactileExecutor:
    """定频闭环执行器 (spec §3.2): 时钟世界里的 run_loop。

    每拍: tick → 收传感器样本(逐个喂滤波) → ctrl.step → backend.write → 记录
    → 看门狗。空拍沿用上一拍滤波值; 连续 stale_limit_s 无样本 → 抬笔中止。
    R1: NullClock + PlantLink 下 z_cmd 与 sim_loop.run_loop 逐位相等。
    """

    def __init__(self, plan, ctrl, filt, sensor, backend, clock,
                 stroke_duration_s: float, fs: float = config.FS,
                 fixed_ori=(0.0, 0.0, 0.0), lift: float = 0.015,
                 stale_limit_s: float = 0.2, noise_std: float = None):
        self._ctrl = ctrl
        self._filt = filt
        self._sensor = sensor
        self._backend = backend
        self._clock = clock
        self._fs = fs
        self._fixed_ori = tuple(fixed_ori)
        self._lift = lift
        self._stale_ticks = int(round(stale_limit_s * fs))
        self.noise_std = noise_std
        self._g_d, self._xy = plan.to_gd_series(stroke_duration_s, fs)

    def run(self) -> TickLog:
        log = TickLog(self._fs)
        dB_f = np.zeros(3)
        stale = 0
        for i in range(len(self._g_d)):
            t, overrun = self._clock.tick()
            samples = self._sensor.read_new()
            raw_last = None
            for s in samples:
                dB_f = self._filt.update(s) if self._filt is not None else s
                raw_last = s
            z_cmd = self._ctrl.step(dB_f, float(self._g_d[i]))
            x, y = float(self._xy[i, 0]), float(self._xy[i, 1])
            self._backend.write(Command(
                tcp_pose=(x, y, z_cmd, *self._fixed_ori)))
            log.append(t, raw_last, np.linalg.norm(dB_f), self._g_d[i],
                       x, y, z_cmd, self._ctrl.frozen, len(samples), overrun)
            stale = 0 if samples else stale + 1
            if stale >= self._stale_ticks:
                self._backend.write(Command(tcp_pose=(
                    x, y, self._ctrl.z_surface + self._lift,
                    *self._fixed_ori)))
                log.set_abort("sensor_stale", i)
                break
        return log


class ReplaySensor:
    """Replay 适配器 (spec §3.5): 包 monitor 源 (start/read/b0), 原始 B → ΔB。

    只验传感器半链: 回放的 ΔB 与 z 无因果, 不构成闭环 (spec §9.3)。
    """

    def __init__(self, source):
        self._source = source
        source.start()

    def read_new(self) -> list:
        return [np.array([bx, by, bz]) - self._source.b0
                for (_t, bx, by, bz) in self._source.read()]
