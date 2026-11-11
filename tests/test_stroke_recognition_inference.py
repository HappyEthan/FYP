import threading
import time
from dataclasses import replace

import numpy as np
import pytest

from brushbot.stroke_classification.features import prepare_sensor, extract
from brushbot.stroke_classification.data import Stroke
from brushbot.stroke_classification.predict import predict_strokes
from brushbot.stroke_classification.store import ModelStore
from brushbot.stroke_classification.training import TrainConfig, train
from brushbot.stroke_recognition.history import load_model
from brushbot.stroke_recognition.inference import PredictionJob, InferenceWorker, evaluate_job
from tests.test_stroke_classifier_training import experiments
from tests.test_stroke_recognition_core import rows


@pytest.fixture(scope='module')
def model_store(tmp_path_factory):
    root = tmp_path_factory.mktemp('live-models')
    task = train(experiments(root,4), TrainConfig(cs=(1.,), kernels=('linear',),
        amplitudes=('A1',), directions=('D3',), weights=(1.,), late_weights=(.5,)), root/'store')
    return ModelStore(root/'store'), task


def make_job(model, kind='preview', stroke_id=1, last=500):
    return PredictionJob('session', stroke_id, kind, model, prepare_sensor(rows(600)), 200, last)


def test_existing_all_family_models_match_offline_and_preview_does_not_mutate(model_store):
    store, task = model_store
    assert len(task['models']) == 5
    for item in task['models']:
        model = load_model(store, task['id'], item['id'])
        assert len(model.labels) == 7
        job = make_job(model, 'final')
        original = model.bundle['model'].scalers[0].mean_.copy()
        for last in (202, 230, 310, 450):
            evaluate_job(replace(job, kind='preview', last=last))
        result = evaluate_job(job)
        stroke = Stroke(sample_id='s',run_id='session',label=None,index=1,
                        **extract(job.record, job.first, job.last, model.config))
        expected = predict_strokes(model.bundle, [stroke])[0]
        assert result['status'] == 'ok'
        assert result['predicted'] == expected['predicted']
        np.testing.assert_allclose(result['scores'], expected['scores'])
        np.testing.assert_array_equal(model.bundle['model'].scalers[0].mean_, original)


def test_too_short_direction_prefix_reports_waiting_not_fallback(model_store):
    store, task = model_store
    item = next(m for m in task['models'] if m['family'] == 'F1')
    model = load_model(store, task['id'], item['id'])
    result = evaluate_job(make_job(model, last=202))
    assert result['status'] == 'unavailable'
    assert result['predicted'] is None
    assert '方向' in result['error'] and '不足' in result['error']


def test_tampered_model_rejected_before_deserialization(tmp_path, model_store):
    store, task = model_store
    import shutil
    shutil.copytree(store.root, tmp_path/'store')
    copy = ModelStore(tmp_path/'store')
    model_id = task['models'][0]['id']
    path = copy.model_path(task['id'], model_id)/'bundle.joblib'
    path.write_bytes(b'not a model')
    with pytest.raises(ValueError, match='校验'):
        load_model(copy, task['id'], model_id)


def test_priority_latest_only_and_shutdown_drains_final_tasks(model_store):
    store, task = model_store
    model = load_model(store, task['id'], task['models'][0]['id'])
    entered, release = threading.Event(), threading.Event()
    order = []
    def blocking(job):
        order.append((job.kind, job.last, job.stroke_id))
        if len(order) == 1:
            entered.set()
            assert release.wait(3)
        return dict(kind=job.kind, stroke_id=job.stroke_id)
    worker = InferenceWorker(evaluator=blocking)
    assert worker.submit(make_job(model,last=250))
    assert entered.wait(3)
    worker.submit(make_job(model,last=300))
    worker.submit(make_job(model,last=400))
    worker.submit(make_job(model,'final',last=500))
    worker.submit(make_job(model,'final',stroke_id=2,last=550))
    release.set()
    worker.close()
    assert order == [('preview',250,1),('final',500,1),('final',550,2)]
    assert worker.results.qsize() == 3


def test_pending_preview_is_replaced_without_growing_queue(model_store):
    store, task = model_store
    model = load_model(store, task['id'], task['models'][0]['id'])
    entered, release = threading.Event(), threading.Event()
    seen = []
    def evaluator(job):
        seen.append(job.last)
        if len(seen) == 1:
            entered.set(); release.wait(3)
        return {'last':job.last}
    worker = InferenceWorker(evaluator=evaluator)
    worker.submit(make_job(model,last=220)); assert entered.wait(3)
    for last in range(230,450):
        worker.submit(make_job(model,last=last))
    release.set()
    assert worker.results.get(timeout=3)['last'] == 220
    assert worker.results.get(timeout=3)['last'] == 449
    worker.close()
    assert seen == [220,449]
