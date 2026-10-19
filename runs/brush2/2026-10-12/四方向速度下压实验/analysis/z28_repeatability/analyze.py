"""Reproduce the 2026-10-12 Z28 comparison without modifying raw runs."""
from pathlib import Path
import csv
import hashlib
import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.ticker import FormatStrFormatter
import numpy as np

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[3]
font_manager.fontManager.addfont('/usr/local/share/fonts/msyh.ttf')
plt.rcParams.update({'font.family': 'Microsoft YaHei', 'axes.unicode_minus': False,
                     'font.size': 11, 'axes.titlesize': 13, 'axes.labelsize': 11,
                     'legend.fontsize': 9, 'savefig.dpi': 180})
COLORS = ['#2563eb', '#d97706', '#059669']
NOTES = ['第1次：基准记录', '第2次：手动调整磁毛', '第3次：板子重新上电']


def stats(values):
    v = np.asarray(values, dtype=float)
    assert len(v) and np.isfinite(v).all()
    return dict(n=len(v), mean=float(v.mean()), median=float(np.median(v)),
                sample_std=float(v.std(ddof=1)), cv_pct=float(v.std(ddof=1)/v.mean()*100))


def load(folder, date, index):
    manifest = json.loads((folder/'manifest.json').read_text())
    assert manifest['status'] == 'completed'
    for name, expected in manifest['sha256'].items():
        assert hashlib.sha256((folder/name).read_bytes()).hexdigest() == expected, name
    profile = json.loads((folder/'identification.json').read_text())
    setup = json.loads((folder/'settings.json').read_text())
    controls = [json.loads(line) for line in (folder/'control.jsonl').read_text().splitlines()]
    sensors = list(csv.DictReader((folder/'sensor.csv').open()))
    assert all(row['valid'] == 'true' for row in sensors)
    source_by_seq = {int(row['seq']): row for row in sensors}
    straight = [row for row in controls if row['phase'] == 'straight_hold']
    rotation = [row for row in controls if row['phase'] == 'rotate_contact']
    assert 'load_start' not in {row['phase'] for row in controls}
    assert len(manifest['baselines']) == 2
    assert {source_by_seq[row['sample_seq']]['baseline_id'] for row in straight+rotation} == {'1'}
    filtered = None
    vectors = {}
    for row in sensors:
        if row['baseline_id'] != '1':
            continue
        value = np.array([float(row[f'dB{axis}_uT']) for axis in 'xyz'])
        filtered = value if filtered is None else .3*value+.7*filtered
        vectors[int(row['seq'])] = filtered.copy()
    replay_error = max(abs(np.hypot(*vectors[row['sample_seq']][:2])-row['a_control_uT'])
                       for row in straight+rotation)
    assert replay_error < 1e-8
    distance = np.array([row['y_cmd_m']*1000-setup['origin_y_mm'] for row in straight])
    signal = np.array([row['a_control_uT'] for row in straight])
    middle = (distance >= 10-1e-8) & (distance <= 40+1e-8)
    tail = distance >= 40-1e-8
    end_rotation = [row['a_control_uT'] for row in rotation
                    if row['t_s'] >= rotation[-1]['t_s']-.3-1e-9]
    actual = [row for row in csv.DictReader((folder/'actual_tcp.csv').open()) if row['valid']=='true']
    actual = [row for row in actual if straight[0]['host_ns'] <= int(row['request_end_ns']) <= straight[-1]['host_ns']]
    actual_distance = np.array([float(row['y_m'])*1000-setup['origin_y_mm'] for row in actual])
    actual_z = np.array([float(row['z_m'])*1000 for row in actual])
    actual_mid = (actual_distance >= 10) & (actual_distance <= 40)
    components = np.array([vectors[row['sample_seq']][:2] for row in straight])
    b0 = manifest['baselines'][-1]
    metric = dict(date=date, repeat=index, raw_folder=str(folder),
                  middle_mean_uT=stats(signal[middle])['mean'],
                  middle_median_uT=stats(signal[middle])['median'],
                  middle_sample_std_uT=stats(signal[middle])['sample_std'],
                  rotation_end_mean_uT=stats(end_rotation)['mean'],
                  tail_mean_uT=stats(signal[tail])['mean'], tail_cv_pct=stats(signal[tail])['cv_pct'],
                  actual_middle_z_mean_mm=float(actual_z[actual_mid].mean()),
                  actual_middle_z_min_mm=float(actual_z[actual_mid].min()),
                  actual_middle_z_max_mm=float(actual_z[actual_mid].max()),
                  sensor_first_uptime_s=int(sensors[0]['sensor_t_us'])/1e6,
                  baseline_Bxy_uT=b0['B0_uT'][:2], baseline_std_Bxy_uT=b0['std_uT'][:2],
                  middle_filtered_Bxy_mean_uT=components[middle].mean(axis=0).tolist(),
                  sensor_samples=len(sensors), invalid_sensor_samples=0,
                  baseline_count=2, active_baseline_id=1,
                  replay_max_error_uT=float(replay_error),
                  max_lateness_ms=max(row['lateness_s'] for row in controls)*1000,
                  profile_sha256=manifest['sha256']['identification.json'],
                  setup_sha256=manifest['sha256']['settings.json'],
                  sources={name: hashlib.sha256((folder/name).read_bytes()).hexdigest()
                           for name in ('manifest.json','control.jsonl','sensor.csv','actual_tcp.csv')})
    if date=='2026-10-12':
        metric['operator_note']=NOTES[index-1]
    return dict(metric=metric, x=distance, a=signal, xy=components,
                rotation_t=np.array([row['t_s'] for row in rotation])-8.9,
                rotation_a=np.array([row['a_control_uT'] for row in rotation]),
                actual_x=actual_distance, actual_z=actual_z)


