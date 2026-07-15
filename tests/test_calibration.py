from brushbot.calligraphy.calibration import func_brush

def test_func_brush_monotonic_decreasing():
    # r 越大(笔画越宽) -> z 越小(压越深)
    zs = [func_brush(r) for r in [0.0002, 0.001, 0.002, 0.003]]
    assert zs[0] > zs[1] > zs[2] > zs[3]

def test_func_brush_overflow_protection():
    assert func_brush(0.01) == -0.006   # 超范围返回极限 z
