"""The editor and hardware compiler must consume the same frozen realization."""
import copy
import json
import shutil

import numpy as np
import pytest

from scripts.brush_path_editor_model import PathModel
from brushbot.experiments.strokeplan_execution import compile_recorded_plan
from brushbot.target_strokeplan import StrokePlan
from tests.test_brush_experiment_archive import raw_template


def model_with_variation():
    model = PathModel()
    model.magnetic_values[:] = 150.
    model.segment_magnetic[:] = 150.
    model.use_endpoint_speeds()
    model.node_speeds[:] = 2.
    config = copy.deepcopy(model.writing_variation)
    config['enabled'] = True
    config['profile']['bias_pct'] = 0.
    model.set_writing_variation(config)
    return model


def reload_compiled(folder):
    plan = StrokePlan.load(folder/'strokeplan.npz')
    settings = {name: json.loads((folder/name).read_text()) for name in (
        'feedforward.json', 'settings.json', 'pi_profile.json', 'entry_profile.json')}
    compiled = compile_recorded_plan(plan, settings['feedforward.json'], settings['settings.json'],
        label='replayed', control_mode='pi', feedback_profile=settings['pi_profile.json'],
        entry_profile=settings['entry_profile.json'])
    return compiled, plan, settings


def test_enable_disable_returns_exact_standard_and_does_not_rewrite_recipe():
    model = model_with_variation()
    recipe = copy.deepcopy(model.recipe())
    standard = model._compile_standard_workspace()[2]
    effective = model.compile_workspace()[2]
    assert not np.array_equal(effective['pose_m_rad'], standard['pose_m_rad'])
    config = copy.deepcopy(model.writing_variation)
    config['enabled'] = False
    model.set_writing_variation(config)
    restored = model.compile_workspace()[2]
    for key in ('pose_m_rad', 'g_ref_uT', 't_s', 's', 'phase'):
        np.testing.assert_equal(restored[key], standard[key])
    assert model.recipe() == recipe


def test_old_state_defaults_to_disabled_and_configuration_survives_switching_strokes():
    model = model_with_variation()
    config = copy.deepcopy(model.writing_variation)
    first = model.stroke_id
    model.add_independent_point([10., 10.])
    model.add_independent_point([20., 10.])
    assert model.writing_variation == config
    second = model.stroke_id
    model.switch_stroke(first)
    assert model.writing_variation == config
    model.switch_stroke(second)
    assert model.writing_variation == config
    state = model.state()
    assert PathModel.from_state(state).writing_variation == config
    for key in ('writing_variation', 'variation_snapshot', 'variation_repeat_seed', 'variation_locked'):
        state.pop(key, None)
    restored = PathModel.from_state(state)
    assert restored.writing_variation['enabled'] is False


def test_export_and_recompile_use_frozen_arrays_even_after_portable_restore(tmp_path):
    model = model_with_variation()
    model.segment_magnetic[:] = np.linspace(150., 150.1, len(model.segment_magnetic))
    config = copy.deepcopy(model.writing_variation)
    config['profile']['bias_pct'] = 1.
    model.set_writing_variation(config)
    first = model.compile_workspace()[2]
    snapshot = copy.deepcopy(model.variation_snapshot)
    assert snapshot['strokes'][0]['report']['correlation'] < .98
    folder, summary = model.export(tmp_path)
    actual, _, settings = reload_compiled(folder)
    assert np.array_equal(first['pose_m_rad'], actual['pose_m_rad'])
    np.testing.assert_equal(first['g_ref_uT'], actual['g_ref_uT'])
    assert json.loads((folder/'writing_variation.json').read_text()) == snapshot
    assert settings['entry_profile.json']['writing_variation'] == snapshot
    assert summary['writing_variation']['enabled'] is True
    restored = PathModel.restore(folder/'editor_state.json')
    again = restored.compile_workspace()[2]
    assert np.array_equal(again['pose_m_rad'], first['pose_m_rad'])
    standard = model._compile_standard_workspace()[2]
    config = copy.deepcopy(restored.writing_variation)
    config['enabled'] = False
    restored.set_writing_variation(config)
    np.testing.assert_equal(restored.compile_workspace()[2]['pose_m_rad'], standard['pose_m_rad'])


def test_new_repetition_changes_only_repeat_layer_and_locked_geometry_change_is_rejected():
    model = model_with_variation()
    model.compile_workspace()
    old = copy.deepcopy(model.variation_snapshot)
    model.regenerate_writing_variation()
    model.compile_workspace()
    new = model.variation_snapshot
    assert new['strokes'][0]['fixed_xy_mm'] == old['strokes'][0]['fixed_xy_mm']
    assert new['strokes'][0]['repeat_xy_mm'] != old['strokes'][0]['repeat_xy_mm']
    model.variation_locked = True
    model.nodes[-1, 0] += .1
    with pytest.raises(ValueError, match='重新生成|锁定'):
        model.compile_workspace()


def test_changed_saved_standard_cannot_reuse_old_snapshot(tmp_path):
    model = model_with_variation()
    folder, _ = model.export(tmp_path)
    _, plan, settings = reload_compiled(folder)
    plan.strokes[0].g_target[:] += .1
    with pytest.raises(ValueError, match='标准输入|不匹配'):
        compile_recorded_plan(plan, settings['feedforward.json'], settings['settings.json'],
            label='changed', control_mode='pi', feedback_profile=settings['pi_profile.json'],
            entry_profile=settings['entry_profile.json'])


def test_segment_targets_and_writing_lift_receive_same_additive_variation():
    model = model_with_variation()
    model.lift_mm[-3:] = .1
    model.segment_magnetic[3:6] = 160.
    _, _, standard, settings, _ = model._compile_standard_workspace()
    effective = model.compile_workspace()[2]
    mask = effective['phase'] == 'measure_00'
    delta = effective['g_ref_uT'][mask] - standard['g_ref_uT'][mask]
    from brushbot.feedforward import lookup_depth_m
    nominal = standard['nominal_g_uT'][mask]
    expected = standard['pose_m_rad'][mask, 2] - (
        lookup_depth_m(settings['feedforward.json'], nominal+delta)
        - lookup_depth_m(settings['feedforward.json'], nominal))
    assert np.allclose(effective['pose_m_rad'][mask, 2], expected, atol=1e-12, rtol=0)
    assert model.segment_magnetic[3:6].tolist() == [160.]*3
    assert model.lift_mm[-3:].tolist() == [.1]*3


def test_variation_snapshot_is_a_supported_portable_archive_input(tmp_path,raw_template):
    from brushbot.experiments.archive import ExperimentArchive
    from brushbot.experiments.reproduce import read_json, verify
    model=model_with_variation()
    model.compile_workspace()
    snapshot=model.variation_snapshot
    store=ExperimentArchive(tmp_path/'records')
    with store.session() as stage:
        raw=stage/'raw'
        shutil.copytree(raw_template,raw)
        archived=store.archive_success(stage,raw,input_files={
            'writing_variation.json':json.dumps(snapshot).encode()})
    assert read_json(archived,'writing_variation.json')==snapshot
    assert verify(archived)>0


def test_multi_stroke_variation_is_complete_and_transfer_is_unchanged():
    model = model_with_variation()
    model.add_independent_point([10., 10.])
    model.add_independent_point([20., 10.])
    standard = model._compile_standard_workspace()[2]
    effective = model.compile_workspace()[2]
    assert len(model.variation_snapshot['strokes']) == 2
    writing = np.char.startswith(effective['phase'], 'measure_')
    np.testing.assert_equal(effective['pose_m_rad'][~writing], standard['pose_m_rad'][~writing])
