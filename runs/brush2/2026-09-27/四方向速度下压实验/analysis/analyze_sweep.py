"""Sweep quality audit and batch-specific exploratory directional fits."""
import csv,json,hashlib,html
import numpy as np
import matplotlib.pyplot as plt
from sweep_plot_common import BASE,DIRS,SPEEDS,NAMES,COLORS,read_json
OUT=BASE/'analysis/sweep_report'
EDGES=np.arange(25.5,35.50001,.25);CENTERS=(EDGES[:-1]+EDGES[1:])/2
UNITS={'right':(1,0),'left':(-1,0),'up':(0,1),'down':(0,-1)}

def fit(x,y,kind):
 if kind=='identity':return 1.,0.
 if kind=='gain':return float(x@y/(x@x)),0.
 k,b=np.polyfit(x,y,1);return float(k),float(b)
def rmse(x):return float(np.sqrt(np.mean(np.square(x))))

def load(f):
 m=read_json(f/'manifest.json');p=read_json(f/'identification.json');s=read_json(f/'settings.json');resolved=read_json(f/'resolved.json')
 assert m['status']=='completed' and m['execution_environment']=='hardware'
 for n,h in m['sha256'].items():assert hashlib.sha256((f/n).read_bytes()).hexdigest()==h
 rows=[json.loads(l) for l in (f/'control.jsonl').read_text().splitlines()]
 sw=[r for r in rows if r['phase']=='sweep_down'];hold=[r for r in rows if r['phase']=='straight_hold']
 z=np.array([r['z_cmd_m']*1000 for r in sw]);g=np.array([r['a_control_uT'] for r in sw]);assert np.isfinite(g).all() and np.all(np.diff(z)<=1e-8)
 assert abs(z[-1]-25)<1e-6 and z[0]>35.99
 sensor=list(csv.DictReader((f/'sensor.csv').open()));lookup={int(r['seq']):r for r in sensor}
 assert {int(lookup[r['sample_seq']]['baseline_id']) for r in sw}=={m['baselines'][-1]['baseline_id']}
 assert m['baselines'][-1]['quality_axes']==[0,1]
 bins=[];counts=[]
 for lo,hi in zip(EDGES[:-1],EDGES[1:]):
  a=g[(z>=lo)&(z<hi)];assert len(a)>0;bins.append(float(np.median(a)));counts.append(len(a))
 unit=np.array(UNITS[p['direction']]);origin=np.array([s['origin_x_mm'],s['origin_y_mm']])
 hd=(np.array([[r['x_cmd_m'],r['y_cmd_m']] for r in hold])*1000-origin)@unit
 hg=np.array([r['a_control_uT'] for r in hold]);core=hg[(hd>=15)&(hd<=65)]
 tcp=list(csv.DictReader((f/'actual_tcp.csv').open()));meta=read_json(f/'actual_tcp_meta.json')
 tcp=[r for r in tcp if r['valid']=='true' and sw[0]['host_ns']<=(int(r['request_start_ns'])+int(r['request_end_ns']))/2<=sw[-1]['host_ns']]
 xyz=np.array([[float(r[k])*1000 for k in ['x_m','y_m','z_m']] for r in tcp]);distance=(xyz[:,:2]-origin)@unit
 # Geometric path comparison at measured XY, not temporal synchronization.
 t=np.clip(2*distance/150-1,0,1);ease=10*t**3-15*t**4+6*t**5
 zgeom=36-11*ease;error=xyz[:,2]-zgeom
 st=dict(run_id=m['run_id'],folder=str(f.relative_to(BASE)),batch_id=resolved['batch_id'],trial_index=resolved['trial_index'],direction=p['direction'],speed_mm_s=p['speed_mm_s'],status=m['status'],hold_median_uT=float(np.median(core)),hold_cv_pct=float(core.std()/core.mean()*100),sweep_min_uT=float(g.min()),sweep_max_uT=float(g.max()),sweep_end_uT=float(g[-1]),n_sweep=len(sw),minimum_bin_samples=min(counts),sensor_frames=len(sensor),invalid_sensor_frames=sum(r['valid']!='true' for r in sensor),max_sweep_age_ms=max(r['sample_age_s'] for r in sw)*1000,tcp_samples=meta['samples'],tcp_invalid=meta['invalid_samples'],tcp_worker_stopped=meta['worker_stopped'],tcp_path_z_error_max_mm=float(abs(error).max()),bin_downward_steps=int(np.sum(np.diff(bins[::-1])<0)),max_bin_drop_uT=float(max(0,-np.diff(bins[::-1]).min())))
 return dict(stats=st,z=z,g=g,bins=np.array(bins),counts=counts,folder=f)

