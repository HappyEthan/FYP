#!/usr/bin/env python3
"""Runtime 彩排 CLI (spec 2026-08-05 §4): 闭环执行链路的纯软件排练。

用法 (单行):
    python scripts/run_tactile.py --sim
    python scripts/run_tactile.py --replay delta_b_v0_20260724/xxx.csv

--sim: 合成示范 → build_plan → TactileExecutor 真时钟 (RealClock 100Hz) 闭环
       (Plant 注入件) → 打印 R2 时序统计 + 接触段跟踪 RMS (Phase 1 基线同量级
       为过关) → TickLog 落盘。
--replay: monitor ReplaySource 回放真实录音走传感器半链 (backend=fake, 不闭环,
       只验数据通路与时序)。
"""
import argparse
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from brushbot.backends.fake import FakeBackend                  # noqa: E402
from brushbot.demo_pipeline import build_plan, load_demo        # noqa: E402
from brushbot.monitor.core import EMA                           # noqa: E402
from brushbot.monitor.sources import ReplaySource               # noqa: E402
from brushbot.runtime import (PlantLink, RealClock,             # noqa: E402
                              ReplaySensor, TactileExecutor)
from brushbot.sim_loop import Plant, V0NoiseSource, rms_pct     # noqa: E402
from brushbot.z_control import ZController                      # noqa: E402
from synth_demo import make_demo, write_demo_csv                # noqa: E402

FS = 100.0
CALIB_Z = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
CALIB_DB = np.array([0.0, 50.0, 100.0, 150.0, 200.0, 250.0])
SEED = 42
STROKE_DURATION_S = 3.0


class TracingLink(PlantLink):
    """PlantLink + 记录 plant 真值 abs_true (RMS 评估用, 库外职责)。"""

    def __init__(self, plant, z0):
        self._plant_ref = plant
        super().__init__(plant, z0)
        self.abs_true = [plant.abs_true]

    def write(self, cmd):
        super().write(cmd)
        self.abs_true.append(self._plant_ref.abs_true)


def _print_r2(summary):
    print("R2 时序: %d 拍, overrun %d (%.2f%%), 最大抖动 %.2fms"
          % (summary["n_ticks"], summary["overrun_total"],
             100.0 * summary["overrun_rate"], 1000.0 * summary["max_jitter_s"]))
    if summary["abort"]:
        print("[中止] %s @ tick %d"
              % (summary["abort"]["reason"], summary["abort"]["tick"]))


def _sim_plan(noise, work):
    rows, _truth = make_demo(speed_mod=0.5, seed=SEED, noise=noise)
    p = work / "demo_sim.csv"
    write_demo_csv(p, rows)
    return build_plan(load_demo(p), CALIB_Z, CALIB_DB)


def run_sim(out_path):
    csvs = sorted(p for p in (ROOT / "delta_b_v0_20260724").glob("*.csv")
                  if "idle" in p.stem)
    work = Path(tempfile.mkdtemp(prefix="run-tactile-"))
    noise = V0NoiseSource(csvs, seed=SEED) if csvs else None
    noise_std = noise.filtered_sigma(EMA) if noise else 7.0
    print("noise_std (EMA 滤波后 σ): %.3f µT" % noise_std)

    plan = _sim_plan(noise, work)
    ctrl = ZController(CALIB_Z, CALIB_DB, noise_std=noise_std)
    plant = Plant(CALIB_Z, CALIB_DB, z_surface=ctrl.z_surface,
                  noise=V0NoiseSource(csvs, seed=SEED + 1) if csvs else None)
    link = TracingLink(plant, z0=ctrl.z_surface)
    ex = TactileExecutor(plan, ctrl, EMA(0.3), sensor=link, backend=link,
                         clock=RealClock(fs=FS),
                         stroke_duration_s=STROKE_DURATION_S, fs=FS,
                         noise_std=noise_std)
    print("闭环彩排: %d 笔, %d 拍 (~%.1fs 真时间)..."
          % (len(plan.strokes), len(ex._g_d), len(ex._g_d) / FS))
    log = ex.run()

    s = log.summary()
    _print_r2(s)
    n = s["n_ticks"]
    res = {"g_d": log["g_d_uT"],
           "abs_true": np.array(link.abs_true[:n])}
    print("接触段跟踪 RMS: %.1f%% (Phase 1 基线 ~9.5%% 同量级为过关)"
          % rms_pct(res, noise_std))
    log.save(out_path)
    print("TickLog -> %s" % out_path)


def run_replay(csv_path, out_path):
    src = ReplaySource(csv_path)
    work = Path(tempfile.mkdtemp(prefix="run-tactile-"))
    plan = _sim_plan(None, work)
    ctrl = ZController(CALIB_Z, CALIB_DB)
    ex = TactileExecutor(plan, ctrl, EMA(0.3), sensor=ReplaySensor(src),
                         backend=FakeBackend(dt=1.0 / FS),
                         clock=RealClock(fs=FS),
                         stroke_duration_s=STROKE_DURATION_S, fs=FS)
    print("回放半链 (不闭环): %s, %d 拍..." % (src.name, len(ex._g_d)))
    log = ex.run()
    _print_r2(log.summary())
    n_new = log["n_new"]
    print("样本: 共 %d 个, 空拍率 %.1f%%, 单拍最多 %d 个"
          % (int(n_new.sum()), 100.0 * float((n_new == 0).mean()),
             int(n_new.max())))
    log.save(out_path)
    print("TickLog -> %s" % out_path)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--sim", action="store_true")
    g.add_argument("--replay", metavar="CSV")
    ap.add_argument("--out", default=None, help="TickLog CSV 输出路径")
    args = ap.parse_args()
    out = args.out or str(Path(tempfile.mkdtemp(prefix="run-tactile-"))
                          / "ticklog.csv")
    if args.sim:
        run_sim(out)
    else:
        run_replay(args.replay, out)


if __name__ == "__main__":
    main()
