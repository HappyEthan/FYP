"""Continuous multi-stroke execution with tangent-aligned tilt and split descent."""
from __future__ import annotations

import math
import numpy as np

from brushbot.feedforward import lookup_depth_m, validate_context
from brushbot.strokeplan_compile import sample_stroke

DT = .02
CHARACTER_ENTRY = dict(mode='directional_character', assume_pose_invariant=True,
    entry_contact_z_mm=36., slow_below_z_mm=50., transfer_z_mm=130.,
    entry_tilt_deg=30., writing_tilt_deg=15., entry_reverse_mm=0., air_rotate_s=1.5,
    rotate_s=3., load_s=3., transfer_speed_mm_s=80., fast_z_speed_mm_s=60.,
    slow_z_speed_mm_s=15., transit_accel_mm_s2=100.,
    angular_speed_deg_s=20., angular_accel_deg_s2=40.)


def tangent_rpy(heading_rad, tilt_deg):
    """Base RPY for Rz(heading) Ry(tilt) Rz(-heading), without a full axial turn."""
    h = np.asarray(heading_rad, float)
    c, s = np.cos(h), np.sin(h)
    ca, sa = np.cos(np.deg2rad(tilt_deg)), np.sin(np.deg2rad(tilt_deg))
    return np.stack([np.arctan2(-sa*s, np.full_like(h, ca)),
                     np.arcsin(sa*c), np.arctan2((ca-1)*c*s, ca*c*c+s*s)], axis=-1)


def orientation_heading(rpy):
    r, p, y = np.asarray(rpy, float)
    # XY projection of the rotated local +Z axis.
    return math.atan2(np.sin(y)*np.sin(p)*np.cos(r)-np.cos(y)*np.sin(r),
                      np.cos(y)*np.sin(p)*np.cos(r)+np.sin(y)*np.sin(r))


