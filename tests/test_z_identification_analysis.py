"""Known dynamic responses must be recovered, while weak excitation is flagged."""
import numpy as np
import pytest


def test_recovers_gain_and_effective_delay_from_a_finite_ramp():
    from brushbot.experiments.identification_analysis import fit_response
    t = np.arange(0, 6, .02)
    u = .5*np.clip((t-1)/.4, 0, 1)
    y = np.full(len(t), 80.)
    for i in range(1, len(t)):
        j = np.searchsorted(t, t[i-1]-.12+1e-10, side='right')-1
        drive = u[j] if j >= 0 else 0.
        y[i] = 80+(y[i-1]-80)*np.exp(-.02/.4)+30*drive*(1-np.exp(-.02/.4))
    result = fit_response(t, u, y)
    assert result['gain_uT_per_mm'] == pytest.approx(30., rel=.04)
    assert result['delay_s'] == pytest.approx(.12, abs=.04)
    assert result['tau_s'] == pytest.approx(.4, rel=.15)
    assert result['rmse_uT'] < .4


def test_flat_input_cannot_produce_a_gain_estimate():
    from brushbot.experiments.identification_analysis import fit_response
    with pytest.raises(ValueError, match='excitation'):
        fit_response(np.arange(100)*.02, np.ones(100), np.ones(100)*80)


def test_short_or_duplicate_timestamps_are_rejected():
    from brushbot.experiments.identification_analysis import fit_response
    with pytest.raises(ValueError, match='time'):
        fit_response(np.zeros(50), np.arange(50), np.arange(50))
