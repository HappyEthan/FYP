"""Historical artifacts are adapted read-only, never retrained or overwritten."""
from pathlib import Path
import hashlib
import pytest


def test_known_five_class_baseline_import_readonly(tmp_path):
    from dataclasses import replace
    from brushbot.stroke_classification.legacy import import_historical_baseline
    from brushbot.stroke_classification.store import ModelStore
    from brushbot.stroke_classification.predict import predict_strokes
    folder=Path(__file__).resolve().parents[1]/'outputs/stroke_model_random10_20261106'
    if not (folder/'model.joblib').exists():pytest.skip('local historical model not present')
    before=hashlib.sha256((folder/'model.joblib').read_bytes()).hexdigest()
    store=ModelStore(tmp_path/'store');task=import_historical_baseline(store,folder)
    assert len(task['labels'])==5
    bundle=store.load_bundle(task['id'],task['models'][0]['id'])
    result=predict_strokes(bundle,bundle['training_strokes'][:5])
    assert len(result[0]['scores'])==5
    assert task['models'][0]['metrics']['correct']==48
    out_of_scope=replace(bundle['training_strokes'][0],label=5,index=6,run_id='new-run')
    predicted=predict_strokes(bundle,[out_of_scope])[0]
    assert predicted['unsupported'] and predicted['predicted'] is None
    assert predicted['correct'] is None and predicted['scores'] is None
    assert hashlib.sha256((folder/'model.joblib').read_bytes()).hexdigest()==before
    same=import_historical_baseline(store,folder)
    assert same['id']==task['id']
