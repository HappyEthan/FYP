"""Offline, recorded-data analysis; no hardware access. Run from any directory."""
import csv
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

OUT = Path(__file__).resolve().parent
RAW = OUT.parent.parent / 'raw'
plt.rcParams.update({'font.family': 'Noto Sans CJK SC', 'font.size': 10,
                     'axes.spines.top': False, 'axes.spines.right': False})


def wrap(a):
    return (np.asarray(a) + 180) % 360 - 180


def angle(xy):
    return np.degrees(np.arctan2(xy[:, 1], xy[:, 0]))


def mean_angle(a):
    return float(np.degrees(np.angle(np.mean(np.exp(1j * np.radians(a))))))


def metrics(error):
    error = wrap(error)
    assert len(error) and np.isfinite(error).all()
    return dict(n=len(error), bias_deg=mean_angle(error),
                mae_deg=float(np.mean(abs(error))),
                median_abs_deg=float(np.median(abs(error))),
                p95_abs_deg=float(np.percentile(abs(error), 95)),
                within_15_deg=float(np.mean(abs(error) <= 15)),
                within_30_deg=float(np.mean(abs(error) <= 30)))


def load(folder):
    manifest = json.loads((folder / 'manifest.json').read_text())
    assert manifest['status'] == 'completed'
    assert manifest['execution_environment'] == 'hardware'
    for name, digest in manifest['sha256'].items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest
    with (folder / 'sensor.csv').open() as stream:
        sensor = list(csv.DictReader(stream))
    control = [json.loads(line) for line in (folder / 'control.jsonl').read_text().splitlines()]
    with (folder / 'actual_tcp.csv').open() as stream:
        actual = [r for r in csv.DictReader(stream) if r['valid'] == 'true']
    base = control[0]['host_ns']
    at = np.array([((int(r['request_start_ns']) - base) +
                    (int(r['request_end_ns']) - base)) / 2e9 for r in actual])
    ap = np.array([[float(r[k]) for k in ('x_m', 'y_m')] for r in actual]) * 1000
    assert np.all(np.diff(at) > 0) and np.max(np.diff(at)) < .25
    assert len(manifest['baselines']) == 1 and manifest['filter']['kind'] == 'ema'
    baseline = manifest['baseline']
    b0 = np.array(baseline['B0_uT'][:2])
    alpha = manifest['filter']['alpha']
    z = None
    filtered = {}
    # Reproduce initialization using ALL baseline samples, as acquisition.py does.
    for row in sensor:
        if row['valid'] != 'true':
            continue
        seq = int(row['seq'])
        raw = np.array([float(row[k]) for k in ('Bx_uT', 'By_uT')])
        if baseline['first_seq'] <= seq <= baseline['last_seq']:
            delta = raw - b0
            z = delta.copy() if z is None else alpha * delta + (1-alpha) * z
        elif row['dBx_uT']:
            assert int(row['baseline_id']) == baseline['baseline_id']
            delta = np.array([float(row[k]) for k in ('dBx_uT', 'dBy_uT')])
            assert np.allclose(delta, raw - b0, atol=1e-9, rtol=0)
            z = alpha * delta + (1-alpha) * z
            filtered[seq] = (z.copy(), raw, (int(row['host_rx_ns'])-base)/1e9)
    replay_error = max(abs(np.linalg.norm(filtered[r['sample_seq']][0])-r['a_control_uT'])
                       for r in control)
    assert replay_error < 1e-8
    parts = []
    for stroke in range(4):
        cc = [r for r in control if r['phase'] == f'measure_{stroke:02}']
        t = np.array([(r['host_ns']-base)/1e9 for r in cc])
        seq = np.array([r['sample_seq'] for r in cc])
        assert len(np.unique(seq)) == len(seq)
        b = np.array([filtered[s][0] for s in seq])
        raw = np.array([filtered[s][1] for s in seq])
        st = np.array([filtered[s][2] for s in seq])
        xy = np.array([[r['x_cmd_m'], r['y_cmd_m']] for r in cc]) * 1000
        arc = np.r_[0, np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))]
        cv = np.gradient(xy, t, axis=0)
        ct = angle(cv)
        # 0.2-second centered displacement on independent actual TCP records.
        av = np.column_stack([(np.interp(st+.1, at, ap[:,j]) -
                               np.interp(st-.1, at, ap[:,j]))/.2 for j in range(2)])
        theta = angle(av)
        speed = np.linalg.norm(av, axis=1)
        g = np.linalg.norm(b, axis=1)
        turn_rate = abs(np.degrees(np.gradient(np.unwrap(np.radians(ct)), t)))
        valid = ((st-.1 > t[0]) & (st+.1 < t[-1]) &
                 (st-.1 >= at[0]) & (st+.1 <= at[-1]) & (speed > 2) & (g > 30))
        body = valid & (arc >= 15) & (arc <= arc[-1]-10)
        stable = body & (turn_rate <= 20)
        parts.append(dict(stroke=np.full(len(t), stroke+1), t=t-t[0], seq=seq,
                          b=b, raw=raw, phi=angle(b), theta=theta, command_theta=ct,
                          speed=speed, g=g, arc=arc, valid=valid, body=body,
                          stable=stable, turn_rate=turn_rate, xy=xy))
    data = {key: np.concatenate([p[key] for p in parts]) for key in parts[0]}
    quality = dict(run=str(folder), run_id=manifest['run_id'], baseline_xy_uT=b0.tolist(),
                   snapshot_hashes_verified=True, ema_norm_replay_max_error_uT=replay_error,
                   sensor_rows=len(sensor), invalid_sensor_rows=sum(r['valid']!='true' for r in sensor),
                   max_tcp_interval_s=float(np.max(np.diff(at))),
                   max_tcp_read_ms=max((int(r['request_end_ns'])-int(r['request_start_ns']))/1e6 for r in actual),
                   writing_rows=len(data['t']), valid_rows=int(data['valid'].sum()),
                   stable_rows=int(data['stable'].sum()),
                   sensor_noise_xy_rss_uT=float(np.linalg.norm(baseline['std_uT'][:2])),
                   sources_sha256={name: hashlib.sha256((folder/name).read_bytes()).hexdigest()
                                   for name in ('manifest.json','sensor.csv','control.jsonl','actual_tcp.csv')})
    return data, parts, quality


