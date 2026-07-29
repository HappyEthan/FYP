"""逐样本实时滤波器: 2 阶 Butterworth IIR 与 One Euro 自适应低通.

信号链: MLX90393 (100 Hz) → 滤波器 → ZController (外部组合, 控制环脚本接线).
接口与 monitor/core.py:EMA 一致: update((3,)|(N,3)) → 同形状, reset().
NaN 策略: 含非有限值的样本原样透传且不更新内部状态.

见 docs/superpowers/specs/2026-07-29-filter-design.md
"""
import numpy as np


def _validate(x):
    """输入校验: 返回 ((N,3) 数组, 是否单样本)."""
    x = np.asarray(x, dtype=float)
    single = x.ndim == 1
    if single:
        x = x.reshape(1, 3)
    elif x.ndim != 2 or x.shape[1] != 3:
        raise ValueError("update() 需要 (3,) 或 (N,3) 数组, 当前形状: %s" % (x.shape,))
    return x, single


class ButterworthFilter:
    """2 阶 Butterworth IIR 低通 biquad, 三通道独立, 逐样本实时滤波."""

    def __init__(self, fc: float, fs: float = 100.0):
        if not 0.0 < fc < fs / 2.0:
            raise ValueError("fc 必须在 (0, fs/2) 之间, 当前: %s" % fc)
        self.fc = float(fc)
        self.fs = float(fs)
        # 双线性变换 + 频率预畸变, Q = 1/sqrt(2)
        k = np.tan(np.pi * fc / fs)
        q = 1.0 / np.sqrt(2.0)
        norm = 1.0 / (1.0 + k / q + k * k)
        self._b = np.array([k * k, 2.0 * k * k, k * k]) * norm
        self._a = np.array([2.0 * (k * k - 1.0), 1.0 - k / q + k * k]) * norm
        self._x1 = self._x2 = self._y1 = self._y2 = None

    def update(self, x: np.ndarray) -> np.ndarray:
        x, single = _validate(x)
        out = np.empty_like(x)
        for i, xi in enumerate(x):
            if not np.all(np.isfinite(xi)):
                out[i] = xi          # NaN 透传, 状态不更新
                continue
            if self._x1 is None:     # 冷启动: 以首样本为稳态 (DC 增益=1 → 首输出=输入)
                self._x1 = self._x2 = xi.copy()
                self._y1 = self._y2 = xi.copy()
            yi = (self._b[0] * xi + self._b[1] * self._x1 + self._b[2] * self._x2
                  - self._a[0] * self._y1 - self._a[1] * self._y2)
            self._x2, self._x1 = self._x1, xi.copy()
            self._y2, self._y1 = self._y1, yi
            out[i] = yi
        return out[0] if single else out

    def reset(self) -> None:
        self._x1 = self._x2 = self._y1 = self._y2 = None

    def freq_response(self, f) -> np.ndarray:
        """数字频响 H(e^{j2πf/fs}). f: Hz 标量或数组, 返回复数同形状."""
        z1 = np.exp(-2j * np.pi * np.asarray(f, dtype=float) / self.fs)
        z2 = z1 * z1
        return ((self._b[0] + self._b[1] * z1 + self._b[2] * z2)
                / (1.0 + self._a[0] * z1 + self._a[1] * z2))
