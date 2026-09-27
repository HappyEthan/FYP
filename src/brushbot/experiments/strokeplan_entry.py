"""Rotational contact followed by a +X lead-in or stationary loading."""
from __future__ import annotations

import math
import numpy as np

from brushbot.feedforward import lookup_depth_m, validate_context
from brushbot.strokeplan_compile import compile_target_plan, sample_stroke
from brushbot.experiments.trajectory import time_law

DT = .02
DEFAULT_ENTRY = dict(entry_contact_z_mm=36., entry_ry_deg=30., rotate_s=3.,
    slide_settle_s=1., load_s=3., travel_mm=450., speed_mm_s=10.,
    xy_accel_mm_s2=50., post_lift_hold_s=2.,
    angular_speed_deg_s=10., angular_accel_deg_s2=20.)
STATIONARY_ENTRY = dict(mode='stationary', assume_direction_invariant=False,
    entry_contact_z_mm=36., entry_ry_deg=30., rotate_s=3., load_s=3.,
    post_lift_hold_s=2., angular_speed_deg_s=10., angular_accel_deg_s2=20.,
    transit_speed_mm_s=10., air_rotate_s=3.)


def compile_rotational_target(plan, table, setup, profile):
    # Reuse the already exercised identification motion law and limit checker.
    # Import lazily: identification also uses the recorded StrokePlan engine.
    from brushbot.experiments.z_identification import _check_trajectory, _ease, _ticks

    plan.validate()
    validate_context(plan, table, setup)
    p = dict(profile)
    stationary = p.get('mode') == 'stationary'
    if stationary:
        # Older stationary profiles retain their original movement timing.
        p.setdefault('transit_speed_mm_s', 10.)
        p.setdefault('air_rotate_s', p.get('rotate_s'))
    if set(p) != set(STATIONARY_ENTRY if stationary else DEFAULT_ENTRY):
        raise ValueError('rotational entry profile fields differ from contract')
    if stationary and type(p['assume_direction_invariant']) is not bool:
        raise ValueError('assume_direction_invariant must be boolean')
    for key, value in p.items():
        if key in {'mode', 'assume_direction_invariant'}:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError('entry requires finite positive '+key)
    for key in ('rotate_s', 'load_s', 'post_lift_hold_s') + (() if stationary else ('slide_settle_s',)):
        _ticks(p[key])
    if stationary:
        _ticks(p['air_rotate_s'])
    if len(plan.strokes) != 1 or plan.meta['coordinate_frame'] != 'paper':
        raise ValueError('rotational entry requires one paper-frame stroke')
    rpy = np.asarray(setup['vertical_rpy_rad'], float)
    if not np.allclose(np.rad2deg(rpy), [0, 15, 0], atol=.01, rtol=0):
        raise ValueError('rotational entry requires Rx0 Ry15 Rz0')
    if not 15 < p['entry_ry_deg'] <= 30:
        raise ValueError('entry Ry must be between writing Ry and 30 degrees')
    if not 0 <= setup['contact_z_mm']-p['entry_contact_z_mm'] < setup['max_depth_mm']:
        raise ValueError('entry contact height outside depth range')
    if p['entry_contact_z_mm'] >= setup['wait_z_mm']:
        raise ValueError('entry contact height must be below wait height')
    if not stationary and (p['speed_mm_s'] != table['speed_mm_s'] or p['speed_mm_s'] > setup['max_xy_speed_mm_s']):
        raise ValueError('entry speed outside table/installation support')
    if not stationary and p['xy_accel_mm_s2'] > setup['max_accel_mm_s2']:
        raise ValueError('entry acceleration exceeds installation limit')
    stroke = plan.strokes[0]
    lookup_depth_m(table, stroke.g_target)  # Check every support point before resampling.
    if stroke.orientation is not None and not np.allclose(stroke.orientation, rpy, atol=1e-8, rtol=0):
        raise ValueError('target orientation differs from writing orientation')
    ticks, xy, _, depth = sample_stroke(stroke, table, DT)
    if not math.isclose(ticks[-1], stroke.t[-1], abs_tol=1e-9):
        raise ValueError('rotational target duration must be a multiple of 20 ms')
    if np.any(depth*1000 > setup['max_depth_mm']):
        raise ValueError('target depth limit')
    if stationary:
        # Retain all original support-point, table, pose and translation guards.
        compile_target_plan(plan, table, setup,
                            assume_direction_invariant=p['assume_direction_invariant'])

    start = np.r_[np.array([setup['origin_x_mm'],setup['origin_y_mm'],setup['wait_z_mm']])/1000, rpy]
    poses, phases = [start.copy()], ['wait']

    def append(values, phase):
        poses.extend(values)
        phases.extend([phase]*len(values))

    def transit(target, phase, seconds=None):
        old = np.asarray(poses[-1])
        if seconds is None:
            distance = np.linalg.norm(target[:3]-old[:3])*1000
            transit_speed = p['transit_speed_mm_s'] if stationary else 10.
            speed = (min(setup['return_speed_mm_s'],setup['max_xy_speed_mm_s'])
                     if phase == 'return_high' else min(transit_speed,setup['max_z_speed_mm_s'],setup['max_xy_speed_mm_s']))
            seconds = max(DT,1.875*distance/speed,
                          math.sqrt(5.774*distance/min(50.,setup['max_accel_mm_s2'])))
            seconds = math.ceil(seconds/DT)*DT
        n = _ticks(seconds)
        append(old+(target-old)*_ease(np.arange(1,n+1)/n)[:,None],phase)

    contact_start = start.copy()
    if stationary:
        contact_start[:2] += xy[0]
        if not np.allclose(contact_start[:2], start[:2], atol=1e-12, rtol=0):
            transit(contact_start, 'high_transfer_00')
    tilted = contact_start.copy(); tilted[4] = np.deg2rad(p['entry_ry_deg'])
    transit(tilted,'rotate_air',p['air_rotate_s'] if stationary else p['rotate_s'])
    tilted[2] = p['entry_contact_z_mm']/1000
    transit(tilted,'lower_tilted')
    contact = tilted.copy(); contact[3:] = rpy
    transit(contact,'rotate_contact',p['rotate_s'])

    if stationary:
        initial = contact.copy()
        initial[2] = setup['contact_z_mm']/1000-depth[0]
        if initial[2] > contact[2]+1e-9:
            raise ValueError('initial target must be deeper than rotational contact')
        transit(initial, 'load_workpoint', p['load_s'])
        measurement = np.tile(initial, (len(ticks), 1))
        measurement[:, :2] = xy + start[:2]
        measurement[:, 2] = setup['contact_z_mm']/1000-depth
        append(measurement, 'measure_00')
        lifted = measurement[-1].copy(); lifted[2] = start[2]
        transit(lifted, 'lift')
        append(np.tile(lifted, (_ticks(p['post_lift_hold_s']), 1)), 'post_lift_hold')
        transit(start, 'return_high')
        poses = np.asarray(poses)
        _check_trajectory(poses, setup, p)
        return poses, phases

    law = time_law(p['travel_mm'],p['speed_mm_s'],p['xy_accel_mm_s2'],DT)
    if p['slide_settle_s'] < law['t_acc_s']:
        raise ValueError('settle must reach cruise before depth loading')
    n = math.ceil(law['duration_s']/DT-1e-9)
    local_t = np.arange(1,n+1)*DT
    line = np.tile(contact,(n,1))
    line[:,0] += np.interp(local_t,law['t_s'],law['distance_mm'])/1000
    measure_start_s = p['slide_settle_s']+p['load_s']
    lo = _ticks(measure_start_s)-1
    hi = lo+len(ticks)
    if measure_start_s+ticks[-1] > law['duration_s']-law['t_acc_s']-.5:
        raise ValueError('target does not fit line cruise')
    expected_xy = line[lo:hi,:2]-start[:2]
    # Validate both original and sampled XY: do not silently shift the target.
    original_x = np.interp(measure_start_s+stroke.t,law['t_s'],law['distance_mm'])/1000
    if (not np.allclose(xy,expected_xy,atol=1e-9,rtol=0)
            or not np.allclose(stroke.xy[:,0],original_x,atol=1e-9,rtol=0)
            or not np.allclose(stroke.xy[:,1],0.,atol=1e-9,rtol=0)):
        raise ValueError('target XY must match continuous entry lead-in and cruise')
    line[:,2] = setup['contact_z_mm']/1000-depth[-1]
    initial_z = setup['contact_z_mm']/1000-depth[0]
    if initial_z > contact[2]+1e-9:
        raise ValueError('initial target must be deeper than rotational contact')
    w = _ease(np.clip((local_t[:lo]-p['slide_settle_s'])/p['load_s'],0,1))
    line[:lo,2] = contact[2]+(initial_z-contact[2])*w
    line[lo:hi,2] = setup['contact_z_mm']/1000-depth
    settle = _ticks(p['slide_settle_s'])
    append(line[:settle],'slide_start')
    append(line[settle:lo],'load_workpoint')
    append(line[lo:hi],'measure_00')
    append(line[hi:],'slide_finish')
    lifted = line[-1].copy(); lifted[2] = start[2]
    transit(lifted,'lift')
    append(np.tile(lifted,(_ticks(p['post_lift_hold_s']),1)),'post_lift_hold')
    transit(start,'return_high')
    poses = np.asarray(poses)
    _check_trajectory(poses,setup,p)
    return poses, phases