def main():
 runs=[load(f.parent) for f in sorted((BASE/'raw').glob('*半程*/manifest.json'))]
 batches={}
 for r in runs:batches.setdefault(r['stats']['batch_id'],[]).append(r)
 full=[rr for rr in batches.values() if len(rr)==12];assert len(full)==1
 primary=full[0];ix={(r['stats']['direction'],r['stats']['speed_mm_s']):r for r in primary}
 assert set(ix)=={(d,v) for d in DIRS for v in SPEEDS}
 assert sorted(r['stats']['trial_index'] for r in primary)==list(range(1,13))
 assert len(runs)==12, 'Only the retained new-brush batch is expected'
 OUT.mkdir(exist_ok=True,parents=True)
 with (OUT/'run_quality.csv').open('w',newline='',encoding='utf-8-sig') as f:
  w=csv.DictWriter(f,fieldnames=list(runs[0]['stats']));w.writeheader();w.writerows(r['stats'] for r in runs)
 with (OUT/'sweep_bins.csv').open('w',newline='',encoding='utf-8-sig') as f:
  w=csv.writer(f);w.writerow(['run_id','batch_id','direction','speed_mm_s','command_z_bin_center_mm','median_uT','samples'])
  for r in runs:w.writerows([[r['stats'][k] for k in ['run_id','batch_id','direction','speed_mm_s']]+[z,g,n] for z,g,n in zip(CENTERS,r['bins'],r['counts'])])
 scores=[];models={}
 for d in DIRS:
  xx=np.concatenate([ix['right',v]['bins'] for v in SPEEDS]);yy=np.concatenate([ix[d,v]['bins'] for v in SPEEDS])
  options=[]
  for kind in ['identity','gain','affine']:
   k,b=fit(xx,yy,kind);assert k>0
   errors=[];per_speed={}
   for v in SPEEDS:
    others=[vv for vv in SPEEDS if vv!=v];tx=np.concatenate([ix['right',vv]['bins'] for vv in others]);ty=np.concatenate([ix[d,vv]['bins'] for vv in others]);kk,bb=fit(tx,ty,kind)
    assert kk>0
    e=(ix[d,v]['bins']-bb)/kk-ix['right',v]['bins'];errors.extend(e);per_speed[str(v)]=rmse(e)
   score=dict(direction=d,model=kind,k=k,b_uT=b,train_reference_rmse_uT=rmse((yy-b)/k-xx),leave_speed_out_rmse_uT=rmse(errors),leave_speed_out_max_abs_uT=float(max(abs(np.array(errors)))))
   scores.append(score);options.append(score)
  best=min(options,key=lambda a:a['leave_speed_out_rmse_uT']);models[d]=dict(best,per_speed_affine={str(v):dict(zip(['k','b_uT'],fit(ix['right',v]['bins'],ix[d,v]['bins'],'affine'))) for v in SPEEDS})
 with (OUT/'model_comparison.csv').open('w',newline='',encoding='utf-8-sig') as f:
  w=csv.DictWriter(f,fieldnames=list(scores[0]));w.writeheader();w.writerows(scores)
 def save(fig,n):fig.savefig(OUT/n,dpi=170,bbox_inches='tight');plt.close(fig)
 fig,axs=plt.subplots(1,3,figsize=(16,5),sharey=True,layout='constrained')
 for ax,v in zip(axs,[10.,15.,7.]):
  for d in DIRS:
   r=ix[d,v];ax.plot(r['z'],r['g'],color=COLORS[d],lw=1.5,label=NAMES[d])
  ax.set_xlim(36,25);ax.set_xlabel('命令 TCP Z / mm（向右下压）');ax.set_title(f'{v:g} mm/s');ax.grid(alpha=.2);ax.axvspan(36,35.5,color='gray',alpha=.1);ax.axvspan(25.5,25,color='gray',alpha=.1)
 axs[0].set_ylabel('EMA |ΔBxy| / µT');axs[0].legend()
 fig.suptitle('完整12笔 sweep：Z36 → Z25｜仅此批次用于拟合\n共同拟合区间 Z25.5–35.5，每0.25 mm分箱；Bz不参与',fontsize=14)
 save(fig,'01_sweep_curves.png')
 fig,axs=plt.subplots(2,3,figsize=(15,9),layout='constrained')
 for j,d in enumerate(['up','left','down']):
  m=models[d]
  for v in SPEEDS:
   x,y=ix['right',v]['bins'],ix[d,v]['bins'];axs[0,j].plot(x,y,'.-',label=f'{v:g} mm/s',lw=.8);axs[1,j].plot(CENTERS,(y-m['b_uT'])/m['k']-x,label=f'{v:g} mm/s')
  x=np.array([min(r['bins'].min() for r in primary if r['stats']['direction']=='right'),max(r['bins'].max() for r in primary if r['stats']['direction']=='right')]);axs[0,j].plot(x,m['k']*x+m['b_uT'],'k--',label='合并候选')
  axs[0,j].set_title(f'{NAMES[d]} {m["model"]}: k={m["k"]:.3f}, b={m["b_uT"]:.1f}');axs[0,j].set_xlabel('+X 同高度响应 / µT');axs[0,j].set_ylabel('本方向响应 / µT')
  axs[1,j].axhline(0,color='gray');axs[1,j].set_xlim(35.5,25.5);axs[1,j].set_xlabel('命令 TCP Z / mm');axs[1,j].set_ylabel('归一到+X后的拟合残差 / µT')
  for ax in axs[:,j]:ax.legend(fontsize=9);ax.grid(alpha=.2)
 fig.suptitle('同速度、同高度配对拟合与残差｜图中残差为训练残差，留速度误差另列',fontsize=14)
 save(fig,'03_calibration_residuals.png')
 st=[r['stats'] for r in primary]
 findings=[f'保留换笔后17:07开始的{len(runs)}笔完整sweep，四方向×三速度齐全；17:07之前旧笔数据及分析已按用户要求删除。',
 '完整批次每笔前75 mm保持Z36，后75 mm按平滑曲线下压至Z25。高度、沿程位置与时间耦合；连续采样点不是独立重复。',
 f'完整批次传感帧{sum(s["sensor_frames"] for s in st):,}，无效{sum(s["invalid_sensor_frames"] for s in st)}；TCP采样{sum(s["tcp_samples"] for s in st):,}，无效{sum(s["tcp_invalid"] for s in st)}；最大传感样本年龄{max(s["max_sweep_age_ms"] for s in st):.3f} ms。',
 f'以实测XY代入命令空间路径，sweep段TCP最大Z路径差{max(s["tcp_path_z_error_max_mm"] for s in st):.3f} mm。该指标不做时间同步，也不是笔毛接触深度。',
 '用户已确认17:05–17:07之间换笔，并要求以新sweep为准。当前笔以17:07起的完整12笔为唯一标定依据；旧定高及前两笔sweep属于旧笔，不能混入。连续高度覆盖更好，但仍缺少同条件独立重复。']
 findings.extend([
  '新笔左−X仍有明显非单调形状：10 mm/s在Z约33–32 mm快速增大，Z约32–29 mm形成平台，随后回落；15 mm/s在Z约29 mm附近有局部尖峰，7 mm/s相对平顺。统一线性k,b不能消除这些局部形状。',
  '左−X最大相邻0.25 mm分箱下降量：10 mm/s为24.8 µT，15 mm/s为26.4 µT；其他方向各笔最大值不超过4.4 µT。这是结构异常线索，原因未确认，未据此静默删点。',
  '跨速度通用校正未得到有力支持：+Y最佳倍率模型留速度RMSE仅由30.79降至30.01 µT（约2.5%）；左−X和下−Y校正模型均比不校正更差。因此不建议将本表作为已验证控制标定。'])
 per_speed=[]
 for d in DIRS:
  for v in SPEEDS:
   x,y=ix['right',v]['bins'],ix[d,v]['bins'];k,b=fit(x,y,'affine')
   per_speed.append(dict(direction=d,speed_mm_s=v,k=k,b_uT=b,training_reference_rmse_uT=rmse((y-b)/k-x),independently_validated=False))
  models[d]['interpretation']='reference' if d=='right' else ('weak_improvement_not_validated' if d=='up' else 'no_supported_universal_correction')
 with (OUT/'per_speed_descriptive_fits.csv').open('w',newline='',encoding='utf-8-sig') as f:
  w=csv.DictWriter(f,fieldnames=list(per_speed[0]));w.writeheader();w.writerows(per_speed)
 table=['|方向|候选模型|k|b µT|留速度RMSE：未校正→候选 µT|','|---|---|---:|---:|---:|']
 for d,m in models.items():
  null=next(s for s in scores if s['direction']==d and s['model']=='identity')
  table.append(f'|{NAMES[d]}|{m["model"]}|{m["k"]:.5f}|{m["b_uT"]:.2f}|{null["leave_speed_out_rmse_uT"]:.2f}→{m["leave_speed_out_rmse_uT"]:.2f}|')
 notes=['只用sweep_down；Z25.5–35.5 mm每0.25 mm取EMA |ΔBxy|中位数，共40格/笔。各速度及高度格等权，按同速度同Z与+X配对。两端各0.5 mm统一排除过渡/终止段；没有按拟合好坏删笔或删局部点。',
 '比较恒等、纯倍率、仿射：g方向=k*g参考+b，归一化=(g方向-b)/k。每次留出一个完整速度组，用另两个速度拟合。模型按留速度RMSE选择，选择与评价来自同一数据，仍是探索性内部检验。数百个采样点不当作独立试验，不给虚假置信区间。',
 '此处对齐命令Z，未消除传感/EMA/材料响应滞后；速度变化也改变下压速度，因此不是静态纯深度标定。没有抬起扫描，不能评估迟滞。正斜率不保证每笔局部单调，不能凭全局k,b直接反解Z。',
 '用户确认17:07前后换笔，旧笔记录已删除。表中identity表示模型检验未支持校正，不表示方向已标定等价，尤其不能把左−X的k=1当作有效标定。候选approved=false，未写入机器人配置。']
 payload=dict(status='exploratory_sweep_candidate',approved=False,primary_batch_id=st[0]['batch_id'],z_fit_range_mm=[25.5,35.5],z_bin_width_mm=.25,models=models,runs=[r['stats'] for r in runs],findings=findings,notes=notes,input_sha256={str(p.relative_to(BASE)):hashlib.sha256(p.read_bytes()).hexdigest() for r in runs for p in r['folder'].iterdir() if p.is_file()})
 (OUT/'candidate.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False))
 report='# Sweep批次分析与四方向候选标定\n\n'+'\n'.join('- '+x for x in findings)+'\n\n'+'\n'.join(table)+'\n\n'+'\n\n'.join(notes)
 captions=[('01_sweep_curves.png','完整批次响应'),('03_calibration_residuals.png','拟合与残差')]
 for f,t in captions:report+=f'\n\n## {t}\n\n![{t}]({f})'
 (OUT/'report.md').write_text(report)
 page='<html lang="zh-CN"><meta charset="utf-8"><title>Sweep分析</title><style>body{max-width:1300px;margin:auto;padding:25px;font:17px/1.7 sans-serif;color:#213547}img{width:100%}td{padding:8px;border-bottom:1px solid #ddd}</style><h1>Sweep批次分析与四方向候选标定</h1>'+''.join('<p>'+html.escape(x)+'</p>' for x in findings)+'<table>'
 for row in [table[0],*table[2:]]:page+='<tr>'+''.join('<td>'+html.escape(c)+'</td>' for c in row.strip('|').split('|'))+'</tr>'
 page+='</table>'
 for f,t in captions:page+=f'<h2>{t}</h2><img src="{f}">'
 page+=''.join('<p>'+html.escape(x)+'</p>' for x in notes)+'<a href="candidate.json">候选参数</a> · <a href="run_quality.csv">逐笔质量</a> · <a href="model_comparison.csv">模型比较</a> · <a href="sweep_bins.csv">高度分箱数据</a></html>'
 (OUT/'index.html').write_text(page)
 print('\n'.join(findings));print('\n'.join(table));print(json.dumps(models,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
