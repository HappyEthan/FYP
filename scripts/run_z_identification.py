#!/usr/bin/env python3
"""Record ONE direct-Z identification line; --dry-run never opens hardware.

Entry: airborne Ry15 baseline -> airborne Ry30 -> Z36 -> fixed-XYZ Ry15
contact -> +X slide and depth loading -> two bipolar excitation amplitudes.
Edit the configuration below for the current installation. Every real run
requires manual wetting, the printed wait pose, and typing RUN.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

from brushbot.experiments.acquisition import SampleHub
from brushbot.experiments.adapter import ElfinExperimentArm, RobotResourceLock
from brushbot.experiments.strokeplan_execution import runtime_settings
from brushbot.experiments.tcp_pose_capture import TCPPoseSampler
from brushbot.experiments.z_identification import (
    DEPTH_DELTAS, IdentificationEngine, compile_identification, default_profile, default_sweep_profile,
)
from brushbot.monitor.sources import SerialSource

if __package__:
    from .run_ladder_experiment import (
        ADAPTER_ROOT, DatedLadderRecorder, LiveStatusPanel, MonotonicClock,
        _read_named_coordinate, _report, _vendor_coord_to_si,
    )
    from .run_strokeplan_experiment import run_recorded
else:
    from run_ladder_experiment import (
        ADAPTER_ROOT, DatedLadderRecorder, LiveStatusPanel, MonotonicClock,
        _read_named_coordinate, _report, _vendor_coord_to_si,
    )
    from run_strokeplan_experiment import run_recorded


ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT/'runs/brush2/plans/ry15_rz0_suite_60_200_v1/settings.json'
RUN_ROOT = ROOT/'runs/brush2'
EXPERIMENT_FOLDER = '05_Z动态辨识'
ARM_IP = '192.168.0.10'
SERIAL_PORT = '/dev/ttyACM0'
BAUD = 115200

# User-confirmed entry and usable +X line. Named tool/UCS values come from SETTINGS.
SETUP_OVERRIDES = {'origin_x_mm': -370., 'origin_y_mm': 500.,
                   'vertical_rpy_rad': [0., float(np.deg2rad(15)), 0.]}
DEPTH_PROFILES = dict(DEPTH_DELTAS)  # nominal depth mm -> large perturbation mm
PROFILE = {key: value for key, value in default_profile().items()
           if key not in {'depth_mm', 'delta_mm', 'order'}}
SWEEP_PROFILES = {mode: default_sweep_profile(mode) for mode in ('sweep-down', 'sweep-cycle')}
# Main editable values: travel_mm=450, entry_contact_z_mm=36, entry_ry_deg=30,
# rotate_s=3, slide_settle_s=1, load_s=3, hold_s=4, transition_s=0.4.


class IdentificationRecorder(DatedLadderRecorder):
    def __init__(self, root, snapshots, *, folder_label):
        self._segments = {s['id']: s for s in snapshots['compiled']['segments']}
        super().__init__(root, snapshots, experiment_folder=EXPERIMENT_FOLDER,
                         folder_label=folder_label)

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
            row = dict(row, segment_id=row['phase'],
                       segment_kind=segment.get('kind', 'preparation'),
                       plateau_index=segment.get('plateau_index'),
                       prescribed_depth_m=row['depth_ff_m'])
        super().write(stream, row)


def build_stack(*, profile, setup, root, arm, source, clock, settings_source_bytes=None):
    frozen_source = settings_source_bytes
    fmt = lambda value: f'{value:g}'.replace('.', 'p')
    if 'mode' in profile:
        label = (('连续下压' if profile['mode'] == 'sweep-down' else '下压回升')
                 + f'_Z{fmt(profile["entry_contact_z_mm"])}到{fmt(profile["sweep_end_z_mm"])}mm'
                 + f'_单程{fmt(profile["sweep_s"])}s')
    else:
        label = (f'压深{fmt(profile["depth_mm"])}mm_扰动{fmt(profile["delta_mm"])}mm_'
                 + ('先下压' if profile['order'] == 'press-first' else '先抬起'))

    def record(snapshots):
        snapshots = dict(snapshots, settings_source_bytes=frozen_source)
        snapshots['experiment'] = dict(snapshots['experiment'], run_label=label,
                                      settings_source_sha256=(hashlib.sha256(frozen_source).hexdigest()
                                                             if frozen_source is not None else None))
        return IdentificationRecorder(root, snapshots, folder_label=label)

    hub = SampleHub(source, clock.now_ns, abort_on_invalid_running_sample=True)
    engine = IdentificationEngine(arm, hub, record, clock, dt_s=.02)
    engine.prepare_identification(profile, setup)
    return engine, hub


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['local', 'sweep-down', 'sweep-cycle'], default='local')
    parser.add_argument('--depth-mm', type=float, choices=sorted(DEPTH_PROFILES))
    parser.add_argument('--delta-mm', type=float,
                        help='local large perturbation amplitude in mm; small amplitude is half')
    parser.add_argument('--order', choices=['press-first', 'lift-first'])
    parser.add_argument('--settings', type=Path, default=SETTINGS)
    parser.add_argument('--run-root', type=Path, default=RUN_ROOT)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--no-record-actual-tcp', action='store_true',
                        help='explicitly omit independent TCP evidence (default: enabled)')
    args = parser.parse_args(argv)
    if args.mode != 'local' and any(value is not None for value in
                                   (args.depth_mm, args.delta_mm, args.order)):
        parser.error('--depth-mm, --delta-mm and --order apply only to --mode local')
    args.depth_mm = 7.5 if args.depth_mm is None else args.depth_mm
    args.order = args.order or 'press-first'
    source_bytes = args.settings.read_bytes()
    settings = json.loads(source_bytes)
    settings.update(copy.deepcopy(SETUP_OVERRIDES))
    setup = runtime_settings(settings, hardware=not args.dry_run)
    delta_mm = DEPTH_PROFILES[args.depth_mm] if args.delta_mm is None else args.delta_mm
    profile = (dict(PROFILE, depth_mm=args.depth_mm, delta_mm=delta_mm, order=args.order)
               if args.mode == 'local' else copy.deepcopy(SWEEP_PROFILES[args.mode]))
    compiled = compile_identification(profile, setup)
    pose = compiled['pose_m_rad'][0]
    print('实验: Z 动态辨识；一条直线；触觉反馈关闭；磁目标不适用。')
    print('等待位 XYZ (mm):', np.round(pose[:3]*1000, 3).tolist(),
          'RPY (deg):', np.round(np.rad2deg(pose[3:]), 3).tolist())
    print(f'进笔: 悬空 Ry15 取基线 -> 高位 Ry{profile["entry_ry_deg"]:g}'
          f' -> Z{profile["entry_contact_z_mm"]:g} -> 固定 XYZ 旋转到 Ry15。')
    if args.mode == 'local':
        print('基础压深 {:.3f} mm；扰动 ±{:.3f}/±{:.3f} mm；{}'.format(
            args.depth_mm, profile['delta_mm'], profile['delta_mm']/2, args.order))
    else:
        print('{}: Z {} -> {} mm；单程 {} s；端点保持 {} s；X 始终向前。'.format(
            args.mode, profile['entry_contact_z_mm'], profile['sweep_end_z_mm'],
            profile['sweep_s'], profile['endpoint_hold_s']))
    print('X {:.1f} -> {:.1f} mm；滑动 {:.2f} s；编译轨迹 {:.2f} s，另加启动基线。'.format(
        setup['origin_x_mm'], setup['origin_x_mm']+profile['travel_mm'],
        compiled['slide_duration_s'], compiled['t_s'][-1]))
    print('运动峰值:', json.dumps(compiled['motion_metrics'], ensure_ascii=False))
    print('保存:', args.run_root/'YYYY-MM-DD'/EXPERIMENT_FOLDER/'raw')
    print('实际 TCP 独立采集:', '关闭' if args.no_record_actual_tcp else '约 10 Hz，开启')
    if args.dry_run:
        print('离线预检通过；未连接硬件，未创建实验 run。')
        return 0
    if input('确认手动沾水、等待位姿、旋转接触及整条路径净空后输入 RUN: ').strip() != 'RUN':
        return 0
    return execute_hardware(profile, setup, source_bytes, args.run_root,
                            record_tcp=not args.no_record_actual_tcp)


def execute_hardware(profile, setup, source_bytes, root, *, record_tcp,
                     stack_factory=None, display_name='Z 辨识'):
    # All device imports and connections occur after the operator's RUN.
    sys.path.insert(0, str(ADAPTER_ROOT))
    from huayan_robot import HuayanRobot

    clock = MonotonicClock()
    source = SerialSource(SERIAL_PORT, BAUD)
    lock = RobotResourceLock(Path('/tmp/brushbot-feedforward.lock'), ARM_IP)
    panel = LiveStatusPanel(sys.stdout)
    robot = pose_client = None
    lock.acquire()
    try:
        robot = HuayanRobot(ARM_IP, tcp_name=setup['tcp_name'], ucs_name=setup['ucs_name'],
                            servo_dt=.02, lookahead=.1)
        robot.client.raw_client.tcp.settimeout(.5)
        for method, name, attr, key in (
            ('HRIF_ReadTCPByName', setup['tcp_name'], 'tool_coord', 'tool_coord_si'),
            ('HRIF_ReadUCSByName', setup['ucs_name'], 'user_coord', 'user_coord_si'),
        ):
            coord = _read_named_coordinate(robot.client, method, name)
            if not np.allclose(_vendor_coord_to_si(coord), setup[key], atol=1e-9, rtol=0):
                raise ValueError('controller coordinates differ from settings: '+key)
            setattr(robot.arm, attr, list(coord))
        arm = ElfinExperimentArm(robot, setup, transport_timeout_s=.5, clock_ns=clock.now_ns)
        sampler = None
        if record_tcp:
            from huayan_robot.vendor import CPSClient
            from brushbot.backends.huayan import HuayanBackend
            pose_client = CPSClient(ARM_IP)
            pose_client.tcp.settimeout(.5)
            backend = HuayanBackend(pose_client, servo_dt=.02)
            sampler = TCPPoseSampler(lambda: backend.read().tcp_pose, clock_ns=clock.now_ns)
        source.start()
        factory = build_stack if stack_factory is None else stack_factory
        engine, hub = factory(profile=profile, setup=setup, root=root, arm=arm,
                              source=source, clock=clock, settings_source_bytes=source_bytes)

        def show(lines):
            panel.update((lines[0].replace('StrokePlan', display_name), lines[1]))

        result = run_recorded(engine, hub, clock=clock, live_output_fn=show, pose_sampler=sampler)
        panel.close()
        _report(result)
        if result.get('pose_capture'):
            print('实际 TCP 采集:', json.dumps(result['pose_capture'], ensure_ascii=False))
        return 0 if result['state'] == 'END_WAIT' else 2
    finally:
        try:
            panel.close()
        finally:
            try:
                source.stop()
            finally:
                try:
                    if pose_client is not None:
                        pose_client.tcp.close()
                finally:
                    try:
                        if robot is not None:
                            robot.client.raw_client.tcp.close()
                    finally:
                        lock.release()


if __name__ == '__main__':
    raise SystemExit(main())
