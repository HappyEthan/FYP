"""逐样本实时滤波器: EMA / 2 阶 Butterworth IIR / One Euro 自适应低通.

信号链: MLX90393 (100 Hz) → 滤波器 → ZController (外部组合, 控制环脚本接线).
统一接口: update((3,)|(N,3)) → 同形状, reset().
NaN 策略: 含非有限值的样本原样透传且不更新内部状态.
EMA 为控制环定稿滤波器 (α=CONTROL_EMA_ALPHA, Phase 1 在环评估),
2026-08-10 起归属本模块 (审计 R7); monitor.core 保留 re-export 兼容旧 import.

见 docs/superpowers/specs/2026-07-29-filter-design.md
"""
import numpy as np

from brushbot import config

# 控制环滤波器工作点 (Phase 1 层 1 定稿, 装配态复测前勿改): 唯一常量源
CONTROL_EMA_ALPHA = 0.3


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

    def __init__(self, fc: float, fs: float = config.FS):
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


class OneEuroFilter:
    """One Euro 自适应低通 (Casiez et al. 2012), 三通道独立.

    截止频率 fc = min_cutoff + beta·|dx_filt|:
    静止时截止低 (强降噪), 快速动作时截止升高 (低滞后).
    """

    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.0,
                 d_cutoff: float = 1.0, fs: float = config.FS):
        if min_cutoff <= 0.0 or d_cutoff <= 0.0:
            raise ValueError("min_cutoff/d_cutoff 必须 > 0, 当前: %s / %s"
                             % (min_cutoff, d_cutoff))
        self.min_cutoff = float(min_cutoff)
        self.beta = float(beta)
        self.d_cutoff = float(d_cutoff)
        self.fs = float(fs)
        self._x = None   # 上一滤波输出 (3,)
        self._dx = None  # 速度低通状态 (3,)

    @staticmethod
    def smoothing_alpha(cutoff, dt):
        """一阶低通系数 α = 1 / (1 + τ/dt), τ = 1/(2π·cutoff)."""
        tau = 1.0 / (2.0 * np.pi * np.asarray(cutoff, dtype=float))
        return 1.0 / (1.0 + tau / dt)

    def update(self, x: np.ndarray, dt: float | None = None) -> np.ndarray:
        x, single = _validate(x)
        dt = 1.0 / self.fs if dt is None else float(dt)
        out = np.empty_like(x)
        for i, xi in enumerate(x):
            if not np.all(np.isfinite(xi)):
                out[i] = xi          # NaN 透传, 状态不更新
                continue
            if self._x is None:      # 冷启动: 首输出=输入, 速度置零
                self._x = xi.copy()
                self._dx = np.zeros(3)
                out[i] = xi
                continue
            dx = (xi - self._x) / dt
            a_d = self.smoothing_alpha(self.d_cutoff, dt)
            self._dx = a_d * dx + (1.0 - a_d) * self._dx
            cutoff = self.min_cutoff + self.beta * np.abs(self._dx)
            a = self.smoothing_alpha(cutoff, dt)   # (3,) 逐通道自适应
            self._x = a * xi + (1.0 - a) * self._x
            out[i] = self._x
        return out[0] if single else out

    def reset(self) -> None:
        self._x = None
        self._dx = None


class EMA:
    """指数移动平均滤波器, 三通道独立. 控制环定稿滤波器 (α=0.3).

    y_t = α·x_t + (1-α)·y_{t-1}
    首次 update 直接取输入值, 无冷启动跳变。
    NaN 策略: 含非有限值的样本原样透传且不更新内部状态
    (EMA 有记忆, 不透传则一个坏样本永久毒化后续全部输出)。
    2026-08-10 前住在 monitor/core.py (归属倒置, 审计 R7); 现迁入本模块,
    monitor.core 保留 re-export。
    """

    def __init__(self, alpha: float = CONTROL_EMA_ALPHA):
        if not 0.0 < alpha <= 1.0:
            raise ValueError("alpha 必须在 (0, 1] 之间, 当前: %s" % alpha)
        self.alpha = float(alpha)
        self._value = None          # shape (3,), 首次 update 时初始化

    def update(self, x: np.ndarray) -> np.ndarray:
        """输入 (3,) 或 (N,3) 数组, 返回同形状平滑值."""
        x, single = _validate(x)
        out = np.empty_like(x)
        for i in range(len(x)):
            if not np.all(np.isfinite(x[i])):
                out[i] = x[i]          # NaN 透传, 状态不更新
                continue
            if self._value is None:
                self._value = x[i].copy()
            else:
                self._value = self.alpha * x[i] + (1.0 - self.alpha) * self._value
            out[i] = self._value
        return out[0] if single else out

    def reset(self) -> None:
        """清空状态, 下次 update 重新冷启动."""
        self._value = None


def make_control_filter() -> EMA:
    """控制环滤波器工厂: 生产接线的唯一入口, 杜绝 α 字面量分叉 (审计 R7)."""
    return EMA(CONTROL_EMA_ALPHA)
