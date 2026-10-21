"""Four actual headings, compensated contact, distance-based half sweep."""
import json
import os
from pathlib import Path
import subprocess
import sys
from contextlib import contextmanager

import numpy as np
import pytest

from brushbot.experiments.fake import FakeArm, FakeClock, FakeMagneticSource

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def cli_session(monkeypatch):
    from scripts import run_four_direction_sweep as runner
    events = []
    session = object()
    @contextmanager
    def opened(*args, **kwargs):
        events.append('open')
        try:
            yield session
        finally:
            events.append('close')
    monkeypatch.setattr(runner, 'hardware_session', opened, raising=False)
    return events, session


def setup():
    s = json.loads((ROOT/'runs/brush2/plans/ry15_rz0_suite_60_200_v1/settings.json').read_text())
    s['workspace_min_mm'][1] = 200.
    s.update(baseline_window_s=.04, baseline_timeout_s=.2, baseline_min_samples=3,
             baseline_max_std_uT=[.1]*3, baseline_max_drift_uT_s=.1)
    return s


@pytest.mark.parametrize('direction,unit,rpy', [
    ('right', [1, 0], [0, 15, 0]), ('up', [0, 1], [-15, 0, 0]),
    ('left', [-1, 0], [0, -15, 0]), ('down', [0, -1], [15, 0, 0]),
])
@pytest.mark.parametrize('speed', [2., 10.])
def test_half_distance_and_compensation_in_every_heading(direction, unit, rpy, speed):
    from brushbot.experiments.four_direction_sweep import compile_sweep, default_profile
    p = dict(default_profile(), direction=direction, speed_mm_s=speed,
             travel_mm=80., start_z_mm=35., end_z_mm=26., entry_reverse_mm=5.)
    c = compile_sweep(p, setup())
    poses, phase = c['pose_m_rad'], c['phase']
    unit = np.asarray(unit)
    origin = np.array([-.2, .5])
    rot = poses[phase == 'rotate_contact']
    before = poses[np.flatnonzero(phase == 'rotate_contact')[0]-1]
    assert before[:2] == pytest.approx(origin+.005*unit)
    assert rot[-1, :2] == pytest.approx(origin)
    assert np.all(np.diff(np.vstack([before, rot])[:, :2], axis=0) @ unit <= 1e-12)
    assert rot[:, 2] == pytest.approx(np.full(len(rot), .036))
    assert np.rad2deg(rot[-1, 3:]) == pytest.approx(rpy, abs=1e-10)
    line = poses[np.isin(phase, ['straight_hold', 'sweep_down'])]
    distance = (line[:, :2]-origin) @ unit
    assert np.all(np.diff(distance) > 0)
    assert line[:, :2] == pytest.approx(origin+distance[:, None]*unit)
    assert line[-1, :2] == pytest.approx(origin+.08*unit)
    assert line[distance <= .04+1e-12, 2] == pytest.approx(
        np.full(np.count_nonzero(distance <= .04+1e-12), .035))
    assert np.all(line[distance > .04+1e-12, 2] < .035)
    assert line[-1, 2] == pytest.approx(.026)
    assert line[:, 3:] == pytest.approx(np.tile(np.deg2rad(rpy), (len(line), 1)))
    assert poses[-1] == pytest.approx(poses[0])
    assert np.isnan(c['g_ref_uT']).all()
    assert not c['spec_snapshot']['control']['enabled']
    idx = c['automatic_rebaseline_after_indices'][0]
    assert poses[idx, :3] == pytest.approx([-.2, .5, .13])
    assert np.rad2deg(poses[idx, 3:]) == pytest.approx(rpy, abs=1e-10)
    # Independently check the complete trajectory, including every seam.
    v = np.diff(np.vstack([poses[0], poses, poses[-1]]), axis=0)/.02
    a = np.diff(v, axis=0)/.02
    assert np.max(abs(v[:, 2])) <= .013+1e-8
    assert np.max(np.linalg.norm(a[:, :3], axis=1)) <= .2+1e-8
    assert np.max(np.linalg.norm(np.rad2deg(v[:, 3:]), axis=1)) <= 10.+1e-6


