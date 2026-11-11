"""Numerical preprocessing contracts for the offline analysis artifacts."""
import numpy as np

LABELS = ['右点', '横折钩', '横撇', '撇', '捺']
TAU = np.linspace(0., 1., 128)
PREPROCESSING = dict(version='scalar-ema-baseline128-v1', alpha=.3, points=128,
    amplitude='sqrt(dBx_uT**2+dBy_uT**2) before EMA',
    ema_scope='continuous valid sensor record, not reset at stroke boundary',
    baseline_mode='first_10_percent_fallback', baseline='median of native EMA points with tau<=0.1',
    time='sensor_t_us unwrapped; tau=(t-t0)/(t1-t0)',
    interpolation='linear in normalized sensor time', units='uT',
    model_input='128-point baseline-subtracted EMA vector; no metadata',
    minimum_valid_history_samples=100)

def scalar_ema(raw, valid=None, break_before=None, alpha=0.3):
    raw=np.asarray(raw,dtype=float)
    if raw.ndim!=1 or not 0<alpha<=1:raise ValueError('invalid EMA input')
    good=np.isfinite(raw)
    if valid is not None:good &= np.asarray(valid,dtype=bool)
    breaks=np.zeros(len(raw),dtype=bool) if break_before is None else np.asarray(break_before,dtype=bool)
    if breaks.shape!=raw.shape:raise ValueError('break mask shape')
    out=np.full(len(raw),np.nan);state=None
    for i,value in enumerate(raw):
        if breaks[i] or not good[i]:state=None
        if good[i]:
            state=float(value) if state is None else alpha*float(value)+(1-alpha)*state
            out[i]=state
    return out

def make_feature(t, ema, n_points=128):
    t=np.asarray(t,dtype=float);ema=np.asarray(ema,dtype=float)
    if t.ndim!=1 or t.shape!=ema.shape or len(t)<2 or not np.all(np.isfinite(t)) or not np.all(np.isfinite(ema)) or not np.all(np.diff(t)>0):
        raise ValueError('stroke needs finite amplitudes and strictly increasing times')
    tau=(t-t[0])/(t[-1]-t[0])
    baseline=float(np.median(ema[tau<=.1+1e-12]))
    return np.interp(np.linspace(0.,1.,n_points),tau,ema)-baseline,baseline

def choose_kernel(linear_macro_f1, rbf_macro_f1):
    return 'rbf' if rbf_macro_f1-linear_macro_f1>.02+1e-12 else 'linear'


def prepare_sensor(rows):
    if len(rows)<2:raise ValueError('insufficient sensor rows')
    seq=np.array([int(r['seq']) for r in rows],dtype=np.int64)
    if not np.all(np.diff(seq)>0):raise ValueError('duplicate or decreasing seq')
    raw_t=np.array([int(r['sensor_t_us']) for r in rows],dtype=np.int64)
    dt=np.diff(raw_t)
    wrap=(raw_t[:-1]>2**32-1_000_000)&(raw_t[1:]<1_000_000)&(dt<0)
    dt[wrap]+=2**32
    if not np.any(dt>0):raise ValueError('no positive time intervals')
    nominal=float(np.median(dt[dt>0]));time=np.r_[0.,np.cumsum(dt.astype(float))/1e6]
    bx=np.array([float(r['dBx_uT']) if r.get('dBx_uT','')!='' else np.nan for r in rows])
    by=np.array([float(r['dBy_uT']) if r.get('dBy_uT','')!='' else np.nan for r in rows])
    valid=np.array([r.get('valid','true').lower()=='true' for r in rows]) & np.isfinite(bx)&np.isfinite(by)
    baseline_ids=[r.get('baseline_id','') for r in rows]
    breaks=np.r_[True,(dt<=0)|(dt>2*nominal)|(np.diff(seq)!=1)]
    breaks[1:] |= np.array([a!=b for a,b in zip(baseline_ids[:-1],baseline_ids[1:])])
    raw=np.hypot(bx,by);ema=scalar_ema(raw,valid,breaks)
    resets=np.flatnonzero(valid & (breaks | np.r_[True,~valid[:-1]]))
    return dict(seq=seq, raw_sensor_t_us=raw_t, time=time, nominal_interval_us=nominal,
        bx=bx,by=by,raw=raw,ema=ema,valid=valid,breaks=breaks,resets=resets,
        seq_index={int(s):i for i,s in enumerate(seq)})


def extract_stroke(record, seq_start, seq_end):
    try:begin,end=record['seq_index'][int(seq_start)],record['seq_index'][int(seq_end)]
    except KeyError as e:raise ValueError('stroke seq not found in sensor record') from e
    if end<=begin:raise ValueError('empty or reversed stroke window')
    sl=slice(begin,end+1)
    if not record['valid'][sl].all():raise ValueError('invalid magnetic samples in stroke')
    if record['breaks'][begin+1:end+1].any():raise ValueError('gap, time fault or baseline change within stroke')
    prior=record['resets'][record['resets']<=begin]
    if len(prior)==0 or begin-int(prior[-1])<100:raise ValueError('at least 100 valid pre-stroke samples are required for continuous EMA')
    t=record['time'][sl];tau=(t-t[0])/(t[-1]-t[0]);feat,baseline=make_feature(t,record['ema'][sl])
    native={k:record[k][sl] for k in ['seq','raw_sensor_t_us','bx','by','raw','ema']}
    native.update(elapsed=t-t[0],tau=tau)
    return feat,baseline,native
