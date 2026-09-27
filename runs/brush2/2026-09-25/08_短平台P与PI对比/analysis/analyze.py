"""Audit and analyze four short-plateau hardware runs; no hardware connection."""
from pathlib import Path
import csv
import hashlib
import json
from collections import Counter

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

OUT = Path(__file__).resolve().parent
ROOT = OUT.parent
PROTOCOL = ROOT.parents[1]/'plans/08_短平台160到240回160_P与PI/protocol.json'
PREFIXES = ['18-54-20', '18-56-22', '18-59-14', '19-02-51']
COLORS = ['#2563eb', '#60a5fa', '#c2410c', '#e9a23b']
plt.rcParams.update({'font.family':'Noto Sans CJK JP', 'axes.unicode_minus':False, 'font.size':11})


def read(path):
    return json.loads(path.read_text())


def metrics(e, t):
    a = abs(e)
    return dict(n=len(e), mae_uT=float(a.mean()), bias_uT=float(e.mean()),
        p95_abs_uT=float(np.percentile(a,95)), max_abs_uT=float(a.max()),
        within20_pct=float(np.mean(a<=20)*100), std_uT=float(e.std()),
        severe50_s=float(np.sum(np.diff(t)*(a[:-1]>50))))


def mask(t, interval):
    return (t >= interval[0]-1e-8) & (t <= interval[1]+1e-8)


