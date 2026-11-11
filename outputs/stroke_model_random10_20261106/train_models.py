"""Offline five-class training on ten frozen random robot experiments.

No application source, robot configuration or original archive is modified.
"""
from pathlib import Path
import csv
import hashlib
import io
import importlib.metadata
import json
import platform
import zipfile
from datetime import datetime
from zoneinfo import ZoneInfo

import joblib
import numpy as np
from sklearn.metrics import accuracy_score, balanced_accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC
from threadpoolctl import threadpool_limits

from analysis_utils import LABELS, TAU, PREPROCESSING, prepare_sensor, extract_stroke, choose_kernel

ROOT=Path('/home/serein/FYP')
OUT=Path(__file__).resolve().parent


def sha(data):return hashlib.sha256(data).hexdigest()


def write_json(path, data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def write_csv(path, rows):
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)


def metrics(y,p):
    return dict(correct=int(np.sum(y==p)),total=len(y),accuracy=float(accuracy_score(y,p)),
        macro_f1=float(f1_score(y,p,labels=range(5),average='macro',zero_division=0)),
        balanced_accuracy=float(balanced_accuracy_score(y,p)),
        confusion_matrix=confusion_matrix(y,p,labels=range(5)).tolist(),
        per_class=classification_report(y,p,labels=range(5),target_names=LABELS,output_dict=True,zero_division=0))


def new_model(kernel):
    return make_pipeline(StandardScaler(),SVC(kernel=kernel,C=1.,gamma='scale',
                         probability=False,decision_function_shape='ovr',break_ties=True))


def input_snapshot():
    return {str(p.relative_to(ROOT)):sha(p.read_bytes())
            for d in ['src','scripts','tests'] for p in sorted((ROOT/d).rglob('*.py'))}


def load_data():
    features=[];ys=[];groups=[];samples=[];native=[];provenance=[]
    for run in range(1,11):
        name=f'随机测试1（xy，磁）_{run:03d}'
        path=ROOT/'runs/毛笔实验数据'/name/(name+'.brushrun')
        archive_bytes=path.read_bytes()
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as z:
            contents={f:z.read(f) for f in ['manifest.json','experiment.json','sensor.csv',
                'control.jsonl','preflight.json','variation.json','variation_arrays.npz','strokeplan.npz']}
        m=json.loads(contents['manifest.json']);e=json.loads(contents['experiment.json'])
        v=json.loads(contents['variation.json']);pre=json.loads(contents['preflight.json'])
        assert m['status']==e['status']=='completed' and v['options']['enabled']
        assert v['options']['xy_enabled'] and v['options']['magnetic_enabled']
        assert len(pre['execution_order'])==5
        with np.load(io.BytesIO(contents['strokeplan.npz']),allow_pickle=False) as n:
            assert int(n['n_strokes'])==5
            meta=json.loads(str(n['meta_json']))
            assert meta['stroke_names']==['新增首笔5','笔画1','笔画2','笔画3','笔画4']
        rows=list(csv.DictReader(io.StringIO(contents['sensor.csv'].decode())))
        sensor=prepare_sensor(rows)
        control=[json.loads(l) for l in contents['control.jsonl'].decode().splitlines() if l.strip()]
        for cls in range(5):
            ticks=[r for r in control if r.get('phase')==f'measure_{cls:02d}']
            assert ticks and all(r.get('sample_seq') is not None for r in ticks)
            sequences=np.array([int(r['sample_seq']) for r in ticks])
            assert np.all(np.diff(sequences)>=0)
            first,last=int(sequences[0]),int(sequences[-1])
            x,base,c=extract_stroke(sensor,first,last)
            features.append(x);ys.append(cls);groups.append(run);native.append(c)
            samples.append(dict(sample_id=f'{m["run_id"]}_stroke{cls+1:02d}',run_number=run,
                run_name=name,run_id=m['run_id'],stroke_index=cls+1,true_label=LABELS[cls],
                label_source='frozen acquisition task and audited stroke identity; not image adjudication',
                phase=f'measure_{cls:02d}',seq_start=first,seq_end=last,
                sensor_samples=len(c['seq']),control_samples=len(ticks),duration_s=float(c['elapsed'][-1]),
                reference_baseline_uT=base,baseline_mode='first_10_percent_fallback',
                ema_min_uT=float(c['ema'].min()),ema_max_uT=float(c['ema'].max()),
                quality_status='valid',invalid_samples=0,sampling_gaps=0))
            if run==1 and cls==0:
                begin=sensor['seq_index'][first];end=sensor['seq_index'][last]
                write_csv(OUT/'example_single_stroke.csv',rows[begin-100:end+1])
                write_json(OUT/'example_input.json',dict(seq_start=first,seq_end=last,
                    true_label=LABELS[cls],sample_id=samples[-1]['sample_id'],
                    role='training-sample interface demonstration, not independent evaluation'))
        provenance.append(dict(run_number=run,name=name,run_id=m['run_id'],path=str(path),
            started_at_beijing=datetime.fromisoformat(m['started_at']).astimezone(ZoneInfo('Asia/Shanghai')).isoformat(),
            archive_sha256=sha(archive_bytes),member_sha256={k:sha(b) for k,b in contents.items()},
            root_seed=str(v['batch']['root_seed']),parameters=v.get('parameters',{}),
            effective_statistics=v.get('statistics',{}),scales=v.get('scales',{})))
    X=np.array(features);y=np.array(ys);g=np.array(groups)
    assert X.shape==(50,128) and np.all(np.isfinite(X))
    assert len({p['run_id'] for p in provenance})==10
    assert len({p['root_seed'] for p in provenance})==10
    assert len({p['member_sha256']['variation_arrays.npz'] for p in provenance})==10
    assert np.array_equal(np.bincount(y),[10]*5)
    return X,y,g,samples,native,provenance