@pytest.mark.parametrize('changes', [
    {'direction': 'up', 'travel_mm': 101.},
    {'entry_reverse_mm': 500.}, {'entry_reverse_mm': -1.},
    {'start_z_mm': 25., 'end_z_mm': 36.}, {'end_z_mm': 15.},
    {'speed_mm_s': 0.}, {'speed_mm_s': float('nan')},
    {'travel_mm': 1., 'speed_mm_s': 30.}, {'rotate_s': .02},
])
def test_invalid_or_infeasible_settings_are_rejected(changes):
    from brushbot.experiments.four_direction_sweep import compile_sweep, default_profile
    with pytest.raises(ValueError):
        compile_sweep(dict(default_profile(), **changes), setup())


@pytest.mark.parametrize('wait_z', [35., 40.])
def test_rejects_non_airborne_wait_and_baseline_height(wait_z):
    from brushbot.experiments.four_direction_sweep import compile_sweep, default_profile
    settings = setup()
    settings['wait_z_mm'] = wait_z
    with pytest.raises(ValueError, match='wait.*contact'):
        compile_sweep(default_profile(), settings)


def build(tmp_path, direction='up'):
    from scripts.run_four_direction_sweep import build_stack
    from brushbot.experiments.four_direction_sweep import default_profile
    s = setup()
    clock = FakeClock()
    arm = FakeArm((-.2, .5, .13, *s['vertical_rpy_rad']), clock=clock)
    arm.realtime_state_reads = False
    source = FakeMagneticSource(arm, clock)
    engine, hub = build_stack(profile=dict(default_profile(), direction=direction),
                              setup=s, root=tmp_path, arm=arm, source=source, clock=clock,
                              batch_id='test-batch')
    return engine, hub, arm, source, clock


def test_execution_rebaselines_in_direction_and_records_no_feedback(tmp_path):
    from scripts.run_strokeplan_experiment import run_recorded
    engine, hub, arm, source, clock = build(tmp_path)
    result = run_recorded(engine, hub, clock=clock)
    assert result['state'] == 'END_WAIT', result
    folder = Path(result['run_dir'])
    manifest = json.loads((folder/'manifest.json').read_text())
    assert manifest['status'] == 'completed'
    assert len(manifest['baselines']) == 2
    rows = [json.loads(line) for line in (folder/'control.jsonl').read_text().splitlines()]
    assert all(r['a_ref_uT'] is None and r['depth_fb_m'] == 0 for r in rows)
    assert {r['direction'] for r in rows} == {'up'}
    phases = {r['segment_kind'] for r in rows}
    assert {'sweep', 'straight'} <= phases
    assert engine.feedback_calls == 0
    assert json.loads((folder/'identification.json').read_text())['entry_reverse_mm'] == 5.
    assert json.loads((folder/'resolved.json').read_text())['batch_id'] == 'test-batch'
    assert arm.pose == pytest.approx((-.2, .5, .13, *setup()['vertical_rpy_rad']))


@pytest.mark.parametrize('failure', ['disconnect', 'invalid', 'interrupt'])
def test_failure_during_contact_lifts_without_rotating(tmp_path, failure):
    from scripts.run_strokeplan_experiment import run_recorded
    engine, hub, arm, source, clock = build(tmp_path, 'down')
    original = source.read_frames
    at_failure = None
    def frames():
        nonlocal at_failure
        if engine._telemetry and engine._telemetry['phase'] == 'rotate_contact' and at_failure is None:
            at_failure = arm.pose
            if failure == 'disconnect':
                raise OSError('unplugged')
            if failure == 'interrupt':
                raise KeyboardInterrupt
            data = original()
            data[0]['B_uT'][0] = float('nan')
            return data
        return original()
    source.read_frames = frames
    result = run_recorded(engine, hub, clock=clock)
    assert at_failure is not None
    assert result['state'] == 'ABORTED', result
    assert arm.pose[2] == pytest.approx(.13)
    assert arm.pose[3:] == pytest.approx(at_failure[3:])


