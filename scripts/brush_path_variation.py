"""Build checked execution copies without editing standard workspace data."""
import copy
import hashlib
import json
import secrets
import numpy as np
from brushbot.planning import check_cancelled
from brushbot.experiments.stroke_variation import (ALGORITHM, validate_parameters,
    generate_fields, varied_path, evaluate_fields)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()).hexdigest()


def workspace_source(model):
    from scripts.brush_path_editor_model import PathModel
    states={s['stroke_id']:copy.deepcopy(s) for s in model.other_strokes}
    states[model.stroke_id]=model.state(False)
    snapshots={}
    for key in sorted(states):
        s=states[key];m=PathModel.from_state(s)
        s['settings_snapshot']=m.settings()
        for k in ('feedforward_override','settings_override','entry_profile_override'):s[k]=None
        # Source folder is provenance only and must not affect identity.
        s['source_folder']='.'
        snapshots[key]=s
    return snapshots,digest(snapshots)


def paper_points(model):
    recipe=model.recipe();placement=recipe['placement'];angle=np.deg2rad(placement['rotation_deg'])
    rotation=np.array([[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]])
    return model.points()@rotation.T*placement['scale']+placement['origin_mm']


def make_batch(model,*,seed=None,parameters=None):
    from scripts.brush_path_editor_model import PathModel
    if model.pending_point is not None:raise ValueError('请先完成新笔画的第二个点')
    snapshots,source_digest=workspace_source(model);params=validate_parameters(parameters)
    seed=secrets.randbits(128) if seed is None else seed
    result={}
    for key,state in snapshots.items():
        effective=PathModel.from_state(state).execution_model()
        result[key]=generate_fields(paper_points(effective),root_seed=seed,stroke_id=key,parameters=params)
    return dict(version=1,root_seed=str(seed),parameters=params,source_digest=source_digest,stroke_fields=result)


def execution_state(standard_state,fields,*,xy_enabled,magnetic_enabled,xy_scale=1.,magnetic_scale=1.):
    from scripts.brush_path_editor_model import PathModel,arc
    m=PathModel.from_state(standard_state).execution_model();recipe=m.recipe();points=paper_points(m)
    if xy_enabled:
        path=varied_path(points,fields,xy_scale=xy_scale)
    else:
        q=arc(points);q=q/q[-1]
        path=dict(source_s=q,execution_s=q,execution_xy_mm=points,standard_xy_mm=points,
            original_vertex_indices=np.arange(len(points)),statistics=dict(max_displacement_mm=0.,standard_length_mm=float(arc(points)[-1]),execution_length_mm=float(arc(points)[-1])))
    source,execution=path['source_s'],path['execution_s']
    angle=np.deg2rad(recipe['placement']['rotation_deg']);rotation=np.array([[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]])
    local=(path['execution_xy_mm']-recipe['placement']['origin_mm'])@rotation/recipe['placement']['scale']
    recipe['path']['points_mm']=local.tolist()
    for section,name in [('magnetic_target','knots_s_uT'),('timing','speed_knots_s_mm_s'),('orientation','heading_knots_s_deg'),('orientation','node_angles_s_deg')]:
        if name in recipe[section]:
            recipe[section][name]=[[float(np.interp(row[0],source,execution)),*row[1:]] for row in recipe[section][name]]
    state=m.state(False);state['base_recipe']=recipe
    indices=path['original_vertex_indices'][m.indices]
    state.update(indices=indices.tolist(),nodes_mm=local[indices].tolist(),node_enabled=[True]*len(indices),
        magnetic_values_uT=np.array(recipe['magnetic_target']['knots_s_uT'])[:,1].tolist(),
        variation_execution_recipe=recipe)
    state['settings_snapshot']=m.settings()
    for key in ('feedforward_override','settings_override','entry_profile_override'):state[key]=None
    entry=state['settings_snapshot']['entry_profile.json']
    if magnetic_enabled:
        entry['magnetic_variation']=dict(version=1,fields=copy.deepcopy(fields),source_s=source.tolist(),execution_s=execution.tolist(),magnetic_scale=magnetic_scale)
    else:entry.pop('magnetic_variation',None)
    for row in state['rhythm_regions']:
        row['start']=float(np.interp(row['start'],source,execution));row['end']=float(np.interp(row['end'],source,execution))
    _,gain=evaluate_fields(fields,np.linspace(0,1,1001),magnetic_scale=magnetic_scale if magnetic_enabled else 0.)
    state['variation_statistics']={**path['statistics'],'max_magnetic_relative_change':float(abs(gain).max())}
    return state