def cross_validate(X,y,g):
    folds=[]
    predictions={k:np.full(len(y),-1,dtype=int) for k in ['linear','rbf','nested_selected']}
    scores={k:np.full((len(y),5),np.nan) for k in predictions}
    (OUT/'fold_models').mkdir(exist_ok=True)
    for tr,te in LeaveOneGroupOut().split(X,y,g):
        held=int(g[te][0]);assert set(g[tr]).isdisjoint(g[te])
        assert len(tr)==45 and len(te)==5
        inner_preds={k:np.full(len(tr),-1,dtype=int) for k in ['linear','rbf']}
        inner_splits=[]
        for itr,ite in LeaveOneGroupOut().split(X[tr],y[tr],g[tr]):
            assert set(g[tr[itr]]).isdisjoint(g[tr[ite]])
            inner_splits.append(dict(train_indices=tr[itr].tolist(),validation_indices=tr[ite].tolist()))
            for k in inner_preds:
                model=new_model(k).fit(X[tr[itr]],y[tr[itr]])
                np.testing.assert_allclose(model['standardscaler'].mean_,X[tr[itr]].mean(axis=0))
                inner_preds[k][ite]=model.predict(X[tr[ite]])
        inner_metrics={k:metrics(y[tr],p) for k,p in inner_preds.items()}
        kernel=choose_kernel(inner_metrics['linear']['macro_f1'],inner_metrics['rbf']['macro_f1'])
        paths={};means={}
        for k in ['linear','rbf']:
            model=new_model(k).fit(X[tr],y[tr])
            np.testing.assert_allclose(model['standardscaler'].mean_,X[tr].mean(axis=0))
            predictions[k][te]=model.predict(X[te]);scores[k][te]=model.decision_function(X[te])
            rel=f'fold_models/run{held:02d}_{k}.joblib';joblib.dump(model,OUT/rel)
            paths[k]=rel;means[k]=model['standardscaler'].mean_.tolist()
        predictions['nested_selected'][te]=predictions[kernel][te]
        scores['nested_selected'][te]=scores[kernel][te]
        folds.append(dict(held_out_run=held,train_indices=tr.tolist(),test_indices=te.tolist(),
            selected_kernel=kernel,inner_metrics=inner_metrics,inner_splits=inner_splits,
            model_paths=paths,scaler_means=means,
            outer_metrics={k:metrics(y[te],p[te]) for k,p in predictions.items()}))
        print(f'fold {held:02d}/10: inner selected {kernel}; outer correct '+
              ', '.join(f'{k}={int((p[te]==y[te]).sum())}/5' for k,p in predictions.items()),flush=True)
    assert all(np.all(p>=0) for p in predictions.values())
    return predictions,scores,folds