def test_cli_previews_all_directions_and_adjustments_without_hardware_or_runs(tmp_path):
    run = subprocess.run([sys.executable, str(ROOT/'scripts/run_four_direction_sweep.py'),
                          '--dry-run', '--kind', 'sweep', '--speed-mm-s', '5', '--travel-mm', '60',
                          '--start-z-mm', '34', '--end-z-mm', '27',
                          '--run-root', str(tmp_path/'runs')],
                         env=dict(os.environ, PYTHONPATH=str(ROOT/'src')),
                         text=True, capture_output=True)
    assert run.returncode == 0, run.stderr
    for word in ['right', 'up', 'left', 'down', '34', '27']:
        assert word in run.stdout
    assert not (tmp_path/'runs').exists()


def test_batch_stops_after_failed_direction_and_prechecks_all(monkeypatch, tmp_path, cli_session):
    from scripts import run_four_direction_sweep as runner
    calls = []
    def execute(profile, *args, **kwargs):
        calls.append(profile['direction'])
        return 2
    monkeypatch.setattr(runner, 'execute_hardware', execute)
    monkeypatch.setattr('builtins.input', lambda _: '')
    assert runner.main(['--run-root', str(tmp_path)]) == 2
    assert calls == ['right']
    calls.clear()
    with pytest.raises(ValueError, match='workspace'):
        runner.main(['--travel-mm', '501'])
    assert calls == []


def test_default_batch_is_direction_speed_condition_cross_product(monkeypatch, tmp_path, cli_session):
    from scripts import run_four_direction_sweep as runner
    from brushbot.experiments.four_direction_sweep import compile_sweep
    trials = []
    def execute(p, s, *args, **kwargs):
        c = compile_sweep(p, s)
        line = c['pose_m_rad'][np.isin(c['phase'], ['straight_hold', 'sweep_down'])]
        assert np.linalg.norm(line[-1, :2] - np.array([
            s['origin_x_mm'], s['origin_y_mm']])/1000) == pytest.approx(.15)
        assert c['pose_m_rad'][:, 1].min() >= .3
        assert c['pose_m_rad'][:, 1].max() <= .7
        if p['mode'] == 'four-direction-hold':
            assert line[:, 2] == pytest.approx(np.full(len(line), .036))
            assert 'sweep_down' not in c['phase']
        else:
            assert line[-1, 2] == pytest.approx(.025)
            assert line[0, 2] == pytest.approx(.036)
        trials.append((p['direction'], p['speed_mm_s'], p['mode']))
        return 0
    monkeypatch.setattr(runner, 'execute_hardware', execute)
    monkeypatch.setattr('builtins.input', lambda _: '')
    assert runner.main(['--kind', 'both', '--run-root', str(tmp_path)]) == 0
    assert len(trials) == len(set(trials)) == 24
    assert set(trials) == {(d, v, m) for d in ('right', 'up', 'left', 'down')
                          for v in (10., 15., 7.)
                          for m in ('four-direction-hold', 'four-direction-half-sweep')}


def test_positioning_lifts_before_xy_and_orientation_changes():
    from scripts import run_four_direction_sweep as runner
    arm = FakeArm((-.37, .5, .029, 0., -.26, 0.))
    s = setup()
    s.update(origin_x_mm=-150., origin_y_mm=350.)
    record = runner.position_at_wait(arm, s, sleep=lambda _: None)
    moves = np.array([c['pose'] for c in arm.calls if c['action'] == 'push_pose'])
    assert len(moves)
    assert moves[moves[:, 2] < .13-1e-9, :2] == pytest.approx(
        np.tile([-.37, .5], (np.count_nonzero(moves[:, 2] < .13-1e-9), 1)))
    turning = np.abs(moves[:, 4]+.26) > 1e-9
    assert moves[turning, :3] == pytest.approx(np.tile([-.15, .35, .13], (turning.sum(), 1)))
    assert arm.pose == pytest.approx((-.15, .35, .13, *s['vertical_rpy_rad']))
    assert record['status'] == 'completed'


@pytest.mark.parametrize('pose,fsm', [
    ((-.37, .5, .13, 0., 0., 0.), 0),
    ((-.5, .5, .13, 0., 0., 0.), 33),
    ((float('nan'), .5, .13, 0., 0., 0.), 33),
])
def test_invalid_position_or_state_does_not_move(pose, fsm):
    from scripts import run_four_direction_sweep as runner
    arm = FakeArm(pose, fsm=fsm)
    with pytest.raises((RuntimeError, ValueError)):
        runner.position_at_wait(arm, setup(), sleep=lambda _: None)
    assert not any(c['action'] in {'move_pose', 'push_pose'} for c in arm.calls)