def main():
    folders = sorted(RAW.iterdir())
    assert len(folders) == 2
    loaded = [load(p) for p in folders]
    report = {'runs': [r[2] for r in loaded], 'models': [], 'per_stroke': [], 'direction_groups': [],
              'gate_sensitivity': []}
    a, b = [r[0] for r in loaded]
    # Fit only run 8 stable body, freeze the model before evaluation on run 9.
    fitted = []
    for sign in (-1, 1):
        m = a['stable']
        offset = mean_angle(a['theta'][m] - sign*a['phi'][m])
        loss = metrics(sign*a['phi'][m]+offset-a['theta'][m])['mae_deg']
        fitted.append((loss, sign, offset))
    _, sign, offset = min(fitted)
    report['fit'] = dict(train_run=8, mask='stable', sign=sign, offset_deg=offset,
                         candidates=[dict(train_mae_deg=e,sign=s,offset_deg=o) for e,s,o in fitted])
    for index, (data, parts, quality) in enumerate(loaded, 8):
        predictions = {'raw_atan2': angle(data['raw']), 'delta_atan2': data['phi'],
                       '90_minus_phi': 90-data['phi'],
                       'run8_fitted': sign*data['phi']+offset}
        assert np.max(abs(wrap(angle(data['b'][:, ::-1])-(90-data['phi'])))) < 1e-10
        for min_speed in (2, 5):
            for min_signal in (30, 60, 100):
                m=data['stable'] & (data['speed']>min_speed) & (data['g']>min_signal)
                report['gate_sensitivity'].append(dict(run=index,min_speed_mm_s=min_speed,
                    min_signal_uT=min_signal,**metrics(90-data['phi'][m]-data['theta'][m])))
        for name, pred in predictions.items():
            for mask in ('valid', 'body', 'stable'):
                m = data[mask]
                report['models'].append(dict(run=index,model=name,subset=mask,
                                              **metrics(pred[m]-data['theta'][m])))
        report['runs'][index-8]['command_vs_actual_heading'] = metrics(
            data['command_theta'][data['stable']]-data['theta'][data['stable']])
        report['runs'][index-8]['actual_heading_range_stable_deg'] = np.percentile(
            data['theta'][data['stable']], [0, 50, 100]).tolist()
        for part in parts:
            m=part['stable']
            for model,pred in [('90_minus_phi',90-part['phi']),
                               ('run8_fitted',sign*part['phi']+offset)]:
                report['per_stroke'].append(dict(run=index,stroke=int(part['stroke'][0]),model=model,
                    **metrics(pred[m]-part['theta'][m])))
            for target,label in [(0,'+X'),(-90,'-Y')]:
                m = part['stable'] & (abs(wrap(part['theta']-target))<15)
                if m.sum() < 10:
                    continue
                report['direction_groups'].append(dict(run=index,stroke=int(part['stroke'][0]),
                    heading=label,n=int(m.sum()),actual_deg=mean_angle(part['theta'][m]),
                    magnetic_deg=mean_angle(part['phi'][m]),
                    estimated_deg=mean_angle(90-part['phi'][m]),
                    median_bx_uT=float(np.median(part['b'][m,0])),
                    median_by_uT=float(np.median(part['b'][m,1]))))
        # Numerical rows allow direct inspection of predictions and excluded samples.
        keys=('stroke','t','seq','arc','phi','theta','command_theta','speed','g','valid','body','stable')
        with (OUT/f'run{index}_samples.csv').open('w',newline='') as stream:
            writer=csv.writer(stream)
            writer.writerow([*keys,'ema_dBx_uT','ema_dBy_uT','estimate_90_minus_phi_deg','estimate_run8_fit_deg'])
            for j in range(len(data['t'])):
                writer.writerow([*[data[k][j] for k in keys],*data['b'][j],
                                 wrap(90-data['phi'][j]),wrap(sign*data['phi'][j]+offset)])
        fig, axes=plt.subplots(4,2,figsize=(13,11),layout='constrained')
        for row,part in enumerate(parts):
            axes[row,0].plot(part['arc'],part['b'][:,0],label='EMA ΔBx')
            axes[row,0].plot(part['arc'],part['b'][:,1],label='EMA ΔBy')
            axes[row,0].axhline(0,color='.6',lw=.7)
            axes[row,0].set(ylabel='磁响应 (µT)',title=f'第 {row+1} 笔：有符号磁分量')
            m=part['valid']
            for values,label,color in [(part['theta'],'实测 TCP 方向','#222222'),
                                       (wrap(90-part['phi']),'90° − φ','#2978b5'),
                                       (wrap(sign*part['phi']+offset),'第 8 次拟合映射','#ce7a27')]:
                line=np.where(m,values,np.nan)
                axes[row,1].plot(part['arc'],line,label=label,color=color,lw=1.2)
            axes[row,1].set(ylabel='基坐标行笔角 (°)',ylim=(-185,185),yticks=[-180,-90,0,90,180],
                            title=f'第 {row+1} 笔：方向估计')
            for ax in axes[row]:
                ax.set_xlabel('命令累计弧长 (mm)');ax.grid(alpha=.2)
        axes[0,0].legend(ncol=2);axes[0,1].legend(fontsize=8)
        fig.suptitle(f'中 · 第 {index} 次 | φ = atan2(EMA ΔBy, EMA ΔBx)\n方向参考为按时间对齐的实测 TCP；低速、弱信号及端点不显示',fontsize=14)
        fig.savefig(OUT/f'run{index}_directions.png',dpi=160);plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(12,5),layout='constrained')
    for index,(data,_,_) in enumerate(loaded,8):
        ax=axes[index-8]
        for stroke in range(1,5):
            m=data['stable'] & (data['stroke']==stroke)
            ax.scatter(data['b'][m,0],data['b'][m,1],s=5,alpha=.45,label=f'第 {stroke} 笔')
        ax.axhline(0,color='.5',lw=.7);ax.axvline(0,color='.5',lw=.7)
        ax.set(xlabel='EMA ΔBx (µT)',ylabel='EMA ΔBy (µT)',title=f'第 {index} 次：稳定正文样点')
        ax.set_aspect('equal');ax.grid(alpha=.2);ax.legend(markerscale=3)
    fig.savefig(OUT/'magnetic_plane.png',dpi=160);plt.close(fig)
    report['method'] = dict(angle_convention='base +X=0 deg, +Y=90 deg, wrapped to [-180,180)',
        magnetic_feature='EMA(B-B0) on all valid sensor rows; alpha=0.3, baseline warmup replayed',
        alignment='control sample_seq exact join to sensor; actual TCP interpolation at sensor host_rx_ns; read midpoint timestamps',
        actual_heading='atan2 of actual XY displacement over centered 0.2 s window; no fitted time shift',
        valid='measure only, actual speed >2 mm/s, EMA |dBxy| >30 uT, full 0.2s window inside writing and TCP range',
        body='valid plus command arc >=15 mm and <= total-10 mm',
        stable='body plus abs(command heading rate)<=20 deg/s',
        averaging='equal 20ms control-linked samples, not equal strokes or equal directions; correlated observations',
        validation='sign and circular offset fit on run 8 stable body only; evaluate frozen model on run 9',
        limitations=['Only two consecutive runs of one character; predominantly +X and -Y.',
                     'Writing tilt follows direction, so posture and movement effects are confounded.',
                     'Reference is actual TCP direction, not observed brush-tip motion or ink direction.',
                     'Run 9 stroke 3 is 5mm longer and magnetic targets differ; not identical replicates.',
                     '30uT gate is exploratory, not a calibrated angular confidence threshold.'])
    (OUT/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'fit':report['fit'],'models':[r for r in report['models'] if r['subset']=='stable'],
                      'per_stroke':report['per_stroke'],'groups':report['direction_groups'],
                      'quality':report['runs']},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
