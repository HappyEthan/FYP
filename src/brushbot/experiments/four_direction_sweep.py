"""Direct-Z sweeps in four actual headings; never opens a device."""
from __future__ import annotations

import copy
import math
from bisect import bisect_right

import numpy as np

from brushbot.experiments.strokeplan_character import tangent_rpy
from brushbot.experiments.strokeplan_execution import StrokePlanExperimentEngine, runtime_settings
from brushbot.experiments.trajectory import time_law
from brushbot.experiments.z_identification import DT, _check_trajectory, _ease, _ticks
from brushbot.strokeplan import Stroke, StrokePlan

DIRECTIONS = {'right': (1., 0.), 'up': (0., 1.),
              'left': (-1., 0.), 'down': (0., -1.)}


def default_profile():
    return dict(mode='four-direction-half-sweep', direction='right', travel_mm=80.,
                speed_mm_s=2., xy_accel_mm_s2=50., start_z_mm=36., end_z_mm=25.,
                entry_contact_z_mm=36., entry_reverse_mm=5., entry_tilt_deg=30.,
                writing_tilt_deg=15., rotate_s=3., load_s=3.,
                airborne_settle_s=1., post_lift_hold_s=2.,
                return_to_origin=True, air_rotate_s=3., transfer_speed_mm_s=20.,
                fast_z_speed_mm_s=10., slow_z_speed_mm_s=10., slow_below_z_mm=50.,
                transit_accel_mm_s2=50.,
                angular_speed_deg_s=10., angular_accel_deg_s2=20.)


