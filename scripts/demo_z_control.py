"""Phase 0 Demo: 整体 ΔB 跟踪闭环仿真.

Usage:
    python scripts/demo_z_control.py --output z_control_demo.png
    python scripts/demo_z_control.py --v0 delta_b_v0_20260724/20260724_143839_line_lr_r02 --output demo_line.png
    python scripts/demo_z_control.py --v0 delta_b_v0_20260724/20260724_144151_circle_cw_r01 --output demo_circle.png

Output: three-panel figure — target |ΔB| vs measured, z_cmd decomposition, error.
"""
import argparse

import numpy as np

from brushbot.z_control import ZController
from brushbot.tactile import contact_sim
from brushbot.sim_loop import Plant, run_loop


def _load_v0(path):
    """Load V0 CSV, return (t_s, abs_dB) arrays."""
    d = np.genfromtxt(path, delimiter=",", names=True)
    t = d["t_s"]
    dB = np.c_[d["dBx_uT"], d["dBy_uT"], d["dBz_uT"]]
    abs_dB = np.linalg.norm(dB, axis=1)
    return t, abs_dB


def _synthetic_target(n=400, fs=100.0):
    """Synthetic target: unit-normalized profile [0, 1].

    Shape: ramp up, hold, step down, hold.  Scaled to calibration
    range inside _run_demo.
    """
    t = np.arange(n) / fs
    profile = np.zeros(n)
    n_ramp = 80
    n_hold1 = 120
    profile[:n_ramp] = np.linspace(0, 1.0, n_ramp)             # touch down
    profile[n_ramp:n_ramp + n_hold1] = 1.0                       # press steady
    profile[n_ramp + n_hold1:n_ramp + n_hold1 + n_ramp] = \
        np.linspace(1.0, 0.5, n_ramp)                            # partial lift
    profile[n_ramp + n_hold1 + n_ramp:] = 0.5                    # lighter press
    return t, profile


def _run_demo(target_abs_dB, dt=0.01, kp=None, ki=None,
              calib_z_mm=None, calib_abs_dB=None):
    """闭环 demo: 合成标定 + sim_loop.run_loop (唯一闭环路径)."""
    if calib_z_mm is None or calib_abs_dB is None:
        cal = contact_sim.calibrate()
        calib_z_mm, calib_abs_dB = cal["z_mm"], cal["abs_dB"]
    cal_max = float(calib_abs_dB.max())
    noise_std = max(cal_max * 0.02, 1e-12)
    kw = {}
    if kp is not None:
        kw["kp"] = kp
    if ki is not None:
        kw["ki"] = ki
    ctrl = ZController(calib_z_mm, calib_abs_dB, dt=dt, noise_std=noise_std, **kw)
    target = np.asarray(target_abs_dB, dtype=float).copy()
    if target.max() > 0 and cal_max > 0:
        target *= 0.8 * cal_max / target.max()
    plant = Plant(calib_z_mm, calib_abs_dB, dt=dt)
    res = run_loop(ctrl, None, target, plant)
    return {"time": res["t"], "z_surface": ctrl.z_surface, "target": res["g_d"],
            "meas": res["abs_f"], "z_cmd": res["z_cmd"],
            "z_ff": ctrl.z_surface + res["z_ff"], "z_fb": res["z_fb"],
            "frozen": res["frozen"]}


def plot_result(result, out_path):
    """Three-panel figure: tracking, z decomposition, error."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(10, 8), sharex=True)

    t = result["time"]
    # Panel 1: Tracking
    ax1.plot(t, result["target"], "k-", lw=2, label="target |ΔB|_d")
    ax1.plot(t, result["meas"], "--", color="crimson", lw=1.5, label="|ΔB_meas|")
    frozen_mask = result["frozen"]
    if frozen_mask.any():
        ax1.fill_between(t, 0, result["target"].max() * 0.1,
                          where=frozen_mask, color="gray", alpha=0.15,
                          label="frozen")
    ax1.set_ylabel("|ΔB| (arb.)")
    ax1.legend(fontsize=9)
    ax1.grid(alpha=0.3)

    # Panel 2: z decomposition
    z_surface = result["z_surface"]
    ax2.plot(t, (result["z_cmd"] - z_surface) * 1000, "k-", lw=2, label="z_cmd offset")
    ax2.plot(t, (result["z_ff"] - z_surface) * 1000, ":", color="steelblue", lw=1.5, label="z_ff")
    ax2.plot(t, result["z_fb"] * 1000, "-.", color="orange", lw=1.5, label="z_fb")
    ax2.set_ylabel("z offset (mm)")
    ax2.legend(fontsize=9)
    ax2.grid(alpha=0.3)

    # Panel 3: Error
    error = (result["target"] - result["meas"]) / np.clip(result["target"], 1e-9, None) * 100
    ax3.plot(t, error, lw=1.5, color="crimson")
    ax3.axhline(5, ls=":", color="gray"); ax3.axhline(-5, ls=":", color="gray")
    ax3.text(t[-1] * 0.02, 5.5, "±5%", fontsize=8, color="gray")
    ax3.set_ylabel("relative error (%)")
    ax3.set_xlabel("time (s)")
    ax3.grid(alpha=0.3)

    rms = float(np.sqrt(np.mean(error[len(error)//4:] ** 2)))
    ax3.set_title(f"relative error (last 75% RMS: {rms:.1f}%)")

    fig.suptitle("Phase 0: overall ΔB tracking — closed loop in simulation", fontsize=13)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    print(f"Saved: {out_path}")
    plt.close(fig)
    return rms


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--v0", type=str, default=None,
                   help="V0 CSV path for target |ΔB(t)|")
    p.add_argument("--output", type=str, default="z_control_demo.png",
                   help="Output image path")
    args = p.parse_args()

    if args.v0:
        target_t, target_abs_dB = _load_v0(args.v0)
    else:
        target_t, target_abs_dB = _synthetic_target()

    result = _run_demo(target_abs_dB, dt=0.01)
    rms = plot_result(result, args.output)

    print(f"RMS tracking error (last 75%): {rms:.1f}%")


if __name__ == "__main__":
    main()
