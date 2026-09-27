"""Identification must preserve entry geometry, motion limits and recorded evidence."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from brushbot.experiments.fake import FakeArm, FakeClock, FakeMagneticSource

ROOT = Path(__file__).resolve().parents[1]


def setup():
    data = json.loads((ROOT / 'runs/brush2/plans/ry15_rz0_suite_60_200_v1/settings.json').read_text())
    data.update(origin_x_mm=-370., baseline_window_s=.04, baseline_timeout_s=.2,
                baseline_min_samples=3, baseline_max_std_uT=[.1]*3,
                baseline_max_drift_uT_s=.1, vertical_rpy_rad=[0., np.deg2rad(15), 0.])
    return data


def compile_plan(depth=7.5, order='press-first', **changes):
    from brushbot.experiments.z_identification import compile_identification, default_profile
    profile = default_profile(depth, order=order)
    profile.update(changes)
    return compile_identification(profile, setup())


@pytest.mark.parametrize('depth', [5., 7.5, 10., 12.5, 15.])
def test_rotates_at_constant_xyz_before_sliding_and_loads_while_moving(depth):
    c = compile_plan(depth)
    poses, phase = c['pose_m_rad'], c['phase']
    rotation = poses[phase == 'rotate_contact']
    assert rotation[:, :3] == pytest.approx(np.tile([-.37, .5, .036], (len(rotation), 1)))
    assert rotation[-1, 4] == pytest.approx(np.deg2rad(15))
    assert np.all(np.diff(rotation[:, 4]) < 0)
    lower = poses[phase == 'lower_tilted']
    assert lower[:, 4] == pytest.approx(np.full(len(lower), np.deg2rad(30)))
    load = poses[phase == 'load_workpoint']
    assert np.all(np.diff(load[:, 0]) > 0)
    assert np.all(np.diff(load[:, 2]) <= 0)
    assert load[-1, 2] == pytest.approx((40-depth)/1000)
    holds = [s for s in c['segments'] if s['kind'] == 'plateau']
    assert len(holds) == 9
    first = holds[0]
    assert first['end_tick'] - first['start_tick'] == 200
    assert c['pose_m_rad'][first['start_tick']:first['end_tick'], 2] == pytest.approx(
        np.full(200, (40-depth)/1000))
    slide = poses[np.char.startswith(phase, 'id_')]
    assert slide[:, 4] == pytest.approx(np.full(len(slide), np.deg2rad(15)))
    assert np.isnan(c['g_ref_uT']).all()
    assert poses[0] == pytest.approx([-.37, .5, .13, 0, np.deg2rad(15), 0], abs=1e-6)
    assert poses[-1] == pytest.approx(poses[0])
    # A jump in rotation or Z at a segment boundary is caught independently.
    padded = np.vstack([poses[0], poses, poses[-1]])
    v = np.diff(padded, axis=0)/.02
    accel = np.diff(v, axis=0)/.02
    assert np.max(abs(v[:, 2])) <= .013 + 1e-8
    assert np.max(np.linalg.norm(accel[:, :3], axis=1)) <= .2 + 1e-8
    assert np.max(abs(np.rad2deg(v[:, 4]))) <= 10 + 1e-6
    assert np.max(abs(np.rad2deg(accel[:, 4]))) <= 20 + 1e-6


def test_reverse_order_changes_excitation_not_entry():
    c = compile_plan(order='lift-first')
    depths = [s['depth_mm'] for s in c['segments'] if s['kind'] == 'plateau']
    assert depths == pytest.approx([7.5, 7., 7.5, 8., 7.5, 7.25, 7.5, 7.75, 7.5])


@pytest.mark.parametrize('mode,duration', [('sweep-down', 30.), ('sweep-cycle', 15.)])
def test_sweep_geometry_duration_and_independent_airborne_return(mode, duration):
    from brushbot.experiments.z_identification import compile_identification, default_sweep_profile
    c = compile_identification(default_sweep_profile(mode), setup())
    poses, phase = c['pose_m_rad'], c['phase']
    down = poses[phase == 'sweep_down']
    assert len(down)*.02 == pytest.approx(duration)
    assert np.all(np.diff(down[:, 2]) < 0)
    assert down[-1, 2] == pytest.approx(.024)
    assert np.all(np.diff(down[:, 0]) > 0)
    assert down[:, 4] == pytest.approx(np.full(len(down), np.deg2rad(15)))
    contact = poses[phase == 'rotate_contact']
    assert contact[:, :3] == pytest.approx(np.tile([-.37, .5, .036], (len(contact), 1)))
    if mode == 'sweep-cycle':
        up = poses[phase == 'sweep_up']
        assert len(up)*.02 == pytest.approx(15.)
        assert np.all(np.diff(up[:, 2]) > 0)
        assert np.all(np.diff(up[:, 0]) > 0)
        assert up[-1, 2] == pytest.approx(.036)
    else:
        assert not np.any(phase == 'sweep_up')
    back = poses[phase == 'return_high']
    assert len(back)*.02 == pytest.approx(42.2)
    assert back[:, 2] == pytest.approx(np.full(len(back), .13))
    assert c['motion_metrics']['XY speed'] <= 20.+1e-6
    assert poses[-1] == pytest.approx(poses[0])


@pytest.mark.parametrize('mode', ['sweep-down', 'sweep-cycle'])
def test_sweep_cli_previews_without_devices_or_output(tmp_path, mode):
    run = subprocess.run([sys.executable, str(ROOT/'scripts/run_z_identification.py'),
                          '--mode', mode, '--dry-run', '--run-root', str(tmp_path/'runs')],
                         env=dict(os.environ, PYTHONPATH=str(ROOT/'src')),
                         text=True, capture_output=True)
    assert run.returncode == 0, run.stderr
    assert mode in run.stdout
    assert "Z36" in run.stdout
    assert "Z38" not in run.stdout
    assert not (tmp_path/'runs').exists()


@pytest.mark.parametrize('depth,delta,limits', [
    (5., 1., (4., 6.)), (10., 1., (9., 11.)), (12.5, .5, (12., 13.)),
])
def test_cli_custom_delta_reaches_compiled_and_snapshotted_local_excitation(
        tmp_path, monkeypatch, depth, delta, limits):
    from scripts import run_z_identification as runner
    original = runner.compile_identification
    compiled = []
    def capture(profile, settings):
        result = original(profile, settings)
        compiled.append(result)
        return result
    monkeypatch.setattr(runner, 'compile_identification', capture)
    assert runner.main(['--depth-mm', str(depth), '--delta-mm', str(delta),
                        '--dry-run', '--run-root', str(tmp_path/'runs')]) == 0
    c = compiled[0]
    holds = [s['depth_mm'] for s in c['segments'] if s['kind'] == 'plateau']
    assert (min(holds), max(holds)) == pytest.approx(limits)
    assert c['spec_snapshot']['identification']['delta_mm'] == delta
    assert not (tmp_path/'runs').exists()


@pytest.mark.parametrize('flags', [
    ['--mode', 'sweep-down', '--delta-mm', '1'],
    ['--depth-mm', '5', '--delta-mm', '2'],
])
def test_cli_rejects_delta_for_sweep_or_outside_depth_bounds(tmp_path, flags):
    run = subprocess.run([sys.executable, str(ROOT/'scripts/run_z_identification.py'),
                          *flags, '--dry-run', '--run-root', str(tmp_path/'runs')],
                         env=dict(os.environ, PYTHONPATH=str(ROOT/'src')),
                         text=True, capture_output=True)
    assert run.returncode != 0
    assert 'unrecognized arguments' not in run.stderr
    assert not (tmp_path/'runs').exists()


@pytest.mark.parametrize('mode', ['sweep-down', 'sweep-cycle'])
def test_sweep_recording_and_analysis_preserve_directions_without_fitting_delay(tmp_path, mode):
    from scripts.run_z_identification import build_stack
    from scripts.run_strokeplan_experiment import run_recorded
    from scripts.analyze_z_identification import analyze
    from brushbot.experiments.z_identification import default_sweep_profile
    clock = FakeClock()
    arm = FakeArm((-.37, .5, .13, *setup()['vertical_rpy_rad']), clock=clock)
    arm.realtime_state_reads = False
    source = FakeMagneticSource(arm, clock)
    engine, hub = build_stack(profile=default_sweep_profile(mode), setup=setup(),
                              root=tmp_path/'runs', arm=arm, source=source, clock=clock)
    result = run_recorded(engine, hub, clock=clock)
    assert result['state'] == 'END_WAIT', result
    folder = Path(result['run_dir'])
    original = (folder/'control.jsonl').read_bytes()
    output = analyze([folder], tmp_path/'analysis')
    summary = json.loads((output/'comparison.json').read_text())['runs'][0]
    assert summary['transitions'] == []
    assert summary['profile']['mode'] == mode
    assert summary['profile']['entry_contact_z_mm'] == 36.
    assert 'Z36到24mm' in folder.name
    directions = {r['direction'] for r in summary['sweep_curves']}
    assert directions == ({'press', 'lift'} if mode == 'sweep-cycle' else {'press'})
    assert max(r['depth_mean_mm'] for r in summary['sweep_curves']) > 15.5
    # Fast sweep peak 1.75 mm/s * 50 uT/mm; one-tick input delay plus
    # EMA(alpha=.3) lag gives about 5.84 uT maximum ramp error.
    assert all(abs(r['magnetic_mean_uT']-50*r['depth_mean_mm']) < 7
               for r in summary['sweep_curves'])
    assert (output/'sweep_curves.csv').exists()
    assert (folder/'control.jsonl').read_bytes() == original


@pytest.mark.parametrize('change, message', [
    ({'sweep_end_z_mm': 23.}, 'depth'),
    ({'sweep_s': 50.}, 'fit'),
    ({'sweep_s': .02}, 'Z speed'),
])
def test_sweep_rejects_out_of_bounds_or_infeasible_excitation(change, message):
    from brushbot.experiments.z_identification import compile_identification, default_sweep_profile
    p = default_sweep_profile()
    p.update(change)
    with pytest.raises(ValueError, match=message):
        compile_identification(p, setup())


@pytest.mark.parametrize('change, message', [
    ({'travel_mm': 420.}, 'fit'),
    ({'travel_mm': 500.}, 'workspace'),
    ({'delta_mm': 10.}, 'depth'),
    ({'rotate_s': .1}, 'angular'),
    ({'transition_s': .021}, '20 ms'),
    ({'hold_s': float('nan')}, 'finite'),
    ({'speed_mm_s': True}, 'finite'),
])
def test_rejects_infeasible_plan_without_clipping(change, message):
    with pytest.raises(ValueError, match=message):
        compile_plan(**change)


def build(tmp_path):
    from scripts.run_z_identification import build_stack
    from brushbot.experiments.z_identification import default_profile
    clock = FakeClock()
    arm = FakeArm((-.37, .5, .13, *setup()['vertical_rpy_rad']), clock=clock)
    arm.realtime_state_reads = False
    source = FakeMagneticSource(arm, clock)
    engine, hub = build_stack(profile=default_profile(7.5), setup=setup(),
                              root=tmp_path, arm=arm, source=source, clock=clock)
    return engine, hub, arm, source, clock


def test_full_run_records_null_targets_segments_and_one_airborne_baseline(tmp_path):
    from scripts.run_strokeplan_experiment import run_recorded
    engine, hub, arm, source, clock = build(tmp_path)
    result = run_recorded(engine, hub, clock=clock)
    assert result['state'] == 'END_WAIT', result
    d = Path(result['run_dir'])
    assert d.parent.name == 'raw'
    assert d.parent.parent.name == '05_Z动态辨识'
    manifest = json.loads((d/'manifest.json').read_text())
    assert manifest['status'] == 'completed'
    assert len(manifest['baselines']) == 1
    for fn in ['identification.json', 'settings.json', 'segments.json', 'timeline.npz']:
        assert hashlib.sha256((d/fn).read_bytes()).hexdigest() == manifest['sha256'][fn]
    rows = [json.loads(s) for s in (d/'control.jsonl').read_text().splitlines()]
    assert all(r['a_ref_uT'] is None and r['e_center_uT'] is None and r['depth_fb_m'] == 0 for r in rows)
    assert any(r['segment_kind'] == 'plateau' for r in rows)
    assert any(r['phase'] == 'rotate_contact' for r in rows)
    assert engine.feedback_calls == 0


@pytest.mark.parametrize('failure', ['disconnect', 'invalid', 'stale', 'interrupt'])
def test_sensor_or_operator_failure_preserves_run_and_lifts_without_rotating(tmp_path, failure):
    from scripts.run_strokeplan_experiment import run_recorded
    engine, hub, arm, source, clock = build(tmp_path)
    original = source.read_frames
    fired = False
    def frames():
        nonlocal fired
        if (engine.snapshot().get('telemetry') or {}).get('phase') == 'rotate_contact' and not fired:
            fired = True
            if failure == 'disconnect':
                raise OSError('unplugged')
            if failure == 'interrupt':
                raise KeyboardInterrupt
            if failure == 'stale':
                source.enabled = False
            if failure == 'invalid':
                data = original()
                data[0]['B_uT'][0] = float('nan')
                return data
        return original()
    source.read_frames = frames
    result = run_recorded(engine, hub, clock=clock)
    assert fired
    assert result['state'] == 'ABORTED', result
    assert arm.pose[2] == pytest.approx(.13)
    assert np.deg2rad(15) < arm.pose[4] < np.deg2rad(30)
    manifest = json.loads((Path(result['run_dir'])/'manifest.json').read_text())
    assert manifest['status'] == 'aborted'


def test_cli_preview_and_declined_run_have_no_run_directory(tmp_path):
    script = ROOT/'scripts/run_z_identification.py'
    env = dict(os.environ, PYTHONPATH=str(ROOT/'src'))
    cmd = [sys.executable, str(script), '--depth-mm', '7.5', '--run-root', str(tmp_path/'runs')]
    for flags, stdin in [(['--dry-run'], None), ([], 'NO\n')]:
        run = subprocess.run(cmd+flags, env=env, input=stdin, text=True, capture_output=True)
        assert run.returncode == 0, run.stderr
        assert not (tmp_path/'runs').exists()


@pytest.mark.parametrize('failure', ['baseline', 'initial_tcp'])
def test_startup_failure_does_not_move_or_rotate(tmp_path, failure):
    from scripts.run_strokeplan_experiment import run_recorded
    from brushbot.experiments.tcp_pose_capture import TCPPoseSampler
    engine, hub, arm, source, clock = build(tmp_path)
    sampler = None
    if failure == 'baseline':
        source.enabled = False
    else:
        def unavailable():
            raise OSError('TCP unavailable')
        sampler = TCPPoseSampler(unavailable, clock_ns=clock.now_ns)
    result = run_recorded(engine, hub, clock=clock, pose_sampler=sampler)
    assert result['state'] in {'FAULT', 'ABORTED'}
    assert not any(c['action'] in {'move_pose', 'push_pose', 'start_servo'} for c in arm.calls)
    manifest = json.loads((Path(result['run_dir'])/'manifest.json').read_text())
    assert manifest['status'] in {'fault', 'aborted'}


def test_analysis_exports_quality_flags_and_preserves_raw_input(tmp_path):
    from scripts.run_strokeplan_experiment import run_recorded
    from scripts.analyze_z_identification import analyze
    engine, hub, arm, source, clock = build(tmp_path/'raw_runs')
    result = run_recorded(engine, hub, clock=clock)
    folder = Path(result['run_dir'])
    original = (folder/'control.jsonl').read_bytes()
    output = analyze([folder], tmp_path/'analysis')
    summaries = json.loads((output/'comparison.json').read_text())['runs']
    assert summaries[0]['execution_environment'] == 'synthetic'
    assert len(summaries[0]['transitions']) == 8
    assert all(s['static_gain_uT_per_mm'] == pytest.approx(50., rel=.005)
               for s in summaries[0]['transitions'])
    assert (output/'transition_metrics.csv').exists()
    assert len(list(output.glob('*.png'))) == 1
    assert (folder/'control.jsonl').read_bytes() == original
    with pytest.raises(FileExistsError):
        analyze([folder], output)


@pytest.mark.parametrize('jitter', ['skipped', 'balanced_duplicate'])
def test_analysis_retains_completed_run_with_timing_quality_flags(tmp_path, jitter):
    from scripts.run_strokeplan_experiment import run_recorded
    from brushbot.experiments.identification_analysis import summarize_run
    engine, hub, arm, source, clock = build(tmp_path)
    original = source.read_frames
    fired = False
    def frames():
        nonlocal fired
        if ((engine.snapshot().get('telemetry') or {}).get('phase') == 'id_hold_00'
                and not fired and jitter == 'skipped'):
            clock.advance(.02)
            fired = True
        return original()
    source.read_frames = frames
    result = run_recorded(engine, hub, clock=clock)
    assert result['state'] == 'END_WAIT'
    folder = Path(result['run_dir'])
    if jitter == 'balanced_duplicate':
        path = folder/'control.jsonl'
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        hold = [r for r in rows if r['phase'] == 'id_hold_00']
        # Same number of rows, but one planned tick repeated and another omitted.
        hold[10]['t_s'] = hold[9]['t_s']
        path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
    summary, _ = summarize_run(folder)
    p = summary['plateaus'][0]
    assert p['missing_ticks'] == 1
    assert p['duplicate_ticks'] == (1 if jitter == 'balanced_duplicate' else 0)
    assert 'timing_irregularity' in summary['transitions'][0]['quality_flags']
    assert not summary['transitions'][0]['usable_for_initial_tuning']
    assert len(summary['transitions']) == 8