def compile_variation(model,*,current_only=False,entry_adjustments=None,reference_only=False):
    from scripts.brush_path_editor_model import PathModel
    from scripts.generate_strokeplan_from_json import build_plan
    from brushbot.experiments.strokeplan_targets import validate_execution_targets
    check_cancelled()
    if model.pending_point is not None:raise ValueError('新笔画只有独立起点，请先添加第二个点或取消独立起点')
    status=model.variation_status()
    if status['state']!='ready':raise ValueError('随机结果缺失或已过期，请重新生成本次变化')
    config=model.random_variation;batch=config['batch'];snapshots,source_digest=workspace_source(model)
    order=[model.stroke_id] if current_only else model.stroke_order.copy()
    key=digest([batch,source_digest,order,config['options'],current_only,entry_adjustments,reference_only])
    cached=getattr(model,'_variation_cache',None)
    if cached and cached[0]==key:
        for name,value in cached[2].items():setattr(model,name,copy.deepcopy(value))
        return copy.deepcopy(cached[1])
    standard=PathModel.from_state(model.state());standard.random_variation=None
    baseline=standard._compile_standard(entry_adjustments,reference_only) if current_only else standard._compile_workspace_standard()
    scales={k:dict(xy=1.,magnetic=1.,reasons=[]) for k in order}
    last_error=None
    for attempt in range(11):
        check_cancelled()
        states={};stage='xy';active=order[0]
        try:
            for active in order:
                check_cancelled()
                scale=scales[active]
                s=execution_state(snapshots[active],batch['stroke_fields'][active],xy_enabled=config['options']['xy_enabled'],
                    magnetic_enabled=config['options']['magnetic_enabled'],xy_scale=scale['xy'],magnetic_scale=scale['magnetic'])
                candidate=PathModel.from_state(s);stage='magnetic'
                table=candidate.settings()['feedforward.json']
                if candidate.allow_low_response:
                    table['low_response_trial']=dict(method='linear_to_nominal_zero_depth',trial_authorized=True,measured_lower_uT=table['amplitude_uT'][0],measured_lower_depth_mm=table['depth_mm'][0])
                validate_execution_targets(build_plan(candidate.recipe()).strokes[0],table,candidate.settings()['entry_profile.json'])
                states[active]=s;stage='xy'
            selected=model.stroke_id if model.stroke_id in states else order[0]
            candidate=PathModel.from_state(states[selected]);candidate.other_strokes=[states[k] for k in order if k!=selected];candidate.stroke_order=order
            stage='joint'
            result=candidate._compile_standard(entry_adjustments,reference_only) if current_only else candidate._compile_workspace_standard()
            stats={k:s['variation_statistics'] for k,s in states.items()}
            if max(max(v['max_displacement_mm'],v['max_magnetic_relative_change']) for v in stats.values())<=1e-12:
                raise ValueError('实际随机变化为零，请调整幅度后重新生成')
            execution_spec=copy.deepcopy(result[2]['spec_snapshot'])
            execution_spec.pop('run_label',None)
            model.last_variation=dict(execution_spec=execution_spec,execution_setup=copy.deepcopy(result[2]['setup_snapshot']),version=1,batch=copy.deepcopy(batch),options=copy.deepcopy(config['options']),source_snapshot=snapshots,
                execution_order=order,scales=copy.deepcopy(scales),statistics=stats,source_digest=source_digest,
                execution_digest=key,algorithm=ALGORITHM)
            model._variation_arrays={f'{prefix}_{name}':np.asarray(data[name]).copy() for prefix,data in [('standard',baseline[2]),('execution',result[2])]
                for name in ('t_s','s','phase','pose_m_rad','g_ref_uT','depth_ff_m')}
            from brushbot.experiments.strokeplan_targets import sample_execution_stroke
            from brushbot.experiments.strokeplan_segment_targets import stroke_entry_profile
            for prefix,data in [('standard',baseline),('execution',result)]:
                for index,(k,stroke) in enumerate(zip(order,data[1].strokes)):
                    profile=stroke_entry_profile(data[3]['entry_profile.json'],index)
                    ticks,_,ff,ref,_=sample_execution_stroke(stroke,data[3]['feedforward.json'],profile)
                    for suffix,values in [('t_s',ticks),('g_ff_uT',ff),('g_ref_uT',ref),('s',np.interp(ticks,stroke.t,stroke.s))]:
                        model._variation_arrays[k+'_'+prefix+'_'+suffix]=values
            for k,s in states.items():
                src=PathModel.from_state(snapshots[k]).execution_model()
                model._variation_arrays[k+'_standard_xy_mm']=paper_points(src)
                execmodel=PathModel.from_state(s)
                model._variation_arrays[k+'_execution_xy_mm']=paper_points(execmodel)
            for name in ('last_speed_adaptation','last_workspace_strokes','last_workspace_audit'):
                if hasattr(candidate,name):setattr(model,name,copy.deepcopy(getattr(candidate,name)))
            if current_only:model.last_variation_audit=candidate.audit_targets(result[2])
            else:model.last_variation_audit=copy.deepcopy(getattr(candidate,'last_workspace_audit',candidate.audit_targets(result[2]) if len(order)==1 else []))
            saved={n:copy.deepcopy(getattr(model,n)) for n in ('last_variation','last_variation_audit','_variation_arrays','last_speed_adaptation','last_workspace_strokes','last_workspace_audit') if hasattr(model,n)}
            model._variation_cache=(key,copy.deepcopy(result),saved)
            return result
        except ValueError as exc:
            last_error=exc
            if '实际随机变化为零' in str(exc):break
            targets=[active] if stage in ('magnetic','xy') else order
            for k in targets:
                for name in (('magnetic',) if stage=='magnetic' else ('xy',) if stage=='xy' else ('xy','magnetic')):scales[k][name]*=.5
                scales[k]['reasons'].append(str(exc))
    raise ValueError('随机变化无法通过预检，请减小幅度或重新生成：'+str(last_error)) from last_error
