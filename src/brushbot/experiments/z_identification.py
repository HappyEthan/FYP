"""Direct-depth identification with a fixed-TCP rotational contact entry.

Only nominal command depth is prescribed; there is no magnetic target or
feedforward-table lookup. Compilation is pure and never connects to hardware.
"""
from __future__ import annotations

import copy
import math

import numpy as np

from brushbot.experiments.strokeplan_execution import StrokePlanExperimentEngine, runtime_settings
from brushbot.experiments.trajectory import time_law
from brushbot.strokeplan import Stroke, StrokePlan

DT = .02
DEPTH_DELTAS = {5.: .6, 7.5: .5, 10.: .4, 12.5: .3, 15.: .25}


def default_profile(depth_mm=7.5, *, order='press-first'):
    if isinstance(depth_mm, bool) or depth_mm not in DEPTH_DELTAS:
        raise ValueError('depth must be one of 5, 7.5, 10, 12.5, 15 mm')
    return dict(depth_mm=float(depth_mm), delta_mm=DEPTH_DELTAS[depth_mm],
                order=order, travel_mm=450., speed_mm_s=10., xy_accel_mm_s2=50.,
                entry_contact_z_mm=36., entry_ry_deg=30., rotate_s=3.,
                slide_settle_s=1., load_s=3., hold_s=4., transition_s=.4,
                post_lift_hold_s=2., depth_min_mm=4., depth_max_mm=16.,
                angular_speed_deg_s=10., angular_accel_deg_s2=20.)


def default_sweep_profile(mode='sweep-down'):
    if mode not in ('sweep-down', 'sweep-cycle'):
        raise ValueError('unknown sweep mode')
    p = default_profile()
    for key in ('depth_mm', 'delta_mm', 'order', 'load_s', 'hold_s', 'transition_s'):
        del p[key]
    p.update(mode=mode, slide_settle_s=3., depth_min_mm=4.,
             sweep_end_z_mm=24., sweep_s=30. if mode == 'sweep-down' else 15.,
             endpoint_hold_s=4. if mode == 'sweep-down' else 3.)
    return p


def _ease(u):
    return u**3 * (10 + u * (-15 + 6*u))


def _ticks(seconds):
    ticks = round(seconds / DT)
    if ticks < 1 or not math.isclose(ticks*DT, seconds, abs_tol=1e-9):
        raise ValueError('durations must be positive multiples of 20 ms')
    return ticks


