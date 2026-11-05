"""Writing variation must preserve its source and keep the two layers separate."""
import copy
import json

import numpy as np
import pytest

from tests.test_target_feedforward import settings, table


def writing_inputs():
    calibration = table()
    calibration['depth_mm'] = [5., 6., 8.]
    setup = settings()
    q = np.linspace(0., 1., 401)
    g = 30. + 30. * np.sin(np.pi*q)**2
    xy = np.column_stack([-.2 + .02*(q*q*(3-2*q)), np.full(len(q), .5)])
    poses = np.column_stack([xy, .037-np.interp(g, [20, 40, 80], [5, 6, 8])/1000,
                             np.tile(setup['vertical_rpy_rad'], (len(q), 1))])
    poses = np.vstack([np.tile(poses[0], (4, 1)), poses, np.tile(poses[-1], (4, 1))])
    compiled = dict(t_s=np.arange(len(poses))*.02, pose_m_rad=poses,
                    phase=np.array(['wait']*4 + ['measure_00']*len(q) + ['hold']*4),
                    s=np.r_[[np.nan]*4, q, [np.nan]*4],
                    g_ref_uT=np.r_[[np.nan]*4, g, [np.nan]*4])
    entry = dict(mode='directional_character', angular_speed_deg_s=40.,
                 angular_accel_deg_s2=80.)
    return compiled, compiled['g_ref_uT'].copy(), calibration, setup, entry


def enabled_config(**profile_changes):
    from brushbot.experiments.writing_variation import default_config
    config = default_config()
    config['enabled'] = True
    config['profile'].update(profile_changes)
    return config


def test_fixed_layer_survives_new_repeat_and_source_is_untouched():
    from brushbot.experiments import writing_variation as v
    args = writing_inputs()
    before = {key: value.copy() for key, value in args[0].items()}
    config = enabled_config(bias_pct=20., repeat_level='medium')
    a = v.generate(*args, config, 11)
    b = v.generate(*args, config, 12)
    for key in ('fixed_xy_mm', 'fixed_g_uT'):
        assert a['strokes'][0][key] == b['strokes'][0][key]
    for key in ('repeat_xy_mm', 'repeat_g_uT'):
        assert a['strokes'][0][key] != b['strokes'][0][key]
    assert a == v.generate(*args, config, 11)
    for key in before:
        np.testing.assert_equal(args[0][key], before[key])


def test_replay_is_rng_free_and_changes_only_writing_xy_and_magnetic_depth(monkeypatch):
    from brushbot.experiments import writing_variation as v
    from brushbot.feedforward import lookup_depth_m
    args = writing_inputs()
    config = enabled_config(bias_pct=20., repeat_level='none')
    snapshot = v.generate(*args, config, 17)
    monkeypatch.setattr(np.random, 'default_rng', lambda *a: pytest.fail('replay drew random values'))
    poses, targets, limits = v.apply(*args, json.loads(json.dumps(snapshot)))
    base, nominal, calibration, _, _ = args
    mask = base['phase'] == 'measure_00'
    assert np.array_equal(poses[~mask], base['pose_m_rad'][~mask])
    assert np.array_equal(poses[:, 3:], base['pose_m_rad'][:, 3:])
    np.testing.assert_equal(targets[~mask], base['g_ref_uT'][~mask])
    delta = targets[mask] - base['g_ref_uT'][mask]
    assert targets[mask][200] == pytest.approx(72., abs=.03)
    expected_z = base['pose_m_rad'][mask, 2] - (
        lookup_depth_m(calibration, nominal[mask]+delta) - lookup_depth_m(calibration, nominal[mask]))
    assert np.allclose(poses[mask, 2], expected_z, atol=1e-12, rtol=0)
    assert limits['XY speed'] <= 30.


def test_two_layer_radial_bound_and_discrete_endpoint_velocity_are_preserved():
    from brushbot.experiments import writing_variation as v
    config = enabled_config(repeat_level='medium')
    snapshot = v.generate(*writing_inputs(), config, 31)
    row = snapshot['strokes'][0]
    xy = np.asarray(row['fixed_xy_mm']) + np.asarray(row['repeat_xy_mm'])
    assert 0 < np.linalg.norm(xy, axis=1).max() <= .15+1e-10
    for key in ('fixed_xy_mm', 'repeat_xy_mm', 'fixed_g_uT', 'repeat_g_uT'):
        assert not np.asarray(row[key])[[0, 1, -2, -1]].any()


@pytest.mark.parametrize('repeat_seed', [2, 41])
def test_subswitches_and_repeat_degree_do_not_redraw_fixed_style(repeat_seed):
    from brushbot.experiments import writing_variation as v
    args = writing_inputs()
    config = enabled_config(bias_pct=-10., repeat_level='medium')
    both = v.generate(*args, config, repeat_seed)['strokes'][0]
    xy_only = v.generate(*args, dict(config, magnetic_enabled=False), repeat_seed)['strokes'][0]
    magnetic_only = v.generate(*args, dict(config, xy_enabled=False), repeat_seed)['strokes'][0]
    assert both['fixed_xy_mm'] == xy_only['fixed_xy_mm']
    assert both['repeat_xy_mm'] == xy_only['repeat_xy_mm']
    assert both['fixed_g_uT'] == magnetic_only['fixed_g_uT']
    assert both['repeat_g_uT'] == magnetic_only['repeat_g_uT']
    config['profile']['repeat_level'] = 'none'
    none = v.generate(*args, config, 99)['strokes'][0]
    assert both['fixed_xy_mm'] == none['fixed_xy_mm']
    assert both['fixed_g_uT'] == none['fixed_g_uT']
    assert not np.asarray(none['repeat_xy_mm']).any()
    assert not np.asarray(none['repeat_g_uT']).any()


