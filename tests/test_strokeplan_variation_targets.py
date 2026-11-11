import copy
import numpy as np
import pytest
from tests.test_directional_character import inputs
from tests.test_stroke_variation import fields


def variation():
    f=fields();f['global_ratio']=.04;f['local_ratio']=[0.]*len(f['local_s'])
    return dict(version=1,fields=f,source_s=[0.,1.],execution_s=[0.,1.],magnetic_scale=1.)


def test_inherited_and_overridden_targets_are_varied_once(tmp_path):
    from brushbot.experiments.strokeplan_targets import execution_targets
    plan,table,_,_=inputs(tmp_path);st=plan.strokes[0]
    entry=dict(magnetic_variation=variation(),segment_magnetic_targets=dict(nodes_s=[0.,.6,1.],values_uT=[None,200.]))
    ff,ref=execution_targets(st,table,entry,np.array([0.,.5,.75,1.]))
    assert ff==pytest.approx([180.,187.2,184.05,180.])
    assert ref==pytest.approx([180.,187.2,204.5,200.])


def test_nominal_depth_uses_varied_nominal_curve(tmp_path):
    from brushbot.experiments.strokeplan_execution import compile_recorded_plan
    from brushbot.feedforward import lookup_depth_m
    plan,table,setup,entry=inputs(tmp_path)
    entry['stroke_profiles']=[dict(magnetic_variation=variation()),dict(magnetic_variation=variation(),writing_height={'knots_s_mm':[[0.,0.],[1.,.1]]})]
    c=compile_recorded_plan(plan,table,setup,label='variation',entry_profile=entry)
    first=c['phase']=='measure_00';last=c['phase']=='measure_01'
    mid=np.flatnonzero(first)[len(np.flatnonzero(first))//2]
    assert c['g_ref_uT'][mid]==pytest.approx(187.2)
    assert c['depth_ff_m'][mid]==pytest.approx(lookup_depth_m(table,[187.2])[0])
    assert c['depth_ff_m'][np.flatnonzero(last)[-1]]==pytest.approx(lookup_depth_m(table,[180.])[0]-.0001)
    assert np.isnan(c['g_ref_uT'][~(first|last)]).all()


def test_off_grid_out_of_range_target_is_rejected(tmp_path):
    from brushbot.experiments.strokeplan_targets import validate_execution_targets
    plan,table,_,_=inputs(tmp_path)
    st=copy.deepcopy(plan.strokes[0]);st.g_target[:]=239.
    with pytest.raises(ValueError):validate_execution_targets(st,table,dict(magnetic_variation=variation()))


def test_missing_variation_preserves_legacy_arrays(tmp_path):
    from brushbot.experiments.strokeplan_targets import sample_execution_stroke
    from brushbot.strokeplan_compile import sample_stroke
    plan,table,_,_=inputs(tmp_path);st=plan.strokes[0]
    ticks,xy,ff,ref,depth=sample_execution_stroke(st,table,{})
    old=sample_stroke(st,table)
    for a,b in zip((ticks,xy,ff,depth),old):assert np.array_equal(a,b)
    assert np.array_equal(ff,ref)