def load(folder, label, windows):
    manifest, resolved = read(folder/'manifest.json'), read(folder/'resolved.json')
    assert manifest['status']=='completed' and manifest['execution_environment']=='hardware'
    for name, sha in manifest['sha256'].items():
        assert hashlib.sha256((folder/name).read_bytes()).hexdigest()==sha, (folder,name)
    allrows=[json.loads(s) for s in (folder/'control.jsonl').read_text().splitlines()]
    rows=[r for r in allrows if r['phase']=='measure_00']
    t=np.array([r['t_s'] for r in rows]); t-=t[0]
    assert len(t)==1501 and np.allclose(t,np.arange(1501)*.02,atol=1e-8,rtol=0)
    g=np.array([r['a_ref_uT'] for r in rows]); y=np.array([r['a_control_uT'] for r in rows]);e=g-y
    assert np.isfinite(np.r_[t,g,y]).all()
    assert np.allclose(e,[r['e_center_uT'] for r in rows],atol=1e-10,rtol=0)
    with np.load(folder/'timeline.npz',allow_pickle=False) as timeline:
        use=timeline['phase']=='measure_00'
        assert np.allclose(g,timeline['g_ref_uT'][use],atol=1e-9,rtol=0)
        assert np.allclose([[r['x_cmd_m'],r['y_cmd_m']] for r in rows],timeline['pose_m_rad'][use,:2],atol=1e-9,rtol=0)
    with (folder/'sensor.csv').open() as f:
        sensor={int(r['seq']):r for r in csv.DictReader(f)}
    assert all(sensor[r['sample_seq']]['valid'].lower()=='true' for r in rows)
    c=resolved['control'];mode=c['mode']
    assert (c['kp'],c['max_correction_mm'],c['max_correction_speed_mm_s'],
            c['max_correction_accel_mm_s2'],c['taper_ticks'])==(1.,.8,2.,30.,50)
    assert c['ki']==(.05 if mode=='pi' else 0.)
    corr=np.array([r['depth_fb_m'] for r in rows])*1000
    integral=np.array([r.get('i_correction_m',0.) for r in rows])*1000
    blocked=np.array([r.get('integral_blocked',False) for r in rows])
    cap=abs(corr)>=.8-1e-6
    window_stats={}
    for key,interval in windows.items():
        use=mask(t,interval)
        m=metrics(e[use],t[use]);m.update(mean_correction_mm=float(corr[use].mean()),
            cap_pct=float(cap[use].mean()*100), mean_integral_mm=float(integral[use].mean()),
            integral_start_mm=float(integral[use][0]), integral_end_mm=float(integral[use][-1]),
            integral_blocked_pct=float(blocked[use].mean()*100))
        window_stats[key]=m
    m=metrics(e,t);m.update(cap_pct=float(cap.mean()*100),
        press_cap_pct=float(np.mean(corr>=.8-1e-6)*100),lift_cap_pct=float(np.mean(corr<=-.8+1e-6)*100))
    integral_audit=None
    if mode=='pi':
        assert c['integral_limit_mm']==.2 and c['anti_windup']=='conditional'
        table=read(folder/'feedforward.json')
        scale=(table['depth_mm'][-1]-table['depth_mm'][0])/1000/(table['amplitude_uT'][-1]-table['amplitude_uT'][0])
        previous=0.
        for r in rows:
            p=c['kp']*scale*r['e_center_uT']; delta=c['ki']*scale*r['e_center_uT']*.02
            candidate=float(np.clip(previous+delta,-.0002,.0002));raw=p+candidate
            freeze=((raw>r['feedback_upper_m']+1e-12 and candidate>previous)
                    or (raw<r['feedback_lower_m']-1e-12 and candidate<previous))
            accepted=previous if freeze else candidate
            assert bool(r['integral_blocked'])==freeze
            assert abs(accepted-r['i_correction_m'])<1e-12
            assert abs(p-r['p_request_m'])<1e-12 and abs(raw-r['pi_candidate_m'])<1e-12
            assert abs(np.clip(p+accepted,r['feedback_lower_m'],r['feedback_upper_m'])-r['depth_fb_m'])<1e-12
            previous=accepted
        assert all(r['i_correction_m']==0 for r in allrows if r['phase']!='measure_00')
        counts=Counter(reason for r in rows if r['integral_blocked'] for reason in r['limit_reasons'])
        deep_i=window_stats['deep_240']['mean_integral_mm']
        d=float(np.interp(240,table['amplitude_uT'],table['depth_mm']))
        static_effect=float(np.interp(d+deep_i,table['depth_mm'],table['amplitude_uT'])-240)
        integral_audit=dict(recurrence_verified=True, max_abs_integral_mm=float(abs(integral).max()),
            integral_blocked_pct=float(blocked.mean()*100),
            stored_integral_at_cap_pct=float(np.mean(abs(integral)>=.2-1e-6)*100),
            integral_limit_flag_pct=float(np.mean([r['integral_limit_active'] for r in rows])*100),
            blocked_away_from_full_amplitude_pct=float(np.sum(blocked & ~cap)/blocked.sum()*100),
            reasons_among_blocked_counts=dict(counts), blocked_samples=int(blocked.sum()),
            table_only_deep_integral_effect_uT=static_effect,
            end_of_measurement_integral_mm=float(integral[-1]),outside_measurement_integral_zero=True)
    with (folder/'actual_tcp.csv').open() as f:
        actual=[r for r in csv.DictReader(f) if r['valid'].lower()=='true']
    origin=rows[0]['host_ns'];host=np.array([(r['host_ns']-origin)/1e9 for r in rows])
    actual_t=np.array([((int(r['request_start_ns'])+int(r['request_end_ns']))/2-origin)/1e9 for r in actual])
    use=(actual_t>=0)&(actual_t<=host[-1]);actual_t=actual_t[use]
    actual_z=np.array([float(r['z_m'])*1000 for r in actual])[use]
    zerror=actual_z-np.interp(actual_t,host,[r['z_cmd_m']*1000 for r in rows])
    allcorr=np.array([r['depth_fb_m'] for r in allrows])*1000
    assert np.max(abs(allcorr))<=.8+1e-8
    assert np.max(abs(np.diff(allcorr)))/.02<=2+1e-7
    assert np.max(abs(np.diff(allcorr,n=2)))/.02**2<=30+1e-6
    tcp=dict(z_mae_mm=float(abs(zerror).mean()),z_p95_mm=float(np.percentile(abs(zerror),95)),
        max_control_gap_ms=float(np.diff(host).max()*1000),max_sample_age_ms=max(r['sample_age_s'] for r in rows)*1000,
        metadata=read(folder/'actual_tcp_meta.json'))
    audit=dict(id=label,folder=folder.name,mode=mode,status=manifest['status'],control=c,
        baseline=manifest['baseline'],metrics=m,windows=window_stats,integral=integral_audit,tcp=tcp,
        snapshot_hashes_verified=True,measurement_sensor_references_valid=True,
        source_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()})
    return dict(id=label,folder=folder,mode=mode,t=t,g=g,y=y,e=e,corr=corr,integral=integral,
        blocked=blocked,actual_t=actual_t,zerror=zerror,audit=audit)


def save(fig,name):
    fig.savefig(OUT/(name+'.png'),dpi=170)
    fig.savefig(OUT/(name+'.svg'))
    plt.close(fig)