def validate_profile(profile, setup):
    p = copy.deepcopy(profile)
    sweep = 'mode' in p
    template = default_sweep_profile(p['mode']) if sweep else default_profile()
    if set(p) != set(template):
        raise ValueError('identification profile fields differ from contract')
    if not sweep and p['order'] not in ('press-first', 'lift-first'):
        raise ValueError('unknown perturbation order')
    for key in p.keys() - {'order', 'mode'}:
        value = p[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(key + ' must be finite numeric')
        if value <= 0:
            raise ValueError(key + ' must be positive')
        p[key] = float(value)
    for key in [k for k in p if k.endswith('_s') and k in {
            'rotate_s', 'slide_settle_s', 'load_s', 'hold_s', 'transition_s',
            'post_lift_hold_s', 'sweep_s', 'endpoint_hold_s'}]:
        _ticks(p[key])
    if sweep:
        if not (p['depth_min_mm'] <= setup['contact_z_mm']-p['entry_contact_z_mm']
                < setup['contact_z_mm']-p['sweep_end_z_mm']
                <= p['depth_max_mm'] <= setup['max_depth_mm']):
            raise ValueError('sweep depth outside identification/installation bounds')
    elif not (p['depth_min_mm'] <= p['depth_mm']-p['delta_mm']
              < p['depth_mm']+p['delta_mm'] <= p['depth_max_mm'] <= setup['max_depth_mm']):
        raise ValueError('depth excitation outside identification/installation bounds')
    if not (setup['contact_z_mm']-p['depth_min_mm'] <= p['entry_contact_z_mm']
            < setup['contact_z_mm'] < setup['wait_z_mm']):
        raise ValueError('entry contact height must precede the deeper identification range')
    rpy = np.rad2deg(setup['vertical_rpy_rad'])
    if not np.allclose(rpy, [0, 15, 0], atol=.01, rtol=0):
        raise ValueError('identification requires fixed Rx0 Ry15 Rz0 writing orientation')
    if not (rpy[1] < p['entry_ry_deg'] <= 30.):
        raise ValueError('entry Ry must be above writing Ry and at most 30 degrees')
    if p['speed_mm_s'] > setup['max_xy_speed_mm_s'] or p['xy_accel_mm_s2'] > setup['max_accel_mm_s2']:
        raise ValueError('XY speed/acceleration exceeds installation limit')
    return p


def _check_trajectory(poses, setup, profile):
    mm = poses[:, :3]*1000
    if (not np.isfinite(poses).all() or
            np.any(mm < np.asarray(setup['workspace_min_mm'])-1e-8) or
            np.any(mm > np.asarray(setup['workspace_max_mm'])+1e-8)):
        raise ValueError('workspace limit')
    if np.max(setup['contact_z_mm']-mm[:, 2]) > setup['max_depth_mm']+1e-8:
        raise ValueError('depth limit')
    v = np.diff(np.vstack([poses[0], poses, poses[-1]]), axis=0)/DT
    a = np.diff(v, axis=0)/DT
    checks = [
        (np.max(np.linalg.norm(v[:, :2], axis=1))*1000, setup['max_xy_speed_mm_s'], 'XY speed'),
        (np.max(abs(v[:, 2]))*1000, setup['max_z_speed_mm_s'], 'Z speed'),
        (np.max(np.linalg.norm(v[:, :3], axis=1))*DT*1000, setup['max_step_mm'], 'step'),
        (np.max(np.linalg.norm(a[:, :3], axis=1))*1000, setup['max_accel_mm_s2'], 'acceleration'),
        (np.max(np.linalg.norm(np.rad2deg(v[:, 3:]), axis=1)), profile['angular_speed_deg_s'], 'angular speed'),
        (np.max(np.linalg.norm(np.rad2deg(a[:, 3:]), axis=1)), profile['angular_accel_deg_s2'], 'angular acceleration'),
    ]
    for value, bound, name in checks:
        if value > bound+1e-6:
            raise ValueError(name + ' limit; revise trajectory explicitly')
    return {name: float(value) for value, _, name in checks}


def compile_identification(profile, settings):
    setup = runtime_settings(settings)
    p = validate_profile(profile, setup)
    rpy = np.asarray(setup['vertical_rpy_rad'], float)
    start = np.r_[np.array([setup['origin_x_mm'], setup['origin_y_mm'], setup['wait_z_mm']])/1000, rpy]
    if setup['origin_x_mm']+p['travel_mm'] > setup['workspace_max_mm'][0]+1e-8:
        raise ValueError('workspace limit at line end')
    poses, phases, segments = [start.copy()], ['wait'], []

    def append(values, name, kind, **meta):
        begin = len(poses)
        poses.extend(values)
        phases.extend([name]*len(values))
        segments.append(dict(id=name, kind=kind, start_tick=begin, end_tick=len(poses),
                             start_t_s=begin*DT, end_t_s=len(poses)*DT, **meta))

    def transit(target, name, duration=None):
        old = np.asarray(poses[-1])
        target = np.asarray(target)
        if duration is None:
            distance = float(np.linalg.norm(target[:3]-old[:3]))*1000
            # Only the airborne, constant-Z return uses the installation return speed.
            speed = (min(setup['return_speed_mm_s'], setup['max_xy_speed_mm_s'])
                     if name == 'return_high' else min(10., setup['max_z_speed_mm_s'], setup['max_xy_speed_mm_s']))
            duration = max(DT, 1.875*distance/speed,
                           math.sqrt(5.774*distance/min(50., setup['max_accel_mm_s2'])))
            duration = math.ceil(duration/DT)*DT
        n = _ticks(duration)
        w = _ease(np.arange(1, n+1)/n)
        append(old+(target-old)*w[:, None], name, 'preparation')

    tilted = start.copy()
    tilted[4] = np.deg2rad(p['entry_ry_deg'])
    transit(tilted, 'rotate_air', p['rotate_s'])
    tilted[2] = p['entry_contact_z_mm']/1000
    transit(tilted, 'lower_tilted')
    contact = tilted.copy()
    contact[3:] = rpy
    transit(contact, 'rotate_contact', p['rotate_s'])

    law = time_law(p['travel_mm'], p['speed_mm_s'], p['xy_accel_mm_s2'], DT)
    n = math.ceil(law['duration_s']/DT-1e-9)
    local_t = np.arange(1, n+1)*DT
    x_mm = np.interp(local_t, law['t_s'], law['distance_mm'])
    line = np.tile(contact, (n, 1))
    line[:, 0] += x_mm/1000
    local_phase = np.full(n, 'slide_finish', dtype='U40')
    if 'mode' in p:
        entry_depth = setup['contact_z_mm']-p['entry_contact_z_mm']
        end_depth = setup['contact_z_mm']-p['sweep_end_z_mm']
        settle_n = _ticks(p['slide_settle_s'])
        sweep_n, hold_n = _ticks(p['sweep_s']), _ticks(p['endpoint_hold_s'])
        cycle = p['mode'] == 'sweep-cycle'
        required = settle_n+sweep_n+hold_n+(sweep_n if cycle else 0)
        if (p['slide_settle_s'] < law['t_acc_s'] or
                required*DT > law['duration_s']-law['t_acc_s']-.5):
            raise ValueError('sweep sequence does not fit line cruise')
        depth = np.full(n, entry_depth if cycle else end_depth)
        depth[:settle_n] = entry_depth
        local_phase[:settle_n] = 'slide_start'
        definitions = {}
        cursor = settle_n
        for name, begin, end, count, kind in [
                ('sweep_down', entry_depth, end_depth, sweep_n, 'sweep'),
                ('sweep_bottom_hold', end_depth, end_depth, hold_n, 'sweep_hold'),
                *([('sweep_up', end_depth, entry_depth, sweep_n, 'sweep')] if cycle else [])]:
            depth[cursor:cursor+count] = begin+(end-begin)*_ease(np.arange(1, count+1)/count)
            local_phase[cursor:cursor+count] = name
            definitions[name] = dict(kind=kind, from_depth_mm=float(begin), depth_mm=float(end))
            cursor += count
    else:
        depth0 = p['depth_mm']
        entry_depth = setup['contact_z_mm']-p['entry_contact_z_mm']
        depth = np.full(n, depth0)
        settle_n, load_n = _ticks(p['slide_settle_s']), _ticks(p['load_s'])
        if p['slide_settle_s'] < law['t_acc_s']:
            raise ValueError('slide preparation must reach cruise before depth loading')
        depth[:settle_n] = entry_depth
        local_phase[:settle_n] = 'slide_start'
        depth[settle_n:settle_n+load_n] = entry_depth+(depth0-entry_depth)*_ease(np.arange(1, load_n+1)/load_n)
        local_phase[settle_n:settle_n+load_n] = 'load_workpoint'
        sign = 1 if p['order'] == 'press-first' else -1
        offsets = np.array([0, 1, 0, -1, 0, .5, 0, -.5, 0])*sign*p['delta_mm']
        cursor = settle_n+load_n
        required = cursor+9*_ticks(p['hold_s'])+8*_ticks(p['transition_s'])
        if required*DT > law['duration_s']-law['t_acc_s']-.5:
            raise ValueError('identification sequence does not fit line cruise; lengthen line or split runs')
        definitions = {}
        for i, offset in enumerate(offsets):
            if i:
                ticks = _ticks(p['transition_s'])
                previous = depth0+offsets[i-1]
                depth[cursor:cursor+ticks] = previous+(offset-offsets[i-1])*_ease(np.arange(1, ticks+1)/ticks)
                name = f'id_ramp_{i:02d}'
                local_phase[cursor:cursor+ticks] = name
                definitions[name] = dict(kind='transition', from_depth_mm=float(previous),
                                         depth_mm=float(depth0+offset), plateau_index=i)
                cursor += ticks
            ticks = _ticks(p['hold_s'])
            depth[cursor:cursor+ticks] = depth0+offset
            name = f'id_hold_{i:02d}'
            local_phase[cursor:cursor+ticks] = name
            definitions[name] = dict(kind='plateau', depth_mm=float(depth0+offset),
                                     offset_mm=float(offset), plateau_index=i)
            cursor += ticks
    line[:, 2] = (setup['contact_z_mm']-depth)/1000
    boundaries = np.r_[0, np.flatnonzero(local_phase[1:] != local_phase[:-1])+1, n]
    for lo, hi in zip(boundaries[:-1], boundaries[1:]):
        name = str(local_phase[lo])
        meta = definitions.get(name, {'kind': 'preparation'})
        append(line[lo:hi], name, **meta)
    lifted = line[-1].copy()
    lifted[2] = setup['wait_z_mm']/1000
    transit(lifted, 'lift')
    append(np.tile(lifted, (_ticks(p['post_lift_hold_s']), 1)), 'post_lift_hold', 'airborne')
    transit(start, 'return_high')
    append(np.tile(start, (10, 1)), 'hold', 'airborne')
    poses = np.asarray(poses)
    metrics = _check_trajectory(poses, setup, p)
    phase = np.asarray(phases)
    nominal_depth = np.maximum(setup['contact_z_mm']/1000-poses[:, 2], 0.)
    s = np.clip((poses[:, 0]-start[0])/(p['travel_mm']/1000), 0, 1)
    ref = np.full(len(poses), np.nan)
    spec = dict(version=1, name='z_identification', run_label='z_identification',
                path={'kind': 'z_identification', 'axis': '+x'},
                control={'enabled': False, 'mode': 'identification'},
                identification=p, baseline_pose='airborne_Ry15', wetting='manual_before_run',
                signal='filtered_dBxy_norm_uT', magnetic_target=None,
                depth_semantics='nominal positive-down command depth; not bristle indentation')
    derived = StrokePlan([Stroke(s=s, xy=poses[:, :2], g_press=ref, z_ff=nominal_depth)], meta={
        'artifact_role': 'derived_identification_timeline', 'magnetic_target': None,
        'depth_source': 'prescribed excitation, no calibration lookup',
        'stroke_durations_s': [(len(poses)-1)*DT]})
    return dict(plan=derived, t_s=np.arange(len(poses))*DT, s=s, phase=phase,
                pose_m_rad=poses, g_ref_uT=ref, depth_ff_m=nominal_depth,
                segments=segments, spec_snapshot=spec, setup_snapshot=setup,
                motion_metrics=metrics, slide_duration_s=float(n*DT))


class IdentificationEngine(StrokePlanExperimentEngine):
    """Reuse baseline, recording and stop handling with direct-depth preparation."""

    def prepare_identification(self, profile, setup):
        if self.state not in {'UNPREPARED', 'READY'}:
            raise RuntimeError('cannot prepare during a run')
        self._compiled = compile_identification(profile, setup)
        self._setup = copy.deepcopy(self._compiled['setup_snapshot'])
        self._spec = copy.deepcopy(self._compiled['spec_snapshot'])
        self.feedback = None
        self.state, self.phase, self.last_error = 'READY', 'ready', ''
        return self.snapshot()

    def _check_pose(self, pose):
        super()._check_pose(pose)
        if self._setup['contact_z_mm']-pose[2]*1000 > self._setup['max_depth_mm']+1e-8:
            raise RuntimeError('depth_limit')
        angles = np.rad2deg(pose[3:])
        if (not np.isfinite(pose).all() or abs(angles[0]) > .01 or abs(angles[2]) > .01
                or angles[1] < 14.99 or angles[1] > self._spec['identification']['entry_ry_deg']+.01):
            raise RuntimeError('workspace_limit')
        if self._last_command_pose is not None:
            angular_speed = np.linalg.norm(np.rad2deg(np.asarray(pose[3:])-self._last_command_pose[3:]))/DT
            if angular_speed > self._spec['identification']['angular_speed_deg_s']+1e-6:
                raise RuntimeError('speed_limit')

    def fail(self, reason):
        # The shared driver handles external source failure outside engine.step().
        if self.state == 'RUN' and 'source_disconnected' in str(reason):
            self._begin_abort('source_disconnected')
        else:
            super().fail(reason)
