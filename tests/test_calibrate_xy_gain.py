import importlib.util
from pathlib import Path

import numpy as np
import pytest


_PATH = Path(__file__).parents[1] / "scripts" / "calibrate_xy_gain.py"
_SPEC = importlib.util.spec_from_file_location("calibrate_xy_gain", _PATH)
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)


def test_estimate_x_gain_corrects_axis_aligned_ellipse():
    theta = np.linspace(0.0, 4.0 * np.pi, 2000, endpoint=False)
    samples = np.column_stack([200.0 * np.cos(theta), 500.0 * np.sin(theta)])
    result = _MOD.estimate_x_gain(samples)
    assert result["Rx_uT"] == pytest.approx(200.0, rel=0.01)
    assert result["Ry_uT"] == pytest.approx(500.0, rel=0.01)
    assert result["x_gain"] == pytest.approx(2.5, rel=0.02)
    assert result["axis_ratio_after"] == pytest.approx(1.0)


def test_estimate_x_gain_rejects_incomplete_data():
    with pytest.raises(ValueError, match="不足"):
        _MOD.estimate_x_gain(np.zeros((10, 2)))


def test_parse_line():
    assert _MOD.parse_line(b"123,1.5,-2,3\n") == (123.0, 1.5, -2.0, 3.0)
    assert _MOD.parse_line(b"# t_us,Bx,By,Bz\n") is None
    assert _MOD.parse_line(b"broken\n") is None
