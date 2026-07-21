import os

import pytest

from brushbot import config
from brushbot.write_hanzi import write_hanzi

GRAPHICS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "makemeahanzi", "graphics.txt",
)

needs_data = pytest.mark.skipif(
    not os.path.exists(GRAPHICS),
    reason="需要 Make Me a Hanzi 数据集, 见 src/brushbot/README.md 下载说明",
)


@needs_data
def test_write_hanzi_draws_character_within_writing_box(tmp_path):
    out = str(tmp_path / "yong.png")
    res = write_hanzi("永", graphics_path=GRAPHICS, size=0.032, out_png=out)

    assert res["n_down"] > 50
    assert os.path.exists(res["png"])

    down = [(x, y) for (x, y, z) in res["trace"] if z <= config.PAPER_Z + 0.002]
    xs = [p[0] for p in down]
    ys = [p[1] for p in down]
    # 字应落在 size(3.2cm) 量级的范围内, 留跟踪误差余量
    assert 0.02 < max(xs) - min(xs) < 0.06
    assert 0.02 < max(ys) - min(ys) < 0.06


@needs_data
def test_write_hanzi_raises_for_absent_character(tmp_path):
    with pytest.raises(KeyError):
        write_hanzi("Q", graphics_path=GRAPHICS,
                    out_png=str(tmp_path / "x.png"))
