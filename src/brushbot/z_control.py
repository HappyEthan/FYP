"""Z 轴闭环控制 Phase 0: 整体 ΔB 跟踪.

控制律: z_cmd = z_surface + z_ff(|ΔB_d|) + Kp·e + Ki·∫e
  e = |ΔB_d| − |ΔB_meas|
  前馈为主, 积分仅补残差.

见 docs/superpowers/specs/2026-07-28-z-control-phase0-design.md
"""
import numpy as np


class ZController:
    """整体 ΔB 标量跟踪控制器。"""

    def __init__(self, calib_z_mm: np.ndarray, calib_abs_dB: np.ndarray,
                 dt: float = 0.01, kp: float = 0.5, ki: float = 0.1,
                 z_surface: float = 0.20, dz_margin: float = 3e-3,
                 noise_std: float = 7.0):
        """
        Parameters
        ----------
        calib_z_mm : (N,) 压深 mm (从接触起点起算)
        calib_abs_dB : (N,) 对应 |ΔB| μT
        dt : 控制周期 (s)
        kp/ki : 比例/积分增益 (z 单位: m)
        z_surface : 纸面高度 (m)
        dz_margin : 积分限幅 ±m
        noise_std : 噪声标准差 (μT), 用于接触判定
        """
        assert len(calib_z_mm) == len(calib_abs_dB) > 1
        # Sort by abs_dB so np.interp works correctly even with non-monotonic input
        abs_dB = np.asarray(calib_abs_dB, dtype=float)
        z_offset_m = np.asarray(calib_z_mm, dtype=float) / 1000.0
        sort_idx = np.argsort(abs_dB)
        self._calib_dB = abs_dB[sort_idx]
        self._z_offset_m = z_offset_m[sort_idx]
        self._dt = dt
        self._kp = kp
        self._ki = ki
        self._z_surface = z_surface
        self._dz_margin = dz_margin
        self._noise_std = noise_std

        self._z_fb = 0.0
        self._frozen = False

    def _z_ff_lookup(self, g_d: float) -> float:
        """|ΔB| (μT) → z_offset (m). 超出标定范围则饱和."""
        return float(np.interp(g_d, self._calib_dB, self._z_offset_m,
                               left=0.0, right=self._z_offset_m[-1]))

    def step(self, dB_meas: np.ndarray, g_d: float) -> float:
        """计算 z_cmd (m, 世界坐标).

        Parameters
        ----------
        dB_meas : (3,) 当前 ΔB 测量值 (μT)
        g_d : 目标 |ΔB| (μT)

        Returns
        -------
        z_cmd : float  z 命令 (m)
        """
        abs_meas = float(np.linalg.norm(dB_meas))
        e = g_d - abs_meas
        self._last_g_d = g_d

        # NaN/Inf guard: freeze and return safe z_cmd
        if not (np.isfinite(abs_meas) and np.isfinite(g_d)):
            self._frozen = True
            return float(self._z_surface + self._z_ff_lookup(g_d) + self._z_fb)

        # Contact / lift detection
        if abs_meas < 3.0 * self._noise_std or g_d < 3.0 * self._noise_std:
            self._frozen = True
        else:
            self._frozen = False

        # Feedforward
        z_ff = self._z_ff_lookup(g_d)

        # Feedback (only integrate when not frozen)
        if not self._frozen:
            self._z_fb += self._ki * e * self._dt
            self._z_fb = np.clip(self._z_fb, -self._dz_margin, self._dz_margin)

        z_cmd = self._z_surface + z_ff + self._kp * e + self._z_fb
        return float(z_cmd)

    def reset(self):
        """重置积分器."""
        self._z_fb = 0.0
        self._frozen = False

    @property
    def z_ff(self) -> float:
        return self._z_ff_lookup(self._last_g_d) if hasattr(self, '_last_g_d') else 0.0

    @property
    def z_surface(self) -> float:
        """纸面高度 (m)."""
        return self._z_surface

    @property
    def z_fb(self) -> float:
        return self._z_fb

    @property
    def frozen(self) -> bool:
        return self._frozen
