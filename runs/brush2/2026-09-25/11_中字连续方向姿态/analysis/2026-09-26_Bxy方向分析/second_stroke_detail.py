"""Zoom into recorded run 9 stroke 2; uses previously verified sample export."""
import csv
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

OUT=Path(__file__).resolve().parent
with (OUT/'run9_samples.csv').open() as stream:
    rows=[r for r in csv.DictReader(stream) if r['stroke']=='2']
keys=('arc','t','theta','command_theta','phi','estimate_90_minus_phi_deg','ema_dBx_uT','ema_dBy_uT')
d={k:np.array([float(r[k]) for r in rows]) for k in keys}
valid=np.array([r['valid']=='True' for r in rows])
assert len(rows)==1017 and np.all(np.diff(d['arc'])>=0)
bins=[]
for low,high in [(15,90),(90,100),(100,105),(105,110),(110,115),(115,120),(120,130),(130,140),(140,145)]:
    mask=(d['arc']>=low)&(d['arc']<high)&valid
    assert mask.sum()>0
    bins.append(dict(arc_mm=[low,high],n=int(mask.sum()),
                     time_s=[float(d['t'][mask][0]),float(d['t'][mask][-1])],
                     **{k:float(np.median(d[k][mask])) for k in keys[2:]}))
result=dict(run=9,stroke=2,angle_unit='degree',reference='+X=0, +Y=90, -Y=-90',
            statistic='per-bin sample median, all valid moving samples including turns',
            time_origin='measure_01 start',arclength='command path accumulated distance from stroke start',
            actual_heading='asynchronous TCP interpolated to sensor time, centered 0.2s displacement',
            estimated_heading='wrap(90-phi), empirical mapping; phi=atan2(EMA dBy, EMA dBx)',bins=bins)
(OUT/'run9_stroke2_turn.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
plt.rcParams.update({'font.family':'Noto Sans CJK SC','font.size':11,
                     'axes.spines.top':False,'axes.spines.right':False})
fig,axes=plt.subplots(2,1,figsize=(11.5,8),sharex=True,layout='constrained')
m=(d['arc']>=85)&(d['arc']<=150)&valid
x=d['arc'][m]
axes[0].plot(x,d['command_theta'][m],color='.6',ls='--',lw=1.3,label='命令方向')
axes[0].plot(x,d['theta'][m],color='#20262c',lw=1.8,label='实测 TCP 方向')
axes[0].plot(x,d['estimate_90_minus_phi_deg'][m],color='#236da2',lw=2.2,label='磁推算方向：90° − φ')
axes[0].set(ylabel='行笔角 (°)',ylim=(-110,25),yticks=[-90,-60,-30,0],
            title='实际方向转到 −90° 后，磁推算仍约为 −35°，随后逐渐接近 −60°')
axes[0].legend(loc='lower left',ncol=3,fontsize=10)
axes[1].plot(x,d['ema_dBx_uT'][m],color='#236da2',lw=2,label='EMA ΔBx')
axes[1].plot(x,d['ema_dBy_uT'][m],color='#dc7726',lw=2,label='EMA ΔBy')
axes[1].set(ylabel='磁分量 (µT)',xlabel='第二笔从起点累计行程 (mm)',ylim=(-185,255),
            title='转折后 ΔBx 变得更负、ΔBy 下降；两者共同改变磁向量角')
axes[1].legend(loc='center left',ncol=2)
for ax in axes:
    ax.axvspan(100,118,color='#e7cfa4',alpha=.32)
    ax.axvline(118,color='.55',lw=1,ls=':')
    ax.set_xlim(85,150);ax.grid(alpha=.2)
axes[0].text(109,17,'主要转折区 ≈100–118 mm',ha='center',fontsize=10)
fig.suptitle('最近整字记录 · 第 9 次 · 第二笔横折局部\n基坐标 +X=0°，−Y=−90°；阴影为近似转折范围',fontsize=15)
fig.savefig(OUT/'run9_stroke2_turn.png',dpi=180)
plt.close(fig)
print(json.dumps(result,ensure_ascii=False,indent=2))
