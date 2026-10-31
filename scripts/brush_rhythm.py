"""Offline region rhythm, bounded by a verified reference; no hardware access."""
import copy
import hashlib
import json
from collections import OrderedDict
from threading import RLock
import numpy as np

PRESETS={'顿笔':.30,'行笔':1.,'收笔':.55}
_REFERENCE_CACHE=OrderedDict()
_CACHE_LOCK=RLock()


def validate_regions(regions):
    if not isinstance(regions,list):raise ValueError('节奏区域必须为列表')
    ids=set()
    for row in regions:
        if not isinstance(row,dict) or set(row)!={'id','start','end','label','ratio'}:raise ValueError('节奏区域字段不合法')
        if not isinstance(row['id'],str) or not row['id'] or row['id'] in ids:raise ValueError('节奏区域编号重复')
        ids.add(row['id'])
        if row['label'] not in PRESETS:raise ValueError('节奏类型应为顿笔、行笔或收笔')
        values=[row[k] for k in ('start','end','ratio')]
        if any(isinstance(v,bool) or not isinstance(v,(float,int)) for v in values) or not np.isfinite(values).all():raise ValueError('节奏参数必须为有限数值')
        if not 0<=row['start']<row['end']<=1 or row['end']-row['start']<1e-5:raise ValueError('节奏区域须在路径0–100%范围内且起点小于终点')
        if not .1<=row['ratio']<=1:raise ValueError('节奏倍率须在10%至100%之间')


def rhythm_factor(progress,regions):
    validate_regions(regions)
    q=np.asarray(progress,float);factor=np.ones_like(q)
    for row in regions:
        a,b=row['start'],row['end'];ramp=(b-a)*.15
        weight=np.minimum(np.clip((q-a)/ramp,0,1),np.clip((b-q)/ramp,0,1))
        # Stroke endpoints do not need a blend back to a nonexistent neighbor.
        if a==0:weight=np.clip((b-q)/ramp,0,1)
        if b==1:weight=np.clip((q-a)/ramp,0,1)
        if a==0 and b==1:weight=np.ones_like(q)
        weight=6*weight**5-15*weight**4+10*weight**3
        factor=np.minimum(factor,1-(1-row['ratio'])*weight)
    return factor


def rhythm_knots(reference_timing,regions):
    validate_regions(regions)
    knots=np.array(reference_timing['speed_knots_s_mm_s'],float)
    edges=[q for r in regions for q in (r['start'],r['start']+.15*(r['end']-r['start']),r['end']-.15*(r['end']-r['start']),r['end'])]
    q=np.unique(np.r_[np.linspace(0,1,1601),knots[:,0],edges])
    base=np.interp(q,knots[:,0],knots[:,1])
    values=np.minimum(base,np.maximum(.02,base*rhythm_factor(q,regions)))
    return np.column_stack([q,values])


def verified_reference(recipe,settings):
    # Contents, rather than file mtimes, invalidate this cache after calibration edits.
    fingerprint=hashlib.sha256(json.dumps([recipe,settings],sort_keys=True,allow_nan=False).encode()).hexdigest()
    with _CACHE_LOCK:
        if fingerprint in _REFERENCE_CACHE:
            result=_REFERENCE_CACHE.pop(fingerprint);_REFERENCE_CACHE[fingerprint]=result
            return copy.deepcopy(result)
    from scripts.brush_speed_adaptation import adapt_speed
    result=adapt_speed(recipe,settings)
    with _CACHE_LOCK:
        _REFERENCE_CACHE[fingerprint]=copy.deepcopy(result)
        while len(_REFERENCE_CACHE)>8:_REFERENCE_CACHE.popitem(last=False)
    return result


def slowdown_reasons(report):
    labels={'XY speed':'平面速度限制','Z speed':'升降速度限制','acceleration':'XYZ合成加速度限制',
        'angular speed':'笔杆转向速度限制','angular acceleration':'笔杆转向加速度限制','step':'单步位移限制'}
    failures=report.get('failures',[])
    reasons={labels.get(row['limit'],row['limit']) for row in failures}
    if report.get('reference_report'):reasons.update(slowdown_reasons(report['reference_report']))
    if report.get('strokes'):
        for child in report['strokes']:reasons.update(slowdown_reasons(child))
    if not reasons and report.get('adapted'):reasons.add('前馈表或现场配置的速度上限')
    return sorted(reasons)
