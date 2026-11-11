"""Continuous EMA and label-free, native-time magnetic representations."""
from dataclasses import asdict, dataclass
import numpy as np


@dataclass(frozen=True)
class FeatureConfig:
    alpha: float = .3
    points: int = 128
    direction_threshold: float = 5.
    direction_coverage: float = .9
    warmup: int = 100

    def validate(self):
        if not 0 < self.alpha <= 1 or self.points != 128 or self.warmup < 100:
            raise ValueError('EMA必须在(0,1]，重采样固定128点，预热不少于100点')
        if self.direction_threshold <= 0 or not 0 < self.direction_coverage <= 1:
            raise ValueError('方向阈值及覆盖率无效')
        return self

    def to_dict(self):
        return asdict(self)


def ema(values, valid, breaks, alpha=.3):
    result=np.full(len(values),np.nan)
    state=None
    for i,value in enumerate(values):
        if breaks[i] or not valid[i]: state=None
        if valid[i]:
            state=float(value) if state is None else alpha*value+(1-alpha)*state
            result[i]=state
    return result


def prepare_sensor(rows, config=FeatureConfig()):
    config.validate()
    if len(rows)<2: raise ValueError('传感器采样不足')
    seq=np.array([int(r['seq']) for r in rows],dtype=np.int64)
    if np.any(np.diff(seq)<=0): raise ValueError('seq重复或逆序')
    clock=np.array([int(r['sensor_t_us']) for r in rows],dtype=np.int64)
    dt=np.diff(clock)
    wrap=(clock[:-1]>2**32-1_000_000)&(clock[1:]<1_000_000)&(dt<0)
    dt[wrap]+=2**32
    if not np.any(dt>0): raise ValueError('传感器时钟无效')
    nominal=float(np.median(dt[dt>0]))
    time=np.r_[0.,np.cumsum(dt.astype(float))/1e6]
    bx=np.array([float(r.get('dBx_uT') or 'nan') for r in rows])
    by=np.array([float(r.get('dBy_uT') or 'nan') for r in rows])
    valid=np.array([str(r.get('valid','true')).lower() in ('true','1') for r in rows])
    valid &= np.isfinite(bx)&np.isfinite(by)
    ids=[r.get('baseline_id','') for r in rows]
    breaks=np.r_[True,(dt<=0)|(dt>2*nominal)|(np.diff(seq)!=1)]
    breaks[1:] |= np.array([a!=b for a,b in zip(ids[:-1],ids[1:])])
    raw=np.hypot(bx,by)
    scalar=ema(raw,valid,breaks,config.alpha)
    u=ema(bx,valid,breaks,config.alpha);v=ema(by,valid,breaks,config.alpha)
    resets=np.flatnonzero(valid & (breaks | np.r_[True,~valid[:-1]]))
    return dict(seq=seq,time=time,raw=raw,ema=scalar,u=u,v=v,valid=valid,
                breaks=breaks,resets=resets,seq_index={int(s):i for i,s in enumerate(seq)})


def direction_features(tau,u,v,magnitude,config=FeatureConfig()):
    grid=np.linspace(0,1,config.points)
    angle=np.arctan2(v,u)
    good=np.isfinite(angle)&(magnitude>=config.direction_threshold)&(np.hypot(u,v)>1e-8)
    ref=good & (tau<=.1+1e-12)
    resultant=np.mean(np.exp(1j*angle[ref])) if np.any(ref) else 0j
    anchor_ok=np.count_nonzero(ref)>=5 and abs(resultant)>=.2
    anchor=float(np.angle(resultant)) if anchor_ok else np.nan
    mapped=np.full(config.points,np.nan);segment=np.full(config.points,-1)
    edges=np.flatnonzero(np.diff(np.r_[False,good,False].astype(int)))
    for part,(start,stop) in enumerate(zip(edges[::2],edges[1::2])):
        if stop-start<2: continue
        take=(grid>=tau[start])&(grid<=tau[stop-1])
        mapped[take]=np.interp(grid[take],tau[start:stop],np.unwrap(angle[start:stop]))
        segment[take]=part
    wrap=lambda x: np.arctan2(np.sin(x),np.cos(x))
    d2=np.full(config.points,np.nan)
    if segment[0]>=0: d2[0]=0.
    adjacent=(segment[1:]>=0)&(segment[1:]==segment[:-1])
    d2[1:][adjacent]=wrap(np.diff(mapped)[adjacent])
    relative=wrap(mapped-anchor) if anchor_ok else np.full(config.points,np.nan)
    return {'D1':relative,'D2':d2,'D3':np.r_[np.sin(relative),np.cos(relative)]},dict(
        coverage=float(np.mean(np.isfinite(mapped))),anchor_ok=bool(anchor_ok),
        anchor_r=float(abs(resultant)),anchor=anchor if anchor_ok else None)


def extract(record,first,last,config=FeatureConfig()):
    try: begin,end=record['seq_index'][int(first)],record['seq_index'][int(last)]
    except KeyError as exc: raise ValueError('笔画边界不在传感器记录内') from exc
    if end<=begin: raise ValueError('笔画边界为空或逆序')
    sl=slice(begin,end+1)
    if not record['valid'][sl].all() or record['breaks'][begin+1:end+1].any():
        raise ValueError('笔画内部存在无效采样、时钟缺口或基线切换')
    resets=record['resets'][record['resets']<=begin]
    if not len(resets) or begin-resets[-1]<config.warmup:
        raise ValueError('笔画开始前连续有效预热不足100点')
    t=record['time'][sl];tau=(t-t[0])/(t[-1]-t[0])
    scalar=record['ema'][sl]
    baseline=float(np.median(scalar[tau<=.1+1e-12]))
    a0=np.interp(np.linspace(0,1,config.points),tau,scalar)
    a1=a0-baseline
    scale=max(float(np.quantile(a0,.95)-np.quantile(a0,.05)),1e-8)
    reps={'A0':a0,'A1':a1,'A2':(a0-np.median(a0))/scale,'A4':np.r_[0.,np.diff(a1)]}
    directions,info=direction_features(tau,record['u'][sl],record['v'][sl],scalar,config)
    reps.update(directions)
    return dict(amplitude=a0,baseline=baseline,native_tau=tau,native_ema=scalar,
                native_u=record['u'][sl],native_v=record['v'][sl],feature_config=config.to_dict(),
                representations=reps,direction_info=info,seq_start=int(first),seq_end=int(last))
