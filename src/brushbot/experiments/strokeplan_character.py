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
    stroke_profiles=p.pop('stroke_profiles',None)
    if stroke_profiles is not None:
        allowed={'writing_tilt_deg','segment_magnetic_targets','writing_height','node_angles','entry_reverse_mm'}
        if (not isinstance(stroke_profiles,list) or len(stroke_profiles)!=len(plan.strokes)
                or any(not isinstance(row,dict) or set(row)-allowed for row in stroke_profiles)
                or any(key in p for key in ('segment_magnetic_targets','writing_height','tail_exit'))):
            raise ValueError('invalid stroke_profiles: one contact profile per stroke required')
        for row in stroke_profiles:
            if 'node_angles' in row and type(row['node_angles']) is not bool:raise ValueError('node_angles must be boolean')
    tail_exit = p.pop('tail_exit', None)
    segment_targets=p.pop('segment_magnetic_targets',None)
    if segment_targets is not None:
        from brushbot.experiments.strokeplan_segment_targets import validate_segment_targets
        validate_segment_targets(segment_targets,table)
        if len(plan.strokes)!=1 or tail_exit is not None:
            raise ValueError('segment_magnetic_targets requires one stroke and no tail_exit')
    writing_height = p.pop('writing_height', None)
    height_knots = None
    if writing_height is not None:
        if len(plan.strokes)!=1 or not isinstance(writing_height,dict) or set(writing_height)!={'knots_s_mm'}:
            raise ValueError('writing_height requires one stroke and knots_s_mm')
        height_knots=np.asarray(writing_height['knots_s_mm'],dtype=float)
        if (height_knots.ndim!=2 or height_knots.shape[1]!=2 or len(height_knots)<2
                or not np.isfinite(height_knots).all() or height_knots[0,0]!=0 or height_knots[-1,0]!=1
                or np.any(np.diff(height_knots[:,0])<=0) or np.any(height_knots[:,1]<0)
                or height_knots[0,1]!=0 or tail_exit is not None):
            raise ValueError('writing_height requires increasing progress 0..1, nonnegative offsets, zero initial offset and no tail_exit')
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
    if tail_exit is not None:
        if (len(plan.strokes) != 1 or not isinstance(tail_exit, dict)
                or set(tail_exit) != {'start_s', 'end_s', 'end_z_mm'}):
            raise ValueError('tail_exit requires one stroke and explicit start_s/end_s/end_z_mm')
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
               for v in tail_exit.values()):
            raise ValueError('tail_exit requires finite numeric values')
        if not (0 < tail_exit['start_s'] < tail_exit['end_s'] <= 1
                and setup['contact_z_mm'] < tail_exit['end_z_mm'] <= p['slow_below_z_mm']):
            raise ValueError('tail_exit requires increasing progress and clearance above contact')
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
        local=stroke_profiles[i] if stroke_profiles is not None else {}
        writing_tilt=local.get('writing_tilt_deg',p['writing_tilt_deg'])
        reverse_mm=local.get('entry_reverse_mm',p['entry_reverse_mm'])
        if (isinstance(writing_tilt,bool) or not isinstance(writing_tilt,(int,float)) or not math.isfinite(writing_tilt)
                or not 0<writing_tilt<p['entry_tilt_deg']):raise ValueError('invalid per-stroke writing tilt')
        if (isinstance(reverse_mm,bool) or not isinstance(reverse_mm,(int,float)) or not math.isfinite(reverse_mm)
                or reverse_mm<0):raise ValueError('invalid per-stroke entry reverse')
        if 'segment_magnetic_targets' in local:
            from brushbot.experiments.strokeplan_segment_targets import validate_segment_targets
            validate_segment_targets(local['segment_magnetic_targets'],table)
        if stroke_profiles is not None:
            height_knots=None
            if 'writing_height' in local:
                value=local['writing_height']
                if not isinstance(value,dict) or set(value)!={'knots_s_mm'}:raise ValueError('invalid per-stroke writing_height')
                height_knots=np.asarray(value['knots_s_mm'],float)
                if (height_knots.ndim!=2 or height_knots.shape[1]!=2 or len(height_knots)<2
                        or not np.isfinite(height_knots).all() or height_knots[0,0]!=0 or height_knots[-1,0]!=1
                        or np.any(np.diff(height_knots[:,0])<=0) or np.any(height_knots[:,1]<0) or height_knots[0,1]!=0):
                    raise ValueError('invalid per-stroke writing_height')
        if st.orientation is None:
            raise ValueError('directional character requires explicit target orientations')
        orient = np.asarray(st.orientation,float)
        if local.get('node_angles',False) or plan.meta.get('recipe',{}).get('orientation',{}).get('node_angles_s_deg') is not None:
            tilt=np.rad2deg(np.arccos(np.clip(np.cos(orient[:,0])*np.cos(orient[:,1]),-1,1)))
            if np.any(tilt<=0) or np.any(tilt>=p['entry_tilt_deg']):raise ValueError('node tilt outside entry tilt range')
            if not np.isclose(tilt[0],writing_tilt,atol=.01):raise ValueError('initial node tilt differs from entry')
        elif not np.allclose(np.cos(orient[:,0])*np.cos(orient[:,1]),
                           np.cos(np.deg2rad(writing_tilt)),atol=2e-4,rtol=0):
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
        entry_offset = reverse_mm/1000*np.array([math.cos(heading),math.sin(heading)])
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
        if height_knots is not None:
            progress=np.interp(ticks,st.t,st.s)
            k=np.clip(np.searchsorted(height_knots[:,0],progress,side='right')-1,0,len(height_knots)-2)
            u=np.clip((progress-height_knots[k,0])/(height_knots[k+1,0]-height_knots[k,0]),0.,1.)
            offset=height_knots[k,1]+_ease(u)*(height_knots[k+1,1]-height_knots[k,1])
            measurement[:,2]+=offset/1000
            if np.any(measurement[:,2]>setup['contact_z_mm']/1000+1e-9):
                raise ValueError('writing_height would exceed nominal paper Z; reduce lift')
        if tail_exit is None:
            append(measurement,f'measure_{i:02}')
        else:
            progress = np.interp(ticks, st.t, st.s)
            first = int(np.searchsorted(progress, tail_exit['start_s']))
            if first < 2 or first >= len(measurement)-2:
                raise ValueError('tail_exit needs contact samples before lift and multiple lift samples')
            end = float(np.interp(tail_exit['end_s'], st.s, st.t))
            begin = float(ticks[first-1])
            if end <= begin + 2*DT:
                raise ValueError('tail_exit duration too short')
            # Absolute Z exit, independent of the magnetic table after begin.
            # The named exit phase never runs P/PI magnetic tracking.
            start_z = measurement[first-1, 2]
            q = np.clip((ticks[first:]-begin)/(end-begin), 0., 1.)
            measurement[first:, 2] = start_z + (tail_exit['end_z_mm']/1000-start_z)*_ease(q)
            append(measurement[:first], f'measure_{i:02}')
            append(measurement[first:], f'tail_exit_{i:02}')
        lifted = measurement[-1].copy(); lifted[2] = p['transfer_z_mm']/1000
        move(lifted,f'lift_{i:02}',p['fast_z_speed_mm_s'])
    move(start,'return_high',min(p['transfer_speed_mm_s'],setup['return_speed_mm_s']))
    poses = np.asarray(poses)
    try:_check_trajectory(poses,setup,p)
    except ValueError as exc:
        if hasattr(exc,'sample_index'):
            index=min(exc.sample_index,len(phases)-1);exc.phase=phases[index]
            if exc.phase.startswith('measure_'):
                stroke_index=int(exc.phase.split('_')[1]);first=phases.index(exc.phase)
                stroke=plan.strokes[stroke_index]
                exc.path_progress=float(np.interp((index-first)*DT,stroke.t,stroke.s))
        raise
    return poses,phases
