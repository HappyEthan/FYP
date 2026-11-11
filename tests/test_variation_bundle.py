import json
import shutil
import numpy as np
import pytest
from tests.test_brush_variation_model import model,enable


def load_compile(folder):
    from brushbot.target_strokeplan import StrokePlan
    from brushbot.experiments.strokeplan_execution import compile_recorded_plan
    values={n:json.loads((folder/n).read_text()) for n in ['feedforward.json','settings.json','entry_profile.json','pi_profile.json']}
    return compile_recorded_plan(StrokePlan.load(folder/'strokeplan.npz'),values['feedforward.json'],values['settings.json'],
        label='reloaded',control_mode='pi',feedback_profile=values['pi_profile.json'],entry_profile=values['entry_profile.json'])


def test_export_reloads_exact_commands_and_preserves_standard_state(model,tmp_path):
    from brushbot.experiments.variation_bundle import validate_variation_bundle
    enable(model);preview=model.compile_workspace()[2]
    folder,_=model.export(tmp_path/'exports')
    assert (folder/'variation.json').exists() and (folder/'variation_arrays.npz').exists()
    compiled=load_compile(folder)
    assert np.array_equal(compiled['pose_m_rad'],preview['pose_m_rad'])
    assert np.array_equal(compiled['g_ref_uT'],preview['g_ref_uT'],equal_nan=True)
    frozen=validate_variation_bundle(folder,compiled)
    assert frozen['batch']['root_seed']=='101'
    from scripts.brush_path_editor_model import PathModel
    restored=PathModel.restore(folder/'editor_state.json')
    assert np.array_equal(restored.points(),model.points())
    assert np.array_equal(restored.compile_workspace()[2]['pose_m_rad'],preview['pose_m_rad'])


def test_moved_export_is_independent_of_source(model,tmp_path):
    from brushbot.experiments.variation_bundle import validate_variation_bundle
    enable(model);folder,_=model.export(tmp_path/'exports')
    moved=tmp_path/'moved';shutil.copytree(folder,moved)
    for name in ['recipe.json','feedforward.json','settings.json','entry_profile.json','pi_profile.json']:(tmp_path/name).unlink()
    validate_variation_bundle(moved,load_compile(moved))


@pytest.mark.parametrize('damage',['missing','metadata','arrays','settings'])
def test_broken_bundle_rejected_before_any_execution(model,tmp_path,damage):
    from brushbot.experiments.variation_bundle import validate_variation_bundle
    enable(model);folder,_=model.export(tmp_path/'exports');compiled=load_compile(folder)
    if damage=='missing':(folder/'variation.json').unlink()
    elif damage=='metadata':
        d=json.loads((folder/'variation.json').read_text());d['algorithm']='unknown';(folder/'variation.json').write_text(json.dumps(d))
    elif damage=='arrays':(folder/'variation_arrays.npz').write_bytes(b'corrupt')
    else:
        p=folder/'settings.json';d=json.loads(p.read_text());d['max_depth_mm']+=1.;p.write_text(json.dumps(d))
    with pytest.raises(ValueError):validate_variation_bundle(folder,compiled)


def test_off_export_stays_compatible_and_atomic_failures_do_not_publish(model,tmp_path,monkeypatch):
    from brushbot.experiments.variation_bundle import validate_variation_bundle
    folder,_=model.export(tmp_path/'old')
    assert validate_variation_bundle(folder,load_compile(folder)) is None
    enable(model)
    import brushbot.experiments.variation_bundle as bundle
    def failure(*args):raise ValueError('controlled write failure')
    monkeypatch.setattr(bundle,'write_variation_bundle',failure)
    with pytest.raises(ValueError):model.export(tmp_path/'new')
    assert not list((tmp_path/'new').rglob('strokeplan.npz'))


def test_xy_only_missing_audit_cannot_silently_run_as_legacy(model,tmp_path):
    from brushbot.experiments.variation_bundle import validate_variation_bundle
    enable(model,mag=False);folder,_=model.export(tmp_path/'exports');compiled=load_compile(folder)
    (folder/'variation.json').unlink();(folder/'variation_arrays.npz').unlink()
    with pytest.raises(ValueError):validate_variation_bundle(folder,compiled)


def test_fake_recording_archive_contains_frozen_variation_and_original_sensor(model,tmp_path):
    from types import SimpleNamespace
    from brushbot.experiments.archive import ExperimentArchive
    from brushbot.experiments.reproduce import open_bundle
    from brushbot.target_strokeplan import StrokePlan
    from tests.test_brush_experiment_archive import fake_execute
    enable(model);folder,_=model.export(tmp_path/'exports')
    artifacts={p.name:p.read_bytes() for p in folder.iterdir() if p.is_file()}
    table=json.loads(artifacts['feedforward.json']);setup=json.loads(artifacts['settings.json']);entry=json.loads(artifacts['entry_profile.json'])
    store=ExperimentArchive(tmp_path/'records')
    with store.session() as stage:
        result=fake_execute(SimpleNamespace(control_mode='feedforward'),plan=StrokePlan.load(folder/'strokeplan.npz'),table=table,setup=setup,
            artifacts=artifacts,label='variation_archive',feedback_profile=None,entry_profile=entry,work_root=stage/'raw')
        from pathlib import Path
        sensor=(Path(result['run_dir'])/'sensor.csv').read_bytes()
        saved=store.archive_success(stage,Path(result['run_dir']),input_files=artifacts,require_editor=True)
    with open_bundle(saved) as payload:
        assert (payload/'variation.json').read_bytes()==artifacts['variation.json']
        assert (payload/'variation_arrays.npz').read_bytes()==artifacts['variation_arrays.npz']
        assert (payload/'sensor.csv').read_bytes()==sensor


@pytest.mark.parametrize('change',['kp','feedforward','setup'])
def test_actual_runtime_control_and_setup_must_match_frozen_inputs(model,tmp_path,change):
    from brushbot.experiments.variation_bundle import validate_variation_bundle
    from brushbot.experiments.strokeplan_execution import compile_recorded_plan
    from brushbot.target_strokeplan import StrokePlan
    enable(model);folder,_=model.export(tmp_path/'exports')
    table=json.loads((folder/'feedforward.json').read_text())
    setup=json.loads((folder/'settings.json').read_text())
    entry=json.loads((folder/'entry_profile.json').read_text())
    pi=json.loads((folder/'pi_profile.json').read_text())
    mode='pi'
    if change=='kp':pi['kp']*=2.
    elif change=='feedforward':mode='feedforward';pi=None
    else:setup['max_xy_speed_mm_s']+=1.
    compiled=compile_recorded_plan(StrokePlan.load(folder/'strokeplan.npz'),table,setup,label='allowed-variable-label',control_mode=mode,feedback_profile=pi,entry_profile=entry)
    with pytest.raises(ValueError):validate_variation_bundle(folder,compiled)
