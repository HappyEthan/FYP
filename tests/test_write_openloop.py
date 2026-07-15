import os
from brushbot.write_openloop import write
from brushbot.examples.strokes import SHI_SEQ

def test_write_shi_produces_trace_and_png(tmp_path):
    out = str(tmp_path / "shi.png")
    res = write(SHI_SEQ, gui=False, speed=0.05, out_png=out)
    assert res["n_down"] > 20            # 有足够落笔点
    assert os.path.exists(res["png"])
    # 落笔轨迹覆盖两笔 -> x,y 都有明显跨度 (十字)
    from brushbot import config
    down = [(x, y) for (x, y, z) in res["trace"] if z <= config.PAPER_Z + 0.002]
    xspan = max(p[0] for p in down) - min(p[0] for p in down)
    yspan = max(p[1] for p in down) - min(p[1] for p in down)
    assert xspan > 0.01 and yspan > 0.01
