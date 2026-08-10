"""runtime 测试 (spec: 2026-08-05-runtime-integration-design.md §3/§6)。

Clock 契约: tick() 阻塞到下一拍边界, 返回 (t_now_s, overrun)。
- 首拍立即返回 (0.0, 0) (建立 t0)。
- t 是相对 t0 的秒数; NullClock 恒为 i*dt, RealClock 为真实流逝时间。
- overrun = 本拍迟到的整周期数, 只记不停。

TactileExecutor 验收核心 = R1: NullClock 下 z_cmd 与 sim_loop.run_loop 逐位相等。
"""
import math

import numpy as np
import pytest

from brushbot.monitor.core import EMA
from brushbot.runtime import (
    NullClock, PlantLink, RealClock, TactileExecutor, TickLog)
from brushbot.sim_loop import Plant, run_loop
from brushbot.strokeplan import Stroke, StrokePlan
from brushbot.types import Command
from brushbot.z_control import ZController, calib_lookup_z


class TestNullClock:
    def test_returns_ideal_timeline_immediately(self):
        clk = NullClock(fs=100.0)
        assert clk.tick() == (0.0, 0)
        assert clk.tick() == (pytest.approx(0.01), 0)
        assert clk.tick() == (pytest.approx(0.02), 0)


class FakeTime:
    """确定性时间源: monotonic 可手动推进, sleep 精确推进。"""
    def __init__(self):
        self.now = 1000.0  # 非零起点: 验证返回的是相对时间
        self.sleeps = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.sleeps.append(s)
        self.now += s


class TestRealClock:
    def test_first_tick_establishes_origin(self):
        ft = FakeTime()
        clk = RealClock(fs=100.0, monotonic=ft.monotonic, sleep=ft.sleep)
        assert clk.tick() == (0.0, 0)
        assert ft.sleeps == []  # 首拍不睡

    def test_sleeps_to_absolute_boundaries_no_drift(self):
        ft = FakeTime()
        clk = RealClock(fs=100.0, monotonic=ft.monotonic, sleep=ft.sleep)
        clk.tick()
        ft.now += 0.003  # 本拍干活 3ms
        t, overrun = clk.tick()
        assert t == pytest.approx(0.01)
        assert overrun == 0
        # 即使每拍干活时长不同, 边界仍是绝对的 t0 + i*dt
        ft.now += 0.007
        t, _ = clk.tick()
        assert t == pytest.approx(0.02)

    def test_timeline_monotonic_over_many_ticks(self):
        ft = FakeTime()
        clk = RealClock(fs=100.0, monotonic=ft.monotonic, sleep=ft.sleep)
        ts = [clk.tick()[0] for _ in range(20)]
        assert ts == sorted(ts)
        assert ts[-1] == pytest.approx(0.19)

    def test_overrun_counts_missed_periods_and_resyncs(self):
        ft = FakeTime()
        clk = RealClock(fs=100.0, monotonic=ft.monotonic, sleep=ft.sleep)
        clk.tick()
        ft.now += 0.035  # 干活 35ms: 错过 10ms/20ms/30ms 三个边界
        t, overrun = clk.tick()
        # 迟到 25ms = 2 个整周期, 重新对齐到下一个未来边界 40ms
        assert overrun == 2
        assert t == pytest.approx(0.04)
        # 恢复正常后不再报 overrun
        assert clk.tick() == (pytest.approx(0.05), 0)

    def test_wall_clock_smoke(self):
        # 真实时钟短跑: 50Hz 10 拍 ~0.18s, 时间轴单调且总时长合理
        import time
        clk = RealClock(fs=50.0)
        t0 = time.monotonic()
        ts = [clk.tick()[0] for _ in range(10)]
        elapsed = time.monotonic() - t0
        assert ts == sorted(ts)
        assert ts[-1] == pytest.approx(0.18, abs=0.02)
        assert 0.15 < elapsed < 0.30


# ---------------------------------------------------------------- 执行器测试

CALIB_Z = np.array([0.0, 1.0, 2.0, 3.0])
CALIB_DB = np.array([0.0, 60.0, 110.0, 150.0])
NOISE_STD = 2.0
Z_SURF = 0.20
FS = 100.0
DUR_S = 1.0   # 单笔时长; to_gd_series 默认 gap 0.5s -> 共 150 拍


def make_ctrl():
    return ZController(CALIB_Z, CALIB_DB, z_surface=Z_SURF, noise_std=NOISE_STD)


def make_plant():
    return Plant(CALIB_Z, CALIB_DB, z_surface=Z_SURF)  # 无噪声 -> 确定性