def compile_sweep(profile, settings, *, max_entry_tilt_deg=30.):
    if (isinstance(max_entry_tilt_deg,bool) or not isinstance(max_entry_tilt_deg,(int,float))
            or not math.isfinite(max_entry_tilt_deg) or not 0<max_entry_tilt_deg<90):
        raise ValueError('entry tilt ceiling must be finite and between 0 and 90 degrees')
    p = copy.deepcopy(profile)
    setup = runtime_settings(settings)
    if set(p) != set(default_profile()) or p['mode'] not in {
            'four-direction-half-sweep', 'four-direction-hold'}:
        raise ValueError('four-direction profile fields/mode differ from contract')
    if p['direction'] not in DIRECTIONS:
        raise ValueError('unknown direction')
    if not isinstance(p['return_to_origin'], bool):
        raise ValueError('return_to_origin must be boolean')
    for key, value in p.items():
        if key in {'mode', 'direction', 'return_to_origin'}:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(key+' must be finite')
        if key not in {'start_z_mm', 'end_z_mm', 'entry_contact_z_mm'}:
            if value < 0 or (value == 0 and key != 'entry_reverse_mm'):
                raise ValueError(key+' must be positive (compensation may be zero)')
    hold = p['mode'] == 'four-direction-hold'
    if hold:
        if not (p['end_z_mm'] == p['start_z_mm'] <= setup['contact_z_mm']):
            raise ValueError('hold requires end_z_mm == start_z_mm <= contact_z_mm')
    elif not (p['end_z_mm'] < p['start_z_mm'] <= setup['contact_z_mm']):
        raise ValueError('require end_z_mm < start_z_mm <= contact_z_mm')
    if setup['wait_z_mm'] <= setup['contact_z_mm']:
        raise ValueError('wait_z_mm must be above contact_z_mm for airborne baseline and return')
    if not (p['entry_contact_z_mm'] < p['slow_below_z_mm'] <= setup['wait_z_mm']):
        raise ValueError('require entry contact < slow threshold <= wait height')
    if not (p['end_z_mm'] <= p['entry_contact_z_mm'] <= setup['contact_z_mm']):
        raise ValueError('entry contact height outside depth range')
    if not (0 < p['writing_tilt_deg'] < p['entry_tilt_deg'] <= max_entry_tilt_deg):
        raise ValueError(f'require 0 < writing tilt < entry tilt <= {max_entry_tilt_deg:g} degrees')
    if p['speed_mm_s'] > setup['max_xy_speed_mm_s'] or p['xy_accel_mm_s2'] > setup['max_accel_mm_s2']:
        raise ValueError('XY speed/acceleration exceeds installation limit')
    for key in ('rotate_s', 'air_rotate_s', 'load_s', 'airborne_settle_s', 'post_lift_hold_s'):
        _ticks(p[key])

    unit = np.asarray(DIRECTIONS[p['direction']])
    heading = math.atan2(unit[1], unit[0])
    writing = tangent_rpy(heading, p['writing_tilt_deg'])
    entry = tangent_rpy(heading, p['entry_tilt_deg'])
    origin = np.array([setup['origin_x_mm'], setup['origin_y_mm']])/1000
    start = np.r_[origin, setup['wait_z_mm']/1000, setup['vertical_rpy_rad']]
    poses, phases, segments = [start.copy()], ['wait'], []

    def append(values, name, kind='preparation', **meta):
        begin = len(poses)
        poses.extend(values)
        phases.extend([name]*len(values))
        segments.append(dict(id=name, kind=kind, start_tick=begin, end_tick=len(poses),
                             start_t_s=begin*DT, end_t_s=len(poses)*DT, **meta))

    def move(target, name, minimum_s=DT, z_speed=None):
        old = np.asarray(poses[-1])
        delta_mm = (target[:3]-old[:3])*1000
        xyz_distance = float(np.linalg.norm(delta_mm))
        angle = float(np.linalg.norm(np.rad2deg(target[3:]-old[3:])))
        # Quintic bounds: peak velocity 1.875*span/T, acceleration < 5.774*span/T².
        speed = min(p['transfer_speed_mm_s'], setup['return_speed_mm_s'], setup['max_xy_speed_mm_s'])
        z_speed = min(p['slow_z_speed_mm_s'] if z_speed is None else z_speed,
                      setup['max_z_speed_mm_s'])
        duration = max(minimum_s, 1.875*np.linalg.norm(delta_mm[:2])/speed,
                       1.875*abs(delta_mm[2])/z_speed,
                       math.sqrt(5.774*xyz_distance/min(p['transit_accel_mm_s2'], setup['max_accel_mm_s2'])),
                       1.875*angle/p['angular_speed_deg_s'],
                       math.sqrt(5.774*angle/p['angular_accel_deg_s2']))
        if name in {'rotate_air', 'rotate_contact'}:
            # Preserve the requested experimental rotation timing. An infeasible
            # duration is rejected by the full trajectory check, not stretched.
            duration = minimum_s
        count = _ticks(math.ceil(duration/DT)*DT)
        append(old+(target-old)*_ease(np.arange(1, count+1)/count)[:, None], name)

    baseline_pose = start.copy()
    baseline_pose[3:] = writing
    move(baseline_pose, 'orient_for_baseline', p['air_rotate_s'])
    append(np.tile(baseline_pose, (_ticks(p['airborne_settle_s']), 1)),
           'baseline_settle', 'airborne')
    baseline_index = len(poses)-1
    # The existing engine stops Servo and establishes a fresh stationary baseline here.
    offset_pose = baseline_pose.copy()
    offset_pose[:2] += unit*p['entry_reverse_mm']/1000
    move(offset_pose, 'entry_offset_high')
    tilted = offset_pose.copy()
    tilted[3:] = entry
    move(tilted, 'rotate_air', p['air_rotate_s'])
    tilted[2] = p['slow_below_z_mm']/1000
    move(tilted, 'lower_fast', z_speed=p['fast_z_speed_mm_s'])
    tilted[2] = p['entry_contact_z_mm']/1000
    move(tilted, 'lower_slow')
    contact = tilted.copy()
    contact[:2], contact[3:] = origin, writing
    move(contact, 'rotate_contact', p['rotate_s'])
    workpoint = contact.copy()
    workpoint[2] = p['start_z_mm']/1000
    if not np.allclose(workpoint, contact, atol=1e-12, rtol=0):
        move(workpoint, 'load_start', p['load_s'])

    law = time_law(p['travel_mm'], p['speed_mm_s'], p['xy_accel_mm_s2'], DT)
    count = math.ceil(law['duration_s']/DT-1e-9)
    local_t = np.arange(1, count+1)*DT
    distance_mm = np.interp(local_t, law['t_s'], law['distance_mm'])
    line = np.tile(workpoint, (count, 1))
    line[:, :2] = origin+distance_mm[:, None]*unit/1000
    progress = np.clip(2*distance_mm/p['travel_mm']-1, 0, 1)
    line[:, 2] = (p['start_z_mm']+(p['end_z_mm']-p['start_z_mm'])*_ease(progress))/1000
    split = int(np.searchsorted(distance_mm, p['travel_mm']/2, side='right'))
    if split == 0 or split == count:
        raise ValueError('line too short to sample both halves at 20 ms')
    if hold:
        append(line, 'straight_hold', 'straight')
    else:
        append(line[:split], 'straight_hold', 'straight')
        append(line[split:], 'sweep_down', 'sweep',
               from_depth_mm=setup['contact_z_mm']-p['start_z_mm'],
               depth_mm=setup['contact_z_mm']-p['end_z_mm'])
    lifted = line[-1].copy()
    lifted[2] = setup['wait_z_mm']/1000
    move(lifted, 'lift', z_speed=p['fast_z_speed_mm_s'])
    append(np.tile(lifted, (_ticks(p['post_lift_hold_s']), 1)), 'post_lift_hold', 'airborne')
    if p['return_to_origin']:
        return_pose = baseline_pose.copy()
        move(return_pose, 'return_high')
        move(start, 'restore_wait_orientation', p['air_rotate_s'])
    append(np.tile(poses[-1], (10, 1)), 'hold', 'airborne')
    poses = np.asarray(poses)
    metrics = _check_trajectory(poses, setup, p)
    nominal_depth = np.maximum(setup['contact_z_mm']/1000-poses[:, 2], 0.)
    s = np.clip(((poses[:, :2]-origin) @ unit)/(p['travel_mm']/1000), 0, 1)
    ref = np.full(len(poses), np.nan)
    spec = dict(version=1, name='four_direction_sweep', run_label=p['direction'],
                path={'kind': 'four_direction_sweep', 'axis': p['direction']},
                control={'enabled': False, 'mode': 'identification'}, identification=p,
                timeline_policy='sequential_20ms', wetting='manual_before_run',
                baseline_pose='initial wait, then airborne directional writing pose',
                baseline_window_policy='latest complete baseline_window_s, including boundary sample',
                baseline_writing_rpy_rad=writing.tolist(), signal='filtered_dBxy_norm_uT',
                magnetic_target=None,
                split_semantics='constant Z over full travel' if hold else 'half of XY arc length',
                depth_semantics='nominal positive-down command depth; not bristle indentation')
    derived = StrokePlan([Stroke(s=s, xy=poses[:, :2], g_press=ref, z_ff=nominal_depth)], meta={
        'artifact_role': 'derived_identification_timeline', 'magnetic_target': None,
        'depth_source': 'prescribed excitation, no calibration lookup',
        'stroke_durations_s': [(len(poses)-1)*DT]})
    return dict(plan=derived, t_s=np.arange(len(poses))*DT, s=s, phase=np.asarray(phases),
                pose_m_rad=poses, g_ref_uT=ref, depth_ff_m=nominal_depth,
                segments=segments, spec_snapshot=spec, setup_snapshot=setup,
                motion_metrics=metrics, slide_duration_s=count*DT,
                automatic_rebaseline_after_indices=[baseline_index],
                automatic_rebaseline_next_visits=[1])


