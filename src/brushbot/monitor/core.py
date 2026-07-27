"""无 GUI 核心: 环形缓冲 + 基线 + 派生量. 禁止 import 任何 GUI 库."""
import numpy as np


class RingBuffer:
    """定长环形缓冲, O(1) 写入. 存 (t_s, Bx, By, Bz)."""

    def __init__(self, capacity: int):
        if capacity < 1:
            raise ValueError("capacity 必须 >= 1")
        self.capacity = int(capacity)
        self._t = np.zeros(self.capacity, dtype=float)
        self._B = np.zeros((self.capacity, 3), dtype=float)
        self._w = 0          # 下一个写入位置
        self.n_total = 0     # 累计写入总数

    def append(self, t_s: float, b) -> None:
        self._t[self._w] = t_s
        self._B[self._w] = b
        self._w = (self._w + 1) % self.capacity
        self.n_total += 1

    def latest(self, n: int):
        """返回最近 n 个样本 (t, B), 按时间升序; 不足则返回全部."""
        m = min(int(n), self.capacity, self.n_total)
        if m <= 0:
            return np.empty(0), np.empty((0, 3))
        idx = (self._w - m + np.arange(m)) % self.capacity
        return self._t[idx].copy(), self._B[idx].copy()


class Baseline:
    """基线 B0 与噪声 σ. ΔB = B - B0."""

    def __init__(self):
        self.b0 = np.zeros(3)
        self.sigma = np.zeros(3)
        self.ready = False

    def take(self, B: np.ndarray, update_b0: bool = True) -> None:
        """用一段静止样本 (N,3) 取基线, 同时算三轴标准差.

        update_b0=False 时只重新测 sigma(仍会置 ready=True), b0 保持不变——
        用于回放源: 记录自带的 b0 要原样保留(否则回放不再逐点复现原始 ΔB),
        但门控仍需要一份真实测得的 sigma。
        """
        B = np.asarray(B, dtype=float)
        if B.ndim != 2 or B.shape[1] != 3 or len(B) == 0:
            raise ValueError("take() 需要形如 (N,3) 的非空数组")
        if update_b0:
            self.b0 = B.mean(axis=0)
        self.sigma = B.std(axis=0)
        self.ready = True

    @property
    def sigma_norm(self) -> float:
        return float(np.linalg.norm(self.sigma))

    def apply(self, B: np.ndarray) -> np.ndarray:
        """原始 B → ΔB."""
        return np.asarray(B, dtype=float) - self.b0


class EMA:
    """指数移动平均滤波器, 三通道独立.

    y_t = α·x_t + (1-α)·y_{t-1}
    首次 update 直接取输入值, 无冷启动跳变。
    """

    def __init__(self, alpha: float = 0.3):
        if not 0.0 < alpha <= 1.0:
            raise ValueError("alpha 必须在 (0, 1] 之间, 当前: %s" % alpha)
        self.alpha = float(alpha)
        self._value = None          # shape (3,), 首次 update 时初始化

    def update(self, x: np.ndarray) -> np.ndarray:
        """输入 (3,) 或 (N,3) 数组, 返回同形状平滑值.

        批量输入 (N,3) 时: 对 N 个样本逐行迭代, 返回全部平滑后的序列。
        单样本 (3,) 时: 返回平滑后的 (3,) 向量。
        """
        x = np.asarray(x, dtype=float)
        if x.ndim == 1:
            x = x.reshape(1, 3)
        elif x.ndim != 2 or x.shape[1] != 3:
            raise ValueError("EMA.update() 需要 (3,) 或 (N,3) 数组, 当前形状: %s" % (x.shape,))
        out = np.empty_like(x)
        for i in range(len(x)):
            if self._value is None:
                self._value = x[i].copy()
            else:
                self._value = self.alpha * x[i] + (1.0 - self.alpha) * self._value
            out[i] = self._value
        if out.shape[0] == 1:
            return out[0]
        return out

    def reset(self) -> None:
        """清空状态, 下次 update 重新冷启动."""
        self._value = None


def derive(dB, gate: float) -> dict:
    """单个 ΔB 向量 → 幅值与方向. 幅值低于 gate 时方向置 None(噪声主导, 无意义)."""
    d = np.asarray(dB, dtype=float).reshape(3)
    mag_xy = float(np.hypot(d[0], d[1]))
    mag = float(np.linalg.norm(d))
    if mag < gate:
        return {"mag": mag, "mag_xy": mag_xy, "phi_deg": None, "theta_deg": None}
    return {
        "mag": mag,
        "mag_xy": mag_xy,
        "phi_deg": float(np.degrees(np.arctan2(d[1], d[0]))),
        "theta_deg": float(np.degrees(np.arctan2(mag_xy, d[2]))),
    }