@pytest.mark.parametrize('changes', [dict(xy_limit_mm=-.1), dict(xy_limit_mm=.2),
                                    dict(bias_pct=21), dict(bias_pct=float('nan')),
                                    dict(seed=True), dict(repeat_level='large')])
def test_bad_profile_is_rejected(changes):
    from brushbot.experiments import writing_variation as v
    with pytest.raises(ValueError):
        v.validate_config(enabled_config(**changes))


def test_zero_xy_limit_disables_both_xy_layers():
    from brushbot.experiments import writing_variation as v
    snapshot = v.generate(*writing_inputs(), enabled_config(xy_limit_mm=0), 7)
    row = snapshot['strokes'][0]
    assert not np.asarray(row['fixed_xy_mm']).any()
    assert not np.asarray(row['repeat_xy_mm']).any()


def test_source_change_tampered_snapshot_and_forbidden_repeat_are_rejected():
    from brushbot.experiments import writing_variation as v
    args = writing_inputs()
    config = enabled_config(repeat_level='none')
    snapshot = v.generate(*args, config, 5)
    changed = copy.deepcopy(args)
    changed[0]['pose_m_rad'][200, 0] += .00001
    with pytest.raises(ValueError, match='标准|不匹配'):
        v.apply(*changed, snapshot)
    bad = copy.deepcopy(snapshot)
    bad['strokes'][0]['fixed_xy_mm'][100] = [.15, .15]
    with pytest.raises(ValueError, match='偏差|上限'):
        v.apply(*args, bad)
    bad = copy.deepcopy(snapshot)
    bad['strokes'][0]['repeat_g_uT'][100] = .01
    with pytest.raises(ValueError, match='本次|变化'):
        v.apply(*args, bad)


def test_incompatible_fixed_bias_is_rejected_without_silent_bias_reduction():
    from brushbot.experiments import writing_variation as v
    args = writing_inputs()
    args[0]['g_ref_uT'][4:-4] = 79.
    args[1][4:-4] = 79.
    with pytest.raises(ValueError, match='配置|固定|范围'):
        v.generate(*args, enabled_config(bias_pct=20.), 6)


@pytest.mark.parametrize('bias, level', [(20., 'none'), (0., 'medium')])
def test_waveform_changes_do_not_reject_or_reduce_magnetic_variation(bias, level):
    from brushbot.experiments import writing_variation as v
    args = writing_inputs()
    q = args[0]['s'][4:-4]
    base = 30. + .01*np.exp(-((q-.35)/.03)**2)
    args[0]['g_ref_uT'][4:-4] = base
    args[1][4:-4] = base
    args[0]['pose_m_rad'][4:-4, 2] = .037-np.interp(base, [20, 40, 80], [5, 6, 8])/1000
    config = dict(enabled_config(bias_pct=bias, repeat_level=level), xy_enabled=False)
    snapshot = v.generate(*args, config, 17)
    row = snapshot['strokes'][0]
    assert row['report']['correlation'] < .98
    assert row['repeat_magnetic_scale'] == 1.
    if level == 'medium':
        assert row['report']['peak_shift_fraction'] > .02
    _, targets, _ = v.apply(*args, json.loads(json.dumps(snapshot)))
    np.testing.assert_allclose(targets[4:-4], base+np.asarray(row['fixed_g_uT'])
                               +np.asarray(row['repeat_g_uT']), rtol=0, atol=1e-12)


def test_profile_library_survives_sessions_and_versions_edits(tmp_path):
    from brushbot.experiments import writing_variation as v
    path = tmp_path/'profiles.json'
    store = v.ProfileStore(path)
    initial = store.load()
    assert sorted(p['bias_pct'] for p in initial) == [-20., 0., 20.]
    profile = dict(initial[1], name='试验配置', bias_pct=10.)
    saved = store.save(profile)
    assert saved['revision'] == profile['revision']+1
    assert profile['revision'] == 1
    restored = v.ProfileStore(path).load()
    assert saved in restored
    assert store.save(saved) == saved
    path.write_text('{bad data')
    with pytest.raises(ValueError, match='配置'):
        store.load()


def test_coupled_motion_rejects_instead_of_changing_an_independent_fixed_style():
    from brushbot.experiments import writing_variation as v
    args = writing_inputs()
    # The independent maxima are 2.03732 and 27.45692 mm/s²; their
    # XYZ combination reaches 27.45941. Neither independent style may change.
    args[3]['max_accel_mm_s2'] = 27.458
    config = enabled_config(bias_pct=20., repeat_level='none')
    v.generate(*args, dict(config, magnetic_enabled=False), 2)
    v.generate(*args, dict(config, xy_enabled=False), 2)
    with pytest.raises(ValueError, match='组合未通过'):
        v.generate(*args, config, 2)
