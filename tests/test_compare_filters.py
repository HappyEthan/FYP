"""compare_filters 指标函数单测."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from compare_filters import (build_configs, dynamic_rms, ema_freq_response,
                             f3db, fft_lowpass, group_delay_ms, phase_lag_deg,
                             sigmas, step_settle_ms)
from brushbot.filter import ButterworthFilter


def test_fft_lowpass_zero_phase():
    # 1 Hz 正弦 + 20 Hz 干扰, 截断 5 Hz: 干扰消失且 1 Hz 分量零相移
    t = np.arange(1000) / 100.0
    sig = np.sin(2 * np.pi * 1.0 * t)
    x = np.repeat((sig + 0.5 * np.sin(2 * np.pi * 20.0 * t))[:, None], 3, axis=1)
    y = fft_lowpass(x, fc=5.0)
    np.testing.assert_allclose(y[:, 0], sig, atol=0.02)


def test_sigmas_shape():
    rng = np.random.default_rng(0)
    s = sigmas(rng.normal(0.0, 2.0, size=(5000, 3)))
    assert len(s) == 4 and s[3] == pytest.approx(np.linalg.norm(s[:3]))


def test_ema_freq_response_dc_unity():
    assert abs(ema_freq_response(0.3, 0.0)) == pytest.approx(1.0)


def test_phase_lag_positive_for_lowpass():
    h = ButterworthFilter(8.0).freq_response(3.0)
    assert phase_lag_deg(h) > 0.0


def test_group_delay_positive():
    f = ButterworthFilter(8.0)
    assert 0.0 < group_delay_ms(f.freq_response) < 50.0


def test_f3db_butterworth_equals_fc():
    f = ButterworthFilter(8.0)
    assert f3db(f.freq_response) == pytest.approx(8.0, abs=0.1)


def test_step_settle_reasonable():
    ms = step_settle_ms(lambda: ButterworthFilter(8.0))
    assert 0.0 < ms <= 100.0


def test_dynamic_rms_lower_for_wider_band():
    # 更高截止 → 跟踪 3 Hz 参考更紧 → RMS 更小 (对纯信号无噪声情形)
    t = np.arange(1000) / 100.0
    x = np.repeat(np.sin(2 * np.pi * 2.0 * t)[:, None], 3, axis=1)
    r_wide = dynamic_rms(lambda: ButterworthFilter(12.0), x)
    r_narrow = dynamic_rms(lambda: ButterworthFilter(5.0), x)
    assert r_wide < r_narrow


def test_build_configs_complete():
    cfgs = build_configs()
    labels = [c["label"] for c in cfgs]
    assert any("EMA" in s for s in labels)
    assert sum("Butter" in s for s in labels) == 4
    assert sum("OneEuro" in s for s in labels) == 9
    for c in cfgs:
        assert callable(c["make"]) and callable(c["freq"]) and c["fc_ref"] > 0.0
