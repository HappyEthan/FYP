from pathlib import Path
import csv, json, hashlib
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path('/home/ethan/FYP/runs/brush2/2026-09-25/05_Z动态辨识')
OUT=ROOT/'analysis/四笔扫描对比_20260925'
plt.rcParams.update({'font.family':'Noto Sans CJK JP','axes.unicode_minus':False,'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'figure.dpi':120,'savefig.dpi':180})
COLORS=['#d97706','#2563eb','#059669','#9333ea']
LABELS=['慢扫 1（进笔异常）','慢扫 2','快扫往返 1','快扫往返 2']
runs=[]
for k,p in enumerate(sorted((ROOT/'raw').iterdir())):
    rows=[json.loads(s) for s in (p/'control.jsonl').read_text().splitlines()]
    c={key:np.array([r[key] for r in rows]) for key in rows[0]}
    t=(c['host_ns']-c['host_ns'][0])/1e9
    phase=c['phase']; start=t[np.flatnonzero(phase=='slide_start')[0]]
    d=c['prescribed_depth_m']*1000;y=c['a_control_uT']
    ss=list(csv.DictReader((p/'sensor.csv').open()))
    raw={key:np.array([float(r[key]) if r[key] else float("nan") for r in ss]) for key in ['Bx_uT','By_uT','Bz_uT','dBx_uT','dBy_uT','dBz_uT']}
    raw['t']=np.array([(int(r['host_rx_ns'])-int(c['host_ns'][0]))/1e9 for r in ss])
    tcp=list(csv.DictReader((p/'actual_tcp.csv').open())); valid=[r for r in tcp if r['valid']=='true']
    at=np.array([((int(r['request_start_ns'])-int(c['host_ns'][0]))+(int(r['request_end_ns'])-int(c['host_ns'][0])))/2e9 for r in valid])
    az=np.array([float(r['z_m'])*1000 for r in valid]); ax=np.array([float(r['x_m'])*1000 for r in valid])
    zcmd=np.interp(at,t,c['z_cmd_m']*1000); xcmd=np.interp(at,t,c['x_cmd_m']*1000)
    ip=np.clip(np.searchsorted(t,at,side='right')-1,0,len(t)-1)
    scanning=np.isin(phase[ip],['sweep_down','sweep_up'])
    manifest=json.loads((p/'manifest.json').read_text());profile=json.loads((p/'identification.json').read_text())
    assert manifest['status']=='completed' and manifest['execution_environment']=='hardware'
    for name,expected in manifest['sha256'].items():
        assert hashlib.sha256((p/name).read_bytes()).hexdigest()==expected,(p,name)
    curves={}
    for ph in ['sweep_down','sweep_up']:
        ix=np.flatnonzero(phase==ph)
        if not len(ix):continue
        bx=[];by=[]
        for lower in np.arange(2,16,.25):
            ii=ix[(d[ix]>=lower)&(d[ix]<lower+.25)]
            if len(ii)>=5:
                bx.append(np.mean(d[ii]));by.append(np.mean(y[ii]))
        curves[ph]=(np.array(bx),np.array(by))
    dt=np.diff(t)*1000
    end=y[phase=='hold'];entry=np.isin(phase,['rotate_contact','slide_start'])
    zi=az[scanning]-zcmd[scanning]
    timing=np.rint(c['t_s']/.02).astype(int)
    quality=dict(label=LABELS[k],folder=p.name,run_id=manifest['run_id'],mode=profile['mode'],
      status=manifest['status'],control_samples=len(t),sensor_samples=len(ss),
      sensor_invalid=sum(r['valid']!='true' for r in ss),tcp_samples=len(tcp),tcp_invalid=len(tcp)-len(valid),
      median_control_dt_ms=float(np.median(dt)),p99_control_dt_ms=float(np.percentile(dt,99)),max_control_dt_ms=float(max(dt)),
      missing_plan_ticks=int(np.sum(np.maximum(np.diff(timing)-1,0))),duplicate_plan_ticks=int(np.sum(np.diff(timing)==0)),
      sensor_age_p99_ms=float(np.percentile(c['sample_age_s']*1000,99)),
      entry_peak_uT=float(max(y[entry])),entry_end_1s_mean_uT=float(np.mean(y[(phase=='slide_start')&(t>=start+2)])),
      final_wait_mean_uT=float(np.mean(end)),final_wait_duration_s=float(t[-1]-t[np.flatnonzero(phase=='hold')[0]]),
      scan_tcp_z_mae_mm=float(np.mean(abs(zi))),scan_tcp_z_p95_abs_mm=float(np.percentile(abs(zi),95)),
      scan_tcp_z_max_abs_mm=float(max(abs(zi))),scan_tcp_x_median_error_mm=float(np.median((ax-xcmd)[scanning])),
      manifest_sha256=hashlib.sha256((p/'manifest.json').read_bytes()).hexdigest(),
      control_sha256=hashlib.sha256((p/'control.jsonl').read_bytes()).hexdigest(),
      sensor_sha256=hashlib.sha256((p/'sensor.csv').read_bytes()).hexdigest(),
      tcp_sha256=hashlib.sha256((p/'actual_tcp.csv').read_bytes()).hexdigest())
    runs.append(dict(p=p,c=c,t=t,start=start,d=d,y=y,phase=phase,raw=raw,at=at,az=az,zerr=az-zcmd,scanning=scanning,curves=curves,quality=quality))

def save(fig,name):
    fig.savefig(OUT/(name+'.png'),bbox_inches='tight')
    fig.savefig(OUT/(name+'.pdf'),bbox_inches='tight')
    plt.close(fig)
def decorate(ax,xlabel=None,ylabel=None):
    ax.grid(alpha=.18)
    if xlabel:ax.set_xlabel(xlabel)
    if ylabel:ax.set_ylabel(ylabel)
def curve(r,ph,g):
    x,y=r['curves'][ph]
    assert min(g)>=x[0] and max(g)<=x[-1]
    return np.interp(g,x,y)

# Equal-depth comparisons, not time-weighted performance scores.
grid=np.arange(5,15.0001,.25)
slowdiff=curve(runs[0],'sweep_down',grid)-curve(runs[1],'sweep_down',grid)
fastdiff=curve(runs[2],'sweep_down',grid)-curve(runs[3],'sweep_down',grid)
updiff=curve(runs[2],'sweep_up',grid)-curve(runs[3],'sweep_up',grid)
gaps=[curve(r,'sweep_up',grid)-curve(r,'sweep_down',grid) for r in runs[2:]]
rate=curve(runs[1],'sweep_down',grid)-np.mean([curve(r,'sweep_down',grid) for r in runs[2:]],axis=0)
def stats(a):return dict(mean=float(np.mean(a)),mae=float(np.mean(abs(a))),p95_abs=float(np.percentile(abs(a),95)),maximum_abs=float(max(abs(a))),fraction_abs_le20=float(np.mean(abs(a)<=20)))
comparisons={name:stats(a) for name,a in [('slow_repeat_1_minus_2',slowdiff),('fast_press_repeat_1_minus_2',fastdiff),('fast_lift_repeat_1_minus_2',updiff),('cycle1_lift_minus_press',gaps[0]),('cycle2_lift_minus_press',gaps[1]),('slow2_minus_mean_fast_press',rate)]}
# Inverse crossings: first ascending crossing AFTER the branch minimum.
# First slow run is deliberately not offered as an inverse mapping.
crossings=[]
for k in [1,2,3]:
    for ph,(x,y) in runs[k]['curves'].items():
        imin=int(np.argmin(y));xx=x[imin:];yy=y[imin:]
        for target in [60,100,150,200]:
            hits=np.flatnonzero((yy[:-1]<=target)&(yy[1:]>=target)&(np.diff(yy)>0))
            depth=None
            if len(hits):
                j=hits[0];depth=float(xx[j]+(target-yy[j])*(xx[j+1]-xx[j])/(yy[j+1]-yy[j]))
            crossings.append(dict(run=LABELS[k],direction='下压' if ph=='sweep_down' else '回升',target_uT=target,depth_mm=depth,z_mm=None if depth is None else 40-depth,crossings_found=len(hits)))
# Descriptive slope using +/-0.75mm around each depth, no dynamic fit.
gains=[]
for k in [1,2,3]:
    for center in [5.,7.5,10.,12.5,15.]:
        x,y=runs[k]['curves']['sweep_down'];sel=abs(x-center)<=.75
        gain=float(np.polyfit(x[sel],y[sel],1)[0])
        gains.append(dict(run=LABELS[k],depth_mm=center,apparent_gain_uT_per_mm=gain))

# 1: contact and scan histories, anomalous trial kept visible.
fig,axes=plt.subplots(2,2,figsize=(13,8.4),layout='constrained')
for k,(r,ax) in enumerate(zip(runs,axes.flat)):
    x=r['t']-r['start'];m=(x>=-6)&(x<=46)
    ax.plot(x[m],r['y'][m],color=COLORS[k],lw=1.2,label='磁响应 EMA')
    ax.axvspan(-3,0,color='#f59e0b',alpha=.10,label='固定 XYZ 旋转接触')
    ax.axvline(3,color='#6b7280',ls=':',lw=1,label='开始扫 Z')
    if k==0:
        ax.set_yscale('symlog',linthresh=100);ax.set_ylim(0,10000)
        ax.text(.03,.95,'进笔峰值 8,090 µT\n纵轴：分段对数刻度',transform=ax.transAxes,va='top',color='#b45309')
    else:ax.set_ylim(0,480)
    twin=ax.twinx();twin.plot(x[m],r['c']['z_cmd_m'][m]*1000,color='#64748b',alpha=.65,ls='--',lw=1,label='命令 Z')
    twin.set_ylim(22,42);twin.set_ylabel('命令 Z / mm',color='#64748b')
    ax.set_title(LABELS[k]);ax.set_xlim(-6,46);decorate(ax,'距 X 开始行走 / s','磁响应 / µT')
    ax.legend(loc='upper right',fontsize=8)
fig.suptitle('四笔实测时序｜旋转接触并未消除第一笔的进笔异常',fontsize=16)
save(fig,'01_四笔时序与进笔')

fig,axes=plt.subplots(2,2,figsize=(13,9),layout='constrained')
ax=axes[0,0]
for k in [0,1]:
 x,y=runs[k]['curves']['sweep_down'];ax.plot(x,y,label=LABELS[k],color=COLORS[k],lw=1.8)
ax.axvspan(2,5,color='#f59e0b',alpha=.10);ax.text(2.2,390,'慢扫 1 浅压段\n受进笔异常影响',color='#92400e')
ax.set_ylim(0,460);ax.set_title('A  慢扫重复：保留异常，不强行合并');ax.legend();decorate(ax,'名义命令压深 d=40−Z / mm','磁响应 / µT')
ax=axes[0,1]
for k in [2,3]:
 for ph,ls,label in [('sweep_down','-','下压'),('sweep_up','--','回升')]:
  x,y=runs[k]['curves'][ph];ax.plot(x,y,ls,color=COLORS[k],label=f'{LABELS[k]} · {label}')
ax.axhspan(60,200,color='#2563eb',alpha=.06);ax.set_ylim(0,460);ax.set_title('B  同一深度：回升响应高于下压');ax.legend(fontsize=8);decorate(ax,'名义命令压深 / mm','磁响应 / µT')
ax=axes[1,0]
ax.axhspan(-20,20,color='#059669',alpha=.10,label='±20 µT 参考带')
for arr,label,color,ls in [(slowdiff,'慢扫 1−2',COLORS[0],'-'),(fastdiff,'快扫下压 1−2',COLORS[2],'-'),(updiff,'快扫回升 1−2',COLORS[3],'--')]:ax.plot(grid,arr,label=label,color=color,ls=ls)
ax.axhline(0,color='#64748b',lw=.7);ax.set_title('C  同深度重复差值（5–15 mm）');ax.legend(fontsize=8);decorate(ax,'名义命令压深 / mm','两次响应差 / µT')
ax=axes[1,1]
for i,gap in enumerate(gaps):ax.plot(grid,gap,label=f'往返 {i+1}：回升−下压',color=COLORS[i+2])
ax.plot(grid,rate,label='慢扫 2−两次快扫下压均值',color=COLORS[1],ls=':')
ax.axhline(20,color='#64748b',ls='--',lw=.8);ax.set_title('D  方向差与扫描速率差（包含接触历史等影响）');ax.legend(fontsize=8);decorate(ax,'名义命令压深 / mm','磁响应差 / µT')
fig.suptitle('深度—磁响应对比｜方向依赖明显；重复差不能当作闭环误差',fontsize=16)
save(fig,'02_深度响应与重复性')

fig,axes=plt.subplots(1,2,figsize=(13,5.7),layout='constrained')
ax=axes[0]
for k in [1,2,3]:
 for ph,(x,y) in runs[k]['curves'].items():
  ax.plot(x,y,color=COLORS[k],ls='-' if ph=='sweep_down' else '--',label=LABELS[k]+(' 下压' if ph=='sweep_down' else ' 回升'))
for v in [60,100,150,200]:ax.axhline(v,lw=.7,ls=':',color='#94a3b8')
ax.set_xlim(2,14);ax.set_ylim(35,235);ax.set_title('目标区间：同一磁响应对应多个深度');ax.legend(fontsize=8);decorate(ax,'名义命令压深 / mm','磁响应 / µT')
sec=ax.secondary_xaxis('top',functions=(lambda d:40-d,lambda z:40-z));sec.set_xlabel('对应命令 Z / mm')
ax=axes[1]
for k in [1,2,3]:
 x,y=runs[k]['curves']['sweep_down'];g=np.arange(5,15.01,.25);slope=[]
 for center in g:
  sel=abs(x-center)<=.75;slope.append(np.polyfit(x[sel],y[sel],1)[0])
 ax.plot(g,slope,label=LABELS[k]+' 下压',color=COLORS[k])
ax.axhline(0,color='#94a3b8',lw=.7);ax.set_title('表观局部斜率：深区更陡，但并非处处单调');ax.legend(fontsize=8);decorate(ax,'拟合窗口中心压深 / mm','表观 K / (µT/mm)')
fig.suptitle('目标工作区与非线性｜局部直线拟合窗口 ±0.75 mm；尚非静态标定',fontsize=15)
save(fig,'03_目标区间与表观增益')

fig,axes=plt.subplots(3,1,figsize=(13,10),layout='constrained')
ax=axes[0]
for k in [0,1]:
 r=runs[k];x=r['raw']['t']-r['start'];m=(x>=-6)&(x<=8);ax.plot(x[m],r['raw']['By_uT'][m],lw=.85,color=COLORS[k],label=LABELS[k]+' 原始 By')
ax.axvspan(-3,0,color='#f59e0b',alpha=.1);ax.set_title('第一笔原始 By 出现约 +4910 → −4911 µT 跳变，再反向跳回');ax.legend();decorate(ax,'距 X 开始行走 / s','原始 By / µT')
ax=axes[1]
for k,r in enumerate(runs):
 m=r['scanning'];ax.plot((r['at']-r['start'])[m],r['zerr'][m],'.',ms=2.4,color=COLORS[k],label=LABELS[k])
ax.axhline(0,color='#64748b',lw=.8);ax.set_title('扫描期间实际 TCP Z − 同时刻命令 Z（异步约 10 Hz，未补偿延迟）');ax.legend(ncol=2,fontsize=8);decorate(ax,'距 X 开始行走 / s','Z 差 / mm')
ax=axes[2]
vals=[r['quality']['final_wait_mean_uT'] for r in runs]
ax.bar(LABELS,vals,color=COLORS,width=.55)
for i,v in enumerate(vals):ax.text(i,v+1,f'{v:.1f}',ha='center')
ax.set_ylim(0,65);ax.set_title('返回初始名义等待位后仍有磁残差（仅末尾约 0.18 s，不足以判定稳定漂移）');decorate(ax,None,'EMA 磁响应均值 / µT')
fig.suptitle('质量诊断｜异常峰值需排查；TCP 跟随差较小，但仍有动态滞后',fontsize=16)
save(fig,'04_异常与执行器诊断')

payload=dict(runs=[r['quality'] for r in runs],comparison_depth_grid_mm=grid.tolist(),comparisons=comparisons,target_crossings=crossings,apparent_gains=gains,
 methods={'curve':'0.25 mm command-depth bins, mean EMA magnetic response; >=5 samples/bin',
 'comparison':'linear interpolation on uniform 5..15 mm grid at 0.25 mm; equal-depth weighting',
 'crossing':'first ascending crossing after binned branch minimum; slow run1 excluded because anomalous entry; no extrapolation',
 'apparent_gain':'linear fit to binned press branch in +/-0.75 mm; not steady-state plant gain',
 'tcp':'request midpoint against interpolated host command; finite asynchronous samples; no delay compensation',
 'limits':'n=2 per protocol; rate and direction effects confounded with XY position, wetting and contact history; no magnetic delay estimate'})
(OUT/'four_sweep_metrics.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
for name,data in [('quality_metrics.csv',payload['runs']),('target_crossings.csv',crossings),('apparent_gains.csv',gains)]:
 with (OUT/name).open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
print(json.dumps({'comparisons':comparisons,'crossings':crossings,'gains':gains},ensure_ascii=False,indent=2))