class FourDirectionSweepEngine(StrokePlanExperimentEngine):
    def _record_new_sensor(self):
        # Record every observation first. Only the candidate baseline window is
        # bounded: one startup/transit transient must not poison every retry.
        super()._record_new_sensor()
        if self.state in {'BASELINE', 'REBASELINE'} and self._baseline_rows:
            times = [row['host_rx_ns'] for row in self._baseline_rows]
            cutoff = times[-1] - round(self._setup['baseline_window_s']*1e9)
            # Keep the closest sample at/before cutoff so sampled data spans
            # the FULL window; using >= cutoff can make every window too short.
            first = max(0, bisect_right(times, cutoff)-1)
            if first:
                del self._baseline_rows[:first]

    def prepare_sweep(self, profile, setup):
        if self.state not in {'UNPREPARED', 'READY'}:
            raise RuntimeError('cannot prepare during a run')
        self._compiled = compile_sweep(profile, setup)
        self._setup = copy.deepcopy(self._compiled['setup_snapshot'])
        self._spec = copy.deepcopy(self._compiled['spec_snapshot'])
        angles = self._compiled['pose_m_rad'][:, 3:]
        self._angle_min, self._angle_max = angles.min(axis=0), angles.max(axis=0)
        self.feedback = None
        self.state, self.phase, self.last_error = 'READY', 'ready', ''
        return self.snapshot()

    def _check_pose(self, pose):
        super()._check_pose(pose)
        if not np.isfinite(pose).all():
            raise RuntimeError('workspace_limit')
        if self._setup['contact_z_mm']-pose[2]*1000 > self._setup['max_depth_mm']+1e-8:
            raise RuntimeError('depth_limit')
        # Compiler checks the whole path. Runtime restricts every sent orientation
        # to the compiled envelope, including common wait and directional poses.
        angles = np.asarray(pose[3:])
        if np.any(angles < self._angle_min-1e-9) or np.any(angles > self._angle_max+1e-9):
            raise RuntimeError('workspace_limit')
        if self._last_command_pose is not None:
            speed = np.linalg.norm(np.rad2deg(angles-np.asarray(self._last_command_pose[3:])))/DT
            if speed > self._spec['identification']['angular_speed_deg_s']+1e-6:
                raise RuntimeError('speed_limit')

    def fail(self, reason):
        if self.state == 'RUN' and ('source_disconnected' in str(reason) or reason == 'operator_stop'):
            self._begin_abort(reason)
        else:
            super().fail(reason)