def write_report(runs, grouped):
    p,pi=grouped['p'],grouped['pi']
    improvement=100*(1-pi['all']['mean_mae_uT']/p['all']['mean_mae_uT'])
    rows='\n'.join(f"| {r['id']} | {r['audit']['metrics']['mae_uT']:.2f} | {r['audit']['metrics']['within20_pct']:.2f}% | {r['audit']['metrics']['p95_abs_uT']:.2f} | {r['audit']['metrics']['max_abs_uT']:.2f} | {r['audit']['metrics']['bias_uT']:+.2f} | {r['audit']['metrics']['cap_pct']:.2f}% |" for r in runs)
    window_names={'first_160':'首次160：5–7 s','deep_240':'深压240：16–18 s','return_160':'返回160：27–29 s'}
    window_rows='\n'.join(f"| {name} | {p[k]['mean_mae_uT']:.2f} | {pi[k]['mean_mae_uT']:.2f} | {p[k]['within20_pct']:.2f}% | {pi[k]['within20_pct']:.2f}% |" for k,name in window_names.items())
    detail_rows='\n'.join(f"| {r['id']} | "+' | '.join(f"{r['audit']['windows'][k]['mae_uT']:.2f} / {r['audit']['windows'][k]['bias_uT']:+.2f}" for k in window_names)+' |' for r in runs)
    irows='\n'.join(f"| {r['id']} | {r['audit']['integral']['max_abs_integral_mm']:.4f} | {r['audit']['integral']['integral_blocked_pct']:.2f}% | {r['audit']['integral']['stored_integral_at_cap_pct']:.2f}% | {r['audit']['integral']['blocked_away_from_full_amplitude_pct']:.2f}% |" for r in runs[2:])
    tcp_rows='\n'.join(f"| {r['id']} | {r['audit']['tcp']['z_mae_mm']:.3f} | {r['audit']['tcp']['z_p95_mm']:.3f} | {r['audit']['tcp']['metadata']['max_read_duration_ms']:.2f} | {r['audit']['tcp']['max_control_gap_ms']:.2f} |" for r in runs)
    sources='\n'.join(f"| {r['id']} | [{r['folder'].name}](../raw/{r['folder'].name}/) |" for r in runs)
    overshoots=[float(np.maximum(-r['e'][mask(r['t'],[19,27])],0).max()) for r in runs]
    report=f'''---
project: 04-robot-control
status: active
---

# 短平台：非线性前馈＋P 与慢 PI 对比分析

## 1. 结论

**当前慢 PI 在这四笔短平台实验中表现更好，可以保留为下一步难曲线验证的候选；暂不扩大积分上限或继续增加 Kp。** 两笔 PI 的全程 MAE 均低于两笔 P，预定深压与返回平台的组平均误差也更小。

- 全程平均 MAE：P **{p['all']['mean_mae_uT']:.2f}** → PI **{pi['all']['mean_mae_uT']:.2f} µT**，描述性降低 **{improvement:.1f}%**。
- 全程 ±20 µT 内比例：**{p['all']['within20_pct']:.2f}% → {pi['all']['within20_pct']:.2f}%**；合并 P95：**{p['all']['pooled_p95_abs_uT']:.2f} → {pi['all']['pooled_p95_abs_uT']:.2f} µT**。
- PI 积分确实生效，最大约 **0.069 mm**，未达到 ±0.2 mm 上限；返回平台时积分逐渐释放，未观察到持续积累到上限。
- 本批实际顺序为 **P1→P2→PI1→PI2**，与原方案 P→PI→PI→P 不同。模式与采集先后重合，笔间状态变化尚未隔离，不能将全部改善解释为 I 的独立因果效果。

## 2. 数据与评分口径

四笔均为 completed / hardware，每笔 **1501 个连续测量点、完整 30 s**。目标为 160 保持 8 s、3 s 升至 240、保持 8 s、3 s 返回 160、保持 8 s，X 始终以 10 mm/s 前行。

目标、前馈、现场设置、旋转进笔配置及执行时间线的文件哈希在四笔间一致；manifest 输入哈希校验通过，测量所引用的传感器记录全部有效。共同参数 Kp=1、总修正 ±0.8 mm、修正速度 2 mm/s、加速度 30 mm/s²、首尾渐变 1 s；PI 额外使用 Ki=0.05、积分限幅 ±0.2 mm、条件积分抗饱和。

本报告沿用短平台方案的符号：**误差=目标－实测**。正值表示磁响应偏低、需要增加压深；负值表示磁响应偏高。指标使用日志中的 EMA α=0.3 信号，不重滤波、不平移、不修改基线；首段及末段都计入完整 30 s 评分。

预先约定的三个平台窗口为 **5–7 s、16–18 s、27–29 s**，均包含端点，各 101 点。首次和返回平台均取进入平台后第 5–7 秒。组 MAE 为两笔等权平均；P95 合并两笔绝对误差计算，未对平均曲线评分。±20 表示采样点比例。|误差|>50 µT 的时长按采样区间左端点累积。

## 3. 完整 30 s 跟踪

| 记录 | MAE/µT | ±20 内 | P95/µT | 最大绝对误差/µT | 有符号均值/µT | 总修正到顶比例 |
|---|---:|---:|---:|---:|---:|---:|
{rows}

P1 的 |误差|>50 µT 共 0.22 s；P2 与两笔 PI 均为 0 s。PI 两笔仍有超过 20 µT 的偏离，不能据此称全程误差已控制在 ±20 µT 内。

![四笔跟踪](01_四笔目标跟随.png)

## 4. 首次平台、深压与返回平台

| 预定窗口 | P 平均 MAE/µT | PI 平均 MAE/µT | P ±20 内 | PI ±20 内 |
|---|---:|---:|---:|---:|
{window_rows}

逐笔数值（每格为 **MAE / 有符号平均误差**，单位 µT）：

| 记录 | 首次160 | 深压240 | 返回160 |
|---|---:|---:|---:|
{detail_rows}

### 首次160平台

P 的两笔差异明显：P1 已接近目标，P2 仍平均偏低 22.59 µT。PI 的两笔分别平均偏低 10.27 µT、偏高 0.59 µT。PI 组平均指标较好，但 PI1 没有优于 P1，因此首次平台改善并非逐笔一致。

### 深压240平台

两笔 PI 的 MAE 为 2.30 和 3.17 µT，均低于两笔 P 的 6.59 和 7.58 µT；PI 平均有符号偏差只有 +0.76/+1.40 µT。这是本批最一致的有利观察。四笔该窗口都没有达到总行程上限，±20 内比例均为 100%。

### 深压后返回160平台

PI 的组平均 MAE 为 8.36 µT、±20 内 99.50%，相较 P 组更好；两笔 PI 仍分别平均偏高约 4.17 和 5.81 µT。PI2 的 MAE 9.05 µT 与 P2 的 8.83 µT 接近，没有实现逐笔全面改善。

首次和返回平台位于不同 X、不同时间，且闭环命令 Z 会变化，因此本实验不是固定 Z 的独立滞回辨识。不能将两端信号差直接等同于材料滞回。

![平台指标](02_平台指标与误差.png)

## 5. 返回过程中有没有因积分变差

按预定 **19–27 s** 窗口（下降过渡加返回恢复），P 的平均 MAE 为 {p['return']['mean_mae_uT']:.2f} µT，PI 为 {pi['return']['mean_mae_uT']:.2f} µT，±20 内比例为 {p['return']['within20_pct']:.2f}% 和 {pi['return']['within20_pct']:.2f}%。但 P1/P2 分别为 28.21/5.62 µT，PI1/PI2 为 9.80/10.96 µT：PI 没有优于返回表现最好的 P2。

下降过程仍有短时信号偏高，P1/P2 最大偏高分别 **{overshoots[0]:.2f}/{overshoots[1]:.2f} µT**，PI1/PI2 为 **{overshoots[2]:.2f}/{overshoots[3]:.2f} µT**。因此可表述为“本批 PI 的平均返回表现较好，未见持续积分累积导致的失控”，不能写成“PI 消除了返回超调”。

## 6. I 是否真正起作用，抗饱和是否过于频繁

已逐拍重算两笔 PI 的 P 请求、积分候选、冻结判断、接受的积分和最终限幅输出，均与日志一致；非测量阶段积分清零符合实现。

| 记录 | 最大积分/mm | 积分冻结比例 | 积分达到 ±0.2 mm | 冻结拍中未到总幅值上限的比例 |
|---|---:|---:|---:|---:|
{irows}

两笔积分在深压平台都积累到约 0.067 mm，随后在返回过程中减小：到返回评分窗口平均约 0.008 mm；测量结束时分别约 0.0090/0.0017 mm，离开测量阶段归零。I 的方向与增减逻辑正常，未出现积到 ±0.2 mm 后无法释放的现象。

**冻结频繁主要伴随动态约束。** PI1 的 974 个冻结拍中，965 拍同时记录修正加速度限制；PI2 为 928 拍中的 911 拍。71.15%/86.64% 的冻结拍中，实际修正尚未达到 ±0.8 mm。限制原因可重叠，这些计数描述请求受约束，不代表最终命令超限。P 请求随误差快速变化，而允许发送的修正有速度、加速度及提前制动约束，积分只能在允许方向上缓慢更新。

积分上限两笔均未触发，因此增加 ±0.2 mm 上限对这两条已记录的状态轨迹没有直接作用。当前不因冻结比例高就解除抗饱和或放宽动态限制。

此外，按同一静态前馈表估算，深压平台约 0.067 mm 的积分只对应约 **1.6 µT** 的静态磁响应变化。这只是表内局部估算，不是真实动态贡献。它不足以把全程约 6.01 µT 的组平均 MAE 差完全解释为积分作用；接触状态、初始偏差、动态耦合与先后顺序仍可能参与。

![积分与抗饱和](03_积分与抗饱和.png)

## 7. 执行器跟随、采集与组内差异

| 记录 | TCP Z MAE/mm | TCP Z P95/mm | 最大单次读取/ms | 最大控制记录间隔/ms |
|---|---:|---:|---:|---:|
{tcp_rows}

四笔 TCP 均无无效读取、采集线程正常停止。记录中的反馈修正量、速度、加速度均通过 ±0.8 mm、2 mm/s、30 mm/s² 校验，包含收尾边界。离散运动校验依据计划 20 ms 周期；实际控制记录间隔另列于表中。

TCP 在读取开始/结束的中点时间，与共享主机时钟上的已发送 Z 命令插值比较。采集约 10 Hz，属于较慢位姿跟随诊断，不能排除高频误差。PI 的 Z 跟随 MAE 没有同步改善，因此磁信号指标的改善不能表述为机械臂位置跟随也变好了。

同模式两条实测曲线之间平均绝对差为 P **{p['between_record_response_mae_uT']:.2f} µT**、PI **{pi['between_record_response_mae_uT']:.2f} µT**。本批 PI 两笔更接近，但每种仅两笔，实际顺序又按模式分块，不足以证明更广泛条件下的稳定性。P1/P2 空载 B0y 相差约 46.59 µT，PI 两笔相差约 6.02 µT；这是状态变化的线索，不能将轴向基线差直接当作标量幅值误差。

![TCP与整体指标](04_TCP与整体指标.png)

## 8. 下一步建议

1. **保留当前 PI 配置进入原难曲线验证**：Kp=1、Ki=0.05、总修正 ±0.8 mm、积分 ±0.2 mm、修正速度 2 mm/s、加速度 30 mm/s²、渐变 1 s。当前结果支持继续验证这组参数，尚不支持称“前馈＋PI 已足够”。
2. 继续比较同路径、同期 P 与 PI，交错安排模式并保持进笔、沾水与纸面条件一致。短平台与原 40 s 难曲线不能直接拿总 MAE 作控制器优劣比较。
3. 若难曲线仍有明显偏离，优先区分：过渡段动态滞后、P 修正频繁触动态限制、平台持续偏差。只有确认未饱和平台仍存在可累积的稳定偏差，再判断是否需要小幅调整 Ki；本批没有证据要求扩大积分上限。

本次仅分析与生成图表，没有修改控制器、前馈表、实验参数或原始数据。

## 附录：来源与重现

| 编号 | 原始记录 |
|---|---|
{sources}

数据：[逐笔与分段指标](指标.csv)、[完整统计与来源哈希](summary.json)、[预定方案快照](protocol.json)。图片均有同名 SVG。

```bash
python runs/brush2/2026-09-25/08_短平台P与PI对比/analysis/analyze.py
```
'''
    (OUT/'分析报告.md').write_text(report)


