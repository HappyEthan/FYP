#!/usr/bin/env python3
"""四方向 × 10/15/7 mm/s；默认Z36定高连续12笔，每笔150 mm。

--dry-run 只编译和预检。真机每笔按 Enter 确认，每4笔提醒沾水，逐笔自动重采方向基线。
默认每笔发送 REBOOT 软复位板子；需要支持此命令的 fixed90 固件。
上下分别对应 Base +Y/-Y，左右对应 Base -X/+X。
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime
from functools import partial
import hashlib
import json
import math
from pathlib import Path
import time
import uuid
from zoneinfo import ZoneInfo

import numpy as np

from brushbot.experiments.acquisition import SampleHub
from brushbot.experiments.cartesian_return import build_return_route
from brushbot.experiments.engine import height_deadline_policy
from brushbot.experiments.four_direction_sweep import (
    DIRECTIONS, FourDirectionSweepEngine, compile_sweep, default_profile,
)
from brushbot.experiments.strokeplan_execution import runtime_settings
from brushbot.experiments.strokeplan_character import CHARACTER_ENTRY
from brushbot.experiments.z_identification import DT, _check_trajectory, _ease

if __package__:
    from .run_ladder_experiment import DatedLadderRecorder
    from .run_z_identification import execute_hardware, hardware_session
else:
    from run_ladder_experiment import DatedLadderRecorder
    from run_z_identification import execute_hardware, hardware_session

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT/'runs/brush2/plans/12_中字朝负Y_正X为右/settings.json'
RUN_ROOT = ROOT/'runs/brush2'
EXPERIMENT_FOLDER = '四方向速度下压实验'
DIRECTION_ORDER = ('right', 'up', 'left', 'down')
SPEEDS_MM_S = (10., 15., 7.)
DIRECTION_ORIGINS_MM = {'right': (-150., 500.), 'up': (-150., 450.),
                        'left': (-150., 500.), 'down': (-150., 550.)}

# 常用参数集中在这里，也可通过命令行覆盖。Z 是 Base 下的 TCP 高度（mm）。
PROFILE = dict(default_profile(),
               travel_mm=150.,         # 从原点到末端的总行程；下压组中点开始下压
               speed_mm_s=10.,         # 单笔配置；批次默认使用 SPEEDS_MM_S
               start_z_mm=36.,         # 前半程保持的 TCP Z
               end_z_mm=25.,           # 后半程结束时的 TCP Z
               entry_contact_z_mm=36., # 旋转下笔高度，独立于起始 Z
               entry_reverse_mm=5.,    # 沿用中字配方的反向 XY 补偿
               rotate_s=3.)            # 接触旋转时长；空中旋转沿用中字1.5 s
PROFILE.update({key: CHARACTER_ENTRY[key] for key in (
    'air_rotate_s', 'transfer_speed_mm_s', 'fast_z_speed_mm_s', 'slow_z_speed_mm_s',
    'slow_below_z_mm', 'transit_accel_mm_s2', 'angular_speed_deg_s', 'angular_accel_deg_s2')})
PROFILE['return_to_origin'] = False
Y_WORKSPACE_MM = (300., 700.)  # 上下界均加100；起点也沿+Y平移100。
WAIT_Z_MM = 70.  # 本实验抬笔、笔间转场及空载基线高度。


def position_at_wait(arm, setup, *, sleep=time.sleep, monotonic=time.monotonic,
                     timeout_s=60., record_path=None, context=None, continue_above_z_mm=None):
    """Precheck bounded Servo lift/transfer/orientation, await arrivals, retain failures."""
    record = dict(status='preparing', started_at=datetime.now().astimezone().isoformat(),
                  initial_pose_m_rad=None, route_m_rad=[], completed_waypoints=0,
                  context=copy.deepcopy(context),
                  timing=dict(commands_sent=0, max_lateness_s=0., max_command_duration_s=0.))

    def save():
        if record_path is not None:
            path = Path(record_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False))
            temporary.replace(path)

    lower, upper = np.asarray(setup['workspace_min_mm']), np.asarray(setup['workspace_max_mm'])
    tolerance = float(setup['pose_tolerance_mm'])

    def read_pose():
        state = arm.read_state()
        if not state.get('available'):
            raise RuntimeError('position unavailable during automatic positioning')
        actual = np.asarray(state.get('tcp_pose'), dtype=float)
        if actual.shape != (6,) or not np.isfinite(actual).all():
            raise ValueError('invalid pose during automatic positioning')
        if np.any(actual[:3]*1000 < lower-tolerance) or np.any(actual[:3]*1000 > upper+tolerance):
            raise RuntimeError('workspace limit during automatic positioning')
        return state, actual

    try:
        policy = (None if continue_above_z_mm is None else
                  height_deadline_policy(setup, continue_above_z_mm))
        record['deadline_policy'] = policy
        save()
        state, initial = read_pose()
        record['initial_pose_m_rad'] = initial.tolist()
        if state.get('fsm') != 33:
            raise RuntimeError('automatic positioning requires Standby (33)')
        if setup['wait_z_mm'] <= setup['contact_z_mm']:
            raise ValueError('wait height must be above contact')
        target = (setup['origin_x_mm']/1000, setup['origin_y_mm']/1000,
                  setup['wait_z_mm']/1000, *setup['vertical_rpy_rad'])
        # Accept measured boundary noise, but keep every commanded waypoint within
        # nominal bounds. A reading beyond the pose tolerance was rejected above.
        planning_pose = initial.copy()
        planning_pose[:3] = np.clip(initial[:3]*1000, lower, upper)/1000
        route = build_return_route(planning_pose, target, setup)
        chunks = []
        previous = planning_pose
        for waypoint in route:
            delta = np.asarray(waypoint)-previous
            xy = np.linalg.norm(delta[:2])*1000
            z = abs(delta[2])*1000
            angle = np.linalg.norm(np.rad2deg(delta[3:]))
            seconds = max(DT,
                1.875*xy/min(CHARACTER_ENTRY['transfer_speed_mm_s'],
                             setup['return_speed_mm_s'], setup['max_xy_speed_mm_s']),
                1.875*z/min(CHARACTER_ENTRY['fast_z_speed_mm_s'], setup['max_z_speed_mm_s']),
                math.sqrt(5.774*np.linalg.norm(delta[:3])*1000/min(
                    CHARACTER_ENTRY['transit_accel_mm_s2'], setup['max_accel_mm_s2'])),
                1.875*angle/CHARACTER_ENTRY['angular_speed_deg_s'],
                math.sqrt(5.774*angle/CHARACTER_ENTRY['angular_accel_deg_s2']))
            count = math.ceil(seconds/DT)
            chunk = previous+delta*_ease(np.arange(1, count+1)/count)[:, None]
            # Hold beyond the 0.1 s Servo lookahead before Stop; otherwise Stop
            # can cut off the last waypoint before the arm physically arrives.
            chunk = np.vstack([chunk, np.tile(waypoint, (10, 1))])
            chunks.append(chunk)
            previous = np.asarray(waypoint)
        poses = np.vstack([planning_pose, *chunks])
        metrics = _check_trajectory(poses, setup, CHARACTER_ENTRY)
        record.update(route_m_rad=[list(p) for p in route], status='running',
                      motion_metrics=metrics, planned_duration_s=sum(len(c)*DT for c in chunks),
                      motion_profile=copy.deepcopy(CHARACTER_ENTRY))
        save()
        period_ns = int(round(DT*1e9))
        allowed_ns = int(round(setup['max_tick_lateness_s']*1e9))
        previous_push_ns = previous_duration_s = None
        last_command = planning_pose
        for index, (waypoint, chunk) in enumerate(zip(route, chunks)):
            arm.start_servo()
            started_ns = int(round(monotonic()*1e9))
            for tick, command in enumerate(chunk, 1):
                due_ns = started_ns+tick*period_ns
                paced_ns = max(due_ns, previous_push_ns+period_ns) if previous_push_ns is not None else due_ns
                sleep(max(0., (paced_ns-int(round(monotonic()*1e9)))/1e9))
                now_ns = int(round(monotonic()*1e9))
                lateness_ns = now_ns-due_ns
                record['timing']['max_lateness_s'] = max(record['timing']['max_lateness_s'], lateness_ns/1e9)
                if lateness_ns > allowed_ns:
                    diagnostic = dict(waypoint_index=index, tick=tick,
                        lateness_s=lateness_ns/1e9, allowed_lateness_s=allowed_ns/1e9,
                        previous_command_duration_s=previous_duration_s,
                        target_pose_m_rad=list(waypoint))
                    if policy and min(last_command[2], command[2])*1000 > policy['min_z_mm']:
                        diagnostic.update(min_z_mm=policy['min_z_mm'], action='continue_in_order')
                        record.setdefault('deadline_recoveries', []).append(diagnostic)
                        started_ns += lateness_ns
                    else:
                        record['deadline_diagnostic'] = diagnostic
                        raise RuntimeError('automatic positioning tick lateness: '
                            f'waypoint={index+1}, tick={tick}, late={lateness_ns/1e6:.3f}ms, '
                            f'limit={allowed_ns/1e6:.3f}ms')
                previous_push_ns = now_ns
                try:
                    arm.push_pose(tuple(command))
                finally:
                    previous_duration_s = (int(round(monotonic()*1e9))-now_ns)/1e9
                    record['timing']['max_command_duration_s'] = max(
                        record['timing']['max_command_duration_s'], previous_duration_s)
                record['timing']['commands_sent'] += 1
                last_command = command
            arm.stop()
            deadline = monotonic() + timeout_s
            while True:
                current, actual = read_pose()
                angles = (actual[3:]-waypoint[3:]+np.pi) % (2*np.pi)-np.pi
                if (current.get('fsm') == 33
                        and np.linalg.norm(actual[:3]-waypoint[:3])*1000 <= tolerance
                        and np.all(abs(angles) <= setup['orientation_tolerance_rad'])):
                    break
                if monotonic() >= deadline:
                    raise TimeoutError('automatic positioning timed out')
                sleep(.02)
            record.update(completed_waypoints=index+1, last_pose_m_rad=actual.tolist())
            save()
        record['status'] = 'completed'
    except BaseException as exc:
        try:
            arm.stop()
        except Exception:
            pass
        record.update(status='failed', error=str(exc), error_type=type(exc).__name__)
        raise
    finally:
        record['finished_at'] = datetime.now().astimezone().isoformat()
        save()
    return record


class SweepRecorder(DatedLadderRecorder):
    def __init__(self, root, snapshots):
        p = snapshots['experiment']['identification']
        self._direction = p['direction']
        self._segments = {s['id']: s for s in snapshots['compiled']['segments']}
        kind = '定高' if p['mode'] == 'four-direction-hold' else '半程下压'
        label = f'{kind}_{p["direction"]}_Z{p["start_z_mm"]:g}到{p["end_z_mm"]:g}_速度{p["speed_mm_s"]:g}'
        super().__init__(root, snapshots, experiment_folder=EXPERIMENT_FOLDER, folder_label=label)

    def _write_snapshots(self, snapshots):
        super()._write_snapshots(snapshots)
        self._save_json('identification.json', snapshots['experiment']['identification'])
        self._save_json('settings.json', snapshots['setup'])
        self._save_json('segments.json', snapshots['compiled']['segments'])
        self._save_json('motion_metrics.json', snapshots['compiled']['motion_metrics'])
        if snapshots.get('settings_source_bytes') is not None:
            self._save_bytes('settings_source.json', snapshots['settings_source_bytes'])

    def write(self, stream, row):
        if stream == 'control':
            segment = self._segments.get(row['phase'], {})
            row = dict(row, direction=self._direction, segment_id=row['phase'],
                       segment_kind=segment.get('kind', 'preparation'),
                       prescribed_depth_m=row['depth_ff_m'])
        super().write(stream, row)


def build_stack(*, profile, setup, root, arm, source, clock,
                settings_source_bytes=None, batch_id=None, auto_position=False,
                trial_index=None, trial_count=None, reboot_sensor=False):
    positioning = None
    sensor_reboot = None
    def record(snapshots):
        snapshots = dict(snapshots, settings_source_bytes=settings_source_bytes)
        snapshots['experiment'] = dict(snapshots['experiment'], batch_id=batch_id,
            trial_index=trial_index, trial_count=trial_count, positioning=positioning,
            sensor_reboot=sensor_reboot,
            settings_source_sha256=(hashlib.sha256(settings_source_bytes).hexdigest()
                                   if settings_source_bytes is not None else None))
        return SweepRecorder(root, snapshots)
    hub = SampleHub(source, clock.now_ns, abort_on_invalid_running_sample=True,
                    baseline_quality_axes=(0, 1))
    engine = FourDirectionSweepEngine(arm, hub, record, clock, dt_s=.02)
    engine.prepare_sweep(profile, setup)
    if reboot_sensor:
        date = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d')
        attempt = f'{batch_id or "single"}_{trial_index or 1}_{uuid.uuid4().hex}.json'
        path = Path(root)/date/EXPERIMENT_FOLDER/'sensor_reboots'/attempt
        path.parent.mkdir(parents=True, exist_ok=True)
        sensor_reboot = dict(status='requested', method='esp32_software_restart',
            batch_id=batch_id, trial_index=trial_index, trial_count=trial_count,
            started_at=datetime.now().astimezone().isoformat(), record_path=str(path))
        path.write_text(json.dumps(sensor_reboot, ensure_ascii=False, indent=2)+'\n')
        print('发送 REBOOT；等待板子重新初始化、READY 与新数据（最多15秒）…')
        try:
            sensor_reboot.update(source.reboot())
            print('板子软复位已确认；设备首帧计时:',
                  sensor_reboot['first_frame_sensor_t_us']/1e6, 's；随后重新取基线。')
        except BaseException as exc:
            sensor_reboot.update(status='failed', error_type=type(exc).__name__, error=str(exc))
            raise
        finally:
            sensor_reboot['finished_at'] = datetime.now().astimezone().isoformat()
            path.write_text(json.dumps(sensor_reboot, ensure_ascii=False, indent=2)+'\n')
    if auto_position:
        date = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d')
        attempt = f'{batch_id or "single"}_{trial_index or 1}_{uuid.uuid4().hex}.json'
        path = Path(root)/date/EXPERIMENT_FOLDER/'positioning'/attempt
        positioning = position_at_wait(arm, setup, record_path=path,
            context=dict(batch_id=batch_id, trial_index=trial_index, trial_count=trial_count,
                         profile=profile, setup=setup))
        # Serial was opened before positioning to fail early if unavailable.
        # No hub polling happens during that motion: discard its backlog before
        # engine.start() begins the stationary baseline (and align fresh frames).
        positioning['sensor_buffer_reset'] = source.discard_pending()
    return engine, hub


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--direction', choices=['all', *DIRECTIONS], default='all')
    parser.add_argument('--kind', choices=['both', 'hold', 'sweep'], default='hold')
    parser.add_argument('--hold-z-mm', type=float, default=36.)
    parser.add_argument('--speed-mm-s', type=float, default=None,
                        help='只运行指定速度；省略则依次 10、15、7 mm/s')
    parser.add_argument('--settings', type=Path, default=SETTINGS)
    parser.add_argument('--run-root', type=Path, default=RUN_ROOT)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--reboot-sensor-each-trial', action=argparse.BooleanOptionalAction,
                        default=True, help='默认每笔先软复位板子；需更新 fixed90 固件')
    parser.add_argument('--start-trial', type=int, default=1,
                        help='从所选批次的第N笔开始，原编号及每4笔暂停边界不变')
    parser.add_argument('--no-record-actual-tcp', action='store_true')
    for key in ('travel_mm', 'start_z_mm', 'end_z_mm',
                'entry_contact_z_mm', 'entry_reverse_mm', 'rotate_s'):
        parser.add_argument('--'+key.replace('_', '-'), type=float, default=PROFILE[key],
                            help=f'默认 {PROFILE[key]:g}')
    for key in ('origin_x_mm', 'origin_y_mm'):
        parser.add_argument('--'+key.replace('_', '-'), type=float, default=None,
                            help='覆盖所有选定方向的该坐标；默认使用分方向起点')
    args = parser.parse_args(argv)
    source_bytes = args.settings.read_bytes()
    settings = json.loads(source_bytes)
    settings['workspace_min_mm'][1], settings['workspace_max_mm'][1] = Y_WORKSPACE_MM
    profile = copy.deepcopy(PROFILE)
    for key in ('travel_mm', 'start_z_mm', 'end_z_mm',
                'entry_contact_z_mm', 'entry_reverse_mm', 'rotate_s'):
        profile[key] = getattr(args, key)
    directions = DIRECTION_ORDER if args.direction == 'all' else (args.direction,)
    speeds = SPEEDS_MM_S if args.speed_mm_s is None else (args.speed_mm_s,)
    kinds = ('hold', 'sweep') if args.kind == 'both' else (args.kind,)
    # Compile the entire selected matrix before prompting or opening any device.
    plans = []
    for kind in kinds:
        for speed in speeds:
            for direction in directions:
                x, y = DIRECTION_ORIGINS_MM[direction]
                current = copy.deepcopy(settings)
                current.update(wait_z_mm=WAIT_Z_MM,
                               origin_x_mm=x if args.origin_x_mm is None else args.origin_x_mm,
                               origin_y_mm=y if args.origin_y_mm is None else args.origin_y_mm)
                setup = runtime_settings(current, hardware=not args.dry_run)
                p = dict(profile, direction=direction, speed_mm_s=speed)
                if kind == 'hold':
                    p.update(mode='four-direction-hold', start_z_mm=args.hold_z_mm,
                             end_z_mm=args.hold_z_mm)
                plans.append((p, setup, compile_sweep(p, setup)))
    batch_id = str(uuid.uuid4())
    if not 1 <= args.start_trial <= len(plans):
        parser.error(f'--start-trial must be between 1 and {len(plans)}')
    print(f'共 {len(plans)} 笔；四方向 × 速度 × 定高/半程下压；触觉反馈关闭。')
    print('Y 工作范围 (mm):', list(Y_WORKSPACE_MM))
    print('每笔开始前按 Enter 确认，每4笔提醒沾水；确认后直接移到下一起点，自动重采基线，不回旧原点。')
    print('板子复位:', '每笔 REBOOT → READY → 新数据 → 重采基线；失败即停止。'
          if args.reboot_sensor_each_trial else '已关闭程序软复位。')
    print('中字进笔策略：高位XY 80、快速Z 60、Z50以下下降15 mm/s；空中旋转1.5 s。')
    for index, (p, setup, c) in enumerate(plans, 1):
        line = c['pose_m_rad'][np.isin(c['phase'], ['straight_hold', 'sweep_down'])]
        kind = '定高' if p['mode'] == 'four-direction-hold' else '半程下压'
        print(f'{index}/{len(plans)} {kind} {p["direction"]} '
              f'{p["speed_mm_s"]:g} mm/s；travel={p["travel_mm"]:g} mm；'
              f'Z{p["start_z_mm"]:g}→{p["end_z_mm"]:g}')
        print('等待位 XYZ (mm):', [setup['origin_x_mm'], setup['origin_y_mm'], setup['wait_z_mm']],
              '终点 XYZ (mm):', np.round(line[-1, :3]*1000, 3).tolist(),
              '行走秒数:', round(c['slide_duration_s'], 2))
        print('运动峰值:', json.dumps(c['motion_metrics'], ensure_ascii=False))
    print('保存:', args.run_root/'YYYY-MM-DD'/EXPERIMENT_FOLDER/'raw')
    print(f'本次从第 {args.start_trial} 笔开始，执行 {len(plans)-args.start_trial+1} 笔；'
          '整批复用机器人连接；基线质量只检查 Bx、By，Bz 保留记录。')
    if args.dry_run:
        print('离线预检通过；未连接硬件，未创建实验 run。')
        return 0
    def confirm_trial(trial_index):
        p, _, _ = plans[trial_index-1]
        kind = '定高' if p['mode'] == 'four-direction-hold' else '半程下压'
        reminder = '请沾水，完成后确认；' if trial_index > 1 and (trial_index-1) % 4 == 0 else ''
        return input(f'{reminder}准备纸面与笔，确认路径后按 Enter 开始 '
                     f'{trial_index}/{len(plans)} {kind} {p["direction"]} '
                     f'{p["speed_mm_s"]:g} mm/s（其他输入结束）: ').strip() == ''

    index = args.start_trial
    try:
        if not confirm_trial(index):
            return 0
        with hardware_session(plans[index-1][1], record_tcp=not args.no_record_actual_tcp) as session:
            for index in range(args.start_trial, len(plans)+1):
                p, setup, _ = plans[index-1]
                if index > args.start_trial and not confirm_trial(index):
                    return 0
                kind = '定高' if p['mode'] == 'four-direction-hold' else '半程下压'
                print(f'开始 {index}/{len(plans)} {kind} {p["direction"]} {p["speed_mm_s"]:g} mm/s')
                code = execute_hardware(p, setup, source_bytes, args.run_root,
                                        record_tcp=not args.no_record_actual_tcp, session=session,
                                        stack_factory=partial(build_stack, batch_id=batch_id,
                                                              auto_position=True, trial_index=index,
                                                              reboot_sensor=args.reboot_sensor_each_trial,
                                                              trial_count=len(plans)),
                                        display_name='四方向速度下压')
                if code != 0:
                    return code
    except KeyboardInterrupt:
        print(f'第 {index} 笔附近收到中止；已结束批次，未自动重试。')
        return 130
    except Exception as exc:
        print(f'第 {index} 笔未完成，批次停止；{type(exc).__name__}: {exc}；未自动重连或重放运动。')
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
