"""Real numerical pipeline: group isolation, mask scaling and independent prediction reuse."""
import numpy as np
import pytest
from tests.test_stroke_classifier_data import archive_fixture


def experiments(tmp_path,n=4):
    from brushbot.stroke_classification.data import load_experiment
    return [load_experiment(archive_fixture(tmp_path/f'{i}.brushrun',run=f'run-{i}',seed=i)) for i in range(n)]


def test_mask_scaler_uses_only_training_valid_values():
    from brushbot.stroke_classification.models import MaskedScaler
    scale=MaskedScaler().fit(np.array([[1.,np.nan,np.nan],[3.,5.,np.nan]]))
    actual=scale.transform(np.array([[5.,np.nan,1000.]]))
    np.testing.assert_allclose(actual,[[3.,0.,0.]])


def test_ranking_uses_three_rules_and_keeps_ties():
    from brushbot.stroke_classification.metrics import evaluate,rank_models
    y=np.tile(np.arange(7),3);g=np.repeat(np.arange(3),7)
    a=y.copy();a[0]=1;a[7]=1
    b=y.copy();b[0]=1;b[8]=2
    ma=evaluate(y,a,g);mb=evaluate(y,b,g)
    assert ma['errors']==mb['errors']==2
    assert ma['worst_recall']==pytest.approx(1/3)
    assert mb['worst_recall']==pytest.approx(2/3)
    ranked=rank_models({'A':ma,'B':mb,'C':dict(mb)})
    assert ranked['B']==ranked['C']==1
    assert ranked['A']==3


def test_grouped_training_bundle_roundtrip_and_pca(tmp_path):
    from brushbot.stroke_classification.training import TrainConfig,train
    from brushbot.stroke_classification.store import ModelStore
    from brushbot.stroke_classification.predict import predict_strokes
    ex=experiments(tmp_path)
    config=TrainConfig(families=('F0','F2','F3','F4'),cs=(1.,),kernels=('linear',),
                       gammas=('scale',),directions=('D3',),amplitudes=('A1',),weights=(1.,),late_weights=(.5,))
    store=ModelStore(tmp_path/'store')
    record=train(ex,config,store.root)
    assert len(store.list_tasks())==1
    assert len(record['models'])==4
    for item in record['models']:
        assert item['metrics']['total']==28
        assert len(item['folds'])==4
        for fold in item['folds']:
            assert set(fold['train_runs']).isdisjoint(fold['test_runs'])
            assert len(fold['test_indices'])==7
        bundle=store.load_bundle(record['id'],item['id'])
        predictions=predict_strokes(bundle,ex[0].strokes)
        assert len(predictions)==7
        assert all(len(r['scores'])==7 and r['training_overlap'] for r in predictions)
        assert bundle['pca'].components_.shape[0]==3
        before=bundle['pca'].components_.copy()
        predict_strokes(bundle,ex[1].strokes)
        np.testing.assert_array_equal(bundle['pca'].components_,before)


def test_no_direction_coverage_means_branch_failure_not_smaller_cohort(tmp_path):
    from brushbot.stroke_classification.training import TrainConfig,train
    ex=experiments(tmp_path,3)
    ex[0].strokes[0].representations['D3'][:]=np.nan
    record=train(ex,TrainConfig(families=('F1',),cs=(1.,),kernels=('linear',),
                 directions=('D3',)),tmp_path/'store')
    assert record['models']==[]
    assert record['branches']['F1']['status']=='unavailable'


def test_cancel_does_not_publish_success(tmp_path):
    from brushbot.stroke_classification.training import TrainConfig,train,Cancelled
    from brushbot.stroke_classification.store import ModelStore
    with pytest.raises(Cancelled):
        train(experiments(tmp_path,3),TrainConfig(families=('F0',)),tmp_path/'store',cancel=lambda:True)
    assert ModelStore(tmp_path/'store').list_tasks()==[]


def test_prediction_rejects_incompatible_preprocessing(tmp_path):
    from dataclasses import replace
    from brushbot.stroke_classification.features import FeatureConfig
    from brushbot.stroke_classification.data import load_experiment
    from brushbot.stroke_classification.training import TrainConfig,train
    from brushbot.stroke_classification.store import ModelStore
    from brushbot.stroke_classification.predict import predict_strokes
    ex=experiments(tmp_path,3)
    task=train(ex,TrainConfig(families=('F0',),cs=(1.,),kernels=('linear',),amplitudes=('A1',)),tmp_path/'store')
    bundle=ModelStore(tmp_path/'store').load_bundle(task['id'],task['models'][0]['id'])
    incompatible=load_experiment(ex[0].path,FeatureConfig(alpha=.8))
    with pytest.raises(ValueError,match='预处理'):
        predict_strokes(bundle,incompatible.strokes)


def test_late_fusion_support_projection_is_branch_specific(tmp_path):
    from brushbot.stroke_classification.training import TrainConfig,train,stack_strokes
    from brushbot.stroke_classification.store import ModelStore
    ex=experiments(tmp_path,4)
    task=train(ex,TrainConfig(families=('F3',),cs=(1.,),kernels=('linear',),
                 directions=('D3',),late_weights=(.5,)),tmp_path/'store')
    bundle=ModelStore(tmp_path/'store').load_bundle(task['id'],task['models'][0]['id'])
    model=bundle['model']
    assert model.branch_pcas[0].n_features_in_==128
    assert model.branch_pcas[1].n_features_in_==256
    X=stack_strokes(ex[0].strokes)
    assert model.project(X,1).shape==(7,3)


def test_nested_parameter_selection_fold_scalers_never_fit_test_run(tmp_path):
    import joblib
    from brushbot.stroke_classification.training import TrainConfig,train,stack_strokes
    from brushbot.stroke_classification.store import ModelStore
    ex=experiments(tmp_path,4)
    config=TrainConfig(families=('F0','F3'),cs=(.1,1.),kernels=('linear',),amplitudes=('A1','A2'),
                       directions=('D3',),late_weights=(.25,.75))
    task=train(ex,config,tmp_path/'store')
    store=ModelStore(tmp_path/'store');X=stack_strokes([s for e in ex for s in e.strokes])
    for item in task['models']:
        for i,fold in enumerate(item['folds']):
            model=joblib.load(store.task_path(task['id'])/'fold_models'/item['family']/f'{i:03d}.joblib')
            a=model.candidate.amplitude if item['family']=='F0' else 'A1'
            np.testing.assert_allclose(model.scalers[0].mean_,X[a][fold['train_indices']].mean(axis=0))
            assert len(fold['train_runs'])==3 and len(fold['test_runs'])==1
