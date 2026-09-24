from types import SimpleNamespace
import numpy as np
import pytest
from brushbot.strokeplan import Stroke, StrokePlan
from scripts.run_feedforward_strokeplan import compile_plan, execute
from scripts.generate_measured_strokeplan import generate


def plan_fixture():
    setup = dict(origin_x_mm=-200, origin_y_mm=500, wait_z_mm=130,
                 contact_z_mm=37, max_depth_mm=18,
                 workspace_min_mm=[-400,400,17], workspace_max_mm=[100,600,150],
                 max_xy_speed_mm_s=30, max_z_speed_mm_s=13,
                 max_step_mm=2, max_accel_mm_s2=200)
    return StrokePlan([Stroke(np.array([0.,1.]),np.array([[-.2,.5],[0,.5]]),
                             np.array([30.,30.]),np.array([.01,.01]))],
                      dict(setup=setup,orientation_rpy_rad=[.26,0,1.57],speed_mm_s=10))


def test_compilation_interpolates_lifts_and_returns_without_pose_jumps():
    poses, phases = compile_plan(plan_fixture())
    assert np.allclose(poses[0],poses[-1])
    assert poses[:,2].min() == pytest.approx(.027)
    assert np.max(np.linalg.norm(np.diff(poses[:,:3],axis=0),axis=1)) <= .000201
    measure = poses[np.asarray(phases)=='measure']
    assert measure[-1,0] == pytest.approx(0)
    assert np.ptp(measure[:,2]) < 1e-10


class Arm:
    def __init__(self, pose, fail=False):
        self.pose = pose
        self.fail = fail
        self.stopped = False
        self.sent = []
    def read(self): return SimpleNamespace(tcp_pose=self.pose,fsm=33)
    def start_servo(self): pass
    def push_servo_pose(self,pose):
        if self.fail: raise RuntimeError('20018')
        self.sent.append(pose)
    def stop(self): self.stopped = True


def test_execution_paces_si_commands_and_stops():
    poses,_ = compile_plan(plan_fixture())
    arm = Arm(poses[0])
    now = [0.]
    times = []
    def sleep(seconds):
        now[0] += seconds
        times.append(now[0])
    execute(arm,poses[:5],clock=lambda:now[0],sleep=sleep)
    assert times[:4] == pytest.approx([.02,.04,.06,.08])
    assert arm.sent[0][0] == -.2
    assert len(arm.sent) == 15
    assert np.allclose(arm.sent[-10:], poses[4])
    assert arm.stopped


def test_absolute_schedule_does_not_accumulate_sleep_overshoot():
    poses,_ = compile_plan(plan_fixture())
    arm = Arm(poses[0])
    now = [0.]
    stamps = []
    def sleep(seconds):
        now[0] += seconds + .001
        stamps.append(now[0])
    execute(arm,poses[:5],clock=lambda:now[0],sleep=sleep)
    assert stamps[:4] == pytest.approx([.021,.041,.061,.081])


def test_stop_failure_does_not_hide_original_servo_error():
    poses,_ = compile_plan(plan_fixture())
    arm = Arm(poses[0],fail=True)
    def fail_stop(): raise RuntimeError('stop failed')
    arm.stop = fail_stop
    with pytest.raises(RuntimeError,match='20018'):
        execute(arm,poses,clock=lambda:0,sleep=lambda _:None)


def test_failure_stops_without_retry_or_automatic_lift():
    poses,_ = compile_plan(plan_fixture())
    arm = Arm(poses[0],fail=True)
    with pytest.raises(RuntimeError,match='20018'):
        execute(arm,poses,clock=lambda:0,sleep=lambda _:None)
    assert arm.stopped and not arm.sent


def test_wrong_start_is_rejected_before_motion():
    poses,_ = compile_plan(plan_fixture())
    arm = Arm(np.zeros(6))
    with pytest.raises(ValueError,match='wait'):
        execute(arm,poses)
    assert not arm.sent


def test_workspace_and_target_jerks_rejected():
    plan = plan_fixture()
    plan.strokes[0].xy[1,0] = .2
    with pytest.raises(ValueError,match='workspace'):
        compile_plan(plan)


def test_measured_generator_averages_repeats_and_rejects_extrapolation(tmp_path):
    import json
    folder = tmp_path/'reference'
    folder.mkdir()
    setup = plan_fixture().meta['setup'] | dict(vertical_rpy_rad=[0,0,0],filter={},
        sensor_mount_id='a',tool_coord_si=[0]*6,user_coord_si=[0]*6,tcp_name='TCP',ucs_name='Base')
    for name,value in [('setup',setup),('manifest',dict(run_id='a',status='fault')),
                       ('resolved',dict(path=dict(axis='+x',travel_mm=200),motion=dict(speed_mm_s=10)))]:
        (folder/f'{name}.json').write_text(json.dumps(value))
    rows = [dict(phase=f'measure_{visit:02}',x_cmd_m=float(x),z_cmd_m=z,
                 a_control_uT=a) for visit,z,a in [(0,.0295,20),(1,.027125,30),(2,.02475,60)]
            for x in np.linspace(-.2,0,201)]
    (folder/'control.jsonl').write_text('\n'.join(map(json.dumps,rows)))
    plan = generate([folder],[25])
    assert plan.strokes[0].z_ff[0] == pytest.approx(.0086875)
    assert not plan.meta['reference_table']['approved']
    with pytest.raises(ValueError,match='extrapolation'):
        generate([folder],[61])
