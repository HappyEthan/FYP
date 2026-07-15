import os
from brushbot.calligraphy.render import render_trace

def test_render_square_creates_png(tmp_path):
    out = str(tmp_path / "sq.png")
    pts = [(0.0, 0.0, 0.0), (0.02, 0.0, 0.0), (0.02, 0.02, 0.0), (0.0, 0.02, 0.0)]
    w, h = render_trace(pts, surface_z=0.0, out_path=out)
    assert os.path.exists(out)
    assert w > 0 and h > 0

def test_render_raises_when_no_pen_down(tmp_path):
    out = str(tmp_path / "none.png")
    pts = [(0.0, 0.0, 0.05), (0.02, 0.0, 0.05)]   # 全悬空
    try:
        render_trace(pts, surface_z=0.0, out_path=out)
        assert False, "should raise"
    except ValueError:
        pass
