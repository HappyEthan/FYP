import copy
import json
import numpy as np
import pytest
from scripts.brush_path_editor_model import PathModel


@pytest.fixture
def model(tmp_path):
    from tests.test_strokeplan_json import line_recipe
    from tests.test_directional_character import inputs
    from tests.test_strokeplan_pi_feedback import profile
    _,table,setup,entry=inputs(tmp_path)
    recipe=line_recipe();recipe['path']['corner_radius_mm']=0.
    recipe['timing']['speed_knots_s_mm_s']=[[0.,10.],[1.,10.]]
    recipe['placement']=dict(origin_mm=[80.,10.],rotation_deg=0.,scale=1.)
    recipe['magnetic_target']['knots_s_uT']=[[0.,180.],[.5,200.],[1.,180.]]
    for name,value in [('recipe.json',recipe),('feedforward.json',table),('settings.json',setup),('entry_profile.json',entry),('pi_profile.json',profile())]:
        (tmp_path/name).write_text(json.dumps(value))
    return PathModel(tmp_path)


def enable(m,seed=101,xy=True,mag=True):
    m.set_variation_options(enabled=True,xy_enabled=xy,magnetic_enabled=mag)
    return m.generate_variation(seed=seed)


def test_generation_preserves_standard_and_compiles_nonzero_internal_change(model):
    from scripts.brush_path_variation import workspace_source
    original,digest=workspace_source(model);baseline=model.compile_workspace()
    a=enable(model);varied=model.compile_workspace()
    assert workspace_source(model)==(original,digest)
    assert model.variation_status()['state']=='ready'
    assert np.array_equal(varied[1].strokes[0].xy[[0,-1]],baseline[1].strokes[0].xy[[0,-1]])
    assert np.ptp(varied[1].strokes[0].xy[:,1])>0
    assert np.max(abs(varied[2]['g_ref_uT'][varied[2]['phase']=='measure_00']-180.))>0
    assert model.generate_variation(seed=101)==a


def test_disabled_restores_exact_standard_commands(model):
    baseline=model.compile_workspace()[2]
    enable(model);model.compile_workspace()
    model.set_variation_options(enabled=False)
    restored=model.compile_workspace()[2]
    assert np.array_equal(baseline['pose_m_rad'],restored['pose_m_rad'])
    assert np.array_equal(baseline['g_ref_uT'],restored['g_ref_uT'],equal_nan=True)


def test_stale_source_blocks_export_and_restore_keeps_batch(model,tmp_path):
    enable(model);state=model.state();restored=PathModel.from_state(state)
    assert restored.variation_status()['state']=='ready'
    restored.nodes[-1,0]+=.1
    assert restored.variation_status()['state']=='stale'
    with pytest.raises(ValueError,match='重新生成'):restored.export(tmp_path/'export')
    assert not (tmp_path/'export').exists()


def test_switch_order_and_child_toggles_preserve_draws(model):
    first=model.stroke_id
    model.add_independent_point([0.,10.]);model.add_independent_point([10.,10.]);second=model.stroke_id
    batch=enable(model);model.switch_stroke(first)
    assert model.variation_status()['state']=='ready'
    model.stroke_order.reverse()
    assert model.variation_status()['state']=='ready'
    assert model.generate_variation(seed=101)==batch
    model.set_variation_options(enabled=True,xy_enabled=False,magnetic_enabled=True)
    assert model.random_variation['batch']==batch
    model.set_variation_options(enabled=True,xy_enabled=True,magnetic_enabled=True)
    assert model.random_variation['batch']==batch


def test_invalid_standard_is_not_repaired_by_variation(model):
    model.segment_magnetic[:]=1.
    enable(model)
    with pytest.raises(ValueError):model.compile_workspace()