def frame(ax):
    ax.grid(alpha=.18)
    ax.spines[['top','right']].set_visible(False)


def main():
    all_runs = []
    for date in ('2026-10-10', '2026-10-12'):
        folders = sorted((BASE/date/'四方向速度下压实验/raw').glob('*_定高_up_Z28到28_速度10_第*次'))
        assert len(folders)==(6 if date=='2026-10-10' else 3)
        all_runs.extend(load(folder,date,index) for index,folder in enumerate(folders,1))
    assert len({run['metric']['profile_sha256'] for run in all_runs})==1
    assert len({run['metric']['setup_sha256'] for run in all_runs})==1
    latest=all_runs[-3:]
    metrics=[run['metric'] for run in all_runs]
    today=np.array([run['metric']['middle_mean_uT'] for run in latest])
    groups=[stats([run['middle_mean_uT'] for run in metrics[start:start+3]]) for start in (0,3,6)]
    grid=np.linspace(10,40,301)
    curves=[np.interp(grid,run['x'],run['a']) for run in latest]
    pairwise=[]
    for i,j in ((0,1),(0,2),(1,2)):
        diff=curves[j]-curves[i]
        pairwise.append(dict(repeats=[i+1,j+1], mean_difference_uT=float(diff.mean()),
                             rmse_uT=float(np.sqrt(np.mean(diff**2))),
                             centered_rmse_uT=float(np.sqrt(np.mean((diff-diff.mean())**2)))))
    report=dict(signal='norm of EMA(B-B0)xy, alpha=0.3; uT, not force in N',
                method='Same commanded path window 10-40 mm; tail 40-50 mm; rotation final 0.3 s. No per-run normalization or alignment shift. Sample SD uses ddof=1. Time samples are not independent experimental repetitions. Today includes different preparation operations, so CV is descriptive, not pure repeatability.',
                operator_context='2026-10-10 six runs retraced the original paper line. Operator reports 2026-10-12 preparation was the same, with hand adjustment of the magnetic bristles before run 2 and board power cycling before run 3. Temperature and precise bristle geometry were not measured.',
                runs=metrics, group_middle_statistics=groups, latest_pairwise=pairwise,
                today_second_vs_first_pct=float((today[1]/today[0]-1)*100),
                today_third_vs_first_pct=float((today[2]/today[0]-1)*100),
                conclusion='Today run 2 is about 40% higher in middle response, while runs 1 and 3 have almost equal middle means. The change exists at contact rotation, not just later in the stroke. Average measured TCP Z is nearly equal. Mixed hand adjustment and power cycling prevent attribution to the board alone. No monotonic cumulative increase is supported.',
                generated_images=['latest_three.png','nine_run_history.png','board_and_baseline.png'])
    (HERE/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    columns=['date','repeat','operator_note','rotation_end_mean_uT','middle_mean_uT','middle_median_uT',
             'middle_sample_std_uT','tail_mean_uT','tail_cv_pct','actual_middle_z_mean_mm','sensor_first_uptime_s']
    with (HERE/'per_run_metrics.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=columns,extrasaction='ignore');writer.writeheader();writer.writerows(metrics)

    fig,axes=plt.subplots(2,2,figsize=(13,9),layout='constrained')
    for run,color,note in zip(latest,COLORS,NOTES):
        axes[0,0].plot(run['x'],run['a'],color=color,lw=1.7,label=note)
        axes[0,1].plot(run['rotation_t'],run['rotation_a'],color=color,lw=1.4,label=note)
        axes[1,0].plot(run['actual_x'],run['actual_z'],color=color,lw=1.2,marker='.',ms=4,label=note)
        axes[1,1].plot(run['x'],run['xy'][:,0],color=color,lw=1.4,label=note)
        axes[1,1].plot(run['x'],run['xy'][:,1],color=color,lw=1.2,ls='--')
    axes[0,0].axvspan(10,40,color='#94a3b8',alpha=.12,zorder=0)
    axes[0,0].set(title='A 行笔磁响应：第2次整条曲线更高',xlabel='命令行笔距离（mm）',ylabel='磁响应幅值（µT）',xlim=(0,50))
    axes[0,1].set(title='B 定高转笔：差异在行笔开始前已出现',xlabel='接触转笔开始后的时间（s）',ylabel='磁响应幅值（µT）',xlim=(0,2))
    axes[1,0].axhline(28,color='#475569',lw=1,ls='--',label='命令 Z28')
    axes[1,0].set(title='C 实际 TCP 高度：三次轨迹接近',xlabel='实际 TCP 行笔距离（mm）',ylabel='实际 Z（mm）',xlim=(0,50))
    axes[1,0].yaxis.set_major_formatter(FormatStrFormatter('%.3f'))
    axes[1,1].set(title='D 有符号磁分量：实线 ΔBx，虚线 ΔBy',xlabel='命令行笔距离（mm）',ylabel='滤波磁分量（µT）',xlim=(0,50))
    for ax in axes.flat: frame(ax);ax.legend(loc='best',fontsize=8)
    fig.suptitle('10月12日 Z28 定高转笔实验\n三次操作不同：手动调整磁毛与重新上电均已标注',fontsize=18)
    fig.savefig(HERE/'latest_three.png');plt.close(fig)

    fig,axes=plt.subplots(1,2,figsize=(13,5.2),layout='constrained')
    for index,run in enumerate(all_runs):
        old=index<6
        axes[0].plot(run['x'],run['a'],color='#94a3b8' if old else COLORS[index-6],
                     lw=.9 if old else 1.8,ls='--' if old else '-',alpha=.5 if old else 1,
                     label=('10月10日六笔' if index==0 else None) if old else NOTES[index-6])
    axes[0].set(title='A 九笔沿程响应：本次没有持续逐笔上升',xlabel='命令行笔距离（mm）',ylabel='磁响应幅值（µT）',xlim=(0,50))
    axes[0].legend(fontsize=8,loc='lower right')
    vals=[row['middle_mean_uT'] for row in metrics]
    axes[1].bar(np.arange(9),vals,color=['#cbd5e1']*3+['#64748b']*3+COLORS,width=.7)
    for i,value in enumerate(vals): axes[1].text(i,value+5,f'{value:.1f}',ha='center',fontsize=9)
    axes[1].set_xticks(np.arange(9),[f'10日\n{i}' for i in range(1,7)]+[f'12日\n{i}' for i in range(1,4)])
    axes[1].set(title='B 每笔中段均值（10–40 mm）',ylabel='中段磁响应均值（µT）',ylim=(0,365))
    for x in (2.5,5.5): axes[1].axvline(x,color='#cbd5e1',lw=1)
    for center,g in zip((1,4,7),groups): axes[1].text(center,343,f'组内均值 CV {g["cv_pct"]:.1f}%',ha='center',fontsize=10)
    for ax in axes: frame(ax)
    fig.suptitle('九次 Z28 实验历史对比；12日三笔含操作变化，CV仅描述这组三个数值',fontsize=16)
    fig.savefig(HERE/'nine_run_history.png');plt.close(fig)

    fig,axes=plt.subplots(1,2,figsize=(11,4.5),layout='constrained')
    ages=[row['metric']['sensor_first_uptime_s'] for row in latest]
    axes[0].bar(range(3),ages,color=COLORS,width=.6)
    for i,value in enumerate(ages):axes[0].text(i,value+1,f'{value:.2f} s',ha='center')
    axes[0].set(title='A 首帧板端计时：第3次确实重新开始',ylabel='首帧设备计时（s）',ylim=(0,105))
    for axis,label,shift in ((0,'Bx',-.16),(1,'By',.16)):
        values=[row['metric']['baseline_std_Bxy_uT'][axis] for row in latest]
        axes[1].bar(np.arange(3)+shift,values,width=.3,label=label,color='#475569' if axis==0 else '#94a3b8')
    axes[1].set(title='B 空载基线短窗：未见噪声逐次增大',ylabel='原始磁场标准差（µT）',ylim=(0,8))
    axes[1].legend()
    for ax in axes:ax.set_xticks(range(3),['第1次','第2次\n手动调整磁毛','第3次\n板子重新上电']);frame(ax)
    fig.suptitle('板子状态与有效基线（每笔方向基线约2秒）\n此图不能排除更长时间的温漂或接触后的状态变化',fontsize=16)
    fig.savefig(HERE/'board_and_baseline.png');plt.close(fig)

    lines=['10月12日 Z28 定高转笔实验分析','',
           '参数：+Y；TCP Z28 mm；30°→15°，2秒；补偿5 mm；行程50 mm；10 mm/s。',
           '操作记录：第2次前用手调整磁毛；第3次前板子重新上电。纸面准备方式按操作者说明与10号相同。',
           '因此这三次包含操作变化，不能按完全相同条件下的重复性或板子重启的因果对照解释。','',
           '次序 | 转笔最后0.3秒均值 | 中段10–40mm均值 | 末段40–50mm均值 | 实际Z中段均值']
    for row in metrics[-3:]:lines.append(f'{row["repeat"]} | {row["rotation_end_mean_uT"]:.2f} µT | {row["middle_mean_uT"]:.2f} µT | {row["tail_mean_uT"]:.2f} µT | {row["actual_middle_z_mean_mm"]:.6f} mm')
    lines.extend(['',f'第2次中段比第1次高 {report["today_second_vs_first_pct"]:.2f}%；第3次比第1次变化 {report["today_third_vs_first_pct"]:.3f}%。',
                  f'本组三个中段均值的样本CV为 {groups[-1]["cv_pct"]:.2f}%，只作为描述统计。',
                  '第一、第三次的中段曲线RMSE约4.09 µT；第二次相对第一次主要是约78.30 µT的整体上移。',
                  '每笔仍有沿程爬升；实际Z也有约0.09 mm的共同沿程变化，不能单独分离其贡献。',
                  '各笔参数/设置哈希一致；全部完成；传感器无无效帧；两轮基线均采集，接触旋转和行笔均使用本笔基线1。',
                  '从原始sensor.csv重放EMA与control.jsonl的接触/行笔磁幅值一致；无逐笔累加算法。',
                  '板端首帧计时43.28、88.21、3.92秒，支持第三次前重启；基线Bx/By标准差约5–6 µT，未显示短窗噪声逐次增大。',
                  '现有数据不能证明板子必然随持续上电漂移；手动调整磁毛、接触状态、纸面历史和电子状态未分离。',
                  '后续使用统一的每笔软复位流程时，应同时保持磁毛不被手动调整、纸面/含水准备与复位后等待流程一致，并记录复位结果。',
                  '软复位属于软件初始化；不等同于断电冷却。没有温度记录时，不能声称已消除热漂移。','',
                  '图：latest_three.png（本次详细对比）、nine_run_history.png（九次历史）、board_and_baseline.png（板端计时与基线噪声）。',
                  '详细数值与原始输入哈希见summary.json；逐笔指标见per_run_metrics.csv；运行analyze.py可重新生成。'])
    (HERE/'report.txt').write_text('\n'.join(lines)+'\n')
    for row in metrics[-3:]:print(json.dumps({k:row[k] for k in ('repeat','middle_mean_uT','rotation_end_mean_uT','actual_middle_z_mean_mm','sensor_first_uptime_s')},ensure_ascii=False))
    print('Outputs:',HERE)


if __name__=='__main__':main()