def main():
    before=input_snapshot()
    X,y,g,samples,native,provenance=load_data()
    write_json(OUT/'application_source_before.json',before)
    write_csv(OUT/'sample_audit.csv',samples)
    write_json(OUT/'excluded_samples.json',[])
    np.savez_compressed(OUT/'features_128.npz',X=X,y=y,groups=g,tau=TAU,
        sample_ids=np.array([r['sample_id'] for r in samples]))
    feature_rows=[]
    for i,s in enumerate(samples):
        for j in range(128):feature_rows.append(dict(sample_id=s['sample_id'],run_number=int(g[i]),
            stroke_label=LABELS[y[i]],tau=float(TAU[j]),delta_uT=float(X[i,j])))
    write_csv(OUT/'features_128.csv',feature_rows)
    with (OUT/'curves_native.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['sample_id','run_number','stroke_label','seq','sensor_t_us','elapsed_s','tau','dBx_uT','dBy_uT','raw_uT','ema_uT'])
        for i,c in enumerate(native):
            for j in range(len(c['seq'])):
                w.writerow([samples[i]['sample_id'],int(g[i]),LABELS[y[i]],*[c[k][j] for k in ['seq','raw_sensor_t_us','elapsed','tau','bx','by','raw','ema']]])
    with threadpool_limits(limits=1):
        predictions,scores,folds=cross_validate(X,y,g)
        overall={k:metrics(y,p) for k,p in predictions.items()}
        selected=choose_kernel(overall['linear']['macro_f1'],overall['rbf']['macro_f1'])
        final=new_model(selected).fit(X,y)
        joblib.dump(final,OUT/'model.joblib')
    write_json(OUT/'cv_folds.json',folds)
    write_json(OUT/'metrics.json',dict(primary='nested_selected',evaluation='nested leave-one-whole-run-out; 10 outer groups, 9 inner groups',
        aggregate=overall,majority_baseline=metrics(y,np.zeros(len(y),dtype=int)),
        position_control=dict(accuracy=1.,note='task-order mapping only; not magnetic recognition'),
        final_kernel=selected,final_training_samples=len(y),
        final_selection_rule='rbf only if fixed-kernel full-data grouped-CV macro_f1 exceeds linear by >0.02; else linear',
        independent_new_test_runs=0))
    rows=[]
    for k,p in predictions.items():
        for i,s in enumerate(samples):
            rows.append(dict(sample_id=s['sample_id'],run_number=int(g[i]),true_label=LABELS[y[i]],
                model=k,selected_kernel=folds[int(g[i])-1]['selected_kernel'] if k=='nested_selected' else k,
                predicted_label=LABELS[p[i]],correct=bool(p[i]==y[i]),
                **{f'score_{LABELS[c]}':float(scores[k][i,c]) for c in range(5)}))
    write_csv(OUT/'predictions.csv',rows)
    np.savez_compressed(OUT/'oof_predictions.npz',**{f'pred_{k}':v for k,v in predictions.items()},
        **{f'score_{k}':v for k,v in scores.items()})
    versions={name:importlib.metadata.version(name) for name in ['numpy','scipy','scikit-learn','matplotlib','joblib','threadpoolctl']}
    model_meta=dict(created_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
        model_type='sklearn Pipeline(StandardScaler,SVC)',kernel=selected,C=1.,gamma='scale',
        break_ties=True,decision_function_shape='ovr',probability=False,
        label_mapping={str(i):n for i,n in enumerate(LABELS)},preprocessing=PREPROCESSING,
        training_samples=50,training_runs=10,feature_dimensions=128,
        model_sha256=sha((OUT/'model.joblib').read_bytes()),versions=versions,python=platform.python_version(),
        input_format='model.joblib takes already-preprocessed 128-point delta-uT vectors; predict_stroke.py handles raw CSV',
        scope='five known classes, pre-segmented complete measure stroke; no unknown rejection or live segmenter',
        metrics_role='CV evaluates the modeling procedure; final model has not seen a fresh independent test run')
    write_json(OUT/'model_metadata.json',model_meta)
    write_json(OUT/'data_manifest.json',dict(sources=provenance,application_source_snapshot=before))
    (OUT/'requirements.txt').write_text('\n'.join(f'{k}=={v}' for k,v in versions.items())+'\n')
    from visual_report import render_all
    render_all(OUT,X,y,g,samples,native,predictions,scores,folds,overall,model_meta)
    assert before==input_snapshot(),'application source files changed during analysis'
    for p in provenance:assert sha(Path(p['path']).read_bytes())==p['archive_sha256']
    write_json(OUT/'source_integrity.json',dict(application_source_unchanged=True,all_ten_archives_unchanged=True))
    print(json.dumps(dict(final_kernel=selected,metrics={k:{q:v[q] for q in ['correct','total','accuracy','macro_f1']} for k,v in overall.items()}),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