def make_plan():
    """单笔画: g_press 正弦鼓包, 两端 0 (穿越 3σ 接触阈值, 覆盖 freeze 切换)。"""
    m = 50
    s = np.linspace(0.0, 1.0, m)
    xy = np.column_stack([np.linspace(0.40, 0.44, m), np.zeros(m)])
    g = 100.0 * np.sin(np.pi * s)
    z_ff = np.asarray(calib_lookup_z(g, CALIB_Z, CALIB_DB), float)
    return StrokePlan(strokes=[Stroke(s=s, xy=xy, g_press=g, z_ff=z_ff)])


class ListSensor:
    """预排好的样本流: schedule[i] = 第 i 拍到达的样本列表。"""
    def __init__(self, schedule):
        self.schedule = schedule
        self.i = 0

    def read_new(self):
        out = self.schedule[self.i] if self.i < len(self.schedule) else []
        self.i += 1
        return out


class RecordingBackend:
    def __init__(self):
        self.writes = []

    def write(self, cmd):
        self.writes.append(cmd)


def make_executor(sensor, backend, **kw):
    kw.setdefault("clock", NullClock(fs=FS))
    kw.setdefault("stroke_duration_s", DUR_S)
    kw.setdefault("fs", FS)
    return TactileExecutor(make_plan(), make_ctrl(), EMA(0.3),
                           sensor=sensor, backend=backend, **kw)


class TestPlantLink:
    def test_matches_direct_plant_bit_exact(self):
        z_seq = [0.2, 0.201, 0.199, 0.2005]
        ref_plant = make_plant()
        ref = [ref_plant.step(z) for z in [Z_SURF] + z_seq]

        link = PlantLink(make_plant(), z0=Z_SURF)
        got = [link.read_new()[0]]           # 首拍预热 = plant.step(z0)
        for z in z_seq:
            link.write(Command(tcp_pose=(0.4, 0.0, z, 0.0, 0.0, 0.0)))
            got.append(link.read_new()[0])
        assert np.array_equal(np.array(ref), np.array(got))

    def test_read_new_drains_buffer(self):
        link = PlantLink(make_plant(), z0=Z_SURF)
        assert len(link.read_new()) == 1
        assert link.read_new() == []


class TestAlignmentR1:
    def test_z_cmd_bitwise_equal_to_run_loop(self):
        plan = make_plan()
        g_d, xy = plan.to_gd_series(DUR_S, FS)
        ref = run_loop(make_ctrl(), EMA(0.3), g_d, make_plant())
        # freeze 穿越段确实被场景覆盖 (悬空/接触两态都出现)
        assert ref["frozen"].any() and (~ref["frozen"]).any()

        link = PlantLink(make_plant(), z0=Z_SURF)
        log = make_executor(sensor=link, backend=link).run()

        assert np.array_equal(log["z_cmd_m"], ref["z_cmd"])   # 零容差
        assert np.array_equal(log["g_d_uT"], g_d)
        assert np.array_equal(log["x_m"], xy[:, 0])
        assert np.array_equal(log["frozen"], ref["frozen"])

    def test_commands_carry_xy_and_fixed_ori(self):
        link = PlantLink(make_plant(), z0=Z_SURF)
        backend = RecordingBackend()
        # sensor 与 plant 闭环断开也能跑 (backend 只记录): 这里只验 Command 组装
        ex = make_executor(sensor=link, backend=backend,
                           fixed_ori=(math.pi, 0.0, math.pi / 2))
        log = ex.run()
        cmd = backend.writes[0]
        assert cmd.tcp_pose[3:] == (math.pi, 0.0, math.pi / 2)
        assert cmd.tcp_pose[2] == log["z_cmd_m"][0]


class TestEmptyTickTolerance:
    def test_every_third_tick_empty(self):
        n = 150
        rng = np.random.default_rng(7)
        full = [rng.normal(0, 5, 3) for _ in range(n)]
        schedule = [[full[i]] if i % 3 != 2 else [] for i in range(n)]
        log = make_executor(ListSensor(schedule), RecordingBackend()).run()

        assert np.isfinite(log["z_cmd_m"]).all()
        # 滤波器状态忠于真实样本流: 与只喂真样本的参考 EMA 一致
        ref = EMA(0.3)
        ref_out = [ref.update(s) for i, s in enumerate(full) if i % 3 != 2]
        got = log["dBf_norm_uT"][np.array([i % 3 != 2 for i in range(n)])]
        assert np.allclose(got, [np.linalg.norm(o) for o in ref_out])
        # 空拍标记: raw 三列 NaN + n_new=0 双重标记
        empty = np.array([i % 3 == 2 for i in range(n)])
        assert np.isnan(log["dBx_uT"][empty]).all()
        assert (log["n_new"][empty] == 0).all()
        assert (log["n_new"][~empty] == 1).all()


