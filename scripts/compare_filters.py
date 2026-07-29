#!/usr/bin/env python3
"""滤波器定量对比: EMA / Butterworth / One Euro → 选型报告.

用法 (单行):
    python scripts/compare_filters.py
    python scripts/compare_filters.py path/to/*.csv --out docs/filter-comparison.md

默认跑 delta_b_v0_20260724/ 全部数据. 装配态 E0 数据到位后, 用装配态 CSV
重跑同一命令即可重新选型 (spec §4).
"""
import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from brushbot.filter import ButterworthFilter, OneEuroFilter  # noqa: E402
from brushbot.monitor.core import EMA                          # noqa: E402

FS = 100.0        # 采样率 Hz
F_SIG = 3.0       # 目标信号带宽 Hz (提按动作)
REF_FC = 3.0      # 动态跟踪参考: FFT 零相位截断频率 Hz
SETTLE_TOL = 0.05


def load_csv(path):
    """ΔB CSV → dict(name, t, dB). 列: t_us,t_s,dBx_uT,dBy_uT,dBz_uT."""
    d = np.genfromtxt(path, delimiter=",", names=True)
    dB = np.column_stack([d["dBx_uT"], d["dBy_uT"], d["dBz_uT"]])
    return {"name": Path(path).stem, "t": d["t_s"], "dB": dB}


def fft_lowpass(x, fc, fs=FS):
    """FFT 域理想截断 (零相位, 离线参考用). x: (N,3)."""
    X = np.fft.rfft(x, axis=0)
    f = np.fft.rfftfreq(len(x), d=1.0 / fs)
    X[f > fc] = 0.0
    return np.fft.irfft(X, n=len(x), axis=0)


def sigmas(x):
    """(N,3) → (σx, σy, σz, |σ|), 关于各通道均值的标准差."""
    s = x.std(axis=0)
    return float(s[0]), float(s[1]), float(s[2]), float(np.linalg.norm(s))


def ema_freq_response(alpha, f, fs=FS):
    """一阶 EMA 频响 H = α / (1 - (1-α)·z⁻¹)."""
    z1 = np.exp(-2j * np.pi * np.asarray(f, dtype=float) / fs)
    return alpha / (1.0 - (1.0 - alpha) * z1)


def phase_lag_deg(h):
    """复频响 → 相位滞后 (度, 正值=滞后)."""
    return float(-np.degrees(np.angle(h)))


def group_delay_ms(freq_fn, f0=F_SIG, df=0.01):
    """群延迟 τ_g = -dφ/dω 数值微分 @ f0, 返回 ms."""
    phi = np.unwrap(np.angle(freq_fn(np.array([f0 - df, f0 + df]))))
    return float(-(phi[1] - phi[0]) / (2.0 * np.pi * 2.0 * df) * 1000.0)


def f3db(freq_fn):
    """数值求 -3dB 频率 (Hz)."""
    f = np.linspace(0.05, FS / 2.0 - 0.5, 4000)
    mag = np.abs(freq_fn(f))
    idx = np.nonzero(mag <= 1.0 / np.sqrt(2.0))[0]
    return float(f[idx[0]]) if len(idx) else float("nan")


def step_settle_ms(make_filter, tol=SETTLE_TOL, n=500):
    """阶跃响应进入并保持 ±tol 所需时间 (ms). 冷启动于 0, 样本 1 阶跃到 1."""
    x = np.zeros((n, 3))
    x[1:] = 1.0
    y = make_filter().update(x)[:, 0]
    bad = np.abs(y - 1.0) > tol
    last = int(np.max(np.nonzero(bad)[0])) if bad.any() else 0
    return last * 1000.0 / FS


def dynamic_rms(make_filter, dB):
    """滤波输出 vs FFT 零相位参考 (REF_FC) 的逐元素 RMS (µT)."""
    y = make_filter().update(dB)
    ref = fft_lowpass(dB, REF_FC)
    return float(np.sqrt(np.mean((y - ref) ** 2)))


def build_configs():
    """全部对比配置. fc_ref: σ 对照用的 FFT 截断频率."""
    cfgs = [{"label": "EMA a=0.3", "make": lambda: EMA(0.3),
             "freq": lambda f: ema_freq_response(0.3, f),
             "fc_ref": f3db(lambda f: ema_freq_response(0.3, f))}]
    for fc in (5.0, 8.0, 10.0, 12.0):
        cfgs.append({"label": "Butter fc=%g" % fc,
                     "make": (lambda fc=fc: ButterworthFilter(fc)),
                     "freq": ButterworthFilter(fc).freq_response,
                     "fc_ref": fc})
    for mc in (0.5, 1.0, 2.0):
        for beta in (0.01, 0.03, 0.1):
            a_slow = OneEuroFilter.smoothing_alpha(mc, 1.0 / FS)
            cfgs.append({"label": "OneEuro mc=%g b=%g" % (mc, beta),
                         "make": (lambda mc=mc, b=beta: OneEuroFilter(mc, b)),
                         "freq": (lambda f, a=a_slow: ema_freq_response(a, f)),
                         "fc_ref": mc})
    return cfgs
