"""Analyze the fixed 16:21-16:22 three-run cohort; raw runs remain unchanged."""
from pathlib import Path
import csv
import hashlib
import importlib.util
import json

import numpy as np

HERE = Path(__file__).resolve().parent
EXPERIMENT = HERE.parents[1]
loader_spec = importlib.util.spec_from_file_location(
    'previous_z28_analysis', HERE.parent/'z28_repeatability/analyze.py')
previous = importlib.util.module_from_spec(loader_spec)
loader_spec.loader.exec_module(previous)
plt = previous.plt
COLORS = previous.COLORS
NAMES = [
    '16-21-05_定高_up_Z28到28_速度10_第4次',
    '16-21-45_定高_up_Z28到28_速度10_第5次',
    '16-22-32_定高_up_Z28到28_速度10_第6次',
]
EARLIER = [
    '15-16-28_定高_up_Z28到28_速度10_第1次',
    '15-17-15_定高_up_Z28到28_速度10_第2次',
    '15-17-56_定高_up_Z28到28_速度10_第3次',
]


def load(name, repeat, reset_required):
    folder = EXPERIMENT/'raw'/name
    # Reuse the verified extraction and EMA replay, replacing historical notes.
    run = previous.load(folder, '2026-10-12', (repeat-1) % 3+1)
    metric = run['metric']
    metric.update(repeat=repeat, raw_folder=str(folder))
    if reset_required:
        metric['operator_note'] = 'preparation not yet confirmed'
    manifest = json.loads((folder/'manifest.json').read_text())
    resolved = json.loads((folder/'resolved.json').read_text())
    settings = json.loads((folder/'settings.json').read_text())
    controls = [json.loads(line) for line in (folder/'control.jsonl').read_text().splitlines()]
    sensors = list(csv.DictReader((folder/'sensor.csv').open()))
    periods = np.diff([int(row['sensor_t_us']) for row in sensors])
    assert (periods > 0).all()
    metric['sensor_median_interval_us'] = float(np.median(periods))
    metric['sensor_nominal_observed_hz'] = 1e6/metric['sensor_median_interval_us']
    metric['baseline_drift_Bxy_uT_s'] = manifest['baselines'][-1]['drift_uT_s'][:2]
    metric['middle_filtered_raw_Bxy_mean_uT'] = (
        np.array(metric['middle_filtered_Bxy_mean_uT'])+metric['baseline_Bxy_uT']).tolist()
    sensor_by_seq = {int(row['seq']): row for row in sensors}
    mid = [row for row in controls if row['phase'] == 'straight_hold'
           and 10-1e-8 <= row['y_cmd_m']*1000-settings['origin_y_mm'] <= 40+1e-8]
    raw = np.array([[float(sensor_by_seq[row['sample_seq']][f'B{axis}_uT'])
                    for axis in 'xyz'] for row in mid])
    metric['middle_raw_Bxyz_mean_uT'] = raw.mean(axis=0).tolist()
    metric['middle_control_sample_count'] = len(mid)
    actual = list(csv.DictReader((folder/'actual_tcp.csv').open()))
    metric['actual_tcp_samples'] = len(actual)
    metric['invalid_actual_tcp_samples'] = sum(row['valid'] != 'true' for row in actual)
    assert metric['invalid_actual_tcp_samples'] == 0
    rot = [row for row in controls if row['phase'] == 'rotate_contact']
    run['rotation_t'] = np.array([row['t_s'] for row in rot])-rot[0]['t_s']+.02
    if reset_required:
        reboot = resolved['sensor_reboot']
        assert reboot['status'] == 'completed'
        assert reboot['requested_host_ns'] <= reboot['ack_host_ns'] <= reboot['ready_host_ns'] <= reboot['completed_host_ns']
        assert reboot['first_frame_sensor_t_us'] < 1_000_000
        record = Path(reboot['record_path'])
        assert json.loads(record.read_text()) == reboot
        metric.update(reboot=reboot,
            reboot_duration_s=(reboot['completed_host_ns']-reboot['requested_host_ns'])/1e9,
            reboot_ack_latency_ms=(reboot['ack_host_ns']-reboot['requested_host_ns'])/1e6,
            reboot_record_sha256=hashlib.sha256(record.read_bytes()).hexdigest())
    return run


