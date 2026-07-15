from brushbot.calligraphy.strokeseq import process
from brushbot.calligraphy.calibration import func_brush

def test_process_scales_xy_by_alpha():
    seq = [(0, 0.5, 0.5, 0.001)]     # 延续点
    pts = process(seq, func_brush, alpha=0.04, beta=0.5)
    assert len(pts) == 1
    x, y, z = pts[0]
    assert abs(x - 0.02) < 1e-9      # 0.5 * 0.04
    assert abs(y - 0.02) < 1e-9

def test_process_new_stroke_has_lift_in_point():
    seq = [(1, 0.5, 0.5, 0.001), (0, 0.6, 0.5, 0.001)]
    pts = process(seq, func_brush, alpha=0.04, beta=0.5)
    # 新笔: 入锋点(悬空 z=0.05) + 落点, 再加延续点; 末尾 5 个抬笔点
    zs = [p[2] for p in pts]
    assert max(zs) >= 0.05           # 有悬空入锋
    assert len(pts) >= 3
