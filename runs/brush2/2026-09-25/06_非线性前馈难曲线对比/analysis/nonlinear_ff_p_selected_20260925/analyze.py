"""Reproduce the local measured FF/P comparison; never connects to hardware."""
from pathlib import Path
import csv
import hashlib
import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
DT = .02
COLORS = ['#2563eb', '#60a5fa', '#c2410c', '#f59e0b']
plt.rcParams.update({'font.family':'Noto Sans CJK JP', 'axes.unicode_minus':False,
                     'font.size':11, 'savefig.dpi':180})


def read_json(path):
    return json.loads(path.read_text())


def duration(mask, t):
    # Left endpoint classifies each recorded 20 ms interval; no fictitious last interval.
    return float(np.sum(np.diff(t)*np.asarray(mask)[:-1]))


def longest(mask, t):
    best = current = 0.
    for yes, step in zip(mask[:-1], np.diff(t)):
        current = current+step if yes else 0.
        best = max(best, current)
    return float(best)


def stats(e, t):
    ae = np.abs(e)
    return dict(samples=len(e), mae_uT=float(ae.mean()), rmse_uT=float(np.sqrt(np.mean(e*e))),
        bias_uT=float(e.mean()), p95_abs_uT=float(np.percentile(ae,95)), max_abs_uT=float(ae.max()),
        within20_pct=float(np.mean(ae<=20)*100), severe50_s=duration(ae>50,t),
        longest_severe50_s=longest(ae>50,t))


