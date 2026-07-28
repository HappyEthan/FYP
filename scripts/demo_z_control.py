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
    """Run closed-loop demo with synthetic plant.

    Controller gains and noise level are auto-computed from the
    calibration curve magnitude unless explicitly overridden.

    Returns dict of arrays for plotting.
    """
    if calib_z_mm is None or calib_abs_dB is None:
        cal = contact_sim.calibrate()
        calib_z_mm = cal["z_mm"]
        calib_abs_dB = cal["abs_dB"]

    # --- Auto-compute controller parameters from calibration ---
    cal_max = float(calib_abs_dB.max())
    z_range_m = calib_z_mm[-1] / 1000.0
    slope = z_range_m / cal_max if cal_max > 0 else 1.0  # m / arb

    if kp is None:
        kp = 0.3 * slope
    if ki is None:
        ki = 0.03 * slope
    noise_std = max(cal_max * 0.02, 1e-12)

    ctrl = ZController(calib_z_mm, calib_abs_dB, dt=dt, kp=kp, ki=ki,
                       noise_std=noise_std)
    z_surface = ctrl.z_surface

    # --- Scale target to fit within calibration range ---
    target_max = float(np.max(np.abs(target_abs_dB)))
    if target_max > 0 and cal_max > 0:
        target_abs_dB = np.asarray(target_abs_dB, dtype=float).copy()
        target_abs_dB *= 0.8 * cal_max / target_max

    # --- Synthetic plant: interpolate calibration curve ---
    z_off_mm_grid = np.linspace(0, calib_z_mm[-1], 500)
    abs_dB_grid = np.interp(z_off_mm_grid, calib_z_mm, calib_abs_dB)

    press_direction = np.array([1.0, 0.3, 0.1])
    press_direction = press_direction / np.linalg.norm(press_direction)

    n = len(target_abs_dB)
    time = np.arange(n) * dt
    z_cmd_arr = np.empty(n)
    z_ff_arr = np.empty(n)
    z_fb_arr = np.empty(n)
    meas_arr = np.empty(n)
    frozen_arr = np.empty(n, dtype=bool)
    rng = np.random.default_rng(42)

    dB_meas = np.zeros(3)  # start at zero (no contact)
    for i, g_d in enumerate(target_abs_dB):
        z_cmd = ctrl.step(dB_meas, g_d)
        z_off_mm = (z_cmd - z_surface) * 1000.0
        abs_meas = float(np.interp(z_off_mm, z_off_mm_grid, abs_dB_grid,
                                    left=0.0, right=abs_dB_grid[-1]))
        noise = rng.normal(0, noise_std * 0.5)
        abs_meas = max(0.0, abs_meas + noise)
        dB_meas = press_direction * abs_meas  # used in NEXT iteration (1-step delay)

        z_cmd_arr[i] = z_cmd
        z_ff_arr[i] = ctrl.z_ff
        z_fb_arr[i] = ctrl.z_fb
        meas_arr[i] = abs_meas
        frozen_arr[i] = ctrl.frozen

    return {
        "time": time,
        "z_surface": z_surface,
        "target": np.asarray(target_abs_dB),
        "meas": meas_arr,
        "z_cmd": z_cmd_arr,
        "z_ff": z_ff_arr,
        "z_fb": z_fb_arr,
        "frozen": frozen_arr,
    }


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