class TestMultiSampleTick:
    def test_filter_consumes_samples_in_order(self):
        s1, s2 = np.array([10.0, 0, 0]), np.array([20.0, 0, 0])
        schedule = [[s1.copy(), s2.copy()]] + [[] for _ in range(149)]
        log = make_executor(ListSensor(schedule), RecordingBackend()).run()

        ref = EMA(0.3)
        ref.update(s1)
        expect = np.linalg.norm(ref.update(s2))
        assert log["dBf_norm_uT"][0] == pytest.approx(expect)
        assert log["n_new"][0] == 2


class TestWatchdog:
    def test_aborts_at_threshold_with_lift_command(self):
        n_ok = 5
        schedule = [[np.array([50.0, 0, 0])]] * n_ok  # 之后永远空拍
        backend = RecordingBackend()
        ex = make_executor(ListSensor(schedule), backend, stale_limit_s=0.2)
        log = ex.run()

        stale_ticks = 20                       # 0.2s * 100Hz
        n_ticks = n_ok + stale_ticks
        assert len(log["z_cmd_m"]) == n_ticks  # 恰在阈值拍中止
        info = log.summary()["abort"]
        assert info is not None
        assert "stale" in info["reason"]
        assert info["tick"] == n_ticks - 1
        # 末条指令是抬笔: z = z_surface + lift, XY 保持中止拍位置
        last = backend.writes[-1]
        assert last.tcp_pose[2] == pytest.approx(Z_SURF + 0.015)
        assert last.tcp_pose[0] == backend.writes[-2].tcp_pose[0]
        # 正常写入数 = 拍数, 抬笔是额外一条
        assert len(backend.writes) == n_ticks + 1


class TestNaNChain:
    def test_nan_sample_freezes_and_z_stays_finite(self):
        schedule = [[np.array([50.0, 0, 0])]] * 10 \
            + [[np.array([np.nan, 0, 0])]] \
            + [[np.array([50.0, 0, 0])]] * 139
        log = make_executor(ListSensor(schedule), RecordingBackend()).run()
        assert log["frozen"][10]               # NaN 拍 frozen
        assert np.isfinite(log["z_cmd_m"]).all()


class TestTickLog:
    def test_columns_save_roundtrip_and_summary(self, tmp_path):
        clock = NullClock(fs=FS)
        clock_ticks = [(0.0, 0), (0.01, 0), (0.03, 1)]  # 1 次 overrun

        class StubClock:
            def __init__(self):
                self.i = 0

            def tick(self):
                out = clock_ticks[self.i]
                self.i += 1
                return out

        schedule = [[np.array([50.0, 0, 0])]] * 150
        ex = make_executor(ListSensor(schedule), RecordingBackend(),
                           clock=StubClock())
        # 只跑 3 拍: 截短目标序列
        ex._g_d = ex._g_d[:3]
        ex._xy = ex._xy[:3]
        log = ex.run()

        assert log.summary()["overrun_total"] == 1
        assert log.summary()["n_ticks"] == 3
        assert log.summary()["abort"] is None

        path = tmp_path / "ticklog.csv"
        log.save(path)
        back = np.genfromtxt(path, delimiter=",", names=True)
        for col in ("t_s", "dBx_uT", "dBy_uT", "dBz_uT", "dBf_norm_uT",
                    "g_d_uT", "x_m", "y_m", "z_cmd_m", "frozen", "n_new",
                    "overrun"):
            assert col in back.dtype.names
        assert np.allclose(back["z_cmd_m"], log["z_cmd_m"])


class TestReplaySensor:
    def test_wraps_source_batches_to_delta_b(self):
        class StubSource:
            b0 = np.array([100.0, 200.0, 300.0])

            def __init__(self):
                self.started = False
                self._batches = [
                    [(0.0, 110.0, 200.0, 300.0), (0.01, 100.0, 205.0, 300.0)],
                    [],
                ]

            def start(self):
                self.started = True

            def read(self):
                return self._batches.pop(0) if self._batches else []

        from brushbot.runtime import ReplaySensor
        src = StubSource()
        sensor = ReplaySensor(src)
        assert src.started                       # 构造即 start
        batch = sensor.read_new()
        assert np.allclose(batch[0], [10.0, 0.0, 0.0])   # ΔB = B - b0
        assert np.allclose(batch[1], [0.0, 5.0, 0.0])
        assert sensor.read_new() == []           # 空批透传