def main():
    protocol=read(PROTOCOL)
    windows=protocol['plateau_windows_s']|protocol['transition_windows_s']
    paths=sorted(p for p in (ROOT/'raw').iterdir() if (p/'manifest.json').exists())
    assert [p.name[:8] for p in paths]==PREFIXES
    runs=[load(p,label,windows) for p,label in zip(paths,['P1','P2','PI1','PI2'])]
    common=['strokeplan.npz','feedforward.json','settings.json','entry_profile.json','timeline.npz']
    assert len({tuple(r['audit']['source_sha256'][k] for k in common) for r in runs})==1
    grouped={}
    for mode in ['p','pi']:
        rr=[r for r in runs if r['mode']==mode]
        grouped[mode]={}
        for key,interval in {'all':[0,30],**windows}.items():
            ee=np.concatenate([r['e'][mask(r['t'],interval)] for r in rr])
            ms=[r['audit']['metrics'] if key=='all' else r['audit']['windows'][key] for r in rr]
            grouped[mode][key]=dict(mean_mae_uT=float(np.mean([m['mae_uT'] for m in ms])),
                within20_pct=float(np.mean(abs(ee)<=20)*100),pooled_p95_abs_uT=float(np.percentile(abs(ee),95)),
                mean_severe50_s=float(np.mean([m['severe50_s'] for m in ms])),
                mean_cap_pct=float(np.mean([m['cap_pct'] for m in ms])))
        grouped[mode]['between_record_response_mae_uT']=float(np.mean(abs(rr[0]['y']-rr[1]['y'])))
    summary=dict(method='All four completed hardware records; error=target-measured; all 1501 measurement points. No trimming, re-filtering, time-shift, or baseline refit.',
        windows=windows, window_endpoints_inclusive=True,protocol_sha256=hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
        planned_order=protocol['sequence'],actual_order=[r['id'] for r in runs],
        caveat='Actual order P,P,PI,PI; order/contact/baseline effects not isolated; n=2 per mode. Integrator replay verifies computation, not causal tracking improvement.',
        grouped=grouped,runs=[r['audit'] for r in runs])
    (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    with (OUT/'指标.csv').open('w',newline='',encoding='utf-8-sig') as f:
        keys=['id','mode','window','mae_uT','bias_uT','p95_abs_uT','within20_pct','severe50_s','cap_pct']
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader()
        for r in runs:
            for key,m in {'all':r['audit']['metrics'],**r['audit']['windows']}.items():
                w.writerow(dict(id=r['id'],mode=r['mode'],window=key,**{k:m[k] for k in keys[3:]}))
    (OUT/'protocol.json').write_bytes(PROTOCOL.read_bytes())

    fig,axes=plt.subplots(2,2,figsize=(14,8.5),sharex=True,sharey=True,layout='constrained')
    for ax,r,color in zip(axes.flat,runs,COLORS):
        t,g=r['t'],r['g']; ax.fill_between(t,g-20,g+20,color='#94a3b8',alpha=.18)
        ax.plot(t,g,'--',color='#111827',lw=1.4,label='目标 ±20 µT')
        ax.plot(t,r['y'],color=color,lw=1.1,label='实测 EMA α=0.3')
        for interval in protocol['plateau_windows_s'].values():ax.axvspan(*interval,color='#16a34a',alpha=.09)
        m=r['audit']['metrics']
        ax.set(title=f"{r['id']} · MAE {m['mae_uT']:.2f} µT · ±20 内 {m['within20_pct']:.1f}%",
               xlabel='测量时间 / s',ylabel='磁响应 / µT',xlim=(0,30),ylim=(105,275))
        ax.legend(fontsize=9,loc='upper left');ax.grid(alpha=.18)
    fig.suptitle('短平台：非线性前馈＋P 与慢 PI｜四笔完整记录\n绿色竖带为预定评分窗口：5–7 s、16–18 s、27–29 s',fontsize=16)
    save(fig,'01_四笔目标跟随')

    fig,axes=plt.subplots(2,2,figsize=(14,8.5),layout='constrained')
    for ax,rr,name in [(axes[0,0],runs[:2],'P'),(axes[0,1],runs[2:],'PI')]:
        ax.axhspan(-20,20,color='#16a34a',alpha=.1);ax.axhline(0,color='gray',lw=.8)
        for r in rr:ax.plot(r['t'],r['e'],color=COLORS[runs.index(r)],lw=1.1,label=r['id'])
        ax.set(title=f'{name}：正误差为信号不足，负误差为信号过高',xlabel='测量时间 / s',ylabel='目标－实测 / µT',xlim=(0,30),ylim=(-65,65));ax.legend()
    x=np.arange(3);keys=list(protocol['plateau_windows_s']);labels=['首次160\n5–7 s','深压240\n16–18 s','返回160\n27–29 s']
    for ax,metric,title,ylabel in [(axes[1,0],'mae_uT','预定平台：每笔 MAE','绝对误差 / µT'),
                                 (axes[1,1],'bias_uT','预定平台：每笔有符号偏差','目标－实测均值 / µT')]:
        for i,(r,color) in enumerate(zip(runs,COLORS)):
            vals=[r['audit']['windows'][k][metric] for k in keys]
            ax.bar(x+(i-1.5)*.18,vals,.17,color=color,label=r['id'])
        ax.axhline(0,color='gray',lw=.8);ax.set(title=title,xticks=x,xticklabels=labels,ylabel=ylabel);ax.legend(ncol=4,fontsize=9)
    for ax in axes.flat:ax.grid(alpha=.18,axis='y')
    fig.suptitle('平台与误差结构｜全程指标和局部平台分开评价',fontsize=16)
    save(fig,'02_平台指标与误差')

    fig,axes=plt.subplots(3,2,figsize=(14,10),sharex=True,layout='constrained')
    for col,r,color in [(0,runs[2],COLORS[2]),(1,runs[3],COLORS[3])]:
        ax=axes[0,col];ax.plot(r['t'],r['corr'],color=color,label='实际 P+I 修正')
        ax.axhline(.8,color='gray',ls='--');ax.axhline(-.8,color='gray',ls='--')
        ax.set(title=r['id'],ylabel='总反馈修正 / mm',ylim=(-.95,.95));ax.legend(fontsize=9)
        ax=axes[1,col];ax.plot(r['t'],r['integral'],color='#0f766e',label='积分状态')
        ax.axhline(.2,color='gray',ls='--');ax.axhline(-.2,color='gray',ls='--')
        ax.set(ylabel='积分修正 / mm',ylim=(-.22,.22));ax.legend(fontsize=9)
        ax=axes[2,col]
        edges=np.arange(0,31);centers=(edges[:-1]+edges[1:])/2
        frac=[r['blocked'][(r['t']>=a-1e-8)&(r['t']<b-1e-8)].mean()*100 for a,b in zip(edges[:-1],edges[1:])]
        ax.bar(centers,frac,width=.85,color='#64748b')
        ax.set(xlabel='测量时间 / s',ylabel='每秒积分冻结比例 / %',ylim=(0,105))
    for ax in axes.flat:ax.grid(alpha=.18);ax.set_xlim(0,30)
    fig.suptitle('积分确实工作，但未达到 ±0.2 mm 上限\n总修正仍限 ±0.8 mm；积分冻结主要伴随动态约束',fontsize=16)
    save(fig,'03_积分与抗饱和')

    fig,axes=plt.subplots(2,2,figsize=(14,8.3),layout='constrained')
    for ax,rr,name in [(axes[0,0],runs[:2],'P'),(axes[0,1],runs[2:],'PI')]:
        for r in rr:ax.plot(r['actual_t'],r['zerror'],color=COLORS[runs.index(r)],lw=.9,label=f"{r['id']} MAE {r['audit']['tcp']['z_mae_mm']:.3f} mm")
        ax.axhline(0,color='gray',lw=.8);ax.set(title=f'{name}：实际 TCP Z 跟随',xlabel='测量时间 / s',ylabel='实测 Z－命令 Z / mm',xlim=(0,30));ax.legend(fontsize=9)
    for ax,window,title in [(axes[1,0],'all','完整30秒：平均 MAE 与合并 P95'),(axes[1,1],'return','19–27秒：下降与返回恢复过程')]:
        for i,mode in enumerate(['p','pi']):
            v=grouped[mode][window]
            ax.bar(i-.17,v['mean_mae_uT'],.32,color='#2563eb',label='平均 MAE' if i==0 else None)
            ax.bar(i+.17,v['pooled_p95_abs_uT'],.32,color='#94a3b8',label='合并 P95' if i==0 else None)
        ax.set(title=title,xticks=[0,1],xticklabels=['P','PI'],ylabel='绝对误差 / µT');ax.legend(fontsize=9)
    for ax in axes.flat:ax.grid(alpha=.18)
    fig.suptitle('执行器诊断与全程／返回过程比较',fontsize=16)
    save(fig,'04_TCP与整体指标')
    write_report(runs,grouped)
    print(json.dumps(grouped,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
