"""StrokePlan: 离线目标管线的输出契约, 开环/闭环两臂的共同前馈来源.

Stroke 单位纪律: xy/z_ff 为米 (SI), g_press 为 µT (带后缀量纲); s 为归一化弧长.

z 帧纪律 (审计 R3 修正, 2026-08-10):
- `to_waypoints` 输出 **B1/物理世界帧** (z 向上为正): 压笔 = z_surface − z_ff
  (纸面下), 抬笔 = z_surface + lift (纸面上) —— 与 write_openloop/render 一致.
- `to_gd_series`/`to_open_z_series` 服务 **压深正向帧** (z_surface + 压深,
  ZController/sim_loop/TactileExecutor 的内部约定). 真机接入时两帧的符号定点
  见 docs/risk-register.md R20.
见 docs/superpowers/specs/2026-07-31-offline-target-pipeline-design.md
"""
import json
from dataclasses import dataclass, field

import numpy as np

from brushbot import config

FS = 100.0
FORMAT_VERSION = 2   # npz 格式版本: 2 = meta 含 stroke_durations_s (R15)


@dataclass
class Stroke:
    s: np.ndarray        # (M,) 均匀弧长网格 [0,1]
    xy: np.ndarray       # (M,2) 米
    g_press: np.ndarray  # (M,) µT, 零相位滤波后的目标手感
    z_ff: np.ndarray     # (M,) m, 前馈压深 offset (不含 z_surface)