def test_positioning_timeout_stops_arm_without_next_waypoint():
    from scripts import run_four_direction_sweep as runner
    class StuckArm(FakeArm):
        def push_pose(self, pose):
            previous = self.pose
            super().push_pose(pose)
            self.pose = previous
    arm = StuckArm((-.37, .5, .029, 0., 0., 0.))
    clock = FakeClock()
    with pytest.raises(TimeoutError):
        runner.position_at_wait(arm, setup(), sleep=clock.advance,
                                monotonic=lambda: clock.now_ns()/1e9, timeout_s=.1)
    pushed = [c['pose'] for c in arm.calls if c['action'] == 'push_pose']
    assert pushed
    assert all(p[:2] == (-.37, .5) for p in pushed)
    assert arm.calls[-1]['action'] == 'stop'


def test_twelve_pause_every_four_and_finish_at_endpoints(monkeypatch, tmp_path, cli_session):
    from scripts import run_four_direction_sweep as runner
    from brushbot.experiments.four_direction_sweep import compile_sweep
    trials, prompts = [], []
    def execute(p, s, *args, **kwargs):
        assert kwargs['session'] is cli_session[1]
        c = compile_sweep(p, s)
        assert 'return_high' not in c['phase']
        assert 'restore_wait_orientation' not in c['phase']
        endpoint = c['pose_m_rad'][c['phase'] == 'straight_hold'][-1]
        assert c['pose_m_rad'][-1, :2] == pytest.approx(endpoint[:2])
        assert c['pose_m_rad'][-1, 2] == pytest.approx(.07)
        assert c['pose_m_rad'][:, 2].max() <= .07+1e-12
        assert endpoint[2] == pytest.approx(.036)
        assert p['mode'] == 'four-direction-hold'
        trials.append((p['direction'], p['speed_mm_s']))
        return 0
    def prompt(message):
        prompts.append(len(trials))
        assert 'Enter' in message
        assert ('请沾水' in message) == (len(trials) in (4, 8))
        return ''
    monkeypatch.setattr(runner, 'execute_hardware', execute)
    monkeypatch.setattr('builtins.input', prompt)
    assert runner.main(['--run-root', str(tmp_path)]) == 0
    assert len(trials) == len(set(trials)) == 12
    assert prompts == list(range(12))
    assert cli_session[0] == ['open', 'close']


def test_fast_entry_matches_character_policy_and_keeps_slow_near_paper():
    from scripts import run_four_direction_sweep as runner
    from brushbot.experiments.four_direction_sweep import compile_sweep
    s = json.loads(runner.SETTINGS.read_text())
    s['workspace_min_mm'][1] = 100.
    s.update(origin_x_mm=-150., origin_y_mm=400.)
    c = compile_sweep(runner.PROFILE, s)
    poses, phases = c['pose_m_rad'], c['phase']
    v = np.diff(poses[:, 2])*1000/.02
    fast = v[phases[1:] == 'lower_fast']
    slow = v[phases[1:] == 'lower_slow']
    assert 40 < max(abs(fast)) <= 60.00001
    assert max(abs(slow)) <= 15.00001
    assert poses[phases == 'lower_fast'][-1, 2] == pytest.approx(.05)
    assert poses[phases == 'lower_slow'][-1, 2] == pytest.approx(.036)
    assert np.count_nonzero(phases == 'rotate_air')*.02 == pytest.approx(1.5)
    assert np.count_nonzero(phases == 'rotate_contact')*.02 == pytest.approx(3.)


