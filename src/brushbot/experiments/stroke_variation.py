"""Bounded random fields in physical paper millimetres; no hardware or I/O."""
import hashlib
import json
import numpy as np

ALGORITHM = 'fixed_endpoint_quintic_v1'
DEFAULT_PARAMETERS = dict(xy_relative_max=.005, xy_absolute_max_mm=.30,
    xy_broad_fraction=.7, magnetic_global_max=.05, magnetic_local_max=.02)


def validate_parameters(parameters=None):
    if parameters is not None and (not isinstance(parameters, dict) or set(parameters)-DEFAULT_PARAMETERS.keys()):
        raise ValueError('随机参数字段不合法')
    result = {**DEFAULT_PARAMETERS, **(parameters or {})}
    for value in result.values():
        if isinstance(value, bool) or not isinstance(value, (int,float)) or not np.isfinite(value) or value<0:
            raise ValueError('随机幅度必须是非负有限数值')
    if result['xy_broad_fraction'] != .7 or result['magnetic_global_max']+result['magnetic_local_max']>=1:
        raise ValueError('随机比例超出允许范围')
    return result


def _path(points):
    p=np.asarray(points,float)
    if p.ndim!=2 or p.shape[1]!=2 or len(p)<2 or not np.isfinite(p).all():
        raise ValueError('路径必须是有限的二维坐标')
    lengths=np.linalg.norm(np.diff(p,axis=0),axis=1)
    if np.any(lengths<=1e-12):raise ValueError('路径相邻点重复或退化')
    arc=np.r_[0.,np.cumsum(lengths)]
    return p,arc/arc[-1],float(arc[-1])


def _rng(seed, stroke_id, channel):
    payload=json.dumps([str(seed),stroke_id,channel,ALGORITHM],ensure_ascii=False).encode()
    return np.random.Generator(np.random.PCG64(int.from_bytes(hashlib.sha256(payload).digest(),'big')))


def _vectors(rng,count,bound):
    angle=rng.uniform(0,2*np.pi,count);r=rng.uniform(0,bound,count)
    return np.column_stack([r*np.cos(angle),r*np.sin(angle)])


def generate_fields(points_mm, *, root_seed, stroke_id, parameters):
    _,_,length=_path(points_mm);params=validate_parameters(parameters)
    if type(root_seed) is not int or not 0<=root_seed<2**128 or not isinstance(stroke_id,str) or not stroke_id:
        raise ValueError('随机种子或笔画标识不合法')
    n=min(5,max(1,int(np.ceil(length/5))))+1
    bound=min(params['xy_relative_max']*length,params['xy_absolute_max_mm'])
    xy=_rng(root_seed,stroke_id,'xy');mag=_rng(root_seed,stroke_id,'magnetic')
    return dict(version=1,algorithm=ALGORITHM,stroke_id=stroke_id,root_seed=str(root_seed),
        length_mm=length,parameters=params,broad_xy_mm=_vectors(xy,1,bound*.7)[0].tolist(),
        local_s=np.linspace(0,1,n).tolist(),local_xy_mm=_vectors(xy,n,bound*.3).tolist(),
        global_ratio=float(mag.uniform(-params['magnetic_global_max'],params['magnetic_global_max'])),
        local_ratio=mag.uniform(-params['magnetic_local_max'],params['magnetic_local_max'],n).tolist())


