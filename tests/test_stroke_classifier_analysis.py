"""Whole-run diagnostic isolation and backward-compatible search configuration."""
from dataclasses import asdict,replace
import json
import numpy as np
import pytest
from tests.test_stroke_classifier_training import experiments


def small_config():
    from brushbot.stroke_classification.training import TrainConfig
    return TrainConfig(families=('F4',),cs=(.1,1.),kernels=('linear',),weights=(1.,),robustness=False)


def test_independent_fusion_weights_and_legacy_fallback():
    from brushbot.stroke_classification.training import candidates
    config=small_config()
    assert {c.weight for c in candidates('F4',config,('D3',))}=={1.}
    config=replace(config,direction_weights=(.25,),difference_weights=(2.,))
    assert {c.weight for c in candidates('F2',config,('D3',))}=={.25}
    assert {c.weight for c in candidates('F4',config,('D3',))}=={2.}
    for key in ('cs','direction_weights','difference_weights'):
        with pytest.raises(ValueError):replace(config,**{key:(float('nan'),)}).validate()


def test_learning_subsets_nested_reproducible_and_train_only(tmp_path,monkeypatch):
    from brushbot.stroke_classification.analysis import AnalysisConfig,run_analysis
    from brushbot.stroke_classification.models import Candidate,MagneticModel
    data=experiments(tmp_path,4)
    fitted=[];original=MagneticModel.fit
    def observe(self,reps,y,groups,*args,**kwargs):
        fitted.append(set(groups))
        return original(self,reps,y,groups,*args,**kwargs)
    monkeypatch.setattr(MagneticModel,'fit',observe)
    cfg=AnalysisConfig(kind='learning',sizes=(2,3),seeds=(10,11))
    result=run_analysis(data,small_config(),Candidate('F4'),cfg)
    assert len(result['rows'])==4
    assert all(r['metrics']['total']==28 for r in result['rows'])
    assert len(fitted)>0
    for seed in cfg.seeds:
        folds=[f for f in result['folds'] if f['seed']==seed]
        for run in {f['test_runs'][0] for f in folds}:
            a,b=sorted([f for f in folds if f['test_runs']==[run]],key=lambda f:f['size'])
            assert set(a['train_runs'])<set(b['train_runs'])
            assert run not in b['train_runs']
            assert len(a['test_indices'])==7
            assert all(run not in inner['train_runs'] and inner['test_run'] not in inner['train_runs']
                       for inner in a['inner_splits'])
    again=run_analysis(data,small_config(),Candidate('F4'),cfg)
    assert result['folds']==again['folds']
    assert result['rows']==again['rows']


def test_validation_scans_only_named_parameter_and_aggregates_all_runs(tmp_path):
    from brushbot.stroke_classification.analysis import AnalysisConfig,run_analysis
    from brushbot.stroke_classification.models import Candidate
    data=experiments(tmp_path)
    base=Candidate('F4',C=.1,weight=2.)
    result=run_analysis(data,small_config(),base,AnalysisConfig(kind='C',cs=(.01,.1)))
    assert len(result['rows'])==2
    for row in result['rows']:
        assert row['candidate']['weight']==2.
        assert row['candidate']['kernel']=='linear'
        assert row['metrics']['total']==28
        assert row['metrics']['errors']==sum(p['true']!=p['predicted'] for p in row['predictions'])
    grid=run_analysis(data,small_config(),base,AnalysisConfig(kind='joint',cs=(.1,1.),weights=(.5,2.)))
    assert len(grid['rows'])==4
    assert {(r['candidate']['C'],r['candidate']['weight']) for r in grid['rows']}=={(.1,.5),(.1,2.),(1.,.5),(1.,2.)}


def test_config_limits_and_cancel(tmp_path):
    from brushbot.stroke_classification.analysis import AnalysisConfig,run_analysis
    from brushbot.stroke_classification.models import Candidate
    from brushbot.stroke_classification.training import Cancelled
    for cfg,family in [(AnalysisConfig(kind='learning',sizes=(4,)),'F4'),
                       (AnalysisConfig(kind='weight'),'F2'),(AnalysisConfig(kind='C',cs=(0.,)),'F4'),
                       (AnalysisConfig(kind='learning',sizes=(2,)),'F3')]:
        with pytest.raises(ValueError):cfg.validate(4,family)
    with pytest.raises(Cancelled):
        run_analysis(experiments(tmp_path),small_config(),Candidate('F4'),AnalysisConfig(kind='C'),cancel=lambda:True)


def test_task_bound_analysis_checks_sources_and_does_not_change_model(tmp_path):
    from brushbot.stroke_classification.analysis import execute_request
    from brushbot.stroke_classification.training import train
    from brushbot.stroke_classification.store import ModelStore,write_json
    data=experiments(tmp_path)
    config=replace(small_config(),cs=(.1,))
    task=train(data,config,tmp_path/'store');model=task['models'][0]
    store=ModelStore(tmp_path/'store');before=(store.task_path(task['id'])/'task.json').read_bytes()
    request=dict(root=str(store.root),task_id=task['id'],model_id=model['id'],
                 source_fingerprint=task['source_fingerprint'],analysis=dict(kind='C',cs=[.1,1.]))
    path=tmp_path/'request.json';write_json(path,request)
    output=execute_request(path)
    result=json.loads((output/'results.json').read_text())
    assert result['status']=='completed'
    assert result['source_fingerprint']==task['source_fingerprint']
    assert (output/'summary.csv').exists()
    assert (store.task_path(task['id'])/'task.json').read_bytes()==before
    request['source_fingerprint']='changed';write_json(path,request)
    with pytest.raises(ValueError,match='指纹'):execute_request(path)
    # A source removed after training must fail, rather than silently reduce the cohort.
    request['source_fingerprint']=task['source_fingerprint'];write_json(path,request)
    from pathlib import Path
    Path(data[0].path).unlink()
    with pytest.raises((ValueError,OSError)):execute_request(path)


def test_learning_endpoint_matches_original_nested_predictions(tmp_path):
    from brushbot.stroke_classification.analysis import AnalysisConfig,run_analysis
    from brushbot.stroke_classification.models import Candidate
    from brushbot.stroke_classification.training import train
    data=experiments(tmp_path)
    config=small_config()
    task=train(data,config,tmp_path/'store')
    result=run_analysis(data,config,Candidate(**task['models'][0]['candidate']),AnalysisConfig(kind='learning',sizes=(3,),seeds=(10,11)))
    expected=[r['predicted'] for r in task['models'][0]['predictions']]
    assert all([r['predicted'] for r in row['predictions']]==expected for row in result['rows'])


def test_cancel_record_is_not_completed(tmp_path):
    from brushbot.stroke_classification.analysis import execute_request
    from brushbot.stroke_classification.training import train,Cancelled
    from brushbot.stroke_classification.store import ModelStore,write_json
    config=replace(small_config(),cs=(.1,));store=ModelStore(tmp_path/'store')
    task=train(experiments(tmp_path),config,store.root)
    request=dict(root=str(store.root),task_id=task['id'],model_id=task['models'][0]['id'],
                 source_fingerprint=task['source_fingerprint'],analysis=dict(kind='C',cs=[.1]))
    path=tmp_path/'request.json';write_json(path,request)
    with pytest.raises(Cancelled):execute_request(path,cancel=lambda:True)
    records=list(store.task_path(task['id']).glob('analyses/*/record.json'))
    assert len(records)==1 and json.loads(records[0].read_text())['status']=='cancelled'
    assert not (records[0].parent/'results.json').exists()
