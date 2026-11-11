"""Import must retain editable stroke data and the physical execution geometry."""
import copy
import json

import numpy as np
import pytest

from scripts.brush_path_editor_model import PathModel
from scripts.brush_path_variation import paper_points
from tests.test_brush_variation_model import model


def clone(model):
    return PathModel.from_state(model.portable_state())


def test_import_preserves_existing_and_source_parameters(model):
    source = clone(model)
    source.stroke_name = '横'
    source.segment_magnetic[:] = 190.
    source.node_speeds[:] = 3.
    source.node_angles[:] = [12., -45.]
    before = copy.deepcopy(model.state(False))
    original = copy.deepcopy(source.state())
    ids = model.import_strokes(source)
    assert model.state(False) == before
    assert source.state() == original
    assert len(ids) == 1 and ids[0] != source.stroke_id
    assert model.stroke_order == [model.stroke_id, ids[0]]
    imported = PathModel.from_state(model.other_strokes[0])
    assert imported.stroke_name == '横'
    assert imported.segment_magnetic.tolist() == [190.]
    assert imported.node_speeds.tolist() == [3., 3.]
    assert imported.node_angles.tolist() == [[12., -45.], [12., -45.]]
    assert paper_points(imported).min(0)[0] == pytest.approx(paper_points(model).max(0)[0] + 10.)
    assert np.ptp(paper_points(imported), axis=0) == pytest.approx(np.ptp(paper_points(source), axis=0))


def test_import_converts_rotated_scaled_geometry_to_current_canvas(model):
    source = clone(model)
    source.base['placement'] = dict(origin_mm=[-20., 60.], rotation_deg=90., scale=2.)
    physical = paper_points(source).copy()
    model.import_strokes(source, side='original', offset_mm=[3., -4.])
    imported = PathModel.from_state(model.other_strokes[0])
    assert imported.base['placement'] == model.base['placement']
    assert paper_points(imported) == pytest.approx(physical + [3., -4.])
    assert len(imported.original) == len(source.original)
    assert imported.indices.tolist() == source.indices.tolist()
    from scripts.generate_strokeplan_from_json import build_plan
    before = build_plan(source.recipe()).strokes[0]
    after = build_plan(imported.recipe()).strokes[0]
    assert after.xy == pytest.approx(before.xy + [.003, -.004])
    assert after.orientation == pytest.approx(before.orientation, abs=1e-10)


def test_select_multiple_strokes_preserves_source_order_and_relative_positions(model):
    source = clone(model)
    first = source.stroke_id
    source.add_independent_point([0., 30.]); source.add_independent_point([10., 30.])
    second = source.stroke_id
    source.add_independent_point([0., 50.]); source.add_independent_point([10., 50.])
    ids = model.import_strokes(source, stroke_ids=[second, first], side='left', gap_mm=7.)
    assert len(ids) == 2
    a, b = [PathModel.from_state(s) for s in model.other_strokes]
    assert a.import_source['stroke_id'] == first
    assert b.import_source['stroke_id'] == second
    assert (paper_points(b)[0] - paper_points(a)[0]) == pytest.approx([50., 30.])
    assert max(paper_points(a)[:, 0].max(), paper_points(b)[:, 0].max()) == pytest.approx(paper_points(model)[:, 0].min()-7.)
    again = model.import_strokes(source, stroke_ids=[first])
    assert len(set(model.stroke_order)) == 4
    assert again[0] not in ids


@pytest.mark.parametrize('kwargs', [dict(stroke_ids=[]), dict(stroke_ids=['missing']), dict(gap_mm=-1), dict(offset_mm=[float('nan'), 0]), dict(side='bad')])
def test_invalid_import_is_atomic(model, kwargs):
    before = copy.deepcopy(model.state())
    with pytest.raises(ValueError):
        model.import_strokes(clone(model), **kwargs)
    assert model.state() == before


def test_import_adopts_target_shared_settings_and_binds_source_provenance(model):
    source = clone(model)
    source.settings_snapshot['settings.json']['contact_z_mm'] += 1.
    source.settings_snapshot['entry_profile.json']['entry_contact_z_mm'] += 1.
    source.settings_snapshot['entry_profile.json']['entry_reverse_mm'] = 2.
    model.import_strokes(source)
    imported = PathModel.from_state(model.other_strokes[0])
    assert imported.settings()['settings.json'] == model.settings()['settings.json']
    assert imported.settings()['entry_profile.json']['entry_contact_z_mm'] == model.settings()['entry_profile.json']['entry_contact_z_mm']
    assert imported.settings()['entry_profile.json']['entry_reverse_mm'] == 2.
    assert imported.import_source['settings']['settings.json']['contact_z_mm'] == source.settings()['settings.json']['contact_z_mm']
    assert imported.feedforward_override is None
    assert imported.settings_snapshot is not None
    assert PathModel.from_state(model.state()).other_strokes[0]['import_source'] == imported.import_source