def test_constant_height_no_return_run_keeps_direction_baseline(tmp_path):
    from scripts.run_four_direction_sweep import build_stack
    from scripts.run_strokeplan_experiment import run_recorded
    from brushbot.experiments.four_direction_sweep import default_profile
    s = setup()
    clock = FakeClock()
    arm = FakeArm((-.2, .5, .13, *s['vertical_rpy_rad']), clock=clock)
    arm.realtime_state_reads = False
    source = FakeMagneticSource(arm, clock)
    p = dict(default_profile(), mode='four-direction-hold', start_z_mm=34.,
             end_z_mm=34., return_to_origin=False)
    engine, hub = build_stack(profile=p, setup=s, root=tmp_path, arm=arm, source=source, clock=clock)
    result = run_recorded(engine, hub, clock=clock)
    assert result['state'] == 'END_WAIT'
    folder = Path(result['run_dir'])
    manifest = json.loads((folder/'manifest.json').read_text())
    assert len(manifest['baselines']) == 2
    rows = [json.loads(line) for line in (folder/'control.jsonl').read_text().splitlines()]
    line = [r for r in rows if r['phase'] == 'straight_hold']
    assert line
    assert all(r['prescribed_depth_m'] == pytest.approx(.006) for r in line)
    assert arm.pose[:3] == pytest.approx((-.12, .5, .13))


@pytest.mark.parametrize('error_mm', [.01, .6])
def test_positioning_uses_pose_tolerance_for_measured_workspace_boundary(error_mm):
    from scripts import run_four_direction_sweep as runner
    class MeasurementErrorArm(FakeArm):
        def read_state(self):
            state = super().read_state()
            if self.pose[2] >= .13:
                state['tcp_pose'] = (*self.pose[:2], self.pose[2]+error_mm/1000, *self.pose[3:])
            return state
    arm = MeasurementErrorArm((-.37, .5, .029, 0., 0., 0.))
    if error_mm > .5:
        with pytest.raises(RuntimeError, match='workspace'):
            runner.position_at_wait(arm, setup(), sleep=lambda _: None)
        assert arm.calls[-1]['action'] == 'stop'
    else:
        runner.position_at_wait(arm, setup(), sleep=lambda _: None)
        # A subsequent trial must also accept an in-tolerance initial reading.
        runner.position_at_wait(arm, setup(), sleep=lambda _: None)
        assert all(c['pose'][2] <= .13+1e-12 for c in arm.calls if c['action'] == 'push_pose')


def test_positioning_attempt_is_saved_before_moving_and_on_failure(tmp_path):
    from scripts import run_four_direction_sweep as runner
    path = tmp_path/'positioning.json'
    class FailingArm(FakeArm):
        def push_pose(self, pose):
            saved = json.loads(path.read_text())
            assert saved['status'] == 'running'
            assert saved['route_m_rad']
            raise RuntimeError('transport failed')
    arm = FailingArm((-.37, .5, .029, 0., 0., 0.))
    with pytest.raises(RuntimeError, match='transport failed'):
        runner.position_at_wait(arm, setup(), record_path=path)
    saved = json.loads(path.read_text())
    assert saved['status'] == 'failed'
    assert saved['error'] == 'transport failed'
    assert saved['initial_pose_m_rad'][:3] == pytest.approx([-.37, .5, .029])
    assert arm.calls[-1]['action'] == 'stop'


def test_positioning_obeys_character_linear_and_angular_limits():
    from scripts import run_four_direction_sweep as runner
    s = json.loads(runner.SETTINGS.read_text())
    s['workspace_min_mm'][1], s['workspace_max_mm'][1] = 300., 700.
    s.update(origin_x_mm=-150., origin_y_mm=450.)
    clock = FakeClock()
    initial = (-.37, .5, .034, 0., -.26, 0.)
    arm = FakeArm(initial)
    runner.position_at_wait(arm, s, sleep=clock.advance, monotonic=lambda: clock.now_ns()/1e9)
    assert not any(c['action'] == 'move_pose' for c in arm.calls)
    poses = np.array([initial]+[c['pose'] for c in arm.calls if c['action'] == 'push_pose'])
    assert len(poses) > 2
    velocity = np.diff(np.vstack([poses[0], poses, poses[-1]]), axis=0)/.02
    acceleration = np.diff(velocity, axis=0)/.02
    assert np.linalg.norm(velocity[:, :2], axis=1).max()*1000 <= 80.00001
    assert abs(velocity[:, 2]).max()*1000 <= 60.00001
    assert np.linalg.norm(acceleration[:, :3], axis=1).max()*1000 <= 100.00001
    assert np.linalg.norm(np.rad2deg(velocity[:, 3:]), axis=1).max() <= 20.00001
    assert np.linalg.norm(np.rad2deg(acceleration[:, 3:]), axis=1).max() <= 40.00001