def main():
    old = [load(name, i+1, False) for i, name in enumerate(EARLIER)]
    latest = [load(name, i+4, True) for i, name in enumerate(NAMES)]
    all_runs = old+latest
    assert len({run['metric']['profile_sha256'] for run in all_runs}) == 1
    assert len({run['metric']['setup_sha256'] for run in all_runs}) == 1
    metrics = [run['metric'] for run in latest]
    vals = np.array([metric['middle_mean_uT'] for metric in metrics])
    group = previous.stats(vals)
    old_group = previous.stats([run['metric']['middle_mean_uT'] for run in old])
    grid = np.linspace(10, 40, 301)
    curves = [np.interp(grid, run['x'], run['a']) for run in latest]
    pairwise = []
    for i, j in ((0, 1), (0, 2), (1, 2)):
        diff = curves[j]-curves[i]
        pairwise.append(dict(repeats=[i+4, j+4], mean_difference_uT=float(diff.mean()),
            rmse_uT=float(np.sqrt(np.mean(diff**2))),
            centered_rmse_uT=float(np.sqrt(np.mean((diff-diff.mean())**2)))))
    baseline_x = np.array([metric['baseline_Bxy_uT'][0] for metric in metrics])
    loaded_x = np.array([metric['middle_filtered_raw_Bxy_mean_uT'][0] for metric in metrics])
    report = dict(
        cohort='2026-10-12 16:21:05, 16:21:45, 16:22:32; day repeats 4-6',
        units='magnetic response uT, not force N',
        method='EMA alpha=0.3, xy magnitude of B-B0; middle commanded distance 10-40 mm inclusive, tail 40-50 mm inclusive, rotation final 0.3 s; sample SD ddof=1. No amplitude normalization, per-run shift or exclusion. Independent units are runs, not the 151 correlated path samples.',
        operator_context='Latest paper/bristle/water preparation is not yet confirmed. Earlier day repeats 1-3 included hand adjustment before repeat 2 and physical board power cycling before repeat 3.',
        latest=metrics, previous_same_day=[run['metric'] for run in old],
        latest_middle_mean_statistics=group, previous_middle_mean_statistics=old_group,
        pairwise=pairwise,
        latest_middle_range_uT=float(np.ptp(vals)),
        latest_middle_range_relative_to_mean_pct=float(np.ptp(vals)/vals.mean()*100),
        second_vs_first_pct=float((vals[1]/vals[0]-1)*100),
        third_vs_second_pct=float((vals[2]/vals[1]-1)*100),
        third_vs_first_pct=float((vals[2]/vals[0]-1)*100),
        baseline_Bx_range_uT=float(np.ptp(baseline_x)),
        middle_filtered_raw_Bx_range_uT=float(np.ptp(loaded_x)),
        conclusion='All three board software reboots succeeded in about 0.726 s. Between-run middle-response CV remains about 27.1%; reboot alone has not made this cohort closely repeatable. Baseline Bx differs far more than loaded raw Bx. The magnetic initial/loaded state difference remains important. Constant additive electronic offset would be removed if shared by baseline and contact, but time/state-dependent drift, sensitivity drift, bristle geometry and contact preparation are not separated. Older cohort had mixed interventions and 250 Hz acquisition versus current 333 Hz, so the CV change is descriptive, not a controlled causal estimate.',
    )
    context_path = HERE/'operator_context.json'
    if context_path.exists():
        report['operator_context'] = json.loads(context_path.read_text())
        for metric in metrics:
            metric['operator_note'] = report['operator_context']['latest_preparation']
    (HERE/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    columns = ['repeat', 'rotation_end_mean_uT', 'middle_mean_uT', 'tail_mean_uT', 'tail_cv_pct',
               'actual_middle_z_mean_mm', 'reboot_duration_s', 'reboot_ack_latency_ms',
               'sensor_first_uptime_s', 'sensor_nominal_observed_hz']
    with (HERE/'per_run_metrics.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(metrics)

    fig, axes = plt.subplots(2, 2, figsize=(13, 8.4), layout='constrained')
    for run, color in zip(latest, COLORS):
        label = f'第{run["metric"]["repeat"]}次（软复位）'
        axes[0, 0].plot(run['x'], run['a'], color=color, lw=1.5, label=label)
        axes[0, 1].plot(run['rotation_t'], run['rotation_a'], color=color, lw=1.4, label=label)
        axes[1, 0].plot(run['actual_x'], run['actual_z'], color=color, lw=1.1, marker='.', ms=4, label=label)
    axes[0, 0].axvspan(10, 40, alpha=.12, color='#94a3b8', zorder=0)
    axes[0, 0].set(title='A 行笔响应：三笔仍有明显整体差异', xlabel='命令行笔距离（mm）', ylabel='磁响应幅值（µT）', xlim=(0, 50))
    axes[0, 1].set(title='B 接触转笔：差异在行笔之前已出现', xlabel='转笔开始后的时间（s）', ylabel='磁响应幅值（µT）', xlim=(0, 2))
    axes[1, 0].axhline(28, ls='--', lw=1, color='#475569', label='命令 Z28')
    axes[1, 0].set(title='C 实际 TCP 高度：三笔轨迹接近', xlabel='实际行笔距离（mm）', ylabel='实际 Z（mm）', xlim=(0, 50))
    axes[1, 0].yaxis.set_major_formatter(previous.FormatStrFormatter('%.3f'))
    axes[1, 1].bar(range(3), vals, width=.6, color=COLORS)
    for i, value in enumerate(vals):
        axes[1, 1].text(i, value+5, f'{value:.2f}', ha='center', fontsize=12)
    axes[1, 1].set_xticks(range(3), ['第4次\n16:21:05', '第5次\n16:21:45', '第6次\n16:22:32'])
    axes[1, 1].set(title=f'D 中段均值：三笔间样本 CV {group["cv_pct"]:.1f}%', ylabel='10–40 mm 中段均值（µT）', ylim=(0, 400))
    for ax in axes.flat:
        previous.frame(ax)
    for ax in (axes[0, 0], axes[0, 1], axes[1, 0]):
        ax.legend(fontsize=8, loc='best')
    fig.suptitle('每笔软复位后的三次 Z28 实验\n三次重启均成功，磁响应的逐笔差异仍存在', fontsize=18)
    fig.savefig(HERE/'latest_three.png')
    plt.close(fig)

    fig, axes = plt.subplots(1, 3, figsize=(14, 4.4), layout='constrained')
    axes[0].plot(range(3), baseline_x, 'o-', color='#2563eb', label='空载方向基线 B0x')
    axes[0].plot(range(3), loaded_x, 's-', color='#d97706', label='行笔中段原始 Bx（同 EMA）')
    for i, (baseline, loaded) in enumerate(zip(baseline_x, loaded_x)):
        axes[0].plot([i, i], [baseline, loaded], ls=':', color='#94a3b8')
    axes[0].set(title='A 基线与接触原始 Bx', ylabel='原始 Bx（µT）', ylim=(2020, 2520))
    axes[0].legend(fontsize=8, loc='upper center')
    axes[0].text(.02, .03, f'基线范围 {np.ptp(baseline_x):.1f} µT\n接触中段范围 {np.ptp(loaded_x):.1f} µT', transform=axes[0].transAxes, fontsize=10)
    for axis, shift, label, color in ((0, -.17, 'Bx', '#475569'), (1, .17, 'By', '#94a3b8')):
        axes[1].bar(np.arange(3)+shift, [metric['baseline_std_Bxy_uT'][axis] for metric in metrics],
                    width=.32, label=label, color=color)
    axes[1].set(title='B 空载基线短窗噪声', ylabel='方向基线标准差（µT）', ylim=(0, 8))
    axes[1].legend()
    durations = [metric['reboot_duration_s'] for metric in metrics]
    axes[2].bar(range(3), durations, width=.6, color=COLORS)
    for i, duration in enumerate(durations):
        axes[2].text(i, duration+.025, f'{duration:.3f} s', ha='center')
    axes[2].set(title='C 命令到有效新帧：均成功', ylabel='软复位总耗时（s）', ylim=(0, 1))
    for ax in axes:
        ax.set_xticks(range(3), ['第4次', '第5次', '第6次'])
        previous.frame(ax)
    fig.suptitle('软复位记录与磁场基线：基线均值差异远大于短窗噪声', fontsize=17)
    fig.savefig(HERE/'baseline_and_reboot.png')
    plt.close(fig)

    lines = [
        '2026-10-12 16:21–16:22 每笔软复位后三次 Z28 实验分析', '',
        '结论：三次均成功软复位，但磁响应仍有显著逐笔差异，当前流程未获得接近的重复结果。',
        '实验参数与当天前三次完全一致：+Y，Z28定高，30°→15°接触转笔2秒，补偿5mm，行程50mm，10mm/s。',
        '信号为扣基线后 XY 磁矢量经 EMA(alpha=0.3) 的幅值，单位 µT，不是以 N 表示的力。', '',
        '当天编号 | 转笔末0.3秒均值 µT | 中段10–40mm均值 µT | 末段40–50mm均值 µT | 实际中段Z均值 mm | 软复位耗时 s',
    ]
    for metric in metrics:
        lines.append(f'{metric["repeat"]} | {metric["rotation_end_mean_uT"]:.2f} | {metric["middle_mean_uT"]:.2f} | {metric["tail_mean_uT"]:.2f} | {metric["actual_middle_z_mean_mm"]:.6f} | {metric["reboot_duration_s"]:.3f}')
    lines += [
        '', f'三笔中段均值的样本CV为 {group["cv_pct"]:.2f}%，最大最小差 {np.ptp(vals):.2f} µT。',
        f'第5次相对第4次 {report["second_vs_first_pct"]:+.2f}%；第6次相对第5次 {report["third_vs_second_pct"]:+.2f}%；第6次相对第4次 {report["third_vs_first_pct"]:+.2f}%。',
        '差异在接触旋转时已经出现，并非行笔后才逐渐积累。中段曲线主要呈整体幅值差异。',
        '三笔均完成；原始文件哈希与各自manifest一致；传感器无无效帧；实际TCP记录无无效帧。',
        '三笔均有两轮基线，旋转与行笔使用各自本笔方向基线1；原始数据重放EMA与日志幅值完全一致。',
        '重启均收到ACK、READY和有效新帧；总耗时约0.726秒、回应约10ms；第一有效新帧板端计时约0.423秒。',
        '开始记录实验后第一帧板端计时约0.765–0.768秒，三笔板端起始时间一致。', '',
        '基线与接触磁场：',
        '当天编号 | 方向基线B0x µT | 行笔中段原始Bx均值 µT（同EMA） | 中段ΔBx均值 µT',
    ]
    for metric in metrics:
        lines.append(f'{metric["repeat"]} | {metric["baseline_Bxy_uT"][0]:.2f} | {metric["middle_filtered_raw_Bxy_mean_uT"][0]:.2f} | {metric["middle_filtered_Bxy_mean_uT"][0]:.2f}')
    lines += [
        f'方向基线Bx的三笔范围为 {np.ptp(baseline_x):.2f} µT，接触中段原始Bx范围为 {np.ptp(loaded_x):.2f} µT。',
        '基线短窗Bx/By标准差仅约5.2–5.5 µT，无逐笔增大。基线均值变化与短窗抖动是两种现象。',
        '响应计算ΔB=B-B0，因此空载与接触两个磁状态的差决定最终幅值。这里基线差异占中段ΔBx差异很大一部分。',
        '这不是漏取基线的证据，也不应改为强行共用一个基线或逐笔归一化来掩盖差异。',
        '若板子只有在空载与接触阶段共有的恒定加性偏移，扣基线会抵消该项；时变/状态相关偏移、灵敏度变化仍未排除。',
        '初始磁毛形态、磁体相对霍尔位置、接触后的恢复状态、含水或纸面变化同样仍可能影响结果。以上为待验证解释，非已证实原因。',
        '实际Z中段均值只相差约0.0008mm，三笔沿程轨迹接近；共同存在约0.09mm沿程变化，不能据此排除其对单笔爬升的贡献。', '',
        f'与之前三笔的描述对比：旧组三个中段均值CV {old_group["cv_pct"]:.2f}%，新组 {group["cv_pct"]:.2f}%；本次未观察到差异减小。',
        '旧组有手调磁毛和重新上电操作，且新固件采样间隔3ms约333Hz、旧组4ms约250Hz；EMA时间尺度也随采样率改变。',
        '因此不能将这两个CV的差异解释为软复位造成的因果影响。软件重启不等同于断电冷却，热漂移仍需专门检验。',
        '最新三次纸面、含水与手调操作记录：'+(
            report['operator_context']['latest_preparation']
            if isinstance(report['operator_context'], dict) else report['operator_context']),
        '这三次仍重画同一条线，纸面经历重复湿润与摩擦；没有独立的新纸面组，不能把变化单独归因于板子。',
        '下一步优先核对每笔方向基线时的空载磁状态是否一致，可在固定空载姿态、不动磁毛条件下记录原始Bx/By的随时间变化。', '',
        '完整数值、原始路径、文件哈希、重启日志与成对曲线误差见summary.json。',
    ]
    (HERE/'report.txt').write_text('\n'.join(lines)+'\n')
    print(json.dumps({key: report[key] for key in ('latest_middle_mean_statistics', 'second_vs_first_pct',
        'third_vs_second_pct', 'baseline_Bx_range_uT', 'middle_filtered_raw_Bx_range_uT')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
