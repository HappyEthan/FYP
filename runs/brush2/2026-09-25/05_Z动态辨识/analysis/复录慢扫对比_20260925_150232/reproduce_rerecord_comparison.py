from pathlib import Path
import csv,json,hashlib,shutil
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path('/home/ethan/FYP/runs/brush2/2026-09-25/05_Z动态辨识')
OUT=ROOT/'analysis/复录慢扫对比_20260925_150232'
raw=ROOT/'raw'
folders=sorted(raw.iterdir())
plt.rcParams.update({'font.family':'Noto Sans CJK JP','axes.unicode_minus':False,'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
runs=[]
for p in folders:
 rows=[json.loads(s) for s in (p/'control.jsonl').read_text().splitlines()]
 manifest=json.loads((p/'manifest.json').read_text());profile=json.loads((p/'identification.json').read_text())
 for n,h in manifest['sha256'].items():assert hashlib.sha256((p/n).read_bytes()).hexdigest()==h
 t=np.array([r['host_ns'] for r in rows]);ph=np.array([r['phase'] for r in rows]);t=(t-t[np.flatnonzero(ph=='slide_start')[0]])/1e9
 d=np.array([r['prescribed_depth_m']*1000 for r in rows]);y=np.array([r['a_control_uT'] for r in rows])
 curves={}
 for name in ['sweep_down','sweep_up']:
  x=[];b=[]
  for lo in np.arange(2,16,.25):
   ix=(ph==name)&(d>=lo)&(d<lo+.25)
   if sum(ix)>=5:x.append(np.mean(d[ix]));b.append(np.mean(y[ix]))
  if x:curves[name]=(np.array(x),np.array(b))
 sr=list(csv.DictReader((p/'sensor.csv').open()));by=np.array([float(r['By_uT']) for r in sr]);jump=np.flatnonzero(abs(np.diff(by))>1000)
 runs.append(dict(p=p,t=t,ph=ph,d=d,y=y,curves=curves,profile=profile,manifest=manifest,
                  by_jumps=int(len(jump)),by_range=[float(min(by)),float(max(by))],
                  stream_hashes={n:hashlib.sha256((p/n).read_bytes()).hexdigest() for n in ['control.jsonl','sensor.csv','actual_tcp.csv']}))
old,second,fast1,fast2,new=runs
assert new['p'].name.startswith('15-02-32_')
assert new['profile']==second['profile']
assert new['manifest']['sha256']['settings.json']==second['manifest']['sha256']['settings.json']
grid=np.arange(5,15.001,.25)
def sample(r,ph='sweep_down',g=grid):return np.interp(g,*r['curves'][ph])
def metrics(a):return dict(mean=float(np.mean(a)),mae=float(np.mean(abs(a))),p95_abs=float(np.percentile(abs(a),95)),max_abs=float(max(abs(a))),fraction_le20=float(np.mean(abs(a)<=20)))
delta=sample(new)-sample(second)
old_delta=sample(old)-sample(second)
comp={'new_minus_slow2':metrics(delta),'old_minus_slow2':metrics(old_delta)}
mean_slow=(sample(new)+sample(second))/2
mean_fast=(sample(fast1)+sample(fast2))/2
comp['clean_slow_mean_minus_fast_down_mean']=metrics(mean_slow-mean_fast)
cross=[]
for label,r in [('正常慢扫 2',second),('复录慢扫',new)]:
 x,b=r['curves']['sweep_down'];imin=np.argmin(b);x=x[imin:];b=b[imin:]
 for target in [60,100,150,200]:
  hit=np.flatnonzero((b[:-1]<=target)&(b[1:]>=target)&(np.diff(b)>0))
  depth=None
  if len(hit):
   i=hit[0];depth=float(x[i]+(target-b[i])*(x[i+1]-x[i])/(b[i+1]-b[i]))
  cross.append(dict(run=label,target_uT=target,depth_mm=depth))
colors=['#d97706','#2563eb','#dc2626']
labels=['旧慢扫 1（异常，保留）','原正常慢扫 2','复录慢扫 15:02']
fig,axes=plt.subplots(2,2,figsize=(13,9),layout='constrained')
ax=axes[0,0]
for r,label,color in zip([old,second,new],labels,colors):
 mask=(r['t']>=-3)&(r['t']<=20)
 ax.plot(r['t'][mask],r['y'][mask],label=label,color=color,lw=1.1)
ax.set_yscale('symlog',linthresh=100);ax.axvline(3,color='#64748b',ls=':',label='3 s：开始下压扫描')
ax.set_ylim(0,10000);ax.set_title('A  复录未重现巨大进笔异常（纵轴分段对数）');ax.set_xlabel('距 X 开始行走 / s');ax.set_ylabel('磁响应 / µT');ax.legend(fontsize=8)
ax=axes[0,1]
for r,label,color in zip([old,second,new],labels,colors):
 x,b=r['curves']['sweep_down'];ax.plot(x,b,label=label,color=color,lw=1.6,alpha=.55 if r is old else 1)
ax.axhspan(60,200,color='#2563eb',alpha=.06);ax.set_ylim(0,460);ax.set_title('B  两笔正常慢扫的深度响应基本重合');ax.set_xlabel('名义压深 d=40−Z / mm');ax.set_ylabel('磁响应 / µT');ax.legend(fontsize=8)
ax=axes[1,0]
ax.axhspan(-20,20,color='#059669',alpha=.10,label='±20 µT 参考带')
ax.plot(grid,old_delta,color=colors[0],alpha=.7,label='旧异常慢扫−正常慢扫 2')
ax.plot(grid,delta,color=colors[2],label='复录−正常慢扫 2')
ax.axhline(0,color='#64748b',lw=.7);ax.set_title(f'C  复录重复差：MAE {comp["new_minus_slow2"]["mae"]:.1f} µT');ax.set_xlabel('名义压深 / mm');ax.set_ylabel('同深度响应差 / µT');ax.legend(fontsize=8)
ax=axes[1,1]
ax.plot(grid,mean_slow,color='#dc2626',label='两笔正常慢扫下压均值')
ax.plot(grid,mean_fast,color='#059669',label='两笔快扫下压均值')
ax.plot(grid,(sample(fast1,'sweep_up')+sample(fast2,'sweep_up'))/2,color='#9333ea',ls='--',label='两笔快扫回升均值')
ax.axhspan(60,200,color='#2563eb',alpha=.06);ax.set_title('D  复录后，速率/方向差仍存在');ax.set_xlabel('名义压深 / mm');ax.set_ylabel('磁响应 / µT');ax.legend(fontsize=8)
for ax in axes.flat:ax.grid(alpha=.18)
fig.suptitle('复录慢扫对比｜全部数据实际使用 Z38；Z36 尚未实测',fontsize=16)
fig.savefig(OUT/'复录慢扫更新对比.png',dpi=180,bbox_inches='tight');fig.savefig(OUT/'复录慢扫更新对比.pdf',bbox_inches='tight');plt.close(fig)
entry=np.isin(new['ph'],['rotate_contact','slide_start'])
q=dict(folder=new['p'].name,status=new['manifest']['status'],entry_z_mm=new['profile']['entry_contact_z_mm'],
 entry_peak_uT=float(max(new['y'][entry])),at_scan_start_uT=float(new['y'][np.flatnonzero(new['ph']=='sweep_down')[0]]),
 by_large_jumps=new['by_jumps'],by_range_uT=new['by_range'],comparisons=comp,target_crossings=cross,
 depth_grid_mm=grid.tolist(),sources=[dict(folder=r['p'].name,stream_sha256=r['stream_hashes']) for r in runs],
 method='0.25mm command-depth bins >=5 samples, interpolated onto uniform 5..15mm grid; EMA response; no static-gain or delay fit')
(OUT/'复录对比指标.json').write_text(json.dumps(q,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in q.items() if k not in ['sources','depth_grid_mm']},ensure_ascii=False,indent=2))
lines=['---','project: 04-robot-control','status: active','---','','# 复录慢扫更新分析','','## 数据与结论','',f'复录记录：`{new["p"].name}`，状态 hardware/completed。配置与原正常慢扫 2 相同，**实际接触高度仍为 Z38**。', '',f'- 进笔阶段峰值 **{q["entry_peak_uT"]:.1f} µT**，开始下压时 **{q["at_scan_start_uT"]:.1f} µT**；没有重现旧慢扫 1 的 8089.9 µT 峰值。',f'- 原始 By 范围为 **{q["by_range_uT"][0]:.1f}–{q["by_range_uT"][1]:.1f} µT**，无超过 1000 µT 的相邻样本突跳。','- 复录浅区仍有先回落再随深度上升的过程；“没有巨大异常”不表示 3 秒时已完全达到静态平衡。','', '## 同深度重复性（5–15 mm）','','| 指标 | 复录 vs 正常慢扫 2 | 旧异常慢扫 1 vs 正常慢扫 2 |','|---|---:|---:|']
for key,label in [('mae','平均绝对差 / µT'),('p95_abs','P95 绝对差 / µT'),('max_abs','最大绝对差 / µT')]:lines.append(f'| {label} | {comp["new_minus_slow2"][key]:.2f} | {comp["old_minus_slow2"][key]:.2f} |')
lines+=['', '![复录对比](复录慢扫更新对比.png)','', '每条曲线先按 0.25 mm 命令深度分箱，至少 5 个样本/箱，再插值到 5–15 mm、间隔 0.25 mm 的共同网格，等深度加权。这是两条实测响应曲线的差，不是闭环跟踪误差，也不是统计置信区间。','', f'两笔正常慢扫下压均值相对两笔快扫下压均值，平均差 **{comp["clean_slow_mean_minus_fast_down_mean"]["mean"]:.1f} µT**。原先观察到的上下行分支差仍存在；复录提高了慢扫重复性证据，没有消除速率/历史/纸面位置混合影响。','', '## 目标反查（仅用于选择工作点）','','| 目标 / µT | 正常慢扫 2 压深 / mm | 复录慢扫压深 / mm |','|---:|---:|---:|']
for target in [60,100,150,200]:
 vals=[r['depth_mm'] for r in cross if r['target_uT']==target]
 lines.append('| '+str(target)+' | '+' | '.join('未覆盖' if v is None else f'{v:.2f}' for v in vals)+' |')
lines+=['', '反查使用分箱曲线最低点之后的首次向上穿越，不外推。低端目标接近浅压响应下限，不能以完整目标范围均可达来解释这张表。','', '## 后续 Z36 配置','','按操作者要求，后续默认旋转接触/起扫高度改为 Z36；高位 Ry30 下降至 Z36，固定 TCP XYZ 转到 Ry15，再向 +X 行走。慢扫 Z36→24；往返 Z36→24→36。名义压深参考仍为 40 mm，因此扫描范围改为 4–16 mm。','', '**36 比 38 更低 2 mm**，本次复录数据不能证明这一改动降低挤压或异常；是否有效需新高度实测。旧 Z38 与新 Z36 的接触历史、覆盖深度及同一扫描时长下的 Z 速度均不同，应分条件比较。','', '既有 Z38 原始记录和先前报告保留，旧异常笔仍可用于异常诊断。更新后的慢扫重复性以“原正常慢扫 2 + 复录慢扫”为主。','', '原始流 SHA256 保存于 `复录对比指标.json`，未修改原始数据。']
(OUT/'复录分析报告.md').write_text('\n'.join(lines)+'\n')
shutil.copy2('/tmp/analyze_rerecorded_sweep.py',OUT/'reproduce_rerecord_comparison.py')
