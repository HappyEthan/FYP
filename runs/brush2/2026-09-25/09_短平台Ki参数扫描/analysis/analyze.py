"""Reproduce the six-run Ki selection analysis using the predeclared protocol."""
from pathlib import Path
import csv
import hashlib
import json

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import audit

OUT=Path(__file__).resolve().parent
ROOT=OUT.parent
PROTOCOL=ROOT.parents[1]/'plans/09_短平台Ki扫描/protocol.json'
PREFIXES=['19-22-05','19-29-23','19-31-38','19-37-52','19-45-40','19-47-52']
CONDITIONS={'A':.025,'B':.05,'C':.1}
COLORS=['#2563eb','#c2410c']
plt.rcParams.update({'font.family':'Noto Sans CJK JP','axes.unicode_minus':False,'font.size':11})


def save(fig,name):
    fig.savefig(OUT/(name+'.png'),dpi=170)
    fig.savefig(OUT/(name+'.svg'))
    plt.close(fig)


def main():
    protocol=audit.read(PROTOCOL)
    windows=protocol['plateau_windows_s']|protocol['transition_windows_s']
    folders=sorted(p for p in (ROOT/'raw').iterdir() if (p/'manifest.json').exists())
    assert [p.name[:8] for p in folders]==PREFIXES
    runs=[];counts={ki:0 for ki in CONDITIONS.values()}
    for index,p in enumerate(folders):
        resolved=audit.read(p/'resolved.json');ki=resolved['control']['ki']
        assert ki==protocol['ki_sequence'][index]
        assert resolved['run_label']==f'short_ki_scan_step{index+1}_ki{ki:g}'
        counts[ki]+=1;label=next(k for k,v in CONDITIONS.items() if v==ki)+str(counts[ki])
        r=audit.load(p,label,windows);r['ki']=ki;r['step']=index+1
        r['audit']['step']=index+1
        r['audit']['primary_score_uT']=float(np.mean([r['audit']['windows'][k]['mae_uT'] for k in protocol['plateau_windows_s']]))
        use=audit.mask(r['t'],windows['return'])
        r['audit']['return_peak_overshoot_uT']=float(np.maximum(-r['e'][use],0).max())
        for key in protocol['plateau_windows_s']:assert r['audit']['windows'][key]['n']==101
        runs.append(r)
    assert list(counts.values())==[2,2,2]
    common=['strokeplan.npz','feedforward.json','settings.json','entry_profile.json','timeline.npz']
    assert len({tuple(r['audit']['source_sha256'][k] for k in common) for r in runs})==1
    fixed=[{k:v for k,v in r['audit']['control'].items() if k!='ki'} for r in runs]
    assert all(c==fixed[0] for c in fixed)
    grouped={};rrs={}
    for key,ki in CONDITIONS.items():
        rr=rrs[key]=[r for r in runs if r['ki']==ki]
        scores=[r['audit']['primary_score_uT'] for r in rr]
        group=dict(ki=ki,n=2,ids=[r['id'] for r in rr],primary_score_uT=float(np.mean(scores)),
            score_min_uT=min(scores),score_max_uT=max(scores),
            between_record_response_mae_uT=float(np.mean(abs(rr[0]['y']-rr[1]['y']))),
            baseline_B0y_difference_uT=abs(rr[0]['audit']['baseline']['B0_uT'][1]-rr[1]['audit']['baseline']['B0_uT'][1]),
            mean_integral_blocked_pct=float(np.mean([r['audit']['integral']['integral_blocked_pct'] for r in rr])),
            max_abs_integral_mm=max(r['audit']['integral']['max_abs_integral_mm'] for r in rr),
            worst_return_peak_overshoot_uT=max(r['audit']['return_peak_overshoot_uT'] for r in rr))
        for name,interval in {'all':[0,30],**windows}.items():
            errors=np.concatenate([r['e'][audit.mask(r['t'],interval)] for r in rr])
            ms=[r['audit']['metrics'] if name=='all' else r['audit']['windows'][name] for r in rr]
            group[name]=dict(mean_mae_uT=float(np.mean([m['mae_uT'] for m in ms])),
                mae_min_uT=min(m['mae_uT'] for m in ms),mae_max_uT=max(m['mae_uT'] for m in ms),
                within20_pct=float(np.mean(abs(errors)<=20)*100),pooled_p95_abs_uT=float(np.percentile(abs(errors),95)),
                mean_severe50_s=float(np.mean([m['severe50_s'] for m in ms])),mean_cap_pct=float(np.mean([m['cap_pct'] for m in ms])))
        grouped[key]=group
    summary=dict(method='Six complete hardware records only. Error=target-measured; original EMA .3; all 1501 points; no trimming, smoothing, shifts or baseline refitting.',
        primary_score=protocol['primary_score'],selection_rule=protocol['selection_rule'],windows=windows,
        protocol_sha256=hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
        actual_order=[dict(step=r['step'],id=r['id'],ki=r['ki'],time=r['folder'].name[:8]) for r in runs],
        selected_for_further_validation=.1,final_gain_determined=False,
        decision='Ki=.1 has lowest plateau score and full-path error; Ki=.05 has lower mean return-recovery error. Preserve .05 as comparison; .1 is a provisional candidate, not a final selection under the predeclared conflicting-metric rule.',
        common_input_sha256={k:runs[0]['audit']['source_sha256'][k] for k in common},
        groups=grouped,runs=[r['audit'] for r in runs])
    (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    (OUT/'protocol.json').write_bytes(PROTOCOL.read_bytes())
    ordered=[r for key in CONDITIONS for r in rrs[key]]
    with (OUT/'逐笔指标.csv').open('w',newline='',encoding='utf-8-sig') as f:
        fields=['id','step','ki','primary_score_uT','first_mae_uT','deep_mae_uT','return_platform_mae_uT','return_recovery_mae_uT','return_peak_overshoot_uT',*ordered[0]['audit']['metrics']]
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for r in ordered:
            a=r['audit'];win=a['windows']
            w.writerow(dict(id=r['id'],step=r['step'],ki=r['ki'],primary_score_uT=a['primary_score_uT'],
                first_mae_uT=win['first_160']['mae_uT'],deep_mae_uT=win['deep_240']['mae_uT'],
                return_platform_mae_uT=win['return_160']['mae_uT'],return_recovery_mae_uT=win['return']['mae_uT'],
                return_peak_overshoot_uT=a['return_peak_overshoot_uT'],**a['metrics']))
    with (OUT/'参数组指标.csv').open('w',newline='',encoding='utf-8-sig') as f:
        fields=['group','ki','primary_score_uT','worst_score_uT','full_mae_uT','within20_pct','p95_uT','return_recovery_mae_uT','worst_return_peak_overshoot_uT']
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for key,g in grouped.items():
            w.writerow(dict(group=key,ki=g['ki'],primary_score_uT=g['primary_score_uT'],worst_score_uT=g['score_max_uT'],
                full_mae_uT=g['all']['mean_mae_uT'],within20_pct=g['all']['within20_pct'],p95_uT=g['all']['pooled_p95_abs_uT'],
                return_recovery_mae_uT=g['return']['mean_mae_uT'],worst_return_peak_overshoot_uT=g['worst_return_peak_overshoot_uT']))

    fig,axes=plt.subplots(2,3,figsize=(17,9),sharex=True,sharey=True,layout='constrained')
    for col,(key,ki) in enumerate(CONDITIONS.items()):
        for row,(r,color) in enumerate(zip(rrs[key],COLORS)):
            ax=axes[row,col];ax.fill_between(r['t'],r['g']-20,r['g']+20,color='#94a3b8',alpha=.18)
            ax.plot(r['t'],r['g'],'--',color='#111827',lw=1.3,label='目标 ±20 µT');ax.plot(r['t'],r['y'],color=color,lw=1.1,label='实测 EMA')
            for interval in protocol['plateau_windows_s'].values():ax.axvspan(*interval,color='#16a34a',alpha=.08)
            a=r['audit'];ax.set(title=f"{r['id']} · Ki={ki:g} · 主评分 {a['primary_score_uT']:.2f} µT\n全程 MAE {a['metrics']['mae_uT']:.2f} · ±20内 {a['metrics']['within20_pct']:.1f}%",
                xlabel='测量时间 / s',ylabel='磁响应 / µT',xlim=(0,30),ylim=(95,280));ax.legend(fontsize=8,loc='upper left');ax.grid(alpha=.18)
    fig.suptitle('Ki 参数扫描｜相同路径与输出限制，三组各两笔\n绿色竖带为预定评分窗口，完整30 s均保留',fontsize=16)
    save(fig,'01_六笔目标跟随')

    fig,axes=plt.subplots(2,2,figsize=(14,9),layout='constrained')
    panels=[('score','平台主评分：柱为组均值，点为单笔'),('all','完整30秒 MAE'),('return','19–27秒返回过程 MAE'),('return_160','27–29秒返回平台 MAE')]
    for ax,(metric,title) in zip(axes.flat,panels):
        for i,(key,g) in enumerate(grouped.items()):
            mean=g['primary_score_uT'] if metric=='score' else g[metric]['mean_mae_uT']
            values=[r['audit']['primary_score_uT'] if metric=='score' else r['audit']['metrics']['mae_uT'] if metric=='all' else r['audit']['windows'][metric]['mae_uT'] for r in rrs[key]]
            ax.bar(i,mean,color=['#94a3b8','#2563eb','#0f766e'][i],alpha=.8,width=.6)
            ax.scatter([i-.08,i+.08],values,color='#111827',s=24,zorder=3)
            ax.text(i,max(mean,max(values))+.8,f'均值 {mean:.2f}',ha='center',fontsize=10)
        ax.set(title=title,xticks=[0,1,2],xticklabels=['Ki=0.025','Ki=0.05','Ki=0.10'],ylabel='绝对误差 / µT',ylim=(0,40 if metric=='return' else 34 if metric=='return_160' else 25));ax.grid(axis='y',alpha=.18)
    fig.suptitle('选值存在取舍：0.10平台与全程较好，0.05返回均值较低\n主评分严格沿用预定的三个平台MAE等权平均',fontsize=16)
    save(fig,'02_主评分与返回表现')

    fig,axes=plt.subplots(2,3,figsize=(17,8.5),sharex=True,sharey='row',layout='constrained')
    for col,(key,ki) in enumerate(CONDITIONS.items()):
        for r,color in zip(rrs[key],COLORS):
            a=r['audit'];axes[0,col].plot(r['t'],r['integral'],color=color,lw=1.2,label=f"{r['id']} · 冻结 {a['integral']['integral_blocked_pct']:.1f}%")
            axes[1,col].plot(r['t'],r['corr'],color=color,lw=1.0,label=f"{r['id']} · 到顶 {a['metrics']['cap_pct']:.1f}%")
        axes[0,col].axhline(.2,color='gray',ls='--');axes[0,col].axhline(-.2,color='gray',ls='--')
        axes[0,col].set(title=f'Ki={ki:g}',ylabel='积分状态 / mm',ylim=(-.22,.22))
        axes[1,col].axhline(.8,color='gray',ls='--');axes[1,col].axhline(-.8,color='gray',ls='--')
        axes[1,col].set(xlabel='测量时间 / s',ylabel='总反馈修正 / mm',ylim=(-.95,.95))
    for ax in axes.flat:ax.legend(fontsize=9);ax.grid(alpha=.18);ax.set_xlim(0,30)
    fig.suptitle('积分与限幅｜所有记录均未达到积分±0.2 mm上限\n总幅值饱和与动态约束会冻结积分，Ki增大不保证有效积分成比例增加',fontsize=16)
    save(fig,'03_积分状态与反馈限幅')

    fig,axes=plt.subplots(2,3,figsize=(17,8.5),sharex='row',sharey='row',layout='constrained')
    for col,(key,ki) in enumerate(CONDITIONS.items()):
        ax=axes[0,col];ax.axhspan(-20,20,color='#16a34a',alpha=.1);ax.axhline(0,color='gray',lw=.8)
        for r,color in zip(rrs[key],COLORS):
            ax.plot(r['t'],r['e'],color=color,lw=1.1,label=r['id'])
            axes[1,col].plot(r['actual_t'],r['zerror'],color=color,lw=.9,label=f"{r['id']} · Z MAE {r['audit']['tcp']['z_mae_mm']:.3f} mm")
        ax.set(title=f'Ki={ki:g}：返回过程',xlim=(19,30),ylim=(-65,30),xlabel='测量时间 / s',ylabel='目标－实测 / µT')
        axes[1,col].axhline(0,color='gray',lw=.8);axes[1,col].set(xlim=(0,30),xlabel='测量时间 / s',ylabel='实测TCP Z－命令Z / mm')
    for ax in axes.flat:ax.grid(alpha=.18);ax.legend(fontsize=9)
    fig.suptitle('返回过渡与实际TCP跟随｜负磁误差表示信号偏高',fontsize=16)
    save(fig,'04_返回误差与实际TCP')
    write_report(runs,rrs,grouped,protocol)
    print(json.dumps(grouped,ensure_ascii=False,indent=2))


def write_report(runs,rrs,groups,protocol):
    a,b,c=[groups[k] for k in 'ABC']
    ordered=[r for key in 'ABC' for r in rrs[key]]
    group_rows='\n'.join(f"| {g['ki']:g} | {g['primary_score_uT']:.2f} | {g['score_min_uT']:.2f}–{g['score_max_uT']:.2f} | {g['all']['mean_mae_uT']:.2f} | {g['all']['within20_pct']:.2f}% | {g['all']['pooled_p95_abs_uT']:.2f} | {g['return']['mean_mae_uT']:.2f} |" for g in groups.values())
    plateau_rows='\n'.join(f"| {g['ki']:g} | {g['first_160']['mean_mae_uT']:.2f} | {g['deep_240']['mean_mae_uT']:.2f} | {g['return_160']['mean_mae_uT']:.2f} |" for g in groups.values())
    run_rows='\n'.join(f"| {r['id']} | {r['step']} | {r['ki']:g} | {r['audit']['primary_score_uT']:.2f} | {r['audit']['metrics']['mae_uT']:.2f} | {r['audit']['windows']['return']['mae_uT']:.2f} | {r['audit']['return_peak_overshoot_uT']:.2f} | {r['audit']['metrics']['severe50_s']:.2f} |" for r in ordered)
    irows='\n'.join(f"| {r['id']} | {r['audit']['integral']['max_abs_integral_mm']:.4f} | {r['audit']['integral']['integral_blocked_pct']:.2f}% | {r['audit']['metrics']['cap_pct']:.2f}% | {r['audit']['tcp']['z_mae_mm']:.3f} | {r['audit']['tcp']['z_p95_mm']:.3f} |" for r in ordered)
    source_rows='\n'.join(f"| {r['id']} | [{r['folder'].name}](../raw/{r['folder'].name}/) |" for r in ordered)
    improvement=100*(1-c['primary_score_uT']/b['primary_score_uT'])
    return_increase=c['return']['mean_mae_uT']-b['return']['mean_mae_uT']
    report=f'''---
project: 04-robot-control
status: active
---

# 短平台 Ki 参数扫描：六笔综合分析

## 1. 选值结论

**Ki=0.10 是下一阶段优先候选，Ki=0.05 保留作对照，Ki=0.025 暂不优先。当前还不能最终锁定 Ki。**

0.10 的平台主评分为 **{c['primary_score_uT']:.2f} µT**，优于 0.05 的 **{b['primary_score_uT']:.2f} µT** 和 0.025 的 **{a['primary_score_uT']:.2f} µT**；两笔平台评分都较低，完整30 s的跟踪指标也最好。

但0.10的 **19–27 s返回过程平均MAE为 {c['return']['mean_mae_uT']:.2f} µT，0.05为 {b['return']['mean_mae_uT']:.2f} µT**，增加 {return_increase:.2f} µT；返回平台MAE也稍大。按预先约定的“指标冲突时不强行选最优”规则，这一轮可确定优先验证方向，不能宣称0.10已经通过最终选值条件。若下一笔需要一个试用值，采用0.10，继续保留相同限制，不继续向上增加Ki。

## 2. 记录质量与预定规则

六笔全部 completed / hardware，每笔1501个连续测量点、完整30 s；实际顺序 **0.05→0.025→0.10→0.10→0.025→0.05** 与方案一致。三组各两笔，全部纳入，旧批次不混入本次评分。

目标、前馈、现场设置、旋转进笔配置及执行时间线哈希在本批一致；除Ki外的控制参数完全一致：Kp=1、总修正±0.8 mm、积分±0.2 mm、修正速度2 mm/s、加速度30 mm/s²、首尾渐变1 s。各输入快照哈希、传感器引用、目标与XY时间线均通过核对。

误差定义为 **目标－实测**，正值为信号偏低，负值为偏高；使用原记录EMA α=0.3，不裁剪、平移、重滤波或重拟合基线。

主评分严格沿用方案：每笔取首次平台 **5–7 s**、深压平台 **16–18 s**、返回平台 **27–29 s** 的三个MAE等权平均，再对同一Ki的两笔等权平均。每个窗口含端点、101点。完整30 s、19–27 s返回过程、严重偏离和执行器指标作为共同检查项。

预设2 µT阈值仅用于工程上将接近的主评分视作难以区分，并在其他表现相近时倾向较小Ki；不是统计显著性阈值。0.10与0.05主评分相差 {b['primary_score_uT']-c['primary_score_uT']:.2f} µT，超过该阈值，但返回指标仍需单独评估。

## 3. 三组总览

| Ki | 平台主评分/µT | 单笔评分范围/µT | 全程MAE/µT | 全程±20内 | 合并P95/µT | 返回过程MAE/µT |
|---|---:|---:|---:|---:|---:|---:|
{group_rows}

所有MAE均按笔等权；P95合并该组全部绝对误差，未对平均曲线评分。单笔范围不是置信区间。

![六笔跟踪](01_六笔目标跟随.png)

0.10相对0.05的主评分描述性下降 **{improvement:.1f}%**。两笔0.10的主评分分别5.996和6.578 µT；0.05为6.482和13.798 µT。这表明0.10两笔都保持较好的平台表现，但并非每笔都优于表现最好的0.05。

![主评分与返回](02_主评分与返回表现.png)

## 4. 哪个平台改善、哪里有代价

| Ki | 首次160 MAE/µT | 深压240 MAE/µT | 返回160 MAE/µT |
|---|---:|---:|---:|
{plateau_rows}

### 首次平台

0.10的两笔MAE为6.58/8.66 µT，较稳定。0.025的A1平均偏低31.78 µT，整个评分窗口总修正都处于下压0.8 mm上限，积分为0且100%冻结；0.05的B2平均偏低24.61 µT，到顶74.26%、积分冻结86.14%。

这两笔的明显初始偏差不能仅解释为Ki太小：在总行程已经用尽且抗饱和冻结的时段，更大的Ki也无法立即增加允许下压量。该现象提示同时存在工作点／接触状态差异。评分仍完整保留这些笔次，不因饱和而剔除。

### 深压平台

0.10两笔MAE为3.24/3.15 µT，均低于0.05的5.74/10.20 µT以及0.025的8.47/10.41 µT。六笔深压评分窗口均未达到总幅值上限，这是0.10最一致的优势。

### 返回平台与返回过程

0.10返回平台平均MAE为 {c['return_160']['mean_mae_uT']:.2f} µT，0.05为 {b['return_160']['mean_mae_uT']:.2f} µT；两笔0.10均平均偏高约6 µT，虽然对应评分窗口均在±20 µT内，仍存在小偏差。

19–27 s返回过程：0.10两笔MAE为12.30/11.93 µT，0.05为12.89/5.94 µT。0.10的均值较差，但最差单笔略低于0.05最差笔，其最大短时偏高约36–37 µT，也低于0.05最差笔约44 µT。因此结果属于平台、平均返回表现与最差偏离之间的取舍，不能概括为“更大的Ki所有方面都更好”或“确定造成更大峰值超调”。

![返回与TCP](04_返回误差与实际TCP.png)

## 5. 积分确实增大，但尚未达到单独上限

| 记录 | 最大绝对积分/mm | 积分冻结 | 总幅值到顶 | TCP Z MAE/mm | TCP Z P95/mm |
|---|---:|---:|---:|---:|---:|
{irows}

全部积分状态、候选增量、冻结判定及最终输出逐拍重算通过；六笔都没有达到±0.2 mm积分上限。0.10最大积分约0.111/0.118 mm，深压平台约+0.103/+0.105 mm，返回平台已释放并转为约−0.048/−0.034 mm。可确认积分能在深压后释放并反向，没有积到上限后一直卡住。

0.10在下降初期仍带有正积分，直至返回过程中逐步释放；这可能参与返回滞后，但日志无法单独拆出它的因果贡献。冻结比例仍较高，动态限制与总幅值限制同时参与。增加Ki不会让有效积分严格按比例增长，当前数据也没有要求扩大±0.2 mm积分上限。

![积分与限幅](03_积分状态与反馈限幅.png)

## 6. 逐笔指标

编号A为Ki=0.025、B为0.05、C为0.10；组内按采集时间编号，步骤为实际六笔顺序。

| 记录 | 步骤 | Ki | 平台评分/µT | 全程MAE/µT | 返回过程MAE/µT | 返回最大偏高/µT | 全程>50时长/s |
|---|---:|---:|---:|---:|---:|---:|---:|
{run_rows}

0.10两笔都没有|误差|>50 µT区间。0.025两笔分别约0.74/0.76 s，0.05一笔为0、一笔约0.46 s。这一指标支持0.10减少本批严重偏离，但仍不足以替代返回过程的单独检查。

## 7. 可以相信到什么程度

- 指令修正量、修正速度与加速度在完整记录中均守住现有限制，含收尾边界。六笔TCP记录均有效、采集线程正常停止；最大控制记录间隔22.96 ms，最大单次TCP读取19.57 ms。实际TCP约10 Hz，只用于较慢位姿跟随诊断，不能排除高频误差；完整状态见summary.json。
- 参数顺序遵守了前后对称设计，但实际间隔并不相等。两笔0.10相隔6分14秒；0.025相隔16分17秒；0.05相隔25分47秒。每组两笔无法充分隔离时间、沾水和接触条件变化。
- 两笔同组实测曲线之间平均绝对差为：0.025 **{a['between_record_response_mae_uT']:.2f} µT**、0.05 **{b['between_record_response_mae_uT']:.2f} µT**、0.10 **{c['between_record_response_mae_uT']:.2f} µT**。0.10两笔更接近，但也处于更接近的采集时段。
- 对应空载B0y差分别约 **{a['baseline_B0y_difference_uT']:.2f}、{b['baseline_B0y_difference_uT']:.2f}、{c['baseline_B0y_difference_uT']:.2f} µT**。这是状态差异线索，不能直接当成幅值跟踪误差或拿来修正基线。
- 六笔都保留；未按效果挑选数据。1501个时间点不等于1501次独立实验，本批每组只有两笔。

## 8. 下一步范围

**优先用Ki=0.10作为试用候选，同时保留0.05作对照；Kp=1、总修正±0.8 mm、积分±0.2 mm及现有动态限制保持一致。** 不继续扩展完整Ki网格，也不依据平台成绩单独加到0.2或扩大积分行程。

接下来应在原难曲线上比较0.05与0.10，重点检查反复升降时的返回滞后、全程±20比例和严重偏离，同时保留逐笔差异。如果0.10的平台优势能延续且返回过程没有反复变差，才能更有依据地作为工作值；否则保留0.05。现阶段没有准确动态模型，因此本结论是实验筛选，不是理想Ki的理论解。

本次只读取原始记录并生成分析产物，没有修改实验配置、控制器或原始数据。

## 附录：来源和重现

| 记录 | 原始目录 |
|---|---|
{source_rows}

[逐笔指标](逐笔指标.csv)、[参数组指标](参数组指标.csv)、[完整统计及哈希](summary.json)、[预定方案](protocol.json)。图片另有同名SVG。

```bash
python runs/brush2/2026-09-25/09_短平台Ki参数扫描/analysis/analyze.py
```
'''
    (OUT/'分析报告.md').write_text(report)


if __name__=='__main__':
    main()