@pytest.mark.parametrize('completed', [0, 1, 4, 8])
def test_cancel_before_trial_never_starts_next_trial(monkeypatch, tmp_path, cli_session, completed):
    from scripts import run_four_direction_sweep as runner
    calls = []
    monkeypatch.setattr(runner, 'execute_hardware', lambda p, *a, **kw: calls.append(p) or 0)
    answers = iter([''] * completed + ['stop'])
    monkeypatch.setattr('builtins.input', lambda _: next(answers))
    assert runner.main(['--run-root', str(tmp_path)]) == 0
    assert len(calls) == completed
    assert cli_session[0] == (['open', 'close'] if completed else [])


def test_positioning_late_tick_stops_before_sending_command():
    from scripts import run_four_direction_sweep as runner
    clock = FakeClock()
    arm = FakeArm((-.37, .5, .13, 0., 0., 0.))
    with pytest.raises(RuntimeError, match='tick lateness'):
        runner.position_at_wait(arm, setup(), sleep=lambda _: clock.advance(1.),
                                monotonic=lambda: clock.now_ns()/1e9)
    assert arm.calls[-1]['action'] == 'stop'
    assert not any(c['action'] == 'push_pose' for c in arm.calls)


def test_positioning_does_not_burst_commands_after_a_short_transport_stall():
    from scripts import run_four_direction_sweep as runner
    clock = FakeClock()
    starts = []

    class SlowFirstPush(FakeArm):
        def push_pose(self, pose):
            starts.append(clock.now_ns())
            super().push_pose(pose)
            if len(starts) == 1:
                clock.advance(.06)

    arm = SlowFirstPush((-.2, .45, .13, *setup()['vertical_rpy_rad']))
    s = setup()
    s['max_tick_lateness_s'] = .1
    record = runner.position_at_wait(arm, s, sleep=clock.advance,
                                    monotonic=lambda: clock.now_ns()/1e9)
    assert record['status'] == 'completed'
    assert np.min(np.diff(starts)) >= 20_000_000


def test_positioning_timeout_record_identifies_the_late_tick(tmp_path):
    from scripts import run_four_direction_sweep as runner
    clock = FakeClock()
    arm = FakeArm((-.2, .45, .13, *setup()['vertical_rpy_rad']))
    s = setup()
    s['max_tick_lateness_s'] = .1
    path = tmp_path/'positioning.json'
    with pytest.raises(RuntimeError, match='tick lateness'):
        runner.position_at_wait(arm, s, sleep=lambda _: clock.advance(1.),
                                monotonic=lambda: clock.now_ns()/1e9, record_path=path)
    event = json.loads(path.read_text())['deadline_diagnostic']
    assert event['waypoint_index'] == 0
    assert event['tick'] == 1
    assert event['lateness_s'] == pytest.approx(.98)
    assert event['allowed_lateness_s'] == .1
    assert event['previous_command_duration_s'] is None
    assert not any(c['action'] == 'push_pose' for c in arm.calls)


def test_positioning_can_continue_after_delay_above_the_selected_height():
    from scripts import run_four_direction_sweep as runner
    clock = FakeClock()
    arm = FakeArm((-.2, .45, .13, *setup()['vertical_rpy_rad']))
    original = arm.push_pose
    starts = []

    def slow_push(pose):
        starts.append(clock.now_ns())
        original(pose)
        if len(starts) == 1:
            clock.advance(.16)

    arm.push_pose = slow_push
    s = setup()
    s['max_tick_lateness_s'] = .1
    record = runner.position_at_wait(arm, s, sleep=clock.advance,
        monotonic=lambda: clock.now_ns()/1e9, continue_above_z_mm=20.)
    assert record['status'] == 'completed'
    assert len(record['deadline_recoveries']) == 1
    assert record['deadline_recoveries'][0]['previous_command_duration_s'] == pytest.approx(.16)
    assert np.min(np.diff(starts)) >= 20_000_000


