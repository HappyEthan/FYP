"""Export raw-rate magnetic data without interpolation or modifying run logs."""
import csv
import json
import math
from pathlib import Path
import statistics

FIELDS=('seq','sensor_t_us','host_rx_ns','t_sensor_s','dt_sensor_us','gap_before',
        'Bx_uT','By_uT','Bz_uT','dBx_uT','dBy_uT','dBz_uT',
        'dBxy_norm_uT','dBxyz_norm_uT','baseline_id','delta_origin','valid','invalid_reason')


def _number(value):
    try:
        value=float(value)
        return value if math.isfinite(value) else None
    except (TypeError,ValueError):return None


def export_magnetic_timeseries(run_dir):
    run_dir=Path(run_dir)
    manifest=json.loads((run_dir/'manifest.json').read_text())
    baselines=manifest.get('baselines') or ([manifest['baseline']] if manifest.get('baseline') else [])
    baselines={str(item.get('baseline_id',0)):item for item in baselines if isinstance(item,dict)}
    first=next(iter(baselines.values()),None)
    with (run_dir/'sensor.csv').open(newline='') as handle:rows=list(csv.DictReader(handle))
    times=[_number(row.get('sensor_t_us')) for row in rows]
    intervals=[]
    for a,b in zip(times[:-1],times[1:]):
        if a is None or b is None:continue
        delta=b-a
        if delta<0 and a>2**32-1_000_000 and b<1_000_000:delta+=2**32
        if delta>0:intervals.append(delta)
    nominal=statistics.median(intervals) if intervals else None
    directory=run_dir/'analysis';directory.mkdir(exist_ok=True)
    path=directory/'magnetic_timeseries.csv';temporary=path.with_suffix('.csv.tmp')
    elapsed=0.;last=None;gaps=[];invalid=0;offline=0;raw_missing=0;delta_missing=0;time_faults=0
    with temporary.open('w',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=FIELDS);writer.writeheader()
        for row,timestamp in zip(rows,times):
            dt=None;time_valid=timestamp is not None
            if timestamp is not None and last is not None:
                dt=timestamp-last
                if dt<0 and last>2**32-1_000_000 and timestamp<1_000_000:dt+=2**32
                if dt<=0:time_faults+=1;time_valid=False
                else:elapsed+=dt/1e6
            if timestamp is not None:last=timestamp
            gap=bool(dt is not None and nominal is not None and dt>2*nominal)
            if gap:gaps.append(dict(before_seq=int(row['seq']),interval_us=dt,nominal_interval_us=nominal))
            valid=row.get('valid','').lower()=='true'
            raw=[_number(row.get(key)) for key in ('Bx_uT','By_uT','Bz_uT')]
            delta=[_number(row.get(key)) for key in ('dBx_uT','dBy_uT','dBz_uT')]
            baseline_id=row.get('baseline_id','');origin='recorded'
            if not valid:invalid+=1
            if any(value is None for value in raw):raw_missing+=1
            if any(value is None for value in delta):
                baseline=baselines.get(str(baseline_id)) if baseline_id!='' else first
                b0=baseline.get('B0_uT') if baseline else None
                if valid and all(v is not None for v in raw) and isinstance(b0,list) and len(b0)==3 and all(_number(v) is not None for v in b0):
                    delta=[v-float(offset) for v,offset in zip(raw,b0)]
                    baseline_id=baseline.get('baseline_id',0)
                    origin='offline_first_baseline' if row.get('baseline_id','')=='' else 'offline_recorded_baseline'
                    offline+=1
                else:origin='unavailable'
            available=valid and all(value is not None for value in delta)
            if not available:delta_missing+=1
            output={key:row.get(key,'') for key in ('seq','sensor_t_us','host_rx_ns','valid','invalid_reason')}
            output.update(t_sensor_s=elapsed if time_valid else None,dt_sensor_us=dt,gap_before=gap,
                baseline_id=baseline_id,delta_origin=origin,
                dBxy_norm_uT=math.hypot(delta[0],delta[1]) if available else None,
                dBxyz_norm_uT=math.sqrt(sum(v*v for v in delta)) if available else None)
            output.update(dict(zip(('Bx_uT','By_uT','Bz_uT'),raw)))
            output.update(dict(zip(('dBx_uT','dBy_uT','dBz_uT'),delta)))
            writer.writerow(output)
    temporary.replace(path)
    control_path=run_dir/'control.jsonl';nulls={};control_samples=0
    if control_path.exists():
        with control_path.open() as handle:
            for line in handle:
                if not line.strip():continue
                row=json.loads(line);control_samples+=1
                for key,value in row.items():
                    if value is None:nulls[key]=nulls.get(key,0)+1
    summary=dict(source_run=str(run_dir.resolve()),output=str(path.resolve()),sensor_samples=len(rows),
        nominal_sensor_interval_us=nominal,nominal_sensor_rate_hz=1e6/nominal if nominal else None,
        elapsed_sensor_s=elapsed,invalid_samples=invalid,raw_missing_rows=raw_missing,
        delta_missing_rows=delta_missing,offline_baseline_rows=offline,sensor_time_faults=time_faults,
        gaps=gaps,control_samples=control_samples,control_null_counts=nulls,
        interpolated_samples=0,raw_logs_modified=False,
        notes=['Sensor time is the sampling clock; host receive times may arrive in batches.',
               'Baseline-acquisition rows use the first frozen B0 offline and are explicitly marked; not historical control feedback.',
               'No missing samples or target fields are filled with synthetic measurements.',
               'dBxy_norm_uT is unfiltered response, not force. Existing a_control_uT remains in control.jsonl.'])
    summary_path=directory/'magnetic_sampling_summary.json';temp=summary_path.with_suffix('.json.tmp')
    temp.write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False)+'\n');temp.replace(summary_path)
    return summary
