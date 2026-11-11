"""Input contracts: no synthetic labels from missing strokes or broken sensor history."""
import csv
import hashlib
import io
import json
import zipfile

import numpy as np
import pytest


def archive_fixture(path, *, count=7, run='run-a', gap=False, seed=1):
    rng = np.random.default_rng(seed)
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=['seq', 'sensor_t_us', 'dBx_uT', 'dBy_uT', 'valid', 'baseline_id'])
    writer.writeheader()
    controls = []
    for i in range(200 + count * 160):
        stroke = max(0, min(count-1, (i-200)//160))
        t = ((i-200) % 160)/159
        angle = .4*np.sin(t*4+stroke)
        magnitude = 90+stroke*35+20*np.sin(t*(stroke+1)*3)+rng.normal(0,.05)
        writer.writerow(dict(seq=i, sensor_t_us=i*1000+(5000 if gap and i>=240 else 0),
                             dBx_uT=magnitude*np.cos(angle), dBy_uT=magnitude*np.sin(angle),
                             valid='true', baseline_id='one'))
    for j in range(count):
        for seq in range(210+j*160, 350+j*160, 10):
            controls.append(dict(phase=f'measure_{j:02d}', sample_seq=seq))
    members = {'manifest.json':json.dumps(dict(status='completed',run_id=run)).encode(),
               'sensor.csv':stream.getvalue().encode(),
               'control.jsonl':'\n'.join(json.dumps(x) for x in controls).encode()}
    members['bundle_manifest.json'] = json.dumps(dict(version=1,format='brushrun',
        sha256={k:hashlib.sha256(v).hexdigest() for k,v in members.items()})).encode()
    with zipfile.ZipFile(path,'w') as z:
        for k,v in members.items(): z.writestr(k,v)
    return path


def test_seven_strokes_and_first10_contract(tmp_path):
    from brushbot.stroke_classification.data import load_experiment
    ex = load_experiment(archive_fixture(tmp_path/'a.brushrun'))
    assert [s.label for s in ex.strokes] == list(range(7))
    s = ex.strokes[0]
    assert s.amplitude.shape == (128,)
    assert np.isfinite(s.amplitude).all()
    ref = np.median(s.native_ema[s.native_tau <= .1+1e-12])
    assert s.baseline == pytest.approx(ref)
    assert s.representations['A1'][0] == pytest.approx(s.amplitude[0]-ref)
    assert s.representations['D3'].shape == (256,)


@pytest.mark.parametrize('count,gap', [(5,False),(7,True)])
def test_reject_incomplete_or_sensor_gap(tmp_path,count,gap):
    from brushbot.stroke_classification.data import load_experiment
    with pytest.raises(ValueError):
        load_experiment(archive_fixture(tmp_path/'bad.brushrun',count=count,gap=gap))


def test_copy_and_run_identity_deduplicated(tmp_path):
    from brushbot.stroke_classification.data import load_experiment, unique_experiments
    a=load_experiment(archive_fixture(tmp_path/'a.brushrun'))
    b=load_experiment(archive_fixture(tmp_path/'b.brushrun'))
    assert len(unique_experiments([a,b])) == 1


def test_changed_boundary_changes_snapshot(tmp_path):
    from brushbot.stroke_classification.data import load_experiment,unique_experiments
    path=archive_fixture(tmp_path/'a.brushrun')
    before=load_experiment(path)
    with zipfile.ZipFile(path) as z:contents={n:z.read(n) for n in z.namelist()}
    lines=[json.loads(x) for x in contents['control.jsonl'].splitlines()]
    lines[0]['sample_seq']+=2
    contents['control.jsonl']='\n'.join(json.dumps(x) for x in lines).encode()
    contents['bundle_manifest.json']=json.dumps(dict(version=1,format='brushrun',sha256={k:hashlib.sha256(v).hexdigest() for k,v in contents.items() if k!='bundle_manifest.json'})).encode()
    with zipfile.ZipFile(path,'w') as z:
        for k,v in contents.items():z.writestr(k,v)
    after=load_experiment(path)
    assert before.source_hash!=after.source_hash
    with pytest.raises(ValueError):unique_experiments([before,after])


def test_explicit_incompatible_task_protocol_is_not_relabelled(tmp_path):
    from brushbot.stroke_classification.data import load_experiment
    path=archive_fixture(tmp_path/'wrong.brushrun')
    with zipfile.ZipFile(path) as z:members={n:z.read(n) for n in z.namelist()}
    meta=json.loads(members['manifest.json']);meta['stroke_labels']=['横']*7
    members['manifest.json']=json.dumps(meta).encode()
    members['bundle_manifest.json']=json.dumps(dict(version=1,format='brushrun',sha256={k:hashlib.sha256(v).hexdigest() for k,v in members.items() if k!='bundle_manifest.json'})).encode()
    with zipfile.ZipFile(path,'w') as z:
        for k,v in members.items():z.writestr(k,v)
    with pytest.raises(ValueError,match='协议|顺序'):load_experiment(path)


def test_direction_mask_does_not_bridge_invalid_interval():
    from brushbot.stroke_classification.features import direction_features
    tau=np.linspace(0,1,1001)
    angle=np.linspace(3,3.8,len(tau))
    magnitude=np.ones(len(tau))*100
    magnitude[400:450]=0
    features, info = direction_features(tau,np.cos(angle),np.sin(angle),magnitude)
    assert np.isnan(features['D3']).any()
    assert info['coverage'] < 1
    assert np.nanmax(np.abs(features['D2'])) < .02


def test_a1_matches_historical_features_readonly():
    from pathlib import Path
    from brushbot.stroke_classification.data import load_experiment
    root=Path(__file__).resolve().parents[1]
    folder=root/'outputs/stroke_model_random10_20261106'
    if not (folder/'data_manifest.json').exists(): pytest.skip('historical artifacts not installed')
    source=json.loads((folder/'data_manifest.json').read_text())['sources'][0]['path']
    ex=load_experiment(source,expected_count=5)
    with np.load(folder/'features_128.npz') as z:
        np.testing.assert_allclose(np.array([s.representations['A1'] for s in ex.strokes]),z['X'][:5],atol=1e-9)
