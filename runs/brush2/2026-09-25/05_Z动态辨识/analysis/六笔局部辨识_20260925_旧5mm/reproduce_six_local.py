from pathlib import Path
import csv,json,hashlib,shutil
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from brushbot.experiments.identification_analysis import fit_response
ROOT=Path('/home/ethan/FYP/runs/brush2/2026-09-25/05_Z动态辨识')
OUT=ROOT/'analysis/六笔局部辨识_20260925'
OUT.mkdir(exist_ok=False)
plt.rcParams.update({'font.family':'Noto Sans CJK JP','axes.unicode_minus':False,'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'savefig.dpi':180})
colors=['#2563eb','#dc2626'];runs=[];qualities=[];allplateaus=[];allsteps=[]
for index,p in enumerate(sorted((ROOT/'raw').glob('*压深*'))):
    m=json.loads((p/'manifest.json').read_text());profile=json.loads((p/'identification.json').read_text());segments=json.loads((p/'segments.json').read_text());rows=[json.loads(s) for s in (p/'control.jsonl').read_text().splitlines()]
    assert m['execution_environment']=='hardware'
    for name,h in m['sha256'].items():assert hashlib.sha256((p/name).read_bytes()).hexdigest()==h,(p,name)
    keys=['host_ns','phase','t_s','a_control_uT','prescribed_depth_m','x_cmd_m','z_cmd_m','sample_age_s','sample_seq']
    c={k:np.array([r[k] for r in rows]) for k in keys};t=(c['host_ns']-c['host_ns'][0])/1e9;d=c['prescribed_depth_m']*1000;y=c['a_control_uT'];ph=c['phase'];ticks=np.rint(c['t_s']/.02).astype(int)
    assert np.isfinite(np.r_[t,d,y]).all() and np.all(np.diff(t)>0)
    ids=np.flatnonzero(np.char.startswith(ph.astype(str),'id_'));start=t[ids[0]];end=t[ids[-1]];x=t-start
    raw=list(csv.DictReader((p/'sensor.csv').open()));sr={int(r['seq']):r for r in raw};rawt=np.array([(int(r['host_rx_ns'])-int(c['host_ns'][0]))/1e9 for r in raw]);bad=[dict(time_s=(int(r['host_rx_ns'])-int(c['host_ns'][0]))/1e9,reason=r['invalid_reason']) for r in raw if r['valid']!='true'];assert not any(start<=r['time_s']<=end for r in bad)
    # Whole run status is never changed. Both completed and post-measurement abort
    # may supply a complete, strictly verified measurement window.
    expected=np.concatenate([np.arange(s['start_tick'],s['end_tick']) for s in segments if s['kind'] in ['plateau','transition']])
    assert np.array_equal(ticks[ids],expected),(p,'measurement timeline incomplete')
    if m['status']!='completed':
        assert m['status']=='aborted' and ph[-1]=='return_high' and bad and min(b['time_s'] for b in bad)>end
    tcp_rows=list(csv.DictReader((p/'actual_tcp.csv').open()));tcp=[r for r in tcp_rows if r['valid']=='true'];at=np.array([((int(r['request_start_ns'])-int(c['host_ns'][0]))+(int(r['request_end_ns'])-int(c['host_ns'][0])))/2e9 for r in tcp]);az=np.array([float(r['z_m'])*1000 for r in tcp]);ix=np.clip(np.searchsorted(t,at,side='right')-1,0,len(t)-1);tcp_mask=np.char.startswith(ph[ix].astype(str),'id_');zerr=az-np.interp(at,t,c['z_cmd_m']*1000)
    label=f'{profile["depth_mm"]:g} mm · 第{index%2+1}笔';short=f'd{profile["depth_mm"]:g}_r{index%2+1}'
    plateaus=[]
    for s in segments:
        if s['kind']!='plateau':continue
        ii=np.flatnonzero(ph==s['id']);tail=ii[t[ii]>=t[ii[-1]]-.8];slope=float(np.polyfit(t[tail]-t[tail[0]],y[tail],1)[0]);tailtcp=(at>=t[ii[-1]]-.8)&(at<=t[ii[-1]])
        v=dict(run=label,index=s['plateau_index'],id=s['id'],depth_mm=s['depth_mm'],offset_mm=s['offset_mm'],mean_uT=float(np.mean(y[tail])),std_uT=float(np.std(y[tail])),slope_uT_s=slope,stable=bool(abs(slope)<=3),samples=len(ii),tail_samples=len(tail),start_index=int(ii[0]),end_index=int(ii[-1]),start_s=float(x[ii[0]]),end_s=float(x[ii[-1]]),actual_depth_mm=float(40-np.mean(az[tailtcp])),actual_tail_samples=int(sum(tailtcp)))
        plateaus.append(v)
    steps=[]
    for j,after in enumerate(plateaus[1:],1):
        before=plateaus[j-1];du=after['depth_mm']-before['depth_mm'];dy=after['mean_uT']-before['mean_uT'];noise=max(before['std_uT'],after['std_uT'],1.)
        lo=int(np.searchsorted(t,t[before['end_index']]-.8));hi=after['end_index']+1
        model=fit_response(t[lo:hi],d[lo:hi],y[lo:hi]);flags=[]
        if not before['stable'] or not after['stable']:flags.append('platform_not_stable')
        if abs(dy)<3*noise:flags.append('weak_excitation')
        if dy/du<=0:flags.append('nonpositive_local_gain')
        if model['grid_boundary']:flags.append('model_at_search_boundary')
        if model['r_squared'] is None or model['r_squared']<.8 or model['gain_uT_per_mm']<=0:flags.append('poor_model_fit')
        if np.any(abs(np.diff(t[lo:hi])-.02)>.01):flags.append('timing_irregularity')
        step=dict(run=label,index=j,direction='press' if du>0 else 'lift',amplitude='large' if j<=4 else 'small',delta_depth_mm=du,delta_magnetic_uT=dy,apparent_gain_uT_per_mm=dy/du,model=model,quality_flags=flags,passes_heuristics=not flags,fit_start_index=lo,fit_end_index=hi)
        steps.append(step)
    center=[q for q in plateaus if q['offset_mm']==0]
    for q in center:q['return_offset_uT']=q['mean_uT']-center[0]['mean_uT']
    pre=np.isin(ph,['rotate_contact','slide_start']);endhold=y[ph=='hold']
    quality=dict(run=label,folder=p.name,run_id=m['run_id'],status=m['status'],reason=m.get('reason'),measurement_complete=True,measurement_rows=len(ids),measurement_end_s=float(end),invalid_sensor_samples=len(bad),invalid_details=bad,tcp_valid=len(tcp),tcp_total=len(tcp_rows),control_dt_p99_ms=float(np.percentile(np.diff(t)*1000,99)),sensor_age_p99_ms=float(np.percentile(c['sample_age_s'][ids]*1000,99)),entry_peak_uT=float(max(y[pre])),
       final_wait_uT=float(np.mean(endhold)) if len(endhold) else None,baseline_B0_uT=m['baseline']['B0_uT'],
       actual_z_mae_mm=float(np.mean(abs(zerr[tcp_mask]))),actual_z_p95_mm=float(np.percentile(abs(zerr[tcp_mask]),95)),
       stable_plateaus=sum(q['stable'] for q in plateaus),passed_steps=sum(q['passes_heuristics'] for q in steps),positive_apparent_gain_steps=sum(q['apparent_gain_uT_per_mm']>0 for q in steps),
       center_span_uT=max(q['mean_uT'] for q in center)-min(q['mean_uT'] for q in center),
       source_sha256={n:hashlib.sha256((p/n).read_bytes()).hexdigest() for n in ['manifest.json','control.jsonl','sensor.csv','actual_tcp.csv','identification.json','segments.json']})
    raw_at_control={k:np.array([float(sr[int(seq)][k]) for seq in c['sample_seq'][ids]]) for k in ['Bx_uT','By_uT','dBy_uT']}
    qualities.append(quality);allplateaus+=plateaus;allsteps+=steps
    runs.append(dict(p=p,m=m,c=c,t=t,x=x,y=y,d=d,ph=ph,ids=ids,profile=profile,plateaus=plateaus,steps=steps,quality=quality,at=at,az=az,zerr=zerr,tcp_mask=tcp_mask,raw_control=raw_at_control,label=label,short=short))

pairs=[]
for i in [0,2,4]:
    a,b=runs[i:i+2];assert a['profile']==b['profile'];assert a['m']['sha256']['settings.json']==b['m']['sha256']['settings.json']
    diff=b['y'][b['ids']]-a['y'][a['ids']];bias=float(np.mean(diff));rawbydiff=b['raw_control']['By_uT']-a['raw_control']['By_uT']
    pdelta=np.array([b['plateaus'][j]['mean_uT']-a['plateaus'][j]['mean_uT'] for j in range(9)])
    pairs.append(dict(depth_mm=a['profile']['depth_mm'],mean_offset_2_minus_1_uT=bias,curve_mae_uT=float(np.mean(abs(diff))),curve_p95_abs_uT=float(np.percentile(abs(diff),95)),centered_shape_mae_uT=float(np.mean(abs(diff-bias))),plateau_mae_uT=float(np.mean(abs(pdelta))),baseline_By_change_uT=b['quality']['baseline_B0_uT'][1]-a['quality']['baseline_B0_uT'][1],raw_By_mean_change_uT=float(np.mean(rawbydiff)),raw_By_mae_uT=float(np.mean(abs(rawbydiff)))))

def save(fig,name):
    fig.savefig(OUT/(name+'.png'),bbox_inches='tight');fig.savefig(OUT/(name+'.pdf'),bbox_inches='tight');plt.close(fig)
def style(ax,xlabel=None,ylabel=None):
    ax.grid(alpha=.18)
    if xlabel:ax.set_xlabel(xlabel)
    if ylabel:ax.set_ylabel(ylabel)

# 1. Raw response and true asynchronous TCP witness, all six included.
fig,axes=plt.subplots(3,2,figsize=(15,11),sharex=True,layout='constrained')
for i,(r,ax) in enumerate(zip(runs,axes.flat)):
    sel=(r['x']>=-4)&(r['x']<=40);ax.plot(r['x'][sel],r['y'][sel],color=colors[i%2],lw=1,label='磁响应 EMA')
    for p in r['plateaus']:
        ax.axvspan(p['start_s'],p['end_s'],alpha=.065,color='#16a34a' if p['stable'] else '#f59e0b')
        ax.hlines(p['mean_uT'],p['end_s']-.8,p['end_s'],color='#111827',lw=1.8)
    ay=ax.twinx();ay.plot(r['x'][sel],r['d'][sel],color='#64748b',ls='--',lw=1,label='命令深度')
    am=(r['at']-r['t'][r['ids'][0]]>=-4)&(r['at']-r['t'][r['ids'][0]]<=40);ay.scatter(r['at'][am]-r['t'][r['ids'][0]],40-r['az'][am],s=3,color='#94a3b8',alpha=.6)
    ay.set_ylabel('名义 / 实际 TCP 压深 / mm',color='#64748b');ax.set_xlim(-4,40);ax.set_title(r['label']+('（测量完整；返回时中止）' if r['m']['status']=='aborted' else ''))
    style(ax,'距第一个平台开始 / s','磁响应 / µT')
fig.suptitle('六笔局部扰动实测｜灰虚线为命令；黑短线为末 0.8 s 均值；橙底为平台尾段未稳定',fontsize=15)
save(fig,'01_六笔轨迹与磁响应')

# 2. Reproducibility: display absolute traces and scalar-offset removed residuals.
fig,axes=plt.subplots(2,3,figsize=(15,8),layout='constrained')
for j,i in enumerate([0,2,4]):
    a,b=runs[i:i+2];ax=axes[0,j]
    for r,col in zip([a,b],colors):ax.plot(r['x'][r['ids']],r['y'][r['ids']],color=col,label=r['label'],lw=1)
    ax.set_title(f'{pairs[j]["depth_mm"]:g} mm：原始响应重复性');ax.legend(fontsize=8);style(ax,'平台段时间 / s','磁响应 / µT')
    ax=axes[1,j];diff=b['y'][b['ids']]-a['y'][a['ids']];ax.plot(a['x'][a['ids']],diff,color='#9333ea',lw=.8,label='第2笔−第1笔')
    ax.plot(a['x'][a['ids']],diff-pairs[j]['mean_offset_2_minus_1_uT'],color='#059669',lw=.7,alpha=.8,label='减去整段均值差（仅诊断）')
    ax.axhspan(-20,20,color='#059669',alpha=.07);ax.axhline(0,color='#64748b',lw=.6)
    ax.set_title(f'MAE {pairs[j]["curve_mae_uT"]:.1f}；去偏置形状 MAE {pairs[j]["centered_shape_mae_uT"]:.1f} µT');ax.legend(fontsize=8);style(ax,'平台段时间 / s','重复差 / µT')
fig.suptitle('重复性：形状相近，5 mm 两笔存在约 30 µT 固定偏置｜去偏置结果不是控制性能',fontsize=15)
save(fig,'02_重复性与固定偏置')

# 3. Same-depth history and signed apparent slopes.
fig=plt.figure(figsize=(15,10),layout='constrained');gs=fig.add_gridspec(2,3,height_ratios=[1,1.35])
for j,i in enumerate([0,2,4]):
 ax=fig.add_subplot(gs[0,j])
 for r,col in zip(runs[i:i+2],colors):
  center=[p for p in r['plateaus'] if p['offset_mm']==0];ax.plot([p['index'] for p in center],[p['mean_uT'] for p in center],'-o',color=col,label=r['label'])
 ax.set_xticks([0,2,4,6,8],['初始','大下压后','大回升后','小下压后','小回升后']);ax.tick_params(axis='x',labelrotation=20)
 ax.set_title(f'回到相同压深 {runs[i]["profile"]["depth_mm"]:g} mm');ax.legend(fontsize=8);style(ax,None,'平台末 0.8 s 磁响应 / µT')
ax=fig.add_subplot(gs[1,:]);mat=np.array([[q['apparent_gain_uT_per_mm'] for q in r['steps']] for r in runs]);im=ax.imshow(mat,cmap='RdBu_r',vmin=-90,vmax=90,aspect='auto')
for row in range(6):
 for col in range(8):ax.text(col,row,f'{mat[row,col]:.1f}',ha='center',va='center',color='white' if abs(mat[row,col])>50 else '#111827')
ax.set_yticks(range(6),[r['label'] for r in runs]);ax.set_xticks(range(8),['1 大下压','2 回到原深度','3 大回升','4 回到原深度','5 小下压','6 回到原深度','7 小回升','8 回到原深度'])
ax.set_title('相邻平台差分得到的表观 K：含明显负值，不能直接当作静态控制增益');fig.colorbar(im,ax=ax,label='Δ磁响应 / Δ命令深度，µT/mm',shrink=.8)
fig.suptitle('相同深度并不对应唯一磁响应｜接触历史、缓慢变化与纸面位置仍未分离',fontsize=16)
save(fig,'03_回程偏差与表观增益')

# 4. The most interpretable first press, alongside all 48 fit-quality results.
def model_trace(r,s):
 lo,hi=s['fit_start_index'],s['fit_end_index'];t=r['t'][lo:hi];t=t-t[0];u=r['d'][lo:hi];u=u-u[0];model=s['model'];out=np.zeros(len(t))
 for i in range(1,len(t)):
  k=np.searchsorted(t,t[i-1]-model['delay_s']+1e-10,side='right')-1
  delayed=u[k] if k>=0 else 0.;decay=np.exp(-(t[i]-t[i-1])/model['tau_s']);out[i]=decay*out[i-1]+(1-decay)*delayed
 return t,model['offset_uT']+model['gain_uT_per_mm']*out
fig=plt.figure(figsize=(15,9.5),layout='constrained');gs=fig.add_gridspec(2,3,height_ratios=[1,1.2])
for j,i in enumerate([0,2,4]):
 ax=fig.add_subplot(gs[0,j])
 for r,col in zip(runs[i:i+2],colors):
  s=r['steps'][0];lo,hi=s['fit_start_index'],s['fit_end_index'];tt,yp=model_trace(r,s);initial=r['plateaus'][0]['mean_uT']
  ax.plot(tt,r['y'][lo:hi]-initial,color=col,lw=.9,label=r['label']+' 实测')
  ax.plot(tt,yp-initial,color=col,ls='--',lw=1.6,label='一阶+延迟拟合')
 ax.set_title(f'{runs[i]["profile"]["depth_mm"]:g} mm：仅首个下压转换');ax.legend(fontsize=7);style(ax,'拟合窗口时间 / s','相对初始平台变化 / µT')
ax=fig.add_subplot(gs[1,:]);r2=np.array([[s['model']['r_squared'] for s in r['steps']] for r in runs]);im=ax.imshow(r2,vmin=0,vmax=1,cmap='YlGnBu',aspect='auto')
for row in range(6):
 for col in range(8):
  s=runs[row]['steps'][col];ax.text(col,row,f'{r2[row,col]:.2f}'+(' ✓' if s['passes_heuristics'] else ' ×'),ha='center',va='center',color='white' if r2[row,col]>.65 else '#111827')
ax.set_yticks(range(6),[r['label'] for r in runs]);ax.set_xticks(range(8),[str(i) for i in range(1,9)]);ax.set_xlabel('转换编号（×：任一质量条件未通过；✓：仅初筛通过）');ax.set_title('全部转换的 R² 与联合质量标记：高 R² 不等于模型可用');fig.colorbar(im,ax=ax,label='R²',shrink=.8)
fig.suptitle('动态拟合仅供诊断｜多数平台不稳定或增益符号异常，不能据此直接整定 PI',fontsize=16)
save(fig,'04_动态拟合与可信度')

# 5. Explain the shallow baseline offset, execution witness and aborted run.
fig,axes=plt.subplots(2,2,figsize=(14,9),layout='constrained')
for r,col in zip(runs[:2],colors):
 tt=r['x'][r['ids']];rawby=r['raw_control']['By_uT'];b0=r['quality']['baseline_B0_uT'][1]
 axes[0,0].plot(tt,rawby,color=col,lw=.6,alpha=.7,label=r['label'])
 axes[0,1].plot(tt,rawby-b0,color=col,lw=.6,alpha=.7,label=f'{r["label"]}：B0y={b0:.1f}')
axes[0,0].set_title('5 mm：原始 By 两笔接近');axes[0,1].set_title('5 mm：减去各自基线后，出现约 31 µT 偏置')
for ax in axes[0]:ax.legend(fontsize=8);style(ax,'平台段时间 / s','原始 / 差分 By / µT')
ax=axes[1,0]
for i,r in enumerate(runs):
 m=r['tcp_mask'];ax.plot(r['at'][m]-r['t'][r['ids'][0]],r['zerr'][m],'.',ms=2,alpha=.65,label=r['label'])
ax.axhline(0,color='#64748b',lw=.7);ax.legend(fontsize=7,ncol=2);ax.set_title('实际 TCP Z − 同时刻命令 Z，约 10 Hz 异步证据');style(ax,'平台段时间 / s','Z 差 / mm')
ax=axes[1,1];r=runs[3];ax.plot(r['t'],r['c']['z_cmd_m']*1000,color='#64748b',label='10 mm 第2笔命令 Z')
ax.axvspan(r['t'][r['ids'][0]],r['t'][r['ids'][-1]],color='#059669',alpha=.15,label='全部辨识平台已录完')
for bad in r['quality']['invalid_details'][:1]:ax.axvline(bad['time_s'],color='#dc2626',ls='--',label=f'传感器时间回退 {bad["time_s"]:.1f} s')
ax.set_title('10 mm 第2笔：返回阶段中止，测量窗口完整');ax.legend(fontsize=8);style(ax,'距首条控制记录 / s','命令 Z / mm')
fig.suptitle('采集与执行检查｜基线差不能当作真实接触差；中止记录按有效测量窗口使用',fontsize=15)
save(fig,'05_基线执行器与中止诊断')

payload=dict(quality=qualities,pairs=pairs,plateaus=allplateaus,transitions=allsteps,
 methods=dict(plateau_tail_s=.8,stable_slope_limit_uT_s=3,minimum_response='3*max(adjacent tail SD,1uT)',minimum_r2=.8,delay_grid_s=.02,delay_search_range_s=[0,1],tau_search_range_s=[.001,3],
  inclusion='six complete measurement windows; 10mm repeat2 retains aborted status (sensor time rollback during high return)',
  repeat='aligned identical planned id_* ticks, all 1960 measurement rows; optional mean-offset removal is diagnostic only',
  limitations='No no-excitation reference at matched X; spatial and history effects confounded; 2 repeats per depth; no independent validation.'))
(OUT/'six_local_metrics.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
for name,rr in [('quality.csv',qualities),('repeatability.csv',pairs),('plateaus.csv',allplateaus),('transitions.csv',allsteps)]:
 flat=[{k:(json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v) for k,v in r.items()} for r in rr]
 keys=list(dict.fromkeys(k for r in flat for k in r))
 with (OUT/name).open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(flat)
shutil.copy2('/tmp/analyze_six_local_runs.py',OUT/'reproduce_six_local.py')
print(json.dumps({'quality':[{k:r[k] for k in ['run','status','measurement_end_s','entry_peak_uT','actual_z_mae_mm','actual_z_p95_mm','stable_plateaus','passed_steps','positive_apparent_gain_steps','center_span_uT']} for r in qualities],'pairs':pairs,'first_steps':[dict(run=r['label'],K=r['steps'][0]['apparent_gain_uT_per_mm'],**r['steps'][0]['model']) for r in runs]},ensure_ascii=False,indent=2))