def load(folder):
    manifest = read_json(folder/'manifest.json')
    resolved = read_json(folder/'resolved.json')
    hashes = {name:hashlib.sha256((folder/name).read_bytes()).hexdigest()
              for name in manifest['sha256']}
    assert hashes == manifest['sha256'], folder
    rows = [json.loads(s) for s in (folder/'control.jsonl').read_text().splitlines()]
    measure = [r for r in rows if r['phase']=='measure_00']
    with (folder/'sensor.csv').open() as f:
        sensors = {int(r['seq']):r for r in csv.DictReader(f)}
    assert all(sensors[r['sample_seq']]['valid'].lower()=='true' for r in measure)
    timeline = np.load(folder/'timeline.npz', allow_pickle=False)
    mt = timeline['t_s'][timeline['phase']=='measure_00']
    t = np.array([r['t_s'] for r in measure])-mt[0]
    g = np.array([r['a_ref_uT'] for r in measure])
    y = np.array([r['a_control_uT'] for r in measure])
    e = y-g
    valid = (len(measure)==2001 and len(mt)==2001 and np.isfinite(np.r_[t,g,y]).all()
        and np.allclose(t, np.arange(2001)*DT, atol=1e-8, rtol=0)
        and np.allclose(g,timeline['g_ref_uT'][timeline['phase']=='measure_00'],atol=1e-8,rtol=0)
        and np.allclose(np.array([[r['x_cmd_m'],r['y_cmd_m']] for r in measure]),
                        timeline['pose_m_rad'][timeline['phase']=='measure_00',:2],atol=1e-9,rtol=0))
    mode = 'P' if resolved['control'].get('enabled') else 'FF'
    with (folder/'actual_tcp.csv').open() as f:
        actual = [r for r in csv.DictReader(f) if r['valid'].lower()=='true']
    # Shared host monotonic clock; interpolate sent commands at read midpoint.
    origin_ns = measure[0]['host_ns']
    host_t = np.array([(r['host_ns']-origin_ns)/1e9 for r in measure])
    actual_t = np.array([((int(r['request_start_ns'])+int(r['request_end_ns']))/2-origin_ns)/1e9 for r in actual])
    use = (actual_t>=0)&(actual_t<=host_t[-1])
    actual_t = actual_t[use]
    actual_z = np.array([float(r['z_m'])*1000 for r in actual])[use]
    actual_x = np.array([float(r['x_m'])*1000 for r in actual])[use]
    command_z = np.array([r['z_cmd_m']*1000 for r in measure])
    z_error = actual_z-np.interp(actual_t,host_t,command_z)
    x_error = actual_x-np.interp(actual_t,host_t,[r['x_cmd_m']*1000 for r in measure])
    correction = np.array([r['depth_fb_m']*1000 for r in measure])
    slope = np.gradient(g,DT)
    segments = {}
    for name,mask in [('rise',slope>1),('fall',slope< -1),('plateau',abs(slope)<=1),
                      ('first_3s',t<=3+1e-8),('last_3s',t>=37-1e-8)]:
        segments[name] = dict(samples=int(mask.sum()),mae_uT=float(abs(e[mask]).mean()),bias_uT=float(e[mask].mean()))
    cap = resolved['control'].get('max_correction_mm',0.)
    cap_pct = float(np.mean(abs(correction)>=cap-1e-6)*100) if cap else 0.
    m = stats(e,t)
    m.update(amplitude_cap_pct=cap_pct, press_cap_pct=float(np.mean(correction>=cap-1e-6)*100) if cap else 0.,
        lift_cap_pct=float(np.mean(correction<=-cap+1e-6)*100) if cap else 0.,
        raw_request_outside_amplitude_pct=float(np.mean(['feedback_amplitude' in r['limit_reasons'] for r in measure])*100),
        z_tcp_mae_mm=float(abs(z_error).mean()),z_tcp_p95_mm=float(np.percentile(abs(z_error),95)),
        x_tcp_bias_mm=float(x_error.mean()),
        magnetic_sample_max_age_ms=max(r['sample_age_s'] for r in measure)*1000,
        control_max_gap_ms=float(np.diff(host_t).max()*1000),
        max_lateness_ms=max(r['lateness_s'] for r in measure)*1000,
        host_measurement_duration_s=float(host_t[-1]))
    audit = dict(folder=folder.name,mode=mode,status=manifest['status'],reason=manifest.get('reason',''),
        full_measurement=bool(valid),measurement_samples=len(measure),measurement_duration_s=float(t[-1]),
        eligible=bool(valid and manifest['status']=='completed' and manifest['execution_environment']=='hardware'),
        timeline_policy=resolved.get('timeline_policy','wall_clock'),snapshot_hashes_verified=True,
        hashes=hashes,raw_file_sha256={name:hashlib.sha256((folder/name).read_bytes()).hexdigest()
            for name in ['control.jsonl','sensor.csv','actual_tcp.csv','manifest.json']},
        measurement_sensor_references_valid=True,control=resolved['control'],baseline=manifest['baseline'],
        actual_tcp=read_json(folder/'actual_tcp_meta.json'))
    return dict(folder=folder,t=t,g=g,y=y,e=e,rows=measure,host_t=host_t,actual_t=actual_t,
        actual_z=actual_z,z_error=z_error,command_z=command_z,correction=correction,
        metrics=m,segments=segments,audit=audit)


def save(fig,name):
    fig.savefig(OUT/(name+'.png'),bbox_inches='tight')
    fig.savefig(OUT/(name+'.pdf'),bbox_inches='tight')
    plt.close(fig)


