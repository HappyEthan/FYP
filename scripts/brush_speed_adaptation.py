"""Offline local speed adaptation. Never connects to robot or sensor."""
import copy
import numpy as np

from scripts.generate_strokeplan_from_json import build_plan
from brushbot.experiments.strokeplan_execution import compile_recorded_plan
from brushbot.experiments.z_identification import TrajectoryLimitError, _check_trajectory
from brushbot.planning import check_cancelled


def _compress(q,values,tolerance=.02):
    def keep(a,b):
        if b<=a+1:return [a,b]
        error=abs(values[a+1:b]-np.interp(q[a+1:b],q[[a,b]],values[[a,b]]))
        i=a+1+int(np.argmax(error))
        return [a,b] if error.max()<=tolerance else keep(a,i)[:-1]+keep(i,b)
    indices=keep(0,len(q)-1)
    return np.column_stack([q[indices],values[indices]]).tolist()


def adapt_speed(requested,settings,*,max_iterations=160):
    """Lower requested local speeds only; reject errors unrelated to writing speed.

    Actual failed sample progress comes from the compiler, avoiding ambiguous XY
    nearest-point matching at crossings. All candidate plans use original checks.
    """
    recipe=copy.deepcopy(requested)
    timing=recipe['timing'];setup=settings['settings.json'];entry=settings['entry_profile.json']
    cap=min(timing['speed_mm_s'],settings['feedforward.json']['speed_mm_s'],setup['max_xy_speed_mm_s'])
    timing['speed_mm_s']=float(cap)
    timing['accel_mm_s2']=min(timing['accel_mm_s2'],setup['max_accel_mm_s2'])
    timing['angular_speed_deg_s']=min(timing['angular_speed_deg_s'],entry['angular_speed_deg_s'])
    timing['angular_accel_deg_s2']=min(timing['angular_accel_deg_s2'],entry['angular_accel_deg_s2'])
    knots=np.array(timing.get('speed_knots_s_mm_s',[[0,cap],[1,cap]]),float)
    q=np.unique(np.r_[np.linspace(0,1,801),knots[:,0]])
    values=np.minimum(cap,np.interp(q,knots[:,0],knots[:,1]))
    failures=[]

    def compile_recipe(candidate):
        check_cancelled()
        plan=build_plan(candidate)
        compiled=compile_recorded_plan(plan,settings['feedforward.json'],setup,
            label='interactive_heng_pi',control_mode='pi',feedback_profile=settings['pi_profile.json'],entry_profile=entry)
        limits=_check_trajectory(compiled['pose_m_rad'],setup,entry)
        return plan,compiled,limits

    # First preserve the user's exact requested curve if it already passes.
    if 'speed_knots_s_mm_s' in timing:
        timing['speed_knots_s_mm_s']=[[float(s),float(min(v,cap))] for s,v in knots]
    for iteration in range(max_iterations+1):
        check_cancelled()
        if iteration:timing['speed_knots_s_mm_s']=np.column_stack([q,values]).tolist()
        try:
            plan,compiled,limits=compile_recipe(recipe)
            if iteration:
                simplified=copy.deepcopy(recipe)
                simplified['timing']['speed_knots_s_mm_s']=_compress(q,values)
                try:
                    candidate=compile_recipe(simplified)
                    recipe=simplified;plan,compiled,limits=candidate
                except TrajectoryLimitError:pass  # Keep the validated dense curve.
            stroke=plan.strokes[0]
            speed=np.linalg.norm(np.diff(stroke.xy,axis=0),axis=1)*1000/np.diff(stroke.t)
            report=dict(enabled=True,method='local_speed_caps_from_failed_control_samples',
                adapted=bool(failures or recipe['timing']!=requested['timing']),iterations=iteration,
                failures=failures,requested_timing=copy.deepcopy(requested['timing']),
                effective_timing=copy.deepcopy(recipe['timing']),writing_duration_s=float(stroke.t[-1]),
                planned_max_writing_speed_mm_s=float(speed.max()),limits=limits,
                global_time_scaling_applied=False,hardware_executed=False)
            return recipe,plan,compiled,limits,report
        except TrajectoryLimitError as exc:
            if exc.path_progress is None or not (exc.phase or '').startswith('measure_'):
                raise ValueError(f'自动适速无法修改非书写阶段：{exc.phase or "未知阶段"}，{exc}') from exc
            if iteration==max_iterations:break
            center=exc.path_progress
            # Angular planning limits affect only regions that rotate; lowering
            # them also addresses endpoint sampling spikes without scaling XY time globally.
            if exc.limit_name.startswith('angular'):
                timing['angular_accel_deg_s2']*=.75
                timing['angular_speed_deg_s']*=.9
            failures.append(dict(limit=exc.limit_name,value=exc.value,bound=exc.bound,
                progress=center,phase=exc.phase,sample_index=exc.sample_index))
            # Spread reductions across a neighborhood, not a single 20ms tick.
            # Broaden gradually to prevent an isolated speed notch causing new peaks.
            span=min(.04,.012+.00015*iteration)
            weight=np.maximum(0,1-abs(q-center)/span)
            values*=1-.18*weight
            if np.min(values)<.02:break
    raise ValueError('自动适速未能在迭代范围内通过预检；未生成可执行版本。请减小局部转角、磁目标变化或调整路径。')
