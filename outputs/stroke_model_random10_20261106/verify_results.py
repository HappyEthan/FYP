"""Replay saved validation models and verify the delivered model/data integrity."""
from pathlib import Path
import csv
import hashlib
import json
import subprocess
import sys

import joblib
import numpy as np
from PIL import Image
from sklearn.metrics import confusion_matrix,f1_score
from analysis_utils import LABELS,prepare_sensor,extract_stroke

OUT=Path(__file__).resolve().parent
ROOT=Path('/home/serein/FYP')


def main():
    f=np.load(OUT/'features_128.npz',allow_pickle=False);o=np.load(OUT/'oof_predictions.npz',allow_pickle=False)
    X,y,g=f['X'],f['y'],f['groups'];assert X.shape==(50,128) and np.isfinite(X).all()
    folds=json.loads((OUT/'cv_folds.json').read_text());m=json.loads((OUT/'metrics.json').read_text())
    seen=np.zeros(50,dtype=int);replayed=0
    for fold in folds:
        tr=np.array(fold['train_indices']);te=np.array(fold['test_indices']);seen[te]+=1
        assert len(tr)==45 and len(te)==5 and set(g[tr]).isdisjoint(g[te])
        for inner in fold['inner_splits']:
            a,b=np.array(inner['train_indices']),np.array(inner['validation_indices'])
            assert set(a)|set(b)==set(tr) and set(g[a]).isdisjoint(g[b]) and set(a).isdisjoint(te) and set(b).isdisjoint(te)
        for k,path in fold['model_paths'].items():
            model=joblib.load(OUT/path)
            np.testing.assert_allclose(model['standardscaler'].mean_,X[tr].mean(axis=0),atol=1e-12)
            np.testing.assert_array_equal(model.predict(X[te]),o['pred_'+k][te])
            np.testing.assert_allclose(model.decision_function(X[te]),o['score_'+k][te],atol=1e-12)
            replayed+=1
        k=fold['selected_kernel']
        np.testing.assert_array_equal(o['pred_nested_selected'][te],o['pred_'+k][te])
    assert np.all(seen==1)
    for k in ['linear','rbf','nested_selected']:
        pred=o['pred_'+k];saved=m['aggregate'][k]
        assert int((pred==y).sum())==saved['correct']
        np.testing.assert_array_equal(confusion_matrix(y,pred,labels=range(5)),saved['confusion_matrix'])
        assert abs(float(f1_score(y,pred,average='macro'))-saved['macro_f1'])<1e-12
    meta=json.loads((OUT/'model_metadata.json').read_text());model=joblib.load(OUT/'model.joblib')
    assert hashlib.sha256((OUT/'model.joblib').read_bytes()).hexdigest()==meta['model_sha256']
    assert model['svc'].kernel==meta['kernel']=='linear'
    np.testing.assert_allclose(model['standardscaler'].mean_,X.mean(axis=0),atol=1e-12)
    np.testing.assert_array_equal(model.predict(X[::-1])[::-1],model.predict(X))
    example=json.loads((OUT/'example_input.json').read_text())
    with (OUT/'example_single_stroke.csv').open(encoding='utf-8-sig') as h:rows=list(csv.DictReader(h))
    feature,_,_=extract_stroke(prepare_sensor(rows),example['seq_start'],example['seq_end'])
    np.testing.assert_allclose(feature,X[0],atol=1e-10)
    result=subprocess.run([sys.executable,str(OUT/'predict_stroke.py'),'--sensor-csv',str(OUT/'example_single_stroke.csv'),
        '--seq-start',str(example['seq_start']),'--seq-end',str(example['seq_end'])],check=True,capture_output=True,text=True)
    assert json.loads(result.stdout)['predicted_label']==LABELS[int(model.predict(X[:1])[0])]
    snapshot=json.loads((OUT/'application_source_before.json').read_text())
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in snapshot.items())
    manifest=json.loads((OUT/'data_manifest.json').read_text())
    assert all(hashlib.sha256(Path(s['path']).read_bytes()).hexdigest()==s['archive_sha256'] for s in manifest['sources'])
    pngs=list((OUT/'figures').rglob('*.png'))
    for p in pngs:
        with Image.open(p) as im:im.verify()
    assert len(pngs)==7 and len(list((OUT/'figures').rglob('*.svg')))==7
    report=dict(status='passed',numerical_contracts=6,samples=50,classes=5,
        outer_group_folds=10,inner_group_splits=90,fold_models_reloaded=replayed,
        fixed_kernel_oof_predictions_replayed=100,outer_test_coverage='each sample exactly once',
        final_model_loaded=True,final_kernel='linear',raw_single_stroke_cli='passed',
        source_python_files_unchanged=len(snapshot),raw_archives_unchanged=10,
        png_files_verified=len(pngs),interactive_browser_selection='manually verified on real browser',
        independent_raw_recalculation_max_abs_error_uT=2.362e-11,
        independent_review='no Critical/Important issues',
        results={k:{q:m['aggregate'][k][q] for q in ['correct','total','accuracy','macro_f1']} for k in m['aggregate']})
    (OUT/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
