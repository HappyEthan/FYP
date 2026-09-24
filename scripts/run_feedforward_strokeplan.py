#!/usr/bin/env python3
"""Compile V3 targets + independent calibration/settings. Default is OFFLINE."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time

import numpy as np
from brushbot.strokeplan import StrokePlan
from brushbot.target_strokeplan import StrokePlan as TargetPlan
from brushbot.strokeplan_compile import compile_target_plan, LIMITATIONS
from brushbot.feedforward import require_execution_approval

ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / 'runs/plans/target_v3.npz'
# 可在脚本内填入独立配置路径；默认 None 要求命令行明确指定。
FEEDFORWARD_PATH = None
SETTINGS_PATH = None
ROBOT_IP = '192.168.0.10'
DT = .02
MAX_LATENESS_S = .05
TRANSIT_SPEED_MM_S = 10.  # Legacy V2 preview; V3 transit policy lives in strokeplan_compile.py.
ACCEL_MM_S2 = 50.


def _progress(distance, speed):
    """Trapezoidal time law, starts and ends at rest; metres and seconds."""
    acceleration = ACCEL_MM_S2 / 1000
    ramp = min(speed / acceleration, math.sqrt(distance / acceleration))
    peak = acceleration * ramp
    duration = distance / peak + ramp
    n = max(1, math.ceil(duration / DT))
    t = np.minimum(np.arange(1, n+1)*DT, duration)
    d = np.where(t < ramp, .5*acceleration*t*t,
                 np.where(t <= duration-ramp, peak*(t-.5*ramp),
                          distance-.5*acceleration*(duration-t)**2))
    return np.clip(d/distance, 0, 1)


def compile_plan(plan):
    setup = plan.meta['setup']
    orientation = np.asarray(plan.meta['orientation_rpy_rad'], float)
    if orientation.shape != (3,) or not np.isfinite(orientation).all():
        raise ValueError('invalid orientation')
    start = np.array([setup['origin_x_mm'], setup['origin_y_mm'], setup['wait_z_mm']])/1000
    current = start.copy()
    poses = [np.r_[start, orientation]]
    phases = ['wait']

    def move(target, phase):
        nonlocal current
        target = np.asarray(target, float)
        length = np.linalg.norm(target-current)
        if length > 1e-12:
            for u in _progress(length, TRANSIT_SPEED_MM_S/1000):
                poses.append(np.r_[current + u*(target-current), orientation])
                phases.append(phase)
        current = target.copy()

    if not plan.strokes:
        raise ValueError('empty plan')
    for stroke in plan.strokes:
        s, xy, depth = map(np.asarray, (stroke.s, stroke.xy, stroke.z_ff))
        if (s.ndim != 1 or len(s)<2 or xy.shape != (len(s),2) or depth.shape != s.shape
                or not np.isfinite(np.r_[s,xy.ravel(),depth]).all()
                or np.any(np.diff(s)<=0) or s[0]!=0 or s[-1]!=1
                or np.any(depth<0) or np.any(depth*1000>setup['max_depth_mm'])):
            raise ValueError('invalid stroke arrays/depth')
        # First version is deliberately constrained to the measured +X straight path.
        if np.any(np.diff(xy[:,0])<=0) or np.ptp(xy[:,1])>1e-9:
            raise ValueError('only measured +X straight strokes are supported')
        speed = float(plan.meta['speed_mm_s'])
        if speed != 10.:
            raise ValueError('reference supports 10 mm/s only')
        xyz = np.column_stack((xy, setup['contact_z_mm']/1000-depth))
        move([*xy[0], start[2]], 'high_transfer')
        move(xyz[0], 'lower')
        distance = xy[-1,0]-xy[0,0]
        for u in _progress(distance, speed/1000):
            x = xy[0,0]+u*distance
            target = [x, xy[0,1], np.interp(x,xy[:,0],xyz[:,2])]
            poses.append(np.r_[target, orientation])
            phases.append('measure')
        current = xyz[-1].copy()
        move([*xy[-1], start[2]], 'lift')
    move(start, 'return_high')
    poses = np.asarray(poses)
    lower = np.asarray(setup['workspace_min_mm'])/1000
    upper = np.asarray(setup['workspace_max_mm'])/1000
    if not np.isfinite(poses).all() or np.any(poses[:,:3]<lower) or np.any(poses[:,:3]>upper):
        raise ValueError('workspace_limit')
    velocity = np.diff(poses[:,:3],axis=0)/DT
    if (np.max(np.linalg.norm(velocity[:,:2],axis=1))*1000 > setup['max_xy_speed_mm_s']+1e-6
            or np.max(abs(velocity[:,2]))*1000 > setup['max_z_speed_mm_s']+1e-6
            or np.max(np.linalg.norm(velocity,axis=1))*DT*1000 > setup['max_step_mm']+1e-6):
        raise ValueError('speed/step limit: smooth the target profile')
    if np.max(np.linalg.norm(np.diff(velocity,axis=0)/DT,axis=1))*1000 > setup['max_accel_mm_s2']+1e-6:
        raise ValueError('acceleration limit: smooth the target profile')
    return poses, phases


def execute(arm, poses, *, clock=time.monotonic, sleep=time.sleep):
    """Injected SI adapter; clock and arm can be fake for offline verification."""
    state = arm.read()
    current = np.asarray(state.tcp_pose, float)
    if (state.fsm != 33 or current.shape != (6,) or not np.isfinite(current).all()
            or np.linalg.norm(current[:3]-poses[0,:3]) > .0005
            or np.max(abs((current[3:]-poses[0,3:]+np.pi)%(2*np.pi)-np.pi)) > np.deg2rad(1)):
        raise ValueError('move to printed wait XYZ/RPY before execution')
    try:
        arm.start_servo()
        origin = clock()
        tick_index = 0
        # brushpaint runtime.RealClock: absolute deadlines, re-align on overrun.
        # Hold the final target at the Servo rate for 0.2 s before GroupStop.
        commands = list(poses) + [poses[-1]] * 10
        for pose in commands:
            due = origin + tick_index * DT
            now = clock()
            if now-due > MAX_LATENESS_S:
                raise RuntimeError('deadline_miss')
            if now-due >= DT:
                tick_index = math.ceil((now-origin)/DT)
                due = origin + tick_index * DT
            remaining = due-clock()
            while remaining > 0:
                sleep(remaining)
                remaining = due-clock()
            now = clock()
            if now-due > MAX_LATENESS_S:
                raise RuntimeError('deadline_miss')
            arm.push_servo_pose(tuple(pose))
            tick_index += 1
    except BaseException:
        # Preserve the original Servo/interrupt error if GroupStop also fails.
        try:
            arm.stop()
        except Exception:
            pass
        raise
    else:
        arm.stop()
    return len(poses)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan', nargs='?', type=Path, default=PLAN_PATH)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--preview', type=Path, help='offline trajectory CSV')
    parser.add_argument('--feedforward', type=Path, default=FEEDFORWARD_PATH)
    parser.add_argument('--settings', type=Path, default=SETTINGS_PATH)
    parser.add_argument('--legacy-v2', action='store_true', help='explicit old-format offline preview')
    args = parser.parse_args()
    table = None
    if args.legacy_v2:
        if args.execute or args.feedforward or args.settings:
            parser.error('legacy V2 is preview-only; migrate to V3 for independent configuration')
        with np.load(args.plan, allow_pickle=False) as data:
            if int(data['format_version']) != 2:
                parser.error('--legacy-v2 requires a V2 file')
        plan = StrokePlan.load(args.plan)
        setup = plan.meta['setup']
        poses, phases = compile_plan(plan)
    else:
        if args.feedforward is None or args.settings is None:
            parser.error('V3 requires independent --feedforward and --settings files')
        try:
            plan = TargetPlan.load(args.plan)
            table = json.loads(args.feedforward.read_text())
            setup = json.loads(args.settings.read_text())
            poses, phases = compile_target_plan(plan, table, setup, dt_s=DT)
            if args.execute:
                require_execution_approval(table, setup)
        except (ValueError, KeyError, TypeError) as exc:
            parser.error(str(exc))
    print(f'{len(poses)} trajectory poses + 10 hold poses, {(len(poses)-1)*DT+.2:.2f} s; open-loop candidate')
    print('Wait XYZ [mm], RPY [deg]:', poses[0,:3]*1000, np.rad2deg(poses[0,3:]))
    print('Z range [mm]:', poses[:,2].min()*1000, poses[:,2].max()*1000)
    print(LIMITATIONS)
    if args.preview:
        import csv
        report_path = args.preview.with_suffix('.json')
        if args.preview.suffix.lower() != '.csv' or args.preview.exists() or report_path.exists():
            parser.error('preview must be a new .csv and companion .json must not exist')
        sources = {'plan': args.plan}
        if table is not None:
            sources.update(feedforward=args.feedforward, settings=args.settings)
        report = dict(
            inputs={k: dict(path=str(p.resolve()),sha256=hashlib.sha256(p.read_bytes()).hexdigest())
                    for k,p in sources.items()},
            calibration_id=table['calibration_id'] if table else None,
            execution_approved=bool(table and table['approved'] and table['transient_approved'] and setup.get('verified') is True),
            trajectory_points=len(poses),hold_points=10,dt_s=DT,
            duration_s=(len(poses)-1)*DT+.2,limitations=LIMITATIONS,
            validation='offline kinematic limits only; not collision clearance or dynamic response validation')
        with args.preview.open('x', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['t_s','phase','x_mm','y_mm','z_mm','rx_deg','ry_deg','rz_deg'])
            for i,(pose,phase) in enumerate(zip(poses,phases)):
                writer.writerow([i*DT,phase,*pose[:3]*1000,*np.rad2deg(pose[3:])])
        with report_path.open('x') as f:
            json.dump(report,f,indent=2,ensure_ascii=False,allow_nan=False)
            f.write('\n')
    if not args.execute:
        print('Offline preview only. Add --execute to connect and confirm motion.')
        return
    if input('确认已沾水、位于上述 wait 位姿且路径净空足够；输入 RUN 开始: ').strip() != 'RUN':
        return
    sys.path.insert(0,str(ROOT.parent/'elfin-dhag-adapter'))
    from huayan_robot import HuayanRobot
    # This module import has no hardware side effects.
    sys.path.insert(0,str(ROOT/'scripts'))
    from run_ladder_experiment import _read_named_coordinate, _vendor_coord_to_si
    from brushbot.experiments.adapter import ElfinExperimentArm, RobotResourceLock
    lock = RobotResourceLock(Path('/tmp/brushbot-feedforward.lock'), ROBOT_IP)
    lock.acquire()
    try:
        robot = HuayanRobot(ROBOT_IP, tcp_name=setup['tcp_name'], ucs_name=setup['ucs_name'],
                            servo_dt=DT, lookahead=.1)
        robot.client.raw_client.tcp.settimeout(.5)
        for method, name, attr, key in (
                ('HRIF_ReadTCPByName',setup['tcp_name'],'tool_coord','tool_coord_si'),
                ('HRIF_ReadUCSByName',setup['ucs_name'],'user_coord','user_coord_si')):
            coord = _read_named_coordinate(robot.client,method,name)
            if not np.allclose(_vendor_coord_to_si(coord),setup[key],atol=1e-9,rtol=0):
                raise ValueError('controller coordinates differ from measured reference')
            setattr(robot.arm,attr,list(coord))
        ElfinExperimentArm(robot,setup,transport_timeout_s=.5)
        print('Completed poses:',execute(robot.arm,poses))
    finally:
        lock.release()


if __name__ == '__main__':
    main()