def compile_character_target(plan, table, setup, profile):
    from brushbot.experiments.z_identification import _check_trajectory, _ease, _ticks
    plan.validate()
    validate_context(plan, table, setup)
    p = dict(profile)
    entry_order = p.pop('entry_order', 'rotate_then_load')
    if not isinstance(entry_order, str) or entry_order not in {
            'rotate_then_load', 'load_then_rotate'}:
        raise ValueError('invalid entry_order: expected rotate_then_load or load_then_rotate')
    # Existing profiles keep their original stationary rotation.
    p.setdefault('entry_reverse_mm', 0.)
    if set(p) != set(CHARACTER_ENTRY) or p['mode'] != 'directional_character':
        raise ValueError('directional character profile fields differ from contract')
    if p['assume_pose_invariant'] is not True:
        raise ValueError('directional execution requires explicit pose-invariant table assumption')
    for key, value in p.items():
        if key in {'mode','assume_pose_invariant'}:
            continue
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
            raise ValueError('character requires finite numeric '+key)
        if value < 0 or (value == 0 and key != 'entry_reverse_mm'):
            raise ValueError('character requires positive values (entry_reverse_mm may be zero): '+key)
    if plan.meta['coordinate_frame'] != 'paper':
        raise ValueError('directional character requires paper coordinates')
    if not (p['entry_contact_z_mm'] < p['slow_below_z_mm'] <= p['transfer_z_mm'] <= setup['wait_z_mm']):
        raise ValueError('invalid descent/clearance heights')
    if not (0 <= setup['contact_z_mm']-p['entry_contact_z_mm'] < setup['max_depth_mm']):
        raise ValueError('entry contact depth outside limits')
    if not (0 < p['writing_tilt_deg'] < p['entry_tilt_deg'] <= 30.):
        raise ValueError('directional tilt must stay within 30 degrees')
    if p['transit_accel_mm_s2'] > setup['max_accel_mm_s2']:
        raise ValueError('transit acceleration exceeds installation limit')
    for key in ['air_rotate_s','rotate_s','load_s']:
        _ticks(p[key])
    rpy = np.asarray(setup['vertical_rpy_rad'],float)
    start = np.r_[np.array([setup['origin_x_mm'],setup['origin_y_mm'],setup['wait_z_mm']])/1000,rpy]
    poses, phases = [start.copy()], ['wait']

    def append(values, phase):
        poses.extend(values)
        phases.extend([phase]*len(values))

    def move(target, phase, speed, minimum_s=0.):
        old = np.asarray(poses[-1]); delta = target-old
        distance = np.linalg.norm(delta[:3])*1000
        cap = speed
        if np.linalg.norm(delta[:2]) > 1e-12:
            cap = min(cap,setup['max_xy_speed_mm_s'])
        if abs(delta[2]) > 1e-12:
            cap = min(cap,setup['max_z_speed_mm_s'])
        angle = np.linalg.norm(np.rad2deg(delta[3:]))
        seconds = max(DT,minimum_s,1.875*distance/cap,
                      math.sqrt(5.774*distance/p['transit_accel_mm_s2']),
                      1.875*angle/p['angular_speed_deg_s'],
                      math.sqrt(5.774*angle/p['angular_accel_deg_s2']))
        n = int(math.ceil(seconds/DT-1e-9))
        append(old+delta*_ease(np.arange(1,n+1)/n)[:,None],phase)

    for i, st in enumerate(plan.strokes):
        if st.orientation is None:
            raise ValueError('directional character requires explicit target orientations')
        orient = np.asarray(st.orientation,float)
        if not np.allclose(np.cos(orient[:,0])*np.cos(orient[:,1]),
                           np.cos(np.deg2rad(p['writing_tilt_deg'])),atol=2e-4,rtol=0):
            raise ValueError('target tilt differs from writing tilt')
        if (np.linalg.norm(np.diff(st.xy,axis=0),axis=1)/np.diff(st.t)).max()*1000 > table['speed_mm_s']+1e-6:
            raise ValueError('target speed outside table support')
        if (np.linalg.norm(np.diff(orient,axis=0),axis=1)/np.diff(st.t)).max() > np.deg2rad(p['angular_speed_deg_s'])+1e-8:
            raise ValueError('target angular speed limit')
        all_depth = lookup_depth_m(table,st.g_target)
        if max(all_depth)*1000 > setup['max_depth_mm']:
            raise ValueError('target depth limit')
        ticks,xy,_,depth = sample_stroke(st,table,DT)
        if not math.isclose(ticks[-1],st.t[-1],abs_tol=1e-9):
            raise ValueError('target duration must be a multiple of 20 ms')
        xy = xy+start[:2]
        sampled_rpy = np.column_stack([np.interp(ticks,st.t,orient[:,j]) for j in range(3)])
        heading = orientation_heading(orient[0])
        entry_offset = p['entry_reverse_mm']/1000*np.array([math.cos(heading),math.sin(heading)])
        # Start ahead of the target, then reverse during contact rotation so
        # writing begins at the unchanged target XY without a recovery slide.
        high = np.r_[xy[0]+entry_offset,p['transfer_z_mm']/1000,np.asarray(poses[-1])[3:]]
        # Each preceding lift already reaches this clearance; never return XY to origin here.
        move(high,f'high_transfer_{i:02}',p['transfer_speed_mm_s'])
        tilted = high.copy()
        tilted[3:] = tangent_rpy(heading,p['entry_tilt_deg'])
        move(tilted,f'rotate_air_{i:02}',p['transfer_speed_mm_s'],p['air_rotate_s'])
        above = tilted.copy(); above[2] = p['slow_below_z_mm']/1000
        move(above,f'lower_fast_{i:02}',p['fast_z_speed_mm_s'])
        contact = above.copy(); contact[2] = p['entry_contact_z_mm']/1000
        move(contact,f'lower_slow_{i:02}',p['slow_z_speed_mm_s'])
        loaded_z = setup['contact_z_mm']/1000-depth[0]
        if loaded_z > contact[2]+1e-9:
            raise ValueError('initial target must be deeper than rotational contact')
        if entry_order == 'load_then_rotate':
            # The workpoint height comes from the writing-pose table. This
            # ordering does not claim the entry tilt produces that response.
            loaded = contact.copy(); loaded[2] = loaded_z
            move(loaded,f'load_workpoint_{i:02}',p['slow_z_speed_mm_s'],p['load_s'])
            loaded[:2] = xy[0]
            loaded[3:] = sampled_rpy[0]
            move(loaded,f'rotate_contact_{i:02}',p['slow_z_speed_mm_s'],p['rotate_s'])
        else:
            contact[:2] = xy[0]
            contact[3:] = sampled_rpy[0]
            move(contact,f'rotate_contact_{i:02}',p['slow_z_speed_mm_s'],p['rotate_s'])
            loaded = contact.copy(); loaded[2] = loaded_z
            move(loaded,f'load_workpoint_{i:02}',p['slow_z_speed_mm_s'],p['load_s'])
        measurement = np.column_stack([xy,setup['contact_z_mm']/1000-depth,sampled_rpy])
        append(measurement,f'measure_{i:02}')
        lifted = measurement[-1].copy(); lifted[2] = p['transfer_z_mm']/1000
        move(lifted,f'lift_{i:02}',p['fast_z_speed_mm_s'])
    move(start,'return_high',min(p['transfer_speed_mm_s'],setup['return_speed_mm_s']))
    poses = np.asarray(poses)
    _check_trajectory(poses,setup,p)
    return poses,phases