def test_magnetic_shrink_preserves_field_and_segment_structure(model):
    model.segment_magnetic[:]=239.9
    enable(model,xy=False)
    batch=model.random_variation['batch']
    f=batch['stroke_fields'][model.stroke_id]
    f['global_ratio']=.05;f['local_ratio']=[.02]*len(f['local_s'])
    result=model.compile_workspace()
    assert model.last_variation['scales'][model.stroke_id]['magnetic']<1.
    assert result[2]['g_ref_uT'][result[2]['phase']=='measure_00'].max()<=240.+1e-10
    assert batch['stroke_fields'][model.stroke_id]==f


def test_zero_only_feasible_change_does_not_export(model,tmp_path):
    model.segment_magnetic[:]=240.
    enable(model,xy=False)
    batch=model.random_variation['batch']
    f=batch['stroke_fields'][model.stroke_id];f['global_ratio']=.05;f['local_ratio']=[.02]*len(f['local_s'])
    with pytest.raises(ValueError):model.export(tmp_path/'bad')
    assert not list((tmp_path/'bad').rglob('strokeplan.npz'))


def test_effective_range_has_fixed_own_endpoints(model):
    model.add_point(0,target_xy=[0.,0.]);model.set_test_range(0,1)
    baseline=model.compile_workspace()[1].strokes[0].xy[[0,-1]].copy()
    enable(model);result=model.compile_workspace()
    assert np.array_equal(result[1].strokes[0].xy[[0,-1]],baseline)


def test_placement_and_short_paths_use_physical_millimetres(model):
    from scripts.brush_path_variation import execution_state,paper_points,workspace_source
    model.base['placement']['scale']=2.
    model.base['placement']['rotation_deg']=31.
    batch=enable(model);source=workspace_source(model)[0][model.stroke_id]
    state=execution_state(source,batch['stroke_fields'][model.stroke_id],xy_enabled=True,magnetic_enabled=True)
    candidate=PathModel.from_state(state)
    assert np.array_equal(paper_points(candidate)[[0,-1]],paper_points(model)[[0,-1]]) or np.allclose(paper_points(candidate)[[0,-1]],paper_points(model)[[0,-1]],atol=1e-12)
    assert state['variation_statistics']['max_displacement_mm']<=.3+1e-12
    assert np.ptp(candidate.points()[:,1])>0


def test_combined_shrink_rechecks_full_sequence(model,monkeypatch):
    original=PathModel._compile_workspace_standard
    def tighter_motion_check(self):
        result=original(self)
        # Emulate a tighter measured transverse workspace, after real compilation.
        if np.ptp(result[1].strokes[0].xy[:,1])>.00003:
            raise ValueError('controlled transverse workspace limit')
        return result
    monkeypatch.setattr(PathModel,'_compile_workspace_standard',tighter_motion_check)
    batch=enable(model);result=model.compile_workspace()
    assert np.ptp(result[1].strokes[0].xy[:,1])<=.00003
    assert model.last_variation['scales'][model.stroke_id]['xy']<1.
    assert model.last_variation['scales'][model.stroke_id]['magnetic']<1.
    assert model.random_variation['batch']==batch


@pytest.mark.parametrize('position',['start','end'])
def test_pending_start_blocks_cached_preflight_and_export(model,tmp_path,position):
    enable(model);model.compile_workspace()
    model.add_independent_point([2.,10.],position=position)
    assert model.variation_status()['state']!='ready'
    with pytest.raises(ValueError):model.compile_workspace()
    with pytest.raises(ValueError):model.export(tmp_path/'pending')
    assert not list((tmp_path/'pending').rglob('strokeplan.npz'))


def test_current_compile_then_workspace_export_keeps_reports(model,tmp_path):
    enable(model);model.compile()
    folder,summary=model.export(tmp_path/'exports')
    assert (folder/'variation.json').is_file()
    assert len(summary['execution_order'])==1
    # Exercise the opposite scope order with a changed, newly generated source.
    model.nodes[-1,0]+=.1;model.generate_variation(seed=202)
    model.compile_workspace();model.compile()
    folder,summary=model.export(tmp_path/'exports2')
    assert len(summary['execution_order'])==1
