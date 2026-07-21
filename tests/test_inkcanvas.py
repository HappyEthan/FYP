from brushbot.calligraphy.inkcanvas import InkCanvas


def _canvas(res=64):
    return InkCanvas(center_xy=(0.45, 0.0), size_m=0.10, resolution=res)


def test_world_center_maps_to_texture_middle():
    c = _canvas()
    assert c.world_to_px(0.45, 0.0) == (32, 32)


def test_world_corners_map_to_texture_corners():
    c = _canvas()
    # 纸的左上角(世界 -x, +y) -> 贴图 (0,0); y 轴需翻转
    assert c.world_to_px(0.45 - 0.05, 0.0 + 0.05) == (0, 0)
    assert c.world_to_px(0.45 + 0.05, 0.0 - 0.05) == (64, 64)


def test_stroke_inks_along_the_line_only():
    c = _canvas()
    c.stroke(0.45 - 0.03, 0.0, 0.45 + 0.03, 0.0, width_m=0.004)
    assert c.pixel(32, 32) < 128          # 线上应变黑
    assert c.pixel(5, 5) == 255           # 远处仍是白纸


def test_rgb_bytes_has_three_bytes_per_pixel():
    c = _canvas(res=16)
    assert len(c.rgb_bytes()) == 16 * 16 * 3


def test_clear_restores_blank_paper():
    c = _canvas()
    c.stroke(0.45 - 0.03, 0.0, 0.45 + 0.03, 0.0, width_m=0.004)
    assert c.pixel(32, 32) < 128
    c.clear()
    assert c.pixel(32, 32) == 255