def validate_fields(fields):
    keys={'version','algorithm','stroke_id','root_seed','length_mm','parameters','broad_xy_mm','local_s','local_xy_mm','global_ratio','local_ratio'}
    if not isinstance(fields,dict) or set(fields)!=keys or fields['version']!=1 or fields['algorithm']!=ALGORITHM:
        raise ValueError('不支持的随机场版本或字段')
    params=validate_parameters(fields['parameters'])
    try:
        seed=int(fields['root_seed']);length=float(fields['length_mm'])
        q=np.asarray(fields['local_s'],float);xy=np.asarray(fields['local_xy_mm'],float)
        broad=np.asarray(fields['broad_xy_mm'],float);mag=np.asarray(fields['local_ratio'],float)
        global_ratio=float(fields['global_ratio'])
    except (ValueError,TypeError,OverflowError) as exc:raise ValueError('随机场数据损坏') from exc
    if (not 0<=seed<2**128 or str(seed)!=fields['root_seed'] or not isinstance(fields['stroke_id'],str) or not fields['stroke_id']
        or not np.isfinite(length) or length<=0 or q.ndim!=1 or not 2<=len(q)<=6
        or q[0]!=0 or q[-1]!=1 or np.any(np.diff(q)<=0) or xy.shape!=(len(q),2)
        or broad.shape!=(2,) or mag.shape!=q.shape or not np.isfinite(np.r_[q,xy.ravel(),broad,mag,global_ratio]).all()):
        raise ValueError('随机场形状或数值不合法')
    bound=min(params['xy_relative_max']*length,params['xy_absolute_max_mm'])
    if (np.linalg.norm(broad)>bound*.7+1e-12 or np.linalg.norm(xy,axis=1).max()>bound*.3+1e-12
        or abs(global_ratio)>params['magnetic_global_max']+1e-12 or abs(mag).max()>params['magnetic_local_max']+1e-12):
        raise ValueError('随机控制值超出幅度范围')
    return q,xy,broad,mag,global_ratio


def evaluate_fields(fields, source_s, *, xy_scale=1., magnetic_scale=1.):
    knots,local,broad,mag,global_ratio=validate_fields(fields)
    q=np.asarray(source_s,float)
    if q.ndim!=1 or not np.isfinite(q).all() or np.any(q<0) or np.any(q>1):raise ValueError('随机场进度须在0到1内')
    for value in (xy_scale,magnetic_scale):
        if isinstance(value,bool) or not np.isfinite(value) or not 0<=value<=1:raise ValueError('缩小系数须在0到1内')
    k=np.clip(np.searchsorted(knots,q,side='right')-1,0,len(knots)-2)
    u=(q-knots[k])/(knots[k+1]-knots[k]);ease=u**3*(10-15*u+6*u*u)
    b=16*q*q*(1-q)**2
    delta=b[:,None]*(broad+local[k]+ease[:,None]*(local[k+1]-local[k]))*xy_scale
    gain=b*(global_ratio+mag[k]+ease*(mag[k+1]-mag[k]))*magnetic_scale
    return delta,gain


def varied_path(points_mm,fields,*,xy_scale=1.):
    p,q,length=_path(points_mm)
    if not np.isclose(length,fields['length_mm'],rtol=1e-10,atol=1e-10):raise ValueError('随机场与标准路径不匹配')
    count=max(3,int(np.ceil(length/.1))+1)
    if count+len(q)>100000:raise ValueError('随机路径采样点过多')
    grid=np.unique(np.r_[q,fields['local_s'],np.linspace(0,1,count)])
    grid=grid[np.r_[True,np.diff(grid)>1e-12]];grid[-1]=1.
    original=np.column_stack([np.interp(grid,q,p[:,i]) for i in range(2)])
    delta,_=evaluate_fields(fields,grid,xy_scale=xy_scale);result=original+delta
    result[[0,-1]]=p[[0,-1]]
    edges=np.diff(result,axis=0);base_edges=np.diff(original,axis=0)
    if np.any(np.linalg.norm(edges,axis=1)<=1e-12) or np.any(np.einsum('ij,ij->i',edges,base_edges)<=0):
        raise ValueError('随机路径退化或局部反向')
    distance=np.r_[0.,np.cumsum(np.linalg.norm(edges,axis=1))]
    indices=np.array([int(np.argmin(abs(grid-v))) for v in q])
    return dict(source_s=grid,execution_s=distance/distance[-1],standard_xy_mm=original,
        execution_xy_mm=result,original_vertex_indices=indices,
        statistics=dict(max_displacement_mm=float(np.linalg.norm(delta,axis=1).max()),
            standard_length_mm=length,execution_length_mm=float(distance[-1])))
