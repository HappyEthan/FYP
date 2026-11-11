"""One magnetic field applied once to nominal and overridden references."""
import hashlib
import json
from collections import OrderedDict
import numpy as np
from brushbot.feedforward import lookup_depth_m
from brushbot.strokeplan_compile import sample_stroke
from .stroke_variation import evaluate_fields, validate_fields
from .strokeplan_segment_targets import apply_segment_targets

_VALIDATED=OrderedDict()


def magnetic_mapping(value):
    if not isinstance(value,dict) or set(value)!={'version','fields','source_s','execution_s','magnetic_scale'} or value['version']!=1:
        raise ValueError('磁随机场字段或版本不合法')
    validate_fields(value['fields'])
    a=np.asarray(value['source_s'],float);b=np.asarray(value['execution_s'],float)
    if (a.ndim!=1 or b.shape!=a.shape or not 2<=len(a)<=100000
        or not np.isfinite(np.r_[a,b]).all() or a[0]!=0 or b[0]!=0 or a[-1]!=1 or b[-1]!=1
        or np.any(np.diff(a)<=0) or np.any(np.diff(b)<=0)):
        raise ValueError('磁随机场进度映射不合法')
    evaluate_fields(value['fields'],np.array([0.]),magnetic_scale=value['magnetic_scale'])
    return a,b


def execution_targets(stroke,table,entry_profile,progress):
    q=np.asarray(progress,float)
    nominal=np.interp(q,stroke.s,stroke.g_target)
    ref=nominal.copy()
    segments=entry_profile.get('segment_magnetic_targets')
    if segments is not None:ref=apply_segment_targets(q,ref,segments,table)
    field=entry_profile.get('magnetic_variation')
    if field is not None:
        source,execution=magnetic_mapping(field)
        _,gain=evaluate_fields(field['fields'],np.interp(q,execution,source),magnetic_scale=field['magnetic_scale'])
        nominal=nominal*(1+gain);ref=ref*(1+gain)
    return nominal,ref


def validate_execution_targets(stroke,table,entry_profile):
    field=entry_profile.get('magnetic_variation')
    if field is None:
        lookup_depth_m(table,stroke.g_target)
        return
    source,execution=magnetic_mapping(field)
    key=hashlib.sha256(stroke.s.tobytes()+stroke.g_target.tobytes()+json.dumps([entry_profile,table],sort_keys=True,allow_nan=False).encode()).digest()
    if key in _VALIDATED:return
    f=field['fields'];knots=np.asarray(f['local_s']);mag=np.asarray(f['local_ratio'])
    # Split at all field and segment boundaries. On each piece u(s) is monotone,
    # so interval arithmetic bounds the entire continuous curve, not just ticks.
    segments=entry_profile.get('segment_magnetic_targets')
    edges=np.unique(np.r_[0.,1.,np.interp(knots,source,execution),segments['nodes_s'] if segments else []])
    lower=0. if table.get('low_response_trial') else table['amplitude_uT'][0]
    upper=table['amplitude_uT'][-1]
    def certify(left,right,level=0):
        end=np.nextafter(right,left) if segments and right<1. else right
        q=np.unique(np.r_[left,end,stroke.s[(stroke.s>left)&(stroke.s<end)]])
        ff,ref=execution_targets(stroke,table,entry_profile,q)
        lookup_depth_m(table,ff);lookup_depth_m(table,ref)
        s0,s1=np.interp([left,end],execution,source)
        k=min(int(np.searchsorted(knots,(s0+s1)/2,side='right')-1),len(knots)-2)
        u=np.clip((np.array([s0,s1])-knots[k])/(knots[k+1]-knots[k]),0,1)
        e=u**3*(10-15*u+6*u*u)
        c=f['global_ratio']+mag[k]+e*(mag[k+1]-mag[k])
        b=16*np.array([s0,s1])**2*(1-np.array([s0,s1]))**2
        blo=float(b.min());bhi=1. if s0<=.5<=s1 else float(b.max())
        products=np.outer([blo,bhi],[c.min(),c.max()])*field['magnetic_scale']
        hlow,hhigh=products.min(),products.max()
        base=np.interp(q,stroke.s,stroke.g_target)
        baseline_ref=apply_segment_targets(q,base,segments,table) if segments else base
        bound_low=min(base.min(),baseline_ref.min())*(1+hlow)
        bound_high=max(base.max(),baseline_ref.max())*(1+hhigh)
        if bound_low>=lower-1e-10 and bound_high<=upper+1e-10:return
        if level>=12:raise ValueError('无法证明连续磁目标在标定范围内，请减小随机幅度')
        middle=(left+right)/2;certify(left,middle,level+1);certify(middle,right,level+1)
    for a,b in zip(edges[:-1],edges[1:]):certify(float(a),float(b))
    _VALIDATED[key]=True
    while len(_VALIDATED)>32:_VALIDATED.popitem(last=False)


def sample_execution_stroke(stroke,table,entry_profile,dt_s=.02):
    ticks,xy,g,depth=sample_stroke(stroke,table,dt_s)
    if entry_profile.get('magnetic_variation') is None:
        ref=g.copy();segments=entry_profile.get('segment_magnetic_targets')
        if segments is not None:ref=apply_segment_targets(np.interp(ticks,stroke.t,stroke.s),ref,segments,table)
        return ticks,xy,g,ref,depth
    validate_execution_targets(stroke,table,entry_profile)
    ff,ref=execution_targets(stroke,table,entry_profile,np.interp(ticks,stroke.t,stroke.s))
    return ticks,xy,ff,ref,lookup_depth_m(table,ff)
