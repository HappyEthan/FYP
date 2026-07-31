"""Z 轴闭环控制 Phase 0: 整体 ΔB 跟踪.

控制律: z_cmd = z_surface + z_ff(|ΔB_d|) + kp·S_cal·e + ki·S_cal·∫e
  e = |ΔB_d| − |ΔB_meas|
  前馈为主, 积分仅补残差.

见 docs/superpowers/specs/2026-07-28-z-control-phase0-design.md
"""
import numpy as np


class ZController:
    """整体 ΔB 标量跟踪控制器。"""

    def __init__(self, calib_z_mm: np.ndarray, calib_abs_dB: np.ndarray,
                 dt: float = 0.01, kp: float = 1.2077, ki: float = 0.134,
                 z_surface: float = 0.20, dz_margin: float = 3e-3,
                 noise_std: float = 7.0):
        """
        Parameters
        ----------
        calib_z_mm : (N,) 压深 mm (从接触起点起算)
        calib_abs_dB : (N,) 对应 |ΔB| μT
        dt : 控制周期 (s)
        kp/ki : 无量纲增益，每拍将误差的该比例折算为压深修正。
            默认值 = Phase 1 工作点（裸态仿真，`docs/z-phase1-sweep.md` /
            `docs/z-phase1-results.md`）：
            kp=1.2077 出自层 1 增益扫描，EMA a=0.3 臂 wp_P/wp_PI 工作点
            （kp 网格第 8 点，精确值 1.2077485712993403，四舍五入 1.2077）；
            ki=0.134 出自层 2 多笔画收敛场景推荐值（精确值 0.1341347897639862，
            8×synth_press 连写 + calib_scale=0.8，收敛笔数=3，裕度合规候选中最快）。
            ki 面向跨笔画自适应时间尺度（~3 笔收敛），不承诺单笔画内扰动抑制——
            层 2 单笔画场景实测 PI≈P（积分时间常数 τ_i 远超单笔画窗口）。
        z_surface : 纸面高度 (m)
        dz_margin : 积分限幅 ±m
        noise_std : 噪声标准差 (μT), 全带宽裸态口径，接滤波后必须显式传滤波后 σ；用于接触判定
        """
        assert len(calib_z_mm) == len(calib_abs_dB) > 1
        # Sort by abs_dB so np.interp works correctly even with non-monotonic input
        abs_dB = np.asarray(calib_abs_dB, dtype=float)
        z_offset_m = np.asarray(calib_z_mm, dtype=float) / 1000.0
        sort_idx = np.argsort(abs_dB)
        self._calib_dB = abs_dB[sort_idx]
        self._z_offset_m = z_offset_m[sort_idx]

        # Calculate calibration slope S_cal (m/µT)
        db_span = float(self._calib_dB[-1] - self._calib_dB[0])   # 已升序
        assert db_span > 0, "calib |dB| span must be > 0"
        z_span = float(self._z_offset_m.max() - self._z_offset_m.min())
        self._s_cal = z_span / db_span                            # m/µT

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
            self._z_fb += self._ki * self._s_cal * e * self._dt
            self._z_fb = np.clip(self._z_fb, -self._dz_margin, self._dz_margin)

        z_cmd = self._z_surface + z_ff + self._kp * self._s_cal * e + self._z_fb
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

    @property
    def s_cal(self) -> float:
        """标定斜率 (m/µT), 无量纲增益的换算因子."""
        return self._s_cal