def test_loader_prefers_bundle_configuration_over_broken_historical_paths(model, tmp_path):
    from scripts.brush_stroke_import import load_stroke_source
    folder = tmp_path/'bundle'; folder.mkdir()
    state = model.state()
    state['source_folder'] = '/missing/historical'
    state['feedforward_override'] = '/missing/feedforward.json'
    state['entry_profile_override'] = '/missing/entry.json'
    state['settings_override'] = '/missing/settings.json'
    (folder/'editor_state.json').write_text(json.dumps(state))
    for name, value in model.settings().items():
        (folder/name).write_text(json.dumps(value))
    (folder/'recipe.json').write_text(json.dumps(model.base))
    loaded = load_stroke_source(folder/'recipe.json')
    assert loaded.settings() == model.settings()
    assert loaded.folder == folder
    assert loaded.feedforward_override is None


def test_partial_bundle_uses_each_local_configuration_before_historical_override(model, tmp_path):
    from scripts.brush_stroke_import import load_stroke_source
    folder = tmp_path/'partial'; folder.mkdir()
    state = model.portable_state()
    state['feedforward_override'] = '/missing/historical-feedforward.json'
    state['settings_snapshot']['feedforward.json']['amplitude_uT'][0] = -100.
    (folder/'editor_state.json').write_text(json.dumps(state))
    for name, value in model.settings().items():
        if name != 'pi_profile.json':
            (folder/name).write_text(json.dumps(value))
    loaded = load_stroke_source(folder/'editor_state.json')
    assert loaded.settings() == model.settings()


def test_missing_selected_file_does_not_load_another_recipe(model):
    from scripts.brush_stroke_import import load_stroke_source
    with pytest.raises(FileNotFoundError):
        load_stroke_source(model.folder/'does-not-exist.json')


def test_invalid_source_recipe_cannot_partially_import(model):
    source = clone(model)
    source.base['orientation']['smoothing_mm'] = -1.
    before = copy.deepcopy(model.state())
    with pytest.raises(ValueError):
        model.import_strokes(source)
    assert model.state() == before


def test_ordering_changes_only_order_and_round_trips(model):
    first = model.stroke_id
    model.import_strokes(clone(model))
    second = model.stroke_order[-1]
    before = copy.deepcopy(model.state())
    model.reorder_strokes([second, first])
    after = model.state()
    assert after['stroke_workspace']['order'] == [second, first]
    before['stroke_workspace']['order'] = [second, first]
    assert after == before
    assert model.stroke_node_offset(first) == 2
    assert PathModel.from_state(after).stroke_order == [second, first]
    for invalid in ([first], [first, first], [first, 'missing']):
        with pytest.raises(ValueError): model.reorder_strokes(invalid)
        assert model.stroke_order == [second, first]


def test_pending_point_blocks_import_and_ordering(model):
    source = clone(model)
    model.add_independent_point([10., 20.])
    before = copy.deepcopy(model.state())
    with pytest.raises(ValueError, match='第二个点'): model.import_strokes(source)
    with pytest.raises(ValueError, match='第二个点'): model.reorder_strokes(model.stroke_order)
    assert model.state() == before


def test_import_invalidates_batch_sorting_preserves_per_stroke_draws(model):
    model.set_variation_options(enabled=True)
    model.generate_variation(seed=123)
    model.import_strokes(clone(model))
    assert model.variation_status()['state'] == 'stale'
    batch = model.generate_variation(seed=456)
    model.reorder_strokes(model.stroke_order[::-1])
    assert model.variation_status()['state'] == 'ready'
    assert model.random_variation['batch'] == batch


def test_reordered_export_follows_selected_order_and_retains_import(model, tmp_path):
    from brushbot.target_strokeplan import StrokePlan
    first = model.stroke_id
    model.import_strokes(clone(model))
    second = model.stroke_order[-1]
    model.reorder_strokes([second, first])
    folder, report = model.export(tmp_path/'exports')
    assert [s['stroke_id'] for s in report['execution_order']] == [second, first]
    plan = StrokePlan.load(folder/'strokeplan.npz')
    assert plan.strokes[0].xy[0, 0] > plan.strokes[1].xy[-1, 0]
    restored = PathModel.restore(folder/'editor_state.json')
    assert restored.stroke_order == [second, first]
    restored.switch_stroke(second)
    assert restored.import_source['stroke_id'] == first


def test_real_yong_and_heng_import_then_reorder_and_export(tmp_path):
    from scripts.brush_path_editor_model import ROOT
    from scripts.brush_stroke_import import load_stroke_source
    root = ROOT/'runs/brush2/plans/final'
    if not (root/'永字最终方案/editor_state.json').is_file():
        pytest.skip('本地最终方案未随源码分发')
    target = load_stroke_source(root/'永字最终方案/editor_state.json')
    source = load_stroke_source(root/'横笔画最新版方案/editor_state.json')
    originals = copy.deepcopy(target.state())
    ids = target.import_strokes(source)
    assert len(target.stroke_order) == 6
    assert target.total_node_count() == 60
    assert target.state()['stroke_workspace']['others'][:-1] == originals['stroke_workspace']['others']
    target.reorder_strokes(ids + target.stroke_order[:-1])
    folder, report = target.export(tmp_path/'six-stroke')
    assert len(report['execution_order']) == 6
    assert report['execution_order'][0]['stroke_id'] == ids[0]
    assert report['execution_order'][0]['point_range'] == [0, 10]
    assert report['hardware_executed'] is False
    restored = load_stroke_source(folder/'recipe.json')
    assert restored.stroke_order == target.stroke_order
    again = load_stroke_source(root/'永字最终方案/editor_state.json')
    again.import_strokes(restored, stroke_ids=ids)
    assert len(again.stroke_order) == 6