def test_clear_serial_backlog_after_positioning_before_baseline(monkeypatch, tmp_path):
    from functools import partial
    from scripts import run_four_direction_sweep as runner
    from brushbot.experiments.four_direction_sweep import default_profile
    clock = FakeClock()
    arm = FakeArm((-.37, .5, .13, 0., .26, 0.), clock=clock)
    class Source(FakeMagneticSource):
        cleared = False
        def discard_pending(self):
            assert self.arm.pose[:3] == pytest.approx((-.2, .5, .13))
            self.cleared = True
            return {'discarded_bytes': 4096}
    source = Source(arm, clock)
    monkeypatch.setattr(runner, 'position_at_wait', partial(runner.position_at_wait,
        sleep=clock.advance, monotonic=lambda: clock.now_ns()/1e9))
    engine, hub = runner.build_stack(profile=default_profile(), setup=setup(), root=tmp_path,
                                    arm=arm, source=source, clock=clock, auto_position=True)
    assert source.cleared
    assert engine.state == 'READY'
    assert not hub.baseline_ready


def test_failed_sensor_reboot_records_failure_before_any_robot_motion(tmp_path):
    from scripts.run_four_direction_sweep import build_stack, EXPERIMENT_FOLDER
    from brushbot.experiments.four_direction_sweep import default_profile
    clock = FakeClock()
    arm = FakeArm((-.2, .5, .13, *setup()['vertical_rpy_rad']), clock=clock)
    class Source(FakeMagneticSource):
        def reboot(self):
            raise RuntimeError('sensor reboot timeout')
    with pytest.raises(RuntimeError, match='reboot timeout'):
        build_stack(profile=default_profile(), setup=setup(), root=tmp_path,
                    arm=arm, source=Source(arm, clock), clock=clock,
                    auto_position=True, reboot_sensor=True, trial_index=2)
    assert not any(c['action'] == 'push_pose' for c in arm.calls)
    attempt = next(tmp_path.glob(f'*/{EXPERIMENT_FOLDER}/sensor_reboots/*.json'))
    record = json.loads(attempt.read_text())
    assert record['status'] == 'failed'
    assert record['trial_index'] == 2


def test_successful_sensor_reboot_is_saved_with_each_trial_baselines(tmp_path):
    from scripts.run_four_direction_sweep import build_stack
    from scripts.run_strokeplan_experiment import run_recorded
    from brushbot.experiments.four_direction_sweep import default_profile
    clock = FakeClock()
    arm = FakeArm((-.2, .5, .13, *setup()['vertical_rpy_rad']), clock=clock)
    arm.realtime_state_reads = False
    class Source(FakeMagneticSource):
        def reboot(self):
            return dict(status='completed', first_frame_sensor_t_us=200000,
                        method='esp32_software_restart')
    engine, hub = build_stack(profile=default_profile(), setup=setup(), root=tmp_path,
        arm=arm, source=Source(arm, clock), clock=clock, reboot_sensor=True, trial_index=3)
    result = run_recorded(engine, hub, clock=clock)
    assert result['state'] == 'END_WAIT'
    run = Path(result['run_dir'])
    resolved = json.loads((run/'resolved.json').read_text())
    assert resolved['sensor_reboot']['first_frame_sensor_t_us'] == 200000
    assert resolved['sensor_reboot']['status'] == 'completed'
    assert len(json.loads((run/'manifest.json').read_text())['baselines']) == 2


def test_cli_enables_sensor_reboot_for_every_trial_by_default(monkeypatch, tmp_path, cli_session):
    from scripts import run_four_direction_sweep as runner
    seen = []
    def execute(profile, *args, **kwargs):
        seen.append(kwargs['stack_factory'].keywords['reboot_sensor'])
        return 0
    monkeypatch.setattr(runner, 'execute_hardware', execute)
    monkeypatch.setattr('builtins.input', lambda _: '')
    assert runner.main(['--run-root', str(tmp_path), '--speed-mm-s', '10']) == 0
    assert seen == [True, True, True, True]


