"""Read-only adapter for the verified 2026-11-06 five-class amplitude baseline."""
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.decomposition import PCA

from . import LABELS,VERSION
from .data import load_experiment
from .features import FeatureConfig
from .metrics import evaluate
from .models import Candidate,MagneticModel
from .training import source_fingerprint,stack_strokes

KNOWN_SHA='e6617ec60f7d1390a741def73f64ca9e613723b75fbcdc8feb722d42de02587b'


def import_historical_baseline(store,folder):
    folder=Path(folder).resolve()
    for task in store.list_tasks():
        if task.get('legacy_sha')==KNOWN_SHA:return task
    if hashlib.sha256((folder/'model.joblib').read_bytes()).hexdigest()!=KNOWN_SHA:
        raise ValueError('此入口只支持已核验的2026-11-06历史五类基线')
    meta=json.loads((folder/'model_metadata.json').read_text())
    sources=json.loads((folder/'data_manifest.json').read_text())['sources']
    config=FeatureConfig();experiments=[load_experiment(s['path'],config,expected_count=5) for s in sources]
    strokes=[s for e in experiments for s in e.strokes]
    features=stack_strokes(strokes)
    with np.load(folder/'features_128.npz') as f:
        np.testing.assert_allclose(features['A1'],f['X'],atol=1e-9)
    pipeline=joblib.load(folder/'model.joblib')
    model=MagneticModel(Candidate('F0'))
    model.scalers=[pipeline['standardscaler']];model.svcs=[pipeline['svc']]
    model.classes_=model.svcs[0].classes_;model.support_=model.svcs[0].support_
    transformed=model.project_input(features)
    # New visualization only: the saved historical SVC and scaler are never fitted.
    model.pca=PCA(n_components=3,svd_solver='full').fit(transformed)
    model.training_projection=model.pca.transform(transformed)
    y=np.array([s.label for s in strokes]);groups=np.array([s.run_id for s in strokes])
    with np.load(folder/'oof_predictions.npz') as oof:
        pred=oof['pred_linear'];scores=oof['score_linear']
    rows=[dict(sample_id=s.sample_id,run_id=s.run_id,stroke=s.index,true=int(y[i]),predicted=int(pred[i]),scores=scores[i].tolist()) for i,s in enumerate(strokes)]
    bundle=dict(version=VERSION,labels=list(LABELS[:5]),model=model,pca=model.pca,feature_config=config.to_dict(),
        reference_mode='first_10_percent_fallback',training_runs=sorted(set(groups)),sensor_hashes=[e.sensor_hash for e in experiments],
        training_strokes=strokes,training_projection=model.training_projection,candidate=dict(family='F0',kernel='linear',C=1.,amplitude='A1'),
        versions=meta['versions'],source_fingerprint=source_fingerprint(experiments),legacy_source=str(folder))
    task=store.create_task('历史五类幅值基线 · 2026-11-06',dict(version=VERSION,legacy_sha=KNOWN_SHA,run_count=10,sample_count=50,
        labels=list(LABELS[:5]),sources=[dict(path=e.path,run_id=e.run_id,sensor_hash=e.sensor_hash,source_hash=e.source_hash,name=e.name) for e in experiments],
        source_fingerprint=bundle['source_fingerprint'],conditions={'范围':'历史固定linear留一回测；不是新七类训练或当前候选搜索成绩'}))
    item=store.add_model(task,dict(name='历史幅值 linear SVC',family='F0',rank=1,metrics=evaluate(y,pred,groups,5),
                                 folds=[],candidate=bundle['candidate'],predictions=rows,tests=[],robustness=[]),bundle)
    task['branches']={'F0':dict(status='completed',model_id=item['id'])};store.complete(task)
    return task
