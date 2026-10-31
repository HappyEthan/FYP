import csv,json,hashlib
from pathlib import Path
from brushbot.experiments.magnetic_timeseries import export_magnetic_timeseries


def fixture(tmp_path,rows,baseline=True):
    manifest={'baseline':{'baseline_id':0,'B0_uT':[10,20,30]}} if baseline else {}
    (tmp_path/'manifest.json').write_text(json.dumps(manifest))
    fields=['seq','sensor_t_us','host_rx_ns','Bx_uT','By_uT','Bz_uT','dBx_uT','dBy_uT','dBz_uT','baseline_id','valid','invalid_reason']
    with (tmp_path/'sensor.csv').open('w',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=fields);writer.writeheader();writer.writerows(rows)
    (tmp_path/'control.jsonl').write_text(json.dumps({'a_raw_uT':5.,'a_control_uT':4.,'a_ref_uT':None})+'\n')


def row(seq,t,**extra):
    return dict(seq=seq,sensor_t_us=t,host_rx_ns=seq*1000000,Bx_uT=13,By_uT=24,Bz_uT=30,valid='true',**extra)


def test_full_rate_export_preserves_source_and_marks_offline_baseline(tmp_path):
    fixture(tmp_path,[row(1,1000),row(2,4000,dBx_uT=3,dBy_uT=4,dBz_uT=0,baseline_id=0),row(3,7000)])
    source=tmp_path/'sensor.csv';digest=hashlib.sha256(source.read_bytes()).hexdigest()
    report=export_magnetic_timeseries(tmp_path)
    assert hashlib.sha256(source.read_bytes()).hexdigest()==digest
    assert report['sensor_samples']==3 and report['interpolated_samples']==0
    assert report['nominal_sensor_interval_us']==3000
    assert report['control_null_counts']=={'a_ref_uT':1}
    data=list(csv.DictReader(Path(report['output']).open()))
    assert data[0]['delta_origin']=='offline_first_baseline'
    assert data[1]['delta_origin']=='recorded'
    assert all(float(r['dBxy_norm_uT'])==5 for r in data)
    assert float(data[-1]['t_sensor_s'])==.006


def test_time_gap_is_reported_not_filled(tmp_path):
    fixture(tmp_path,[row(1,1000),row(2,4000),row(3,7000),row(4,510000)])
    report=export_magnetic_timeseries(tmp_path)
    assert report['sensor_samples']==4
    assert report['gaps']==[{'before_seq':4,'interval_us':503000.,'nominal_interval_us':3000.}]


def test_invalid_and_missing_baseline_are_not_fabricated(tmp_path):
    fixture(tmp_path,[row(1,1000),dict(seq=2,sensor_t_us=4000,host_rx_ns=2,Bx_uT='',By_uT='',Bz_uT='',valid='false',invalid_reason='non_finite')],baseline=False)
    report=export_magnetic_timeseries(tmp_path)
    data=list(csv.DictReader(Path(report['output']).open()))
    assert report['invalid_samples']==1 and report['delta_missing_rows']==2
    assert data[0]['Bx_uT']=='13.0' and data[0]['dBxy_norm_uT']==''
    assert data[1]['Bx_uT']=='' and data[1]['dBxy_norm_uT']==''


def test_sensor_clock_wrap(tmp_path):
    fixture(tmp_path,[row(1,2**32-1000),row(2,2000),row(3,5000)])
    report=export_magnetic_timeseries(tmp_path)
    assert report['sensor_time_faults']==0
    assert report['nominal_sensor_interval_us']==3000
    assert report['elapsed_sensor_s']==.006