@pytest.mark.parametrize('affected_phase', ['BASELINE', 'REBASELINE'])
def test_baseline_recovers_after_startup_outlier_without_dropping_raw_data(tmp_path, affected_phase):
    import csv
    from scripts.run_strokeplan_experiment import run_recorded
    engine, hub, arm, source, clock = build(tmp_path)
    original = source.read_frames
    affected_time = None
    def frames():
        nonlocal affected_time
        rows = original()
        if engine.state == affected_phase and affected_time is None:
            affected_time = clock.now_ns()
            rows[0]['B_uT'][0] = 0.
        return rows
    source.read_frames = frames
    result = run_recorded(engine, hub, clock=clock)
    assert result['state'] == 'END_WAIT', result
    folder = Path(result['run_dir'])
    raw = list(csv.DictReader((folder/'sensor.csv').open()))
    bad = [r for r in raw if float(r['Bx_uT']) == 0.]
    assert len(bad) == 1  # Original observation retained, never rewritten as valid baseline.
    manifest = json.loads((folder/'manifest.json').read_text())
    baseline = manifest['baselines'][0 if affected_phase == 'BASELINE' else 1]
    assert baseline['first_seq'] > int(bad[0]['seq'])
    assert baseline['B0_uT'] == pytest.approx([10., 20., 30.])


@pytest.mark.parametrize('axis', [0, 1])
def test_continuously_unstable_baseline_still_aborts_without_contact(tmp_path, axis):
    from scripts.run_strokeplan_experiment import run_recorded
    engine, hub, arm, source, clock = build(tmp_path)
    original = source.read_frames
    count = 0
    def frames():
        nonlocal count
        rows = original()
        count += 1
        rows[0]['B_uT'][axis] = 0. if count % 2 else 30.
        return rows
    source.read_frames = frames
    result = run_recorded(engine, hub, clock=clock)
    assert result['state'] == 'ABORTED'
    assert result['last_error'] == 'baseline_failed'
    assert not any(c['action'] == 'push_pose' for c in arm.calls)


def test_bz_variation_is_recorded_but_does_not_gate_xy_baseline(tmp_path):
    from scripts.run_strokeplan_experiment import run_recorded
    engine, hub, arm, source, clock = build(tmp_path)
    original = source.read_frames
    count = 0
    def frames():
        nonlocal count
        rows = original()
        count += 1
        rows[0]['B_uT'][2] = count * 1000. + (10000. if count % 2 else 0.)
        return rows
    source.read_frames = frames
    result = run_recorded(engine, hub, clock=clock)
    assert result['state'] == 'END_WAIT'
    manifest = json.loads((Path(result['run_dir'])/'manifest.json').read_text())
    assert all(b['quality_axes'] == [0, 1] for b in manifest['baselines'])
    assert all(b['std_uT'][2] > 30 for b in manifest['baselines'])


def test_resume_second_trial_keeps_indices_and_wetting_boundaries(monkeypatch, tmp_path, cli_session):
    from scripts import run_four_direction_sweep as runner
    trials, prompts = [], []
    def execute(p, s, *args, **kwargs):
        trials.append((p['direction'], p['speed_mm_s'], kwargs['stack_factory'].keywords['trial_index']))
        return 0
    monkeypatch.setattr(runner, 'execute_hardware', execute)
    monkeypatch.setattr('builtins.input', lambda _: prompts.append(len(trials)) or '')
    assert runner.main(['--start-trial', '2', '--run-root', str(tmp_path)]) == 0
    assert len(trials) == 11
    assert trials[0] == ('up', 10., 2)
    assert trials[-1] == ('down', 7., 12)
    assert prompts == list(range(11))
    assert cli_session[0] == ['open', 'close']


def test_connection_reset_stops_batch_without_replaying_trial(monkeypatch, tmp_path, cli_session):
    from scripts import run_four_direction_sweep as runner
    calls = []
    def execute(p, *args, **kwargs):
        calls.append(p['direction'])
        if len(calls) == 2:
            raise ConnectionResetError('peer reset')
        return 0
    monkeypatch.setattr(runner, 'execute_hardware', execute)
    monkeypatch.setattr('builtins.input', lambda _: '')
    assert runner.main(['--run-root', str(tmp_path)]) == 2
    assert calls == ['right', 'up']
    assert cli_session[0] == ['open', 'close']