def main():
    runs = [load(p) for p in sorted((ROOT/'raw').iterdir()) if (p/'manifest.json').exists()]
    ff = [r for r in runs if r['audit']['eligible'] and r['audit']['mode']=='FF']
    pp = [r for r in runs if r['audit']['eligible'] and r['audit']['mode']=='P'][:2]
    assert len(ff)==2 and len(pp)==2, 'Require two full FF runs and two full P runs.'
    selected = ff+pp
    for r,label,color in zip(selected,['FF1 · 17:06:09','FF2 · 17:29:38','P2 · 17:20:00','P3 · 17:26:10'],COLORS):
        r.update(label=label,color=color)
    for r in selected:
        for name in ['strokeplan.npz','feedforward.json','settings.json','entry_profile.json']:
            assert r['audit']['hashes'][name]==selected[0]['audit']['hashes'][name]
    assert pp[0]['audit']['control']==pp[1]['audit']['control']
    for r in runs:
        r['audit']['selected']=r in selected
        r['audit']['selection_reason']=('完整同配置记录；按时间顺序选取' if r in selected else
            '中止且缺末尾1.80秒；仅保留为部分数据，不按误差高低筛选')

    grouped={}
    for name,group in [('FF',ff),('P',pp)]:
        pooled=np.concatenate([r['e'] for r in group])
        grouped[name]=dict(mean_run_mae_uT=float(np.mean([r['metrics']['mae_uT'] for r in group])),
            pooled_p95_abs_uT=float(np.percentile(abs(pooled),95)),within20_pct=float(np.mean(abs(pooled)<=20)*100),
            mean_run_severe50_s=float(np.mean([r['metrics']['severe50_s'] for r in group])),
            repeat_difference_mae_uT=float(np.mean(abs(group[0]['y']-group[1]['y']))),
            repeat_difference_p95_uT=float(np.percentile(abs(group[0]['y']-group[1]['y']),95)))
    table=read_json(selected[0]['folder']/'feedforward.json')
    reserve=[]
    for target in [160,180,200,220,240]:
        d=np.interp(target,table['amplitude_uT'],table['depth_mm'])
        reserve.append(dict(target_uT=target,depth_mm=float(d),
            table_lift_04mm_delta_uT=float(np.interp(d-.4,table['depth_mm'],table['amplitude_uT'])-target),
            table_press_04mm_delta_uT=float(np.interp(d+.4,table['depth_mm'],table['amplitude_uT'])-target)))
    summary=dict(selection_rule='completed hardware + full finite target/XY/time match; earliest two eligible P; no error-based selection',
        metric_definition='Full measure_00, 2001 points, 0–40 s, logged EMA alpha=.3, measured minus target. No smoothing, lag shifting or baseline re-fitting.',
        severe_definition='|error| > 50 uT, descriptive threshold, duration from left-endpoint intervals',
        tcp_definition='Actual TCP valid read midpoint, same host clock, minus linearly interpolated sent command; asynchronous 10 Hz diagnostic, not pure servo-delay estimate.',
        runs=[dict(**r['audit'],metrics=r['metrics'],segments=r['segments']) for r in runs],
        grouped=grouped,table_only_correction_estimates=reserve,
        caveats=['n=2 per mode; descriptive comparison, not causal significance.',
                 'FF1 uses earlier scheduling version but recorded measurement has all 2001 consecutive samples.',
                 'Baseline, wetting, contact history, time drift and X-dependent response are not separated.',
                 'limit_reasons describe rejected raw requests; actual cap occupancy computed from depth_fb_m.'])
    (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    with (OUT/'metrics.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['run','mode',*selected[0]['metrics']]);writer.writeheader()
        for r in selected:writer.writerow(dict(run=r['folder'].name,mode=r['audit']['mode'],**r['metrics']))

    fig,axes=plt.subplots(2,2,figsize=(14,8.8),sharex=True,sharey=True,layout='constrained')
    for ax,r in zip(axes.flat,selected):
        ax.fill_between(r['t'],r['g']-20,r['g']+20,color='#94a3b8',alpha=.18,label='目标 ±20 µT')
        ax.plot(r['t'],r['g'],color='#111827',lw=1.5,ls='--',label='目标')
        ax.plot(r['t'],r['y'],color=r['color'],lw=1.35,label='实测 EMA α=0.3')
        m=r['metrics'];ax.set_title(f"{r['label']}\nMAE {m['mae_uT']:.1f} µT · ±20 内 {m['within20_pct']:.1f}%",loc='left')
        ax.grid(alpha=.2);ax.set(xlim=(0,40),ylim=(60,300),xlabel='测量时间 / s',ylabel='磁响应 / µT')
    axes[0,0].legend(fontsize=9,loc='upper right')
    fig.suptitle('非线性前馈难曲线：两笔纯前馈 vs 两笔完整前馈＋P\n保留全部 40 s 测量段；P2、P3 按完整性选取',fontsize=16)
    save(fig,'01_四笔目标跟随')

    fig,axes=plt.subplots(2,2,figsize=(14,8.8),layout='constrained')
    for ax,group,title in [(axes[0,0],ff,'纯前馈：有符号误差'),(axes[0,1],pp,'前馈＋P：有符号误差')]:
        ax.axhspan(-20,20,color='#16a34a',alpha=.1);ax.axhline(0,color='gray',lw=.8)
        for r in group:ax.plot(r['t'],r['e'],color=r['color'],label=r['label'],lw=1.1)
        ax.set(title=title,xlim=(0,40),ylim=(-100,100),xlabel='测量时间 / s',ylabel='实测 − 目标 / µT');ax.legend(fontsize=9)
    ax=axes[1,0]
    for r in selected:
        x=np.sort(abs(r['e']));ax.plot(x,np.arange(1,len(x)+1)/len(x)*100,color=r['color'],label=r['label'])
    ax.axvline(20,color='gray',ls='--');ax.axhline(95,color='gray',ls=':')
    ax.set(title='绝对误差累计分布：越靠左越好',xlabel='绝对误差 / µT',ylabel='累计采样比例 / %',xlim=(0,100),ylim=(0,100));ax.legend(fontsize=9)
    ax=axes[1,1];x=np.arange(4)
    ax.bar(x-.18,[r['metrics']['mae_uT'] for r in selected],.35,color=COLORS,label='MAE')
    ax.bar(x+.18,[r['metrics']['p95_abs_uT'] for r in selected],.35,color=COLORS,alpha=.4,label='P95 |误差|')
    ax.set(xticks=x,xticklabels=['FF1','FF2','P2','P3'],ylabel='误差 / µT',title='逐笔指标：P 两次结果差异明显',ylim=(0,95));ax.legend()
    for i,r in enumerate(selected):
        for offset,key in [(-.18,'mae_uT'),(.18,'p95_abs_uT')]:
            value=r['metrics'][key];ax.text(i+offset,value+1,f'{value:.1f}',ha='center',fontsize=9)
    for ax in axes.flat:ax.grid(alpha=.2,axis='y')
    fig.suptitle('误差与重复性｜未剔除开始平台，未做时间平移',fontsize=16)
    save(fig,'02_误差与指标')

    fig,axes=plt.subplots(3,2,figsize=(14,10),sharex=True,layout='constrained')
    for col,r in enumerate(pp):
        ax=axes[0,col];ax.plot(r['t'],r['correction'],color=r['color'],lw=1)
        ax.axhline(.4,color='gray',ls='--');ax.axhline(-.4,color='gray',ls='--')
        ax.set(title=f"{r['label']} · 实际限幅占比 {r['metrics']['amplitude_cap_pct']:.1f}%",ylabel='反馈压深修正 / mm',ylim=(-.48,.48))
        ax=axes[1,col];ffz=r['command_z']+r['correction']
        ax.plot(r['t'],ffz,color='#94a3b8',ls='--',label='名义前馈 Z')
        ax.plot(r['t'],r['command_z'],color=r['color'],lw=1,label='最终命令 Z')
        ax.plot(r['actual_t'],r['actual_z'],color='#111827',lw=.85,alpha=.8,label='实测 TCP Z（约10 Hz）')
        ax.set(ylabel='TCP Z / mm',ylim=(26.2,30.9));ax.legend(fontsize=8)
        ax=axes[2,col];ax.plot(r['actual_t'],r['z_error'],color=r['color']);ax.axhline(0,color='gray',lw=.8)
        ax.set(xlabel='测量时间 / s',ylabel='实测 Z − 命令 Z / mm',ylim=(-.8,.8),
            title=f"Z 跟随 MAE {r['metrics']['z_tcp_mae_mm']:.3f} mm · P95 {r['metrics']['z_tcp_p95_mm']:.3f} mm")
    for ax in axes.flat:ax.grid(alpha=.2);ax.set_xlim(0,40)
    fig.suptitle('P 修正与执行器跟随｜正修正表示下压，负修正表示抬高\nTCP 按读取中点与命令的主机时间对齐；未补偿滞后',fontsize=15)
    save(fig,'03_P限幅与实际Z')

    table_rows='\n'.join(f"| {r['label']} | {r['metrics']['mae_uT']:.2f} | {r['metrics']['p95_abs_uT']:.2f} | {r['metrics']['within20_pct']:.2f}% | {r['metrics']['bias_uT']:+.2f} | {r['metrics']['severe50_s']:.2f} | {r['metrics']['amplitude_cap_pct']:.2f}% |" for r in selected)
    improvement=100*(1-grouped['P']['mean_run_mae_uT']/grouped['FF']['mean_run_mae_uT'])
    report=f'''---
project: 04-robot-control
status: active
---

# 非线性前馈难曲线：四笔完整记录分析

## 选取与计算口径

使用 FF 17:06:09、17:29:38，以及 P 17:20:00、17:26:10（目录第2、3次）。这四笔均 completed、hardware，2001 个连续测量点、完整 40 s，目标及 XY 与快照一致，所有 manifest 输入哈希验证通过。目标、前馈表、现场设置、旋转进笔配置哈希一致；两笔 P 参数完全一致：Kp=2、Ki=0、±0.4 mm。

P 17:11:37 因 acceleration_limit 中止，仅 38.20 s、1911 点，保留为部分记录，不纳入主比较。筛选只按完整性、配置、记录质量，未按误差挑选。部分笔自身 MAE 24.37 µT 也没有用于替换较差的完整 P2。

全部指标使用 measure_00 的原始记录 a_control_uT（EMA α=0.3），误差=实测−目标；未去掉前3秒、未重新滤波、未平移曲线、未重拟合基线。±20 为采样点比例；严重偏离描述阈值定义为 |误差|>50 µT，持续时间按左端采样对应区间求和，总计40 s。完整2001点均参与点统计。

## 四笔结果

| 笔次 | MAE / µT | P95绝对误差 / µT | ±20内 | 平均有符号误差 / µT | >50总时长 / s | 实际±0.4 mm限幅占比 |
|---|---:|---:|---:|---:|---:|---:|
{table_rows}

![四笔跟随](01_四笔目标跟随.png)

## 模式汇总与重复性

- 两笔等权平均 MAE：FF **{grouped['FF']['mean_run_mae_uT']:.2f}** → P **{grouped['P']['mean_run_mae_uT']:.2f} µT**，描述性下降 **{improvement:.1f}%**。
- ±20内：FF **{grouped['FF']['within20_pct']:.2f}%** → P **{grouped['P']['within20_pct']:.2f}%**。尚未达到“大部分误差≤20 µT”。
- 合并各模式4002点得到的 P95：FF {grouped['FF']['pooled_p95_abs_uT']:.2f}、P {grouped['P']['pooled_p95_abs_uT']:.2f} µT；这是合并分位数，不是两笔 P95 的平均。
- 同一时刻两次实测曲线之间的 MAE：FF **{grouped['FF']['repeat_difference_mae_uT']:.2f} µT**，P **{grouped['P']['repeat_difference_mae_uT']:.2f} µT**。两次重复不足以估计稳定的总体方差；不能给出因果改善或统计显著性结论。
- FF1 采用修复前调度，其测量实际记录仍为完整连续2001点；其余三笔采用 sequential_20ms。记录完整性通过，但版本差异保留在 summary.json，不能称所有软件条件完全相同。

![误差与指标](02_误差与指标.png)

## 为什么 P 改善不稳定

1. **修正范围经常耗尽。** P2/P3 实际 |depth_fb|达到0.4 mm的比例分别 {pp[0]['metrics']['amplitude_cap_pct']:.1f}%/{pp[1]['metrics']['amplitude_cap_pct']:.1f}%。P2下压上限占比 {pp[0]['metrics']['press_cap_pct']:.1f}%，整体仍偏低 {abs(pp[0]['metrics']['bias_uT']):.1f} µT。limit_reasons 中 acceleration、z_speed 等表示原始请求落在约束外，并不等于最终已发送指令违规。
2. **按本表预测，±0.4 mm只对应约6–15 µT调整量。** 这是同一静态表的插值估算，不是这四笔新测出的局部增益；实际接触和动态下可能不同。Kp=2时原始请求约在5 µT误差处即触幅值限幅，继续增大Kp对已到幅值上限的部分无法增加修正行程。
3. **同样目标、同样高度，笔内及笔间信号变化大。** 两笔FF首次160 µT平台的平均误差分别 {ff[0]['segments']['first_3s']['bias_uT']:+.1f}/{ff[1]['segments']['first_3s']['bias_uT']:+.1f} µT；末次160 µT平台为 {ff[0]['segments']['last_3s']['bias_uT']:+.1f}/{ff[1]['segments']['last_3s']['bias_uT']:+.1f} µT。仅以Z为输入的静态表在这组轨迹中无法同时解释两端；加载历史、X位置、含水量、纸面和基线均可能参与，现有数据不能拆分因果。
4. **升降方向存在误差差异。** 目标导数>1 µT/s为上升、<-1为下降，其他为近平台（阈值仅用于分组）。P2上升/下降平均误差 {pp[0]['segments']['rise']['bias_uT']:+.1f}/{pp[0]['segments']['fall']['bias_uT']:+.1f} µT；P3为 {pp[1]['segments']['rise']['bias_uT']:+.1f}/{pp[1]['segments']['fall']['bias_uT']:+.1f} µT。方向相关误差与动态滞后相容，但本实验不能单独辨识纯延迟或回滞。

## 实际 TCP 与采集质量

四笔实际TCP均无无效记录；磁测量最大样本年龄均≤1.21 ms，控制记录最大相邻主机时间间隔均≤21.03 ms；修复后的两笔P均完成抬笔回程。未发现这几笔因姿态读取导致的中止或明显控制掉拍。

TCP采用读取开始/结束中点时间，在共享host_monotonic时钟上对已发送Z命令线性插值。约10 Hz只能诊断较慢跟随，不能排除高频误差，也不把其偏差直接解释成纯伺服延迟。

- FF1/FF2 Z跟随MAE：{ff[0]['metrics']['z_tcp_mae_mm']:.3f}/{ff[1]['metrics']['z_tcp_mae_mm']:.3f} mm。
- P2/P3 Z跟随MAE：{pp[0]['metrics']['z_tcp_mae_mm']:.3f}/{pp[1]['metrics']['z_tcp_mae_mm']:.3f} mm；P95：{pp[0]['metrics']['z_tcp_p95_mm']:.3f}/{pp[1]['metrics']['z_tcp_p95_mm']:.3f} mm，转换段的实际跟随仍有偏差。
- P2/P3空载B0y分别 {pp[0]['audit']['baseline']['B0_uT'][1]:.2f}/{pp[1]['audit']['baseline']['B0_uT'][1]:.2f} µT。这是不同基线快照，不能把差值直接当作磁幅值跟踪误差，更不能据此认定应手工改基线。

![P限幅与实际Z](03_P限幅与实际Z.png)

## 下一步优先级

1. 先复核160/200/240 µT短平台在同一进笔、固定沾水流程下的笔间偏差，并记录首次与经历深压后的返回平台；用实测判断是否需每笔工作点校正或区分加载/回升。
2. 再依据新实测局部增益评估所需修正行程，并设置有依据的深度、速度和加速度限制；当前数据不能直接证明更大的修正范围可用。
3. 在修正行程和重复性得到支持后，再测试局部增益调度P或带抗饱和的慢积分。现有结果不足以判定“前馈＋PI一定足够”，也不支持仅增大Kp就能达标。

本次只读取原始记录并生成分析文件，没有修改表、控制器参数、实验脚本或raw数据。

完整审计与分段指标见 [summary.json](summary.json)，四笔指标见 [metrics.csv](metrics.csv)。所有PNG另附同名PDF。重现：在任意目录运行 `python /home/ethan/FYP/runs/brush2/2026-09-25/06_非线性前馈难曲线对比/analysis/nonlinear_ff_p_selected_20260925/analyze.py`。
'''
    (OUT/'分析报告.md').write_text(report)
    print(json.dumps(dict(grouped=grouped,mae_improvement_pct=improvement,selected=[r['folder'].name for r in selected]),ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
