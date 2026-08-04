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
