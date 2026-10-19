"""Export both accepted baseline windows from all runs on the two fixed dates."""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import csv
import hashlib
import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np

HERE = Path(__file__).resolve().parent
RUNS = HERE.parents[2]
DAYS = ('2026-10-10', '2026-10-12')
FONT = '/usr/local/share/fonts/msyh.ttf'
font_manager.fontManager.addfont(FONT)
plt.rcParams.update({'font.family': 'Microsoft YaHei', 'axes.unicode_minus': False,
                     'font.size': 11, 'legend.fontsize': 9, 'savefig.dpi': 180})


def write_csv(path, fieldnames, rows):
    # BOM allows Chinese source labels to open correctly in common CSV viewers.
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def main():
    manifests = sorted((p for p in RUNS.rglob('manifest.json') if any(day in p.parts for day in DAYS)),
                       key=lambda p: json.loads(p.read_text())['started_at'])
    rows, raw_rows, inventory = [], [], []
    by_date = {day: [] for day in DAYS}
    for order, path in enumerate(manifests, 1):
        folder = path.parent
        manifest = json.loads(path.read_text())
        day = next(day for day in DAYS if day in folder.parts)
        for name, expected in manifest['sha256'].items():
            assert hashlib.sha256((folder/name).read_bytes()).hexdigest() == expected, str(folder/name)
        setup_path = folder/'settings.json' if (folder/'settings.json').exists() else folder/'setup.json'
        setup = json.loads(setup_path.read_text())
        resolved = json.loads((folder/'resolved.json').read_text())
        if (folder/'identification.json').exists():
            profile = json.loads((folder/'identification.json').read_text())
            repeat = int(folder.name.split('第')[-1].split('次')[0])
        else:
            trial = json.loads((folder/'contact_test.json').read_text())
            profile = trial['profile']
            repeat = int(folder.name.split('第')[-1].split('次')[0])
        experiment = folder.parent.parent.name
        sensors = list(csv.DictReader((folder/'sensor.csv').open()))
        actual = list(csv.DictReader((folder/'actual_tcp.csv').open()))
        start = datetime.fromisoformat(manifest['started_at']).astimezone(ZoneInfo('Asia/Shanghai'))
        reset = resolved.get('sensor_reboot')
        reset_status = reset['status'] if reset else 'not recorded'
        if not reset and day == '2026-10-12' and repeat == 3 and experiment == '四方向速度下压实验':
            reset_status = 'operator reported power cycle'
        reboot_s = ((reset['completed_host_ns']-reset['requested_host_ns'])/1e9
                    if reset and reset['status']=='completed' else None)
        note = ''
        if experiment == '四方向速度下压实验':
            if day == '2026-10-10':
                note = '操作者确认：六笔仍重画同一条线。'
            elif repeat <= 3:
                note = '按操作者说明与10号准备相同。'
                if repeat == 2:
                    note += '本笔前手动调整磁毛。'
                if repeat == 3:
                    note += '本笔前给板子重新上电。'
            else:
                note = '每笔程序软复位；操作者确认：仍重画同一条线，未手调磁毛，含水准备一致。'
        else:
            note = '接触参数试验：进笔角度或旋转起始高度等参数不同；纸面与磁毛准备无独立记录。'
        source = dict(run_order=order, date=day, time=start.strftime('%H:%M:%S'),
                      experiment=experiment, repeat=repeat, run_name=folder.name,
                      run_dir=str(folder), status=manifest['status'],
                      baseline_count=len(manifest.get('baselines', [])),
                      manifest_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                      sensor_sha256=hashlib.sha256((folder/'sensor.csv').read_bytes()).hexdigest(),
                      actual_tcp_sha256=hashlib.sha256((folder/'actual_tcp.csv').read_bytes()).hexdigest(),
                      sensor_hash_recorded_in_manifest='sensor.csv' in manifest['sha256'],
                      actual_tcp_hash_recorded_in_manifest='actual_tcp.csv' in manifest['sha256'],
                      reboot_status=reset_status, operator_note=note)
        inventory.append(source)
        by_date[day].append(source)
        for baseline in manifest.get('baselines', []):
            bid = baseline['baseline_id']
            window = [row for row in sensors if baseline['first_seq'] <= int(row['seq']) <= baseline['last_seq']]
            valid = [row for row in window if row['valid'] == 'true']
            assert valid and len(window) == baseline['last_seq']-baseline['first_seq']+1
            values = np.array([[float(row[f'B{axis}_uT']) for axis in 'xyz'] for row in valid])
            b0 = np.array(baseline['B0_uT'])
            std = np.array(baseline['std_uT'])
            assert np.allclose(values.mean(axis=0), b0, atol=1e-8, rtol=0)
            assert np.allclose(values.std(axis=0), std, atol=1e-8, rtol=0)
            host = np.array([int(row['host_rx_ns']) for row in valid], dtype=float)
            seconds = (host-int(valid[0]['host_rx_ns']))/1e9
            slope = np.array([np.polyfit(seconds, values[:, axis], 1)[0] for axis in range(3)])
            assert np.allclose(slope, baseline['drift_uT_s'], atol=1e-8, rtol=0)
            first_ns, last_ns = int(valid[0]['host_rx_ns']), int(valid[-1]['host_rx_ns'])
            poses = [row for row in actual if row['valid']=='true'
                     and first_ns <= int(row['request_end_ns']) <= last_ns]
            assert poses, str(folder)
            pose_values = np.array([[float(row[key]) for key in
                                    ('x_m', 'y_m', 'z_m', 'rx_rad', 'ry_rad', 'rz_rad')] for row in poses])
            measured = np.median(pose_values, axis=0)
            nominal_rpy = (setup['vertical_rpy_rad'] if bid == 0
                           else resolved['baseline_writing_rpy_rad'])
            nominal_xyz = [setup['origin_x_mm'], setup['origin_y_mm'], setup['wait_z_mm']]
            label = '等待姿态基线' if bid == 0 else '方向工作姿态基线'
            rec = dict(source, baseline_id=bid, baseline_type=label,
                       sample_count=len(valid), invalid_samples_in_window=len(window)-len(valid),
                       duration_s=(last_ns-first_ns)/1e9,
                       first_seq=baseline['first_seq'], last_seq=baseline['last_seq'],
                       first_sensor_t_us=int(valid[0]['sensor_t_us']), last_sensor_t_us=int(valid[-1]['sensor_t_us']),
                       first_host_rx_ns=first_ns, last_host_rx_ns=last_ns,
                       sensor_median_interval_us=float(np.median(np.mod(np.diff(
                           [int(row['sensor_t_us']) for row in valid]), 2**32))),
                       quality_axes=','.join('xyz'[axis] for axis in baseline['quality_axes']),
                       actual_pose_samples=len(poses), reboot_duration_s=reboot_s,
                       direction=profile['direction'], entry_tilt_deg=profile['entry_tilt_deg'],
                       writing_tilt_deg=profile['writing_tilt_deg'],
                       rotate_s=profile['rotate_s'], entry_contact_z_mm=profile['entry_contact_z_mm'],
                       start_z_mm=profile['start_z_mm'], end_z_mm=profile['end_z_mm'])
            for i, axis in enumerate('xyz'):
                rec[f'B0{axis}_uT'] = float(b0[i])
                rec[f'std_B{axis}_uT'] = float(std[i])
                rec[f'drift_B{axis}_uT_s'] = float(baseline['drift_uT_s'][i])
                rec[f'nominal_{axis}_mm'] = float(nominal_xyz[i])
                rec[f'actual_{axis}_median_mm'] = float(measured[i]*1000)
                rec[f'actual_{axis}_range_mm'] = float(np.ptp(pose_values[:, i])*1000)
            for i, angle in enumerate(('roll', 'pitch', 'yaw')):
                rec[f'nominal_{angle}_deg'] = float(np.rad2deg(nominal_rpy[i]))
                rec[f'actual_{angle}_median_deg'] = float(np.rad2deg(measured[i+3]))
            rows.append(rec)
            for row in window:
                raw_rows.append(dict(date=day, time=source['time'], experiment=experiment,
                                     run_order=order, run_name=folder.name,
                                     accepted_baseline_window_id=bid, baseline_type=label, **row))
    assert len(inventory)==19 and len(rows)==38
    assert [len(by_date[day]) for day in DAYS] == [13, 6]
    assert all(row['invalid_samples_in_window'] == 0 for row in rows)
    columns = ['date', 'time', 'experiment', 'repeat', 'baseline_id', 'baseline_type',
               'B0x_uT', 'B0y_uT', 'B0z_uT', 'std_Bx_uT', 'std_By_uT', 'std_Bz_uT',
               'drift_Bx_uT_s', 'drift_By_uT_s', 'drift_Bz_uT_s', 'sample_count', 'duration_s',
               'nominal_x_mm', 'nominal_y_mm', 'nominal_z_mm',
               'nominal_roll_deg', 'nominal_pitch_deg', 'nominal_yaw_deg',
               'actual_x_median_mm', 'actual_y_median_mm', 'actual_z_median_mm',
               'actual_roll_median_deg', 'actual_pitch_median_deg', 'actual_yaw_median_deg',
               'reboot_status', 'reboot_duration_s', 'sensor_median_interval_us',
               'first_seq', 'last_seq', 'quality_axes', 'run_order', 'run_name', 'run_dir', 'operator_note']
    write_csv(HERE/'all_baselines.csv', columns, rows)
    raw_columns = ['date', 'time', 'experiment', 'run_order', 'run_name',
                   'accepted_baseline_window_id', 'baseline_type', *list(sensors[0])]
    write_csv(HERE/'baseline_raw_samples.csv', raw_columns, raw_rows)
    daily = {}
    for day in DAYS:
        daily[day] = {}
        for bid in (0, 1):
            group = [row for row in rows if row['date']==day and row['baseline_id']==bid]
            daily[day][str(bid)] = {
                f'B0{axis}_uT': dict(min=min(row[f'B0{axis}_uT'] for row in group),
                                     max=max(row[f'B0{axis}_uT'] for row in group),
                                     range=float(np.ptp([row[f'B0{axis}_uT'] for row in group])))
                for axis in 'xyz'}
    failures = []
    for day in DAYS:
        for path in RUNS.glob(f'*/{day}/**/sensor_reboots/*.json'):
            record = json.loads(path.read_text())
            if record['status'] != 'completed':
                failures.append(dict(path=str(path), record=record,
                                     note='Reset failed before baseline acquisition; no accepted baseline is available.'))
    summary = dict(dates=list(DAYS), run_count=len(inventory), baseline_count=len(rows),
        raw_window_sample_count=len(raw_rows), run_inventory=inventory, all_baselines=rows,
        daily_ranges=daily, unsuccessful_prebaseline_reboot_attempts=failures,
        method='Every accepted baseline from every manifest on the two dates under runs/. Recompute B0, population SD and host-time linear drift from the exact first_seq-last_seq raw window; assert agreement with metadata to 1e-8. Nominal and median actual poses are retained separately. No normalization or baseline replacement. Raw sensor columns remain intact; accepted_baseline_window_id identifies the extraction window and is separate from the original baseline_id column.',
        limitations='Baseline 0 (initial wait pose) and baseline 1 (directional working pose) differ in orientation and must be compared separately. Contact test preparation is not independently recorded. Some runs have different entry parameters; older and newer firmware sampling periods differ. Physical board reset is operator-reported for day12 repeat3; not recorded does not mean no physical reset happened.')
    (HERE/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False)+'\n')

    fig, axes = plt.subplots(3, 2, figsize=(13, 9.6), sharex='col', layout='constrained')
    for col, day in enumerate(DAYS):
        records = by_date[day]
        labels = [record['time'] for record in records]
        for axis_index, axis in enumerate('xyz'):
            ax = axes[axis_index, col]
            for bid, color, marker, label in ((0, '#2563eb', 'o', '基线0：等待姿态'),
                                              (1, '#d97706', 's', '基线1：方向工作姿态')):
                group = [row for row in rows if row['date']==day and row['baseline_id']==bid]
                ax.plot(np.arange(len(group)), [row[f'B0{axis}_uT'] for row in group],
                        color=color, marker=marker, ms=4, lw=1.2, label=label)
            ax.set_ylabel(f'空载 B{axis} 均值（µT）')
            ax.grid(alpha=.18)
            ax.spines[['top', 'right']].set_visible(False)
            if day=='2026-10-10':
                ax.axvline(6.5, color='#94a3b8', ls=':', lw=1)
            else:
                ax.axvline(2.5, color='#94a3b8', ls=':', lw=1)
                ax.axvspan(2.6, 5.4, color='#dcfce7', alpha=.45, zorder=0)
            if axis_index==0:
                ax.set_title(f'{day}：{len(records)}笔实验')
                ax.legend(fontsize=8, loc='best')
            ax.set_xticks(np.arange(len(records)), labels, rotation=55, ha='right')
            # Keep both days on the same per-axis scale, retaining Bz's negative sign.
            all_values = [row[f'B0{axis}_uT'] for row in rows]
            padding = max(np.ptp(all_values)*.12, 2.)
            ax.set_ylim(min(all_values)-padding, max(all_values)+padding)
        axes[2, col].set_xlabel('实验开始时间（按实验序号排列，横轴不表示时间间隔）')
    fig.suptitle('10月10日与12日全部空载基线：19笔实验、38个采样窗口\n10号虚线区分接触参数与定高试验；12号绿色区为每笔程序软复位', fontsize=17)
    fig.savefig(HERE/'all_baselines.png')
    plt.close(fig)

    lines = [
        '10月10日与12日全部空载基线数据', '',
        f'范围：runs/ 下这两天全部19笔完成实验，共38条有效基线、{len(raw_rows)}帧原始基线样本。',
        '10月10日：7笔独立接触参数测试、6笔四方向定高实验；10月12日：6笔四方向定高实验。',
        '全部名义基线位置：XYZ=(-150,450,70)mm。',
        '基线0：等待姿态，RPY=(0,+15,0)°。基线1：up方向工作姿态，RPY=(-15,0,0)°。',
        '后续接触旋转与行笔用的是各笔基线1。两种姿态应分开比较。',
        'CSV保留未四舍五入的原始统计值；下表只为阅读保留两位小数，单位µT。', '',
        '日期 时间 类型/重复 | 基线0 Bx By Bz | 基线1 Bx By Bz',
    ]
    for rec in inventory:
        pair = [row for row in rows if row['run_order']==rec['run_order']]
        assert [row['baseline_id'] for row in pair] == [0, 1]
        kind = '接触参数' if rec['experiment']=='独立接触参数测试' else '定高'
        lines.append(f'{rec["date"]} {rec["time"]} {kind}/第{rec["repeat"]}次 | '+
            ' | '.join(' '.join(f'{row[f"B0{axis}_uT"]:.2f}' for axis in 'xyz') for row in pair))
    lines += ['', '各日同姿态的基线均值范围：']
    for day in DAYS:
        for bid in (0, 1):
            fields = daily[day][str(bid)]
            lines.append(f'{day} 基线{bid}：'+', '.join(
                f'B{axis} {fields[f"B0{axis}_uT"]["min"]:.2f}–{fields[f"B0{axis}_uT"]["max"]:.2f}（差{fields[f"B0{axis}_uT"]["range"]:.2f}）'
                for axis in 'xyz'))
    lines += [
        '', '114.5µT仅指12号最新三笔（第4–6次）的方向基线1 Bx范围。',
        '12号全部六笔的方向基线1 Bx范围为145.09µT；10号全部十三笔为83.47µT。',
        '原始样本均值、总体标准差(ddof=0)及线性漂移已逐条重算，与manifest全部一致。',
        '基线质量只检查Bx/By；Bz保留记录，并不参与该质量门槛。',
        '三个程序软复位成功状态来自日志；12号第3次物理上电来自操作者说明。其余“不记录”不能当作“没有重启”。',
        f'另有{len(failures)}次复位失败发生在取基线前，没有基线数据，因此无法列入38条基线。',
        'baseline_raw_samples.csv 中 accepted_baseline_window_id 是本次导出的采样窗口编号；原始 baseline_id 列原样保留。',
        '基线窗口里的原始 baseline_id 通常为空，因为基线尚未建立；不代表漏取基线。',
        '原始数据和实验日志未修改。',
    ]
    (HERE/'readme.txt').write_text('\n'.join(lines)+'\n')
    print(json.dumps({key:summary[key] for key in ('run_count','baseline_count','raw_window_sample_count','daily_ranges')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