@dataclass
class StrokePlan:
    strokes: list
    meta: dict = field(default_factory=dict)

    def save(self, path):
        arrays = {"n_strokes": np.array(len(self.strokes)),
                  "format_version": np.array(FORMAT_VERSION),
                  "meta_json": np.array(json.dumps(self.meta))}
        for i, st in enumerate(self.strokes):
            arrays["s%d_s" % i] = np.asarray(st.s, float)
            arrays["s%d_xy" % i] = np.asarray(st.xy, float)
            arrays["s%d_g" % i] = np.asarray(st.g_press, float)
            arrays["s%d_z" % i] = np.asarray(st.z_ff, float)
        np.savez(path, **arrays)

    @classmethod
    def load(cls, path):
        d = np.load(path, allow_pickle=False)
        n = int(d["n_strokes"])
        strokes = [Stroke(s=d["s%d_s" % i], xy=d["s%d_xy" % i],
                          g_press=d["s%d_g" % i], z_ff=d["s%d_z" % i])
                   for i in range(n)]
        return cls(strokes=strokes, meta=json.loads(str(d["meta_json"])))

    def _durations(self, stroke_duration_s):
        """逐笔回放时长 (s). None → meta 存储值 (示范速度≈执行速度, spec §8.5 硬要求);
        标量 → 全笔统一 (显式覆盖); 序列 → 逐笔指定."""
        n = len(self.strokes)
        if stroke_duration_s is None:
            durs = self.meta.get("stroke_durations_s")
            if durs is None or len(durs) != n:
                raise ValueError(
                    "未传 stroke_duration_s 且 meta['stroke_durations_s'] 缺失或长度"
                    "不符 (%s vs %d 笔) — 示范速度≈执行速度是录制协议硬要求, 旧格式"
                    "计划请显式传时长" % (durs, n))
            return [float(d) for d in durs]
        if np.ndim(stroke_duration_s) == 0:
            return [float(stroke_duration_s)] * n
        durs = [float(d) for d in stroke_duration_s]
        if len(durs) != n:
            raise ValueError("stroke_duration_s 序列长度 %d ≠ 笔数 %d" % (len(durs), n))
        return durs

    def to_waypoints(self, z_surface=config.PAPER_Z, lift=0.015,
                     origin=config.CHAR_ORIGIN):
        """开环路点 (CalliRewrite 式 baseline): 每笔 悬空进入 -> M 点 -> 抬笔.

        B1/物理世界帧: 压笔 z = z_surface − z_ff (纸面下), 抬笔 = z_surface + lift.
        origin 把示范 xy 的包围盒中心平移到该点 (默认 config.CHAR_ORIGIN 保证臂
        可达; None = 保留示范原始坐标). 输出裸 (x,y,z) 列表 (米),
        OpenLoopController 零改动消费."""
        ox = oy = 0.0
        if origin is not None and self.strokes:
            pts = np.vstack([st.xy for st in self.strokes])
            cx, cy = (pts.min(axis=0) + pts.max(axis=0)) / 2.0
            ox, oy = float(origin[0]) - float(cx), float(origin[1]) - float(cy)
        wps = []
        for st in self.strokes:
            x0, y0 = (float(st.xy[0, 0]) + ox, float(st.xy[0, 1]) + oy)
            xe, ye = (float(st.xy[-1, 0]) + ox, float(st.xy[-1, 1]) + oy)
            wps.append((x0, y0, z_surface + lift))
            for (x, y), z in zip(st.xy, st.z_ff):
                wps.append((float(x) + ox, float(y) + oy, z_surface - float(z)))
            wps.append((xe, ye, z_surface + lift))
        return wps

    def to_gd_series(self, stroke_duration_s=None, fs=FS, gap_s=0.5):
        """闭环目标: 逐笔按时长播放 g_press(s), 每笔后接 g_d=0 悬空段 (含最后一笔).

        stroke_duration_s=None 用 meta 存储的示范实际时长 (spec §8.5).
        悬空段 xy 从本笔终点线性过渡到下一笔起点 (末笔停在原地).
        返回 (g_d (T,), xy (T,2)), 可直接喂 sim_loop.run_loop."""
        if not self.strokes:
            raise ValueError("StrokePlan 无笔画, 无法生成 g_d 序列")
        durs = self._durations(stroke_duration_s)
        n_gap = int(round(gap_s * fs))
        frac = np.linspace(0.0, 1.0, n_gap)[:, None]
        g_parts, xy_parts = [], []
        for k, (st, dur) in enumerate(zip(self.strokes, durs)):
            t_norm = np.linspace(0.0, 1.0, int(round(dur * fs)))
            g_parts.append(np.interp(t_norm, st.s, st.g_press))
            xy_parts.append(np.column_stack(
                [np.interp(t_norm, st.s, st.xy[:, 0]),
                 np.interp(t_norm, st.s, st.xy[:, 1])]))
            last = np.asarray(st.xy[-1], float)
            nxt = (np.asarray(self.strokes[k + 1].xy[0], float)
                   if k + 1 < len(self.strokes) else last)
            g_parts.append(np.zeros(n_gap))
            xy_parts.append(last[None, :] * (1.0 - frac) + nxt[None, :] * frac)
        return np.concatenate(g_parts), np.vstack(xy_parts)

    def to_open_z_series(self, stroke_duration_s=None, fs=FS, gap_s=0.5,
                         z_surface=config.PAPER_Z):
        """开环臂 z 序列 (压深正向帧): 由**存储的 z_ff 字段**插值生成 —
        "两臂共享同一前馈" 由数据结构保证 (审计 R6).

        与 to_gd_series 同参数 → 同长度逐拍对齐; 笔内 z = z_surface + interp(z_ff),
        悬空段 = z_surface. 注意: 本序列按 lookup 表在示范支撑点上的取值插值,
        与闭环臂逐拍 lookup(g_d) 在线性标定表下严格等价 (等价锁测试见
        tests/test_strokeplan.py); 表转非线性时两者分叉, 需显式重新决策."""
        if not self.strokes:
            raise ValueError("StrokePlan 无笔画, 无法生成开环 z 序列")
        durs = self._durations(stroke_duration_s)
        n_gap = int(round(gap_s * fs))
        parts = []
        for st, dur in zip(self.strokes, durs):
            t_norm = np.linspace(0.0, 1.0, int(round(dur * fs)))
            parts.append(z_surface + np.interp(t_norm, st.s, st.z_ff))
            parts.append(np.full(n_gap, float(z_surface)))
        return np.concatenate(parts)
