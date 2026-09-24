import math

import pytest

from brushbot.exhibition_monitor.pressure_smoothing import (
    PressureSmoother,
    smooth_pressure_series,
)


def test_pressure_smoother_removes_single_spike_and_changes_gradually():
    smoother = PressureSmoother(window=5, alpha=0.2)
    values = [smoother.update(value) for value in (180.0, 190.0, 500.0, 190.0, 180.0)]
    assert values[-1] < 260.0
    assert values[2] < 300.0
    assert all(math.isfinite(value) for value in values)


def test_pressure_smoother_ignores_invalid_samples_without_resetting_history():
    smoother = PressureSmoother(window=3, alpha=0.2)
    assert smoother.update(200.0) == pytest.approx(200.0)
    assert smoother.update(float("nan")) is None
    assert smoother.update(200.0) == pytest.approx(200.0)


def test_smooth_pressure_series_preserves_time_alignment_and_filters_invalid_values():
    result = smooth_pressure_series([0.0, 0.1, 0.2], [100.0, float("nan"), 200.0])
    assert len(result) == 2
    assert result[0][0] == 0.0
    assert result[-1][0] == 0.2
    assert all(math.isfinite(value) for _, value in result)
