"""无 GUI 核心: 环形缓冲 + 基线 + 派生量. 禁止 import 任何 GUI 库."""
import numpy as np

from brushbot.filter import EMA   # noqa: F401  归属修正(R7): 正典在 filter.py, 此处 re-export 兼容旧 import


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
        # 归一化配置: 椭圆白化矩阵 W(2x2) + 统一半径 R, 或退回 running-max fallback
        self.norm_W = None
        self.norm_R = 0.0
        self.norm_ready = False

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

    # ---- 归一化 (各向同性白化 / 对称半径 / fallback) ----
    def set_norm_matrix(self, W, R: float) -> None:
        """应用椭圆白化矩阵 W(2×2) + 统一半径 R: 归一化用 (W·ΔBxy)/R.

        由 fit_whitening 产生; 把各向异性椭圆矫正回各向同性圆,
        使等幅物理形变在任意方向都得到相同归一化半径.
        """
        self.norm_W = np.asarray(W, dtype=float).reshape(2, 2)
        self.norm_R = float(R) if np.isfinite(R) and R > 0 else 1.0
        self.norm_ready = True

    def set_norm_radius(self, radius) -> None:
        """便捷: 仅对称半径(每轴或标量), 不作白化(当作各向同性).

        等价于 set_norm_matrix(W=diag(1/r), R=1): normalize_xy = ΔB/r.
        """
        r = np.asarray(radius, dtype=float).reshape(2)
        r = np.maximum(r, 1e-9)
        W = np.diag(1.0 / r)                 # 白化退化: 每轴缩放
        self.set_norm_matrix(W, 1.0)

    def clear_norm(self) -> None:
        """退回 running-max fallback 模式."""
        self.norm_W = None
        self.norm_R = 0.0
        self.norm_ready = False

    def normalize_xy(self, dB, fallback_radius: float = 0.0):
        """dB:(N,3) → (N,2) 归一化 dBx,dBy 供单位圆.

        norm_ready   → 白化归一化 (W·ΔBxy)/R, 各向同性(零点∈圆心)
        否则(fallback)→ 旧对称 running-max 除法 (fallback_radius; 0 → 全 0)。
        """
        dB = np.asarray(dB, dtype=float)
        xy = dB[:, :2]
        if self.norm_ready and self.norm_W is not None:
            W = self.norm_W
            whitened = xy @ W.T
            out = whitened / max(self.norm_R, 1e-9)
            return np.clip(out, -1.0, 1.0)
        if fallback_radius > 1e-9:
            return np.clip(xy / fallback_radius, -1.0, 1.0)
        return np.zeros_like(xy)


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


def normalize_symmetric(x, radius):
    """逐轴把 x 除以对称半径 R, 映射到 [-1,1] (零点→圆心 0).

    语义: R 为该轴正/负满压绝对值较大者, 保证双向形变都不超界;
    ΔB=0(无外力/基线) → 0 正好落在圆心. 与旧 min/max→[-1,1]
    的区别: 零点固定在圆心, 而非区间中点.
    接受标量或 (N,2)/(2,) 数组, 按轴逐元素. radius<=0 → 全 0.
    """
    x = np.asarray(x, dtype=float)
    r = np.asarray(radius, dtype=float)
    safe = np.where(r > 1e-12, r, 1.0)
    out = np.where(r > 1e-12, x / safe, 0.0)
    return np.clip(out, -1.0, 1.0)


def filter_bad_frames(samples, k: float = 10.0):
    """按中位数绝对离差(MAD)剔除离群坏帧(毛刺/饱和乱码).

    每个点若任一分量偏离中位 > k·MAD(该轴), 判为坏帧剔除.
    返回 (干净数据, 布尔掩码).
    """
    samples = np.asarray(samples, dtype=float)
    if samples.ndim != 2 or samples.shape[1] < 1 or len(samples) < 3:
        return samples, np.ones(len(samples), dtype=bool)
    med = np.median(samples, axis=0)
    spread = np.median(np.abs(samples - med), axis=0)
    spread = np.maximum(spread, 1e-9)
    mask = np.all(np.abs(samples - med) < k * spread, axis=1)
    return samples[mask], mask


def fit_whitening(samples):
    """从一圈等幅采样拟合各向同性化(白化)变换.

    转圈时物理形变等幅, 但磁场响应各向异性 → ΔBxy 扫出一个椭圆;
    这里用协方差分解求白化矩阵 W, 使 W·ΔBxy 还原为(近似)各向同性的圆.

    返回 (W, R):
      - W: 2×2 白化矩阵, 归一化用 normal_xy = (W·ΔBxy) / R
      - R: 白化后统一半径(p99 幅度), 保证大多数点落在单位圆内
    输入 samples:(N,2) ΔBxy, 应为已去坏帧的等幅转圈数据.
    """
    samples = np.asarray(samples, dtype=float).reshape(-1, 2)
    if len(samples) < 10:
        raise ValueError("fit_whitening 需要至少 10 个样本")
    C = np.cov(samples.T)
    L = np.linalg.cholesky(C)                 # C = L·Lᵀ
    W = np.linalg.inv(L)                      # W·C·Wᵀ = I → 白化
    whitened = samples @ W.T
    # 统一半径取白化后样本的实际最大值(max 已滤坏帧), 保证标定时到达的
    # 物理最大形变映射到点距=1(贴圆边界), 否则 R 取 p99 会压低位.
    R = float(np.max(np.hypot(whitened[:, 0], whitened[:, 1])))
    if not np.isfinite(R) or R < 1e-9:
        R = 1.0
    return W, R
