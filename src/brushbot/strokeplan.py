"""StrokePlan: 离线目标管线的输出契约, 开环/闭环两臂的共同前馈来源.

Stroke 单位纪律: xy/z_ff 为米 (SI), g_press 为 µT (带后缀量纲); s 为归一化弧长.
见 docs/superpowers/specs/2026-07-31-offline-target-pipeline-design.md
"""
import json
from dataclasses import dataclass, field

import numpy as np

FS = 100.0


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

    def to_waypoints(self, z_surface=0.20, lift=0.015):
        """开环路点 (CalliRewrite 式 baseline): 每笔 悬空进入 -> M 点 -> 抬笔.

        输出裸 (x,y,z) 列表 (世界系, 米), OpenLoopController 零改动消费."""
        wps = []
        for st in self.strokes:
            x0, y0 = (float(st.xy[0, 0]), float(st.xy[0, 1]))
            xe, ye = (float(st.xy[-1, 0]), float(st.xy[-1, 1]))
            wps.append((x0, y0, z_surface + lift))
            for (x, y), z in zip(st.xy, st.z_ff):
                wps.append((float(x), float(y), z_surface + float(z)))
            wps.append((xe, ye, z_surface + lift))
        return wps

    def to_gd_series(self, stroke_duration_s, fs=FS, gap_s=0.5):
        """闭环目标: 每笔匀速播放 g_press(s), 每笔后接 g_d=0 悬空段 (含最后一笔).

        悬空段 xy 从本笔终点线性过渡到下一笔起点 (末笔停在原地).
        返回 (g_d (T,), xy (T,2)), 可直接喂 sim_loop.run_loop."""
        if not self.strokes:
            raise ValueError("StrokePlan 无笔画, 无法生成 g_d 序列")
        n_st = int(round(stroke_duration_s * fs))
        n_gap = int(round(gap_s * fs))
        t_norm = np.linspace(0.0, 1.0, n_st)
        frac = np.linspace(0.0, 1.0, n_gap)[:, None]
        g_parts, xy_parts = [], []
        for k, st in enumerate(self.strokes):
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
