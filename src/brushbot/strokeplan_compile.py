"""Offline V3 compilation; target time interpolation precedes feedforward lookup."""
import numpy as np
from brushbot.feedforward import lookup_depth_m, validate_context

LIMITATIONS = ('Open loop; no sensor recording or feedback. Calibration covers +X 10 mm/s only. '
               'Acceleration, deceleration, pauses and changing depth remain unvalidated transients. '
               'Workspace bounds are not collision checking; site clearance must be verified.')


def sample_stroke(stroke, table, dt_s=.02):
    stroke.validate()
    if not np.isfinite(dt_s) or dt_s<=0:
        raise ValueError('invalid control period')
    duration=float(stroke.t[-1])
    if duration/dt_s>1_000_000:
        raise ValueError('trajectory too long')
    # Preserve physical tick spacing. A non-grid terminal time is held at the next tick.
    # A nominal grid endpoint such as 510*.04 must not round up an extra tick.
    ticks=np.arange(int(np.ceil(duration/dt_s-1e-9))+1)*dt_s
    xy=np.column_stack([np.interp(ticks,stroke.t,np.asarray(stroke.xy)[:,i]) for i in range(2)])
    g=np.interp(ticks,stroke.t,stroke.g_target)
    return ticks,xy,g,lookup_depth_m(table,g)


def _transit(start,end,speed,accel,dt):
    distance=float(np.linalg.norm(end-start))
    if distance<1e-12:
        return np.empty((0,3))
    ramp=min(speed/accel,np.sqrt(distance/accel)); peak=accel*ramp
    duration=distance/peak+ramp
    if duration/dt>1_000_000:
        raise ValueError('transit too long')
    t=np.minimum(np.arange(1,int(np.ceil(duration/dt))+1)*dt,duration)
    d=np.where(t<ramp,.5*accel*t*t,
               np.where(t<=duration-ramp,peak*(t-.5*ramp),distance-.5*accel*(duration-t)**2))
    return start+(end-start)*np.clip(d/distance,0,1)[:,None]


def compile_target_plan(plan,table,settings,*,dt_s=.02,assume_direction_invariant=False):
    """Compile XY under an explicit trial assumption; other limits still apply.

    The opt-in does not extend the measured support recorded in the table.
    """
    if type(assume_direction_invariant) is not bool:
        raise ValueError('assume_direction_invariant must be boolean')
    plan.validate()
    validate_context(plan,table,settings)
    if dt_s != .02:
        raise ValueError('current executor requires 20 ms')
    required=('origin_x_mm','origin_y_mm','wait_z_mm','contact_z_mm','max_depth_mm',
              'max_xy_speed_mm_s','max_z_speed_mm_s','max_accel_mm_s2','max_step_mm')
    try:
        values=np.asarray([settings[k] for k in required],float)
        lower=np.asarray(settings['workspace_min_mm'],float)/1000
        upper=np.asarray(settings['workspace_max_mm'],float)/1000
    except (KeyError,TypeError) as exc:
        raise ValueError('incomplete execution settings') from exc
    if (not np.isfinite(values).all() or np.any(values[4:]<=0)
            or lower.shape!=(3,) or upper.shape!=(3,) or not np.isfinite(np.r_[lower,upper]).all()
            or np.any(lower>=upper) or settings['wait_z_mm']<=settings['contact_z_mm']):
        raise ValueError('invalid execution settings')
    rpy=np.asarray(settings['vertical_rpy_rad'],float)
    start=values[:3]/1000
    current=start.copy()
    points=[np.r_[start,rpy]]; phases=['wait']

    def move(target,label):
        nonlocal current
        target=np.asarray(target,float)
        speed=min(10.,settings['max_xy_speed_mm_s'],settings['max_z_speed_mm_s'])/1000
        accel=min(50.,settings['max_accel_mm_s2'])/1000
        for p in _transit(current,target,speed,accel,dt_s):
            points.append(np.r_[p,rpy]); phases.append(label)
        current=target

    for index,stroke in enumerate(plan.strokes):
        xy=np.asarray(stroke.xy,float)
        if not assume_direction_invariant and (np.any(np.diff(xy[:,0]) < -1e-12) or np.ptp(xy[:,1])>1e-9):
            raise ValueError('only +X straight strokes supported')
        speed=np.linalg.norm(np.diff(xy,axis=0),axis=1)/np.diff(stroke.t)*1000
        if speed.max()>table['speed_mm_s']+1e-6:
            raise ValueError('target speed outside calibration support')
        if stroke.orientation is not None:
            delta=(np.asarray(stroke.orientation)-rpy+np.pi)%(2*np.pi)-np.pi
            if np.any(abs(delta)>1e-8):
                raise ValueError('dynamic/different target orientation unsupported')
        # Check ALL targets, including a possible between-tick outlier.
        depth=lookup_depth_m(table,stroke.g_target)
        if np.any(depth*1000>settings['max_depth_mm']):
            raise ValueError('depth limit')
        _,xy,g,depth=sample_stroke(stroke,table,dt_s)
        if plan.meta['coordinate_frame']=='paper':
            xy=xy+start[:2]
        xyz=np.column_stack([xy,settings['contact_z_mm']/1000-depth])
        move([*xyz[0,:2],start[2]],f'high_transfer_{index:02}')
        move(xyz[0],f'lower_{index:02}')
        # Explicit t=0 sample belongs to measure, not the lowering phase.
        points.extend(np.column_stack([xyz,np.tile(rpy,(len(xyz),1))]))
        phases.extend([f'measure_{index:02}']*len(xyz))
        current=xyz[-1]
        move([*current[:2],start[2]],f'lift_{index:02}')
    move(start,'return_high')
    poses=np.asarray(points)
    if not np.isfinite(poses).all() or np.any(poses[:,:3]<lower) or np.any(poses[:,:3]>upper):
        raise ValueError('workspace_limit')
    # Include rest at both boundaries in finite-difference limits.
    v=np.diff(np.vstack([poses[0,:3],poses[:,:3],poses[-1,:3]]),axis=0)/dt_s
    if (np.linalg.norm(v[:,:2],axis=1).max()*1000>settings['max_xy_speed_mm_s']+1e-6
            or abs(v[:,2]).max()*1000>settings['max_z_speed_mm_s']+1e-6
            or np.linalg.norm(v,axis=1).max()*dt_s*1000>settings['max_step_mm']+1e-6):
        raise ValueError('speed/step limit; revise targets/time explicitly')
    if np.linalg.norm(np.diff(v,axis=0)/dt_s,axis=1).max()*1000>settings['max_accel_mm_s2']+1e-6:
        raise ValueError('acceleration limit; revise targets/time explicitly')
    return poses,phases
