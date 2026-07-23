"""机臂末端带触角写字 → 合成触觉 ΔB（连接 brushbot 书写 与 触角磁学）.

思路(不做重物理耦合): 写字照旧(Elfin 开环), 每一拍从运动算触角形变:
  - 压深 penetration = PAPER_Z - z_tip (>0=压入纸)  → 法向弯(提按分量, 固定屈曲方位)
  - 横向位移 dxy                                     → 拖拽弯(方向=反运动方向)
  - 只在接触时(penetration>阈值)有信号; 抬笔→ΔB=0
形变经触角模型 sensor_B → 合成 ΔB. 这就是 B2 需要的"合成 g_meas 源",
现在由真实书写运动驱动。见 docs/tactile-fem-sim.md / deltaB-control.md.
"""
import numpy as np
from brushbot import config
from brushbot.tactile.separability import dB_bend, B0MAG

PRESS_AZIM = 40.0      # 触角轴向压的屈曲方位(触角固定属性, deg)
K_PRESS = 7.0          # 压弯增益: deg per mm 穿透
K_DRAG = 1200.0        # 拖弯增益: deg per (m 每拍横向位移)
PEN_EPS = 5e-4         # 0.5mm 穿透 = 接触阈值


def tactile_from_trace(trace):
    """逐拍笔尖位置 (F,3) → 合成 ΔB (F,3) 与 接触布尔 (F,)."""
    tr = np.asarray(trace, float)
    dxy = np.diff(tr[:, :2], axis=0, prepend=tr[:1, :2])      # 每拍横向位移
    dB = np.zeros((len(tr), 3))
    contact = np.zeros(len(tr), bool)
    for i in range(len(tr)):
        pen = config.PAPER_Z - tr[i, 2]                       # 穿透(m)
        if pen <= PEN_EPS:
            continue                                          # 抬笔: 无接触
        contact[i] = True
        b = dB_bend(K_PRESS * pen * 1000.0, PRESS_AZIM)       # 法向(提按)
        sp = np.hypot(dxy[i, 0], dxy[i, 1])
        if sp > 1e-6:
            az = np.degrees(np.arctan2(dxy[i, 1], dxy[i, 0])) + 180.0   # 反运动方向
            b = b + dB_bend(K_DRAG * sp, az)                  # 拖拽
        dB[i] = b
    return dB, contact


def write_with_tactile(character="永", **kw):
    """写一个字 → 返回 {trace, dB, contact, n_down}. 缺数据集则回退'十'笔序。"""
    try:
        from brushbot.write_hanzi import write_hanzi
        r = write_hanzi(character, gui=kw.get("gui", False),
                        out_png=kw.get("out_png", "/tmp/wt_ink.png"))
    except Exception:
        from brushbot.write_openloop import write as write_seq
        from brushbot.examples.strokes import SHI_SEQ
        r = write_seq(SHI_SEQ, gui=kw.get("gui", False),
                      out_png=kw.get("out_png", "/tmp/wt_ink.png"))
    dB, contact = tactile_from_trace(r["trace"])
    return {**r, "dB": dB, "contact": contact}


def demo(character="永", out_png="writing_tactile.png"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    r = write_with_tactile(character)
    tr = np.asarray(r["trace"]); dB = r["dB"]; ct = r["contact"]
    pc = 100.0 / B0MAG
    down = tr[tr[:, 2] <= config.PAPER_Z + 0.002]
    F = len(tr); xs = np.arange(F)

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 4.6))
    a1.plot(down[:, 0], down[:, 1], ".", ms=2, color="k")
    a1.set_aspect("equal"); a1.set_title(f"(1) ink of '{character}'")
    a1.set_xlabel("x (m)"); a1.set_ylabel("y (m)"); a1.grid(alpha=0.3)

    a2.plot(xs, dB[:, 0] * pc, label="dBx", lw=1.3)
    a2.plot(xs, dB[:, 1] * pc, label="dBy", lw=1.3)
    a2.plot(xs, dB[:, 2] * pc, label="dBz", lw=1.6, color="k")
    a2.plot(xs, np.hypot(dB[:, 0], dB[:, 1]) * pc, label="|dBxy|", lw=1.6, ls="--", color="crimson")
    # 落笔区间阴影
    inb = False
    for i in range(F):
        if ct[i] and not inb:
            s = i; inb = True
        elif not ct[i] and inb:
            a2.axvspan(s, i, color="orange", alpha=0.08); inb = False
    if inb:
        a2.axvspan(s, F, color="orange", alpha=0.08)
    a2.set_title("(2) synthetic antenna ΔB during writing (shade=pen-down)")
    a2.set_xlabel("tick"); a2.set_ylabel("ΔB (% of |B0|)"); a2.legend(fontsize=8, ncol=2); a2.grid(alpha=0.3)
    fig.suptitle(f"antenna on arm tip: writing '{character}' -> synthetic ΔB (feeds B2 g_meas)", fontsize=12)
    fig.tight_layout(); fig.savefig(out_png, dpi=110)
    return r


if __name__ == "__main__":
    import sys
    ch = sys.argv[1] if len(sys.argv) > 1 else "永"
    out = sys.argv[2] if len(sys.argv) > 2 else "writing_tactile.png"
    r = demo(ch, out)
    dB = r["dB"]; ct = r["contact"]
    print(f"ticks={len(dB)}  接触拍={ct.sum()}  "
          f"接触时 |ΔBxy| 均值={np.hypot(dB[ct,0],dB[ct,1]).mean()/B0MAG*100:.1f}%  "
          f"max={np.hypot(dB[ct,0],dB[ct,1]).max()/B0MAG*100:.1f}%")
