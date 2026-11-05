import json
from pathlib import Path
import numpy as np
import pytest
from scripts.brush_path_editor_model import PathModel,arc,CONTEXT


def test_independent_start_is_persisted_and_blocks_accidental_old_stroke_export(tmp_path):
    m=PathModel();before=m.points().copy();original_id=m.stroke_id
    assert m.add_independent_point([10,10]) is False
    assert np.array_equal(m.points(),before) and m.stroke_id==original_id
    path=tmp_path/'draft.json';path.write_text(json.dumps(m.state()))
    restored=PathModel.restore(path)
    assert restored.pending_point==[10.,10.]
    with pytest.raises(ValueError,match='第二个点'):restored.export(tmp_path/'export')
    assert not (tmp_path/'export').exists()
    state=restored.state()
    with pytest.raises(ValueError,match='0.02'):restored.add_independent_point([10.001,10])
    assert restored.state()==state


def test_independent_strokes_switch_restore_and_edit_without_connecting(tmp_path):
    m=PathModel()
    original_points=m.points().copy();first=m.stroke_id
    m.segment_magnetic[-1]=125.;m.node_speeds[-1]=2.
    m.node_angles[-1]=[12.,-45.]
    original=m.state(False)
    m.add_independent_point([10,10]);assert m.add_independent_point([20,10]) is True
    second=m.stroke_id
    assert np.array_equal(m.points(),[[10.,10.],[20.,10.]])
    assert m.segment_magnetic.tolist()==[125.]
    assert m.node_speeds.tolist()==[2.,2.]
    assert np.allclose(m.node_angles.astype(float),[[12.,-45.],[12.,-45.]])
    assert len(m.other_strokes)==1
    m.nodes[-1]+=[0,2];m.segment_magnetic[0]=130.;m.node_speeds[0]=1.
    second_state=m.state(False)
    m.switch_stroke(first)
    assert m.state(False)==original and np.array_equal(m.points(),original_points)
    m.switch_stroke(second)
    assert m.state(False)==second_state
    m.add_independent_point([-5,15]);m.add_independent_point([-5,25]);third=m.stroke_id
    path=tmp_path/'draft.json';path.write_text(json.dumps(m.state()))
    restored=PathModel.restore(path)
    assert [key for key,_ in restored.stroke_entries()]==[first,second,third]
    restored.switch_stroke(second);assert restored.state(False)==second_state
    restored.switch_stroke(first);assert restored.state(False)==original


def test_independent_export_compiles_all_strokes_and_retains_full_workspace(tmp_path):
    m=PathModel();first=m.stroke_id;m.segment_magnetic[-1]=125.
    m.add_independent_point([10.,10.]);m.add_independent_point([20.,10.]);second=m.stroke_id
    _,plan,_,_,_=m.compile()
    assert len(plan.strokes)==1
    assert np.allclose(plan.strokes[0].xy[[0,-1]]*1000,[[150.,10.],[160.,10.]])
    folder,summary=m.export(tmp_path)
    assert summary['stroke_id']==second and summary['workspace_stroke_count']==2
    assert summary['execution_scope']=='all_strokes_in_order'
    assert [row['point_range'] for row in summary['execution_order']]==[[0,20],[21,22]]
    from brushbot.target_strokeplan import StrokePlan
    saved=StrokePlan.load(folder/'strokeplan.npz');assert len(saved.strokes)==2
    assert (folder/'workspace_recipe.json').exists()
    recipe=json.loads((folder/'recipe.json').read_text())
    assert recipe['path']['points_mm']==[[10.,10.],[20.,10.]]
    restored=PathModel.restore(folder/'editor_state.json');restored.switch_stroke(first)
    assert len(restored.nodes)>2


def test_global_point_numbers_continue_across_strokes_and_reindex_after_insert_delete():
    m=PathModel();first=m.stroke_id;count=len(m.nodes)
    m.add_independent_point([10,10]);m.add_independent_point([20,10]);second=m.stroke_id
    assert m.stroke_node_offset()==count and m.total_node_count()==count+2
    m.switch_stroke(first);m.insert_point(len(m.nodes),m.nodes[-1]+[1,0])
    assert m.stroke_node_offset(second)==count+1
    m.delete_point(len(m.nodes)-1);assert m.stroke_node_offset(second)==count
    m.switch_stroke(second);assert m.stroke_node_offset()==count


def test_workspace_transfers_in_air_to_next_minimum_point_and_keeps_own_targets(tmp_path):
    from brushbot.experiments.strokeplan_execution import compile_recorded_plan
    from brushbot.target_strokeplan import StrokePlan
    m=PathModel();m.segment_magnetic[:]=125.;first=m.stroke_id
    m.add_independent_point([10,10]);m.add_independent_point([20,10]);second=m.stroke_id
    m.segment_magnetic[0]=140.;m.node_angles[:]=[12.,-45.];m.node_speeds[:]=2.
    m.switch_stroke(first)  # Editing selection must not change execution order.
    folder,summary=m.export(tmp_path)
    saved=StrokePlan.load(folder/'strokeplan.npz')
    settings={name:json.loads((folder/name).read_text()) for name in ['feedforward.json','settings.json','pi_profile.json','entry_profile.json']}
    c=compile_recorded_plan(saved,settings['feedforward.json'],settings['settings.json'],label='reloaded',control_mode='pi',feedback_profile=settings['pi_profile.json'],entry_profile=settings['entry_profile.json'])
    poses,phases=c['pose_m_rad'],c['phase'];height=settings['entry_profile.json']['transfer_z_mm']/1000
    previous_end=np.flatnonzero(phases=='measure_00')[-1];lift=np.flatnonzero(phases=='lift_00')
    transfer=np.flatnonzero(phases=='high_transfer_01');start=np.flatnonzero(phases=='measure_01')[0]
    assert previous_end<lift[0]<lift[-1]<transfer[0]<transfer[-1]<start
    assert np.allclose(poses[lift,:2],poses[previous_end,:2])
    assert np.allclose(poses[transfer,2],height)
    expected_xy=saved.strokes[1].xy[0]+np.array([settings['settings.json']['origin_x_mm'],settings['settings.json']['origin_y_mm']])/1000
    assert np.allclose(poses[transfer[-1],:2],expected_xy)
    for phase in ['rotate_air_01','lower_fast_01','lower_slow_01','rotate_contact_01','load_workpoint_01']:
        assert np.allclose(poses[phases==phase,:2],expected_xy)
    assert np.allclose(c['g_ref_uT'][phases=='measure_00'],125.)
    assert np.allclose(c['g_ref_uT'][phases=='measure_01'],140.)
    assert np.isnan(c['g_ref_uT'][~np.char.startswith(phases,'measure_')]).all()
    assert summary['execution_order'][1]['stroke_id']==second
    assert settings['entry_profile.json']['stroke_profiles'][1]['writing_tilt_deg']==12.
    assert np.allclose(poses[-1],poses[0])


def test_workspace_invalid_later_stroke_leaves_no_runnable_export(tmp_path):
    m=PathModel();m.add_independent_point([2000,10]);m.add_independent_point([2010,10])
    with pytest.raises(ValueError):m.export(tmp_path/'export')
    assert not (tmp_path/'export').exists()

def test_identity_retains_dense_geometry_and_knots():
    m=PathModel();assert np.allclose(m.points(),m.original,atol=1e-10)
    result=m.recipe()
    for section,key in [('magnetic_target','knots_s_uT'),('timing','speed_knots_s_mm_s')]:
        assert np.allclose(result[section][key],m.base[section][key])

def test_segment_rotation_and_length_translates_downstream():
    m=PathModel();k=3;before=m.nodes.copy();old=m.points();a,b=m.indices[k:k+2]
    chord=np.linalg.norm(before[k+1]-before[k]);length=arc(old[a:b+1])[-1]
    m.set_segment(k,chord*1.3,25.)
    assert np.array_equal(m.nodes[:k+1],before[:k+1])
    assert np.allclose(np.diff(m.nodes[k+1:],axis=0),np.diff(before[k+1:],axis=0))
    d=m.nodes[k+1]-m.nodes[k]
    assert np.rad2deg(np.arctan2(d[1],d[0]))==pytest.approx(25.)
    assert arc(m.points()[a:b+1])[-1]==pytest.approx(length*1.3)

def test_drag_retains_unaffected_segments_and_remaps_knots():
    m=PathModel();before=m.points();k=len(m.nodes)-2;m.nodes[k]+=[.2,-.1]
    p=m.points();assert np.allclose(p[:m.indices[k-1]+1],before[:m.indices[k-1]+1])
    recipe=m.recipe();knots=np.array(recipe['magnetic_target']['knots_s_uT'])
    assert np.all(np.diff(knots[:,0])>0)
    assert np.array_equal(knots[:,1],np.array(m.base['magnetic_target']['knots_s_uT'])[:,1])
    assert knots[-1,0]==pytest.approx(1.)

def test_restore_dense_state_exact(tmp_path):
    m=PathModel();m.nodes[-2]+=[.2,.1];f=tmp_path/'state.json';f.write_text(json.dumps(m.state()))
    restored=PathModel.restore(f)
    assert np.array_equal(restored.nodes,m.nodes)
    assert np.array_equal(restored.points(),m.points())

def test_rejects_nonfinite_and_collapsed_segments():
    m=PathModel()
    with pytest.raises(ValueError):m.set_segment(0,float('nan'),0)
    with pytest.raises(ValueError):m.set_segment(0,0,0)
    m.nodes[1]=m.nodes[0]
    with pytest.raises(ValueError):m.points()

def test_preflight_export_preserves_limits_and_source(tmp_path):
    m=PathModel();folder,summary=m.export(tmp_path)
    assert summary['hardware_executed'] is False
    assert (folder/'strokeplan.npz').exists()
    for name in ['settings.json','pi_profile.json','entry_profile.json','feedforward.json']:
        src=m.folder/name
        assert json.loads((folder/name).read_text())==json.loads(src.read_text())
    state=PathModel.restore(folder/'editor_state.json');assert np.allclose(state.points(),m.points())

def test_out_of_workspace_export_creates_no_runnable_plan(tmp_path):
    m=PathModel();m.nodes[:,0]+=2000
    with pytest.raises(ValueError):m.export(tmp_path)
    assert not list(tmp_path.rglob('strokeplan.npz'))

def test_writing_height_changes_z_only_and_preserves_entry_and_magnetic():
    m=PathModel();_,p0,c0,_,_=m.compile()
    m.lift_mm[-3:]=.2
    _,p1,c1,settings,_=m.compile()
    mask0=c0['phase']=='measure_00';mask1=c1['phase']=='measure_00'
    assert np.array_equal(p0.strokes[0].g_target,p1.strokes[0].g_target)
    assert np.array_equal(c0['g_ref_uT'][mask0],c1['g_ref_uT'][mask1])
    assert np.allclose(c0['pose_m_rad'][mask0,:2],c1['pose_m_rad'][mask1,:2])
    delta=c1['pose_m_rad'][mask1,2]-c0['pose_m_rad'][mask0,2]
    assert delta[-1]==pytest.approx(.0002)
    assert delta[0]==pytest.approx(0.)
    start=np.flatnonzero(mask0)[0]
    assert np.array_equal(c0['pose_m_rad'][:start],c1['pose_m_rad'][:start])
    assert 'writing_height' in settings['entry_profile.json']
    assert np.isfinite(c1['g_ref_uT'][mask1]).all()
    assert np.allclose(c1['plan'].strokes[0].z_ff,c1['depth_ff_m'][mask1])

def test_magnetic_values_apply_and_invalid_target_rejected():
    m=PathModel();m.magnetic_values[2]=170.
    result=m.recipe();assert result['magnetic_target']['knots_s_uT'][2][1]==170.
    m.magnetic_values[2]=1.
    with pytest.raises(ValueError,match='磁目标'):m.compile()

def test_excessive_lift_rejected_before_export(tmp_path):
    m=PathModel();m.lift_mm[-1]=50
    with pytest.raises(ValueError,match='writing_height'):m.export(tmp_path)
    assert not list(tmp_path.rglob('strokeplan.npz'))

def test_lift_and_magnetic_edits_restore_and_export(tmp_path):
    m=PathModel();m.lift_mm[-1]=.2;m.magnetic_values[1]=175
    folder,_=m.export(tmp_path)
    restored=PathModel.restore(folder/'editor_state.json')
    assert np.array_equal(restored.lift_mm,m.lift_mm)
    assert np.array_equal(restored.magnetic_values,m.magnetic_values)
    assert restored.recipe()['magnetic_target']==m.recipe()['magnetic_target']


def test_per_segment_magnetic_target_and_restore(tmp_path):
    m=PathModel();m.segment_magnetic[-1]=130.
    _,plan,c,_,_=m.compile()
    d=arc(m.points());mid=(d[m.indices[-2]]+d[-1])/2/d[-1]
    assert np.interp(mid,plan.strokes[0].s,plan.strokes[0].g_target)==pytest.approx(130.,abs=.02)
    folder,_=m.export(tmp_path);restored=PathModel.restore(folder/'editor_state.json')
    assert restored.segment_magnetic[-1]==130.
    assert restored.segment_magnetic[0] is None

def test_initial_height_cannot_change_entry():
    m=PathModel();m.lift_mm[0]=.1
    with pytest.raises(ValueError,match='第一节点'):m.compile()


def test_aggressive_segment_magnetic_change_keeps_acceleration_guard(tmp_path):
    m=PathModel();m.segment_magnetic[2]=323.
    folder,summary=m.export(tmp_path)
    assert summary['local_speed_adapted'] is True
    assert summary['limits']['Z speed']<=m.settings()['settings.json']['max_z_speed_mm_s']+1e-6
    assert summary['limits']['acceleration']<=m.settings()['settings.json']['max_accel_mm_s2']+1e-6
    report=json.loads((folder/'speed_adaptation.json').read_text())
    assert report['iterations']>0
    assert any(failure['limit']=='Z speed' for failure in report['failures'])
    assert m.segment_magnetic[2]==323.

def test_inherited_numeric_display_does_not_replace_original_curve():
    m=PathModel();before=m.recipe()['magnetic_target']
    values=m.inherited_segment_values()
    assert values.shape==(len(m.nodes)-1,3)
    assert np.isfinite(values).all()
    assert all(v is None for v in m.segment_magnetic)
    assert m.recipe()['magnetic_target']==before
    assert values[0,0]==pytest.approx(m.magnetic_values[0])
    assert values[-1,-1]==pytest.approx(m.magnetic_values[-1])

def test_zero_magnetic_edit_and_draft_allowed_but_execution_not_extrapolated(tmp_path):
    m=PathModel();m.segment_magnetic[-1]=0.
    recipe=m.recipe()
    assert min(v for _,v in recipe['magnetic_target']['knots_s_uT'])==0.
    state=tmp_path/'draft.json';state.write_text(json.dumps(m.state(),allow_nan=False))
    restored=PathModel.restore(state);assert restored.segment_magnetic[-1]==0.
    with pytest.raises(ValueError,match='低于现有标定下限'):m.export(tmp_path/'exports')
    assert not list((tmp_path/'exports').rglob('strokeplan.npz'))
    m.segment_magnetic[-1]=-1.
    with pytest.raises(ValueError,match='输入范围'):m.recipe()

def test_authorized_low_response_trial_exports_zero_and_preserves_measured_knots(tmp_path):
    from brushbot.feedforward import lookup_depth_m,require_execution_approval
    m=PathModel();original=m.settings()['feedforward.json'];m.segment_magnetic[-1]=0.;m.allow_low_response=True
    folder,summary=m.export(tmp_path)
    table=json.loads((folder/'feedforward.json').read_text())
    assert table['amplitude_uT']==original['amplitude_uT']
    assert table['depth_mm']==original['depth_mm']
    assert lookup_depth_m(table,[0.])[0]==0.
    assert lookup_depth_m(table,[original['amplitude_uT'][0]/2])[0]==pytest.approx(original['depth_mm'][0]/2000.)
    assert np.array_equal(lookup_depth_m(table,original['amplitude_uT']),lookup_depth_m(original,original['amplitude_uT']))
    require_execution_approval(table,json.loads((folder/'settings.json').read_text()))
    assert summary['low_response_trial'] is True
    assert 0<summary['retiming_factor']<=1
    assert PathModel.restore(folder/'editor_state.json').allow_low_response is True
    with pytest.raises(ValueError):lookup_depth_m(table,[-1.])
    with pytest.raises(ValueError):lookup_depth_m(table,[original['amplitude_uT'][-1]+1])

def test_low_response_authorization_and_endpoints_must_match():
    from brushbot.feedforward import lookup_depth_m
    m=PathModel();table=m.settings()['feedforward.json']
    with pytest.raises(ValueError):lookup_depth_m(table,[0])
    table['low_response_trial']=dict(method='linear_to_nominal_zero_depth',trial_authorized=False,
        measured_lower_uT=table['amplitude_uT'][0],measured_lower_depth_mm=table['depth_mm'][0])
    with pytest.raises(ValueError,match='low-response'):lookup_depth_m(table,[0])

def test_selected_feedforward_override_is_restored_and_exported(tmp_path):
    from brushbot.feedforward import lookup_depth_m
    m=PathModel();table=m.settings()['feedforward.json']
    table['amplitude_uT']=[66.,69.]+table['amplitude_uT']
    table['depth_mm']=[4.5,4.75]+table['depth_mm']
    selected=tmp_path/'custom.json';selected.write_text(json.dumps(table))
    m.feedforward_override=str(selected)
    assert lookup_depth_m(m.settings()['feedforward.json'],[66,69])==pytest.approx([.0045,.00475])
    folder,_=m.export(tmp_path/'exports')
    assert json.loads((folder/'feedforward.json').read_text())==table
    restored=PathModel.restore(folder/'editor_state.json')
    assert restored.feedforward_override is None
    selected.unlink()
    assert restored.settings()['feedforward.json']==table


def test_equal_adjacent_segment_targets_never_rebound_at_nodes():
    from scripts.generate_strokeplan_from_json import build_plan
    m=PathModel();m.segment_magnetic[-3:]=69.
    recipe=m.recipe();st=build_plan(recipe).strokes[0]
    distances=arc(m.points());nodes=distances[m.indices]/distances[-1]
    # Exclude the one permitted entry transition from the inherited body.
    start=nodes[-4]+.26*(nodes[-3]-nodes[-4])
    q=np.unique(np.r_[np.linspace(start,1.,501),nodes[-3:]])
    assert np.interp(q,st.s,st.g_target)==pytest.approx(np.full(len(q),69.),abs=.01)
    assert st.g_target[-1]==69.

def test_different_adjacent_targets_blend_to_each_other_not_source_curve():
    from scripts.generate_strokeplan_from_json import build_plan
    m=PathModel();m.segment_magnetic[-3:]=[80.,85.,90.]
    st=build_plan(m.recipe()).strokes[0];distances=arc(m.points());nodes=distances[m.indices]/distances[-1]
    q=np.linspace(nodes[-3]-.1*(nodes[-3]-nodes[-4]),1.,501)
    values=np.interp(q,st.s,st.g_target)
    assert values.min()>=80.-1e-6 and values.max()<=90.+1e-6
    assert st.g_target[-1]==90.

def test_explicit_magnetic_control_reference_is_exact_over_entire_segment(tmp_path):
    m=PathModel();m.segment_magnetic[-3:]=[80.,85.,90.]
    _,_,compiled,_,_=m.compile()
    distances=arc(m.points());nodes=distances[m.indices]/distances[-1]
    mask=compiled['phase']=='measure_00';q=compiled['s'][mask];g=compiled['g_ref_uT'][mask]
    owner=np.clip(np.searchsorted(nodes,q,side='right')-1,0,len(m.segment_magnetic)-1)
    for k,value in enumerate(m.segment_magnetic):
        if value is not None:
            assert np.all(g[owner==k]==value)
    folder,_=m.export(tmp_path)
    report=json.loads((folder/'segment_target_audit.json').read_text())
    assert all(r['actual_reference_min_uT']==r['requested_uT']==r['actual_reference_max_uT'] for r in report)
    entry=json.loads((folder/'entry_profile.json').read_text())
    assert entry['segment_magnetic_targets']['values_uT'][-3:]==[80.,85.,90.]

def test_reference_audit_rejects_any_unintended_rebound():
    m=PathModel();m.segment_magnetic[-3:]=80.
    _,_,c,_,_=m.compile();mask=c['phase']=='measure_00'
    indices=np.flatnonzero(mask);c['g_ref_uT'][indices[-3]]=140.
    with pytest.raises(ValueError,match='磁目标与设置不一致'):m.audit_targets(c)

def test_segment_boundary_belongs_to_new_segment_and_last_endpoint_is_final():
    from brushbot.experiments.strokeplan_segment_targets import apply_segment_targets
    m=PathModel();table=m.settings()['feedforward.json']
    profile=dict(nodes_s=[0.,.25,.5,.75,1.],values_uT=[80.,90.,None,100.])
    q=np.array([0.,.249,.25,.499,.5,.749,.75,1.])
    result=apply_segment_targets(q,np.full(len(q),125.),profile,table)
    assert np.array_equal(result,[80.,80.,90.,90.,125.,125.,100.,100.])


def test_add_point_preserves_geometry_targets_and_restore(tmp_path):
    m=PathModel();m.nodes[3]+=[.1,.1];m.segment_magnetic[2]=125
    m.lift_mm[2:4]=[.1,.3]
    before=m.recipe();length=arc(m.points())[-1];count=len(m.nodes)
    node=m.add_point(2)
    assert len(m.nodes)==count+1 and node==3
    assert arc(m.points())[-1]==pytest.approx(length)
    assert list(m.segment_magnetic[2:4])==[125,125]
    assert m.lift_mm[3]==pytest.approx(.2)
    assert np.allclose(m.points()[m.indices],m.nodes)
    f=tmp_path/'state.json';f.write_text(json.dumps(m.state()))
    restored=PathModel.restore(f)
    assert np.allclose(restored.points(),m.points())
    assert np.allclose(restored.recipe()['timing']['speed_knots_s_mm_s'],before['timing']['speed_knots_s_mm_s'])


def test_delete_point_removes_bend_and_keeps_preceding_target():
    m=PathModel();node=len(m.nodes)-3
    m.segment_magnetic[node-1:node+1]=[125,130]
    m.lift_mm[node]=.2
    before=m.points();a,b=m.indices[node-1],m.indices[node+1]
    count=len(m.nodes);m.delete_point(node)
    assert len(m.nodes)==count-1
    assert m.segment_magnetic[node-1]==125
    assert np.allclose(m.points()[:a+1],before[:a+1])
    assert np.allclose(m.points()[b:],before[b:])
    segment=m.points()[a:b+1];d=segment[-1]-segment[0]
    assert np.allclose((segment[:,0]-segment[0,0])*d[1]-(segment[:,1]-segment[0,1])*d[0],0)
    assert len(m.lift_mm)==len(m.nodes)
    assert len(m.segment_magnetic)==len(m.nodes)-1
    with pytest.raises(ValueError):m.delete_point(-1)
    with pytest.raises(ValueError):m.delete_point(len(m.nodes))


def test_topology_compile_preserves_strict_magnetic_targets():
    m=PathModel();m.segment_magnetic[-3:]=125
    m.add_point(len(m.nodes)-3)
    m.delete_point(len(m.nodes)-3)
    _,_,compiled,_,_=m.compile()
    assert m.audit_targets(compiled)


def test_speed_edit_uses_current_geometry_progress_and_restores(tmp_path):
    import copy
    m=PathModel();m.nodes[-2]+=[.3,.2]
    timing=copy.deepcopy(m.recipe()['timing'])
    timing['speed_mm_s']=2.5
    timing['speed_knots_s_mm_s']=[[0,1.2],[.8,2.5],[1,1.8]]
    m.set_timing(timing)
    assert np.allclose(m.recipe()['timing']['speed_knots_s_mm_s'],timing['speed_knots_s_mm_s'])
    f=tmp_path/'speed.json';f.write_text(json.dumps(m.state()))
    restored=PathModel.restore(f)
    assert restored.recipe()['timing']==m.recipe()['timing']
    invalid=copy.deepcopy(timing);invalid['speed_knots_s_mm_s']=[[0,1],[.8,0],[1,1]]
    before=copy.deepcopy(m.base)
    with pytest.raises(ValueError):m.set_timing(invalid)
    assert m.base==before


def test_heading_knots_remap_with_edited_geometry_and_topology(tmp_path):
    m=PathModel();m.base['orientation']['heading_knots_s_deg']=[[.6,None],[.8,-45],[1,-90]]
    m.nodes[-2]+=[.2,.1]
    before=m.recipe()['orientation']['heading_knots_s_deg']
    assert before[0][1] is None
    m.add_point(3)
    assert np.allclose(np.array(m.recipe()['orientation']['heading_knots_s_deg'],object)[:,0].astype(float),np.array(before,object)[:,0].astype(float))
    path=tmp_path/'state.json';path.write_text(json.dumps(m.state()))
    assert PathModel.restore(path).recipe()['orientation']==m.recipe()['orientation']


def test_orientation_edit_remaps_progress_and_updates_execution_tilt(tmp_path):
    m=PathModel();m.nodes[-2]+=[.2,.1]
    orientation=dict(kind='tangent_tilt',tilt_deg=12.,smoothing_mm=16.,heading_knots_s_deg=[[.7,None],[.8,-45.],[.9,-90.],[1.,-90.]])
    m.set_orientation(orientation)
    result=m.recipe()['orientation']
    assert np.allclose(np.array(result['heading_knots_s_deg'],object)[:,0].astype(float),[.7,.8,.9,1])
    _,_,_,settings,_=m.compile()
    assert settings['entry_profile.json']['writing_tilt_deg']==12.
    path=tmp_path/'orientation.json';path.write_text(json.dumps(m.state()))
    assert PathModel.restore(path).recipe()['orientation']==result
    import copy
    before=copy.deepcopy(m.base);invalid=dict(orientation,tilt_deg=30.)
    with pytest.raises(ValueError):m.set_orientation(invalid)
    assert m.base==before


def test_segment_node_angles_restore_split_delete_and_compilation(tmp_path):
    from scripts.generate_strokeplan_from_json import build_plan
    from brushbot.experiments.strokeplan_character import orientation_heading
    m=PathModel();k=len(m.nodes)-4
    m.node_angles[k]=[12.,-45.];m.node_angles[k+1]=[14.,-90.]
    plan=build_plan(m.recipe());st=plan.strokes[0]
    distances=arc(m.points());q=distances[m.indices]/distances[-1]
    heading=np.rad2deg(np.unwrap([orientation_heading(rpy) for rpy in st.orientation]))
    tilt=np.rad2deg(np.arccos(np.clip(np.cos(st.orientation[:,0])*np.cos(st.orientation[:,1]),-1,1)))
    assert np.interp(q[k],st.s,heading)==pytest.approx(-45,abs=.1)
    assert np.interp(q[k+1],st.s,heading)==pytest.approx(-90,abs=.1)
    assert np.interp(q[k],st.s,tilt)==pytest.approx(12,abs=.1)
    _,_,_,settings,_=m.compile()
    assert settings['entry_profile.json']['writing_tilt_deg']==15
    m.add_point(k)
    assert 12<m.node_angles[k+1,0]<14
    assert -90<m.node_angles[k+1,1]<-45
    assert np.array_equal(m.node_angles[k+2],[14,-90])
    m.delete_point(k+1)
    assert np.array_equal(m.node_angles[k+1],[14,-90])
    path=tmp_path/'nodeangles.json';path.write_text(json.dumps(m.state()))
    restored=PathModel.restore(path)
    assert np.array_equal(restored.node_angles,m.node_angles)
    assert restored.recipe()['orientation']==m.recipe()['orientation']


def test_auto_speed_recomputes_after_edits_without_changing_requested_motion():
    import copy
    m=PathModel();m.segment_magnetic[2]=323.
    requested=copy.deepcopy(m.recipe());settings=copy.deepcopy(m.settings())
    result,_,compiled,actual,limits=m.compile()
    assert result['path']==requested['path']
    assert result['magnetic_target']==requested['magnetic_target']
    assert result['orientation']==requested['orientation']
    assert m.recipe()==requested
    assert actual['settings.json']==settings['settings.json']
    assert m.last_speed_adaptation['global_time_scaling_applied'] is False
    assert m.last_speed_adaptation['iterations']>0
    assert m.audit_targets(compiled)
    m.nodes[3]+=[.2,.15];m.node_angles[-3,1]=-60.;m.node_angles[-2,1]=-100.
    next_requested=copy.deepcopy(m.recipe())
    result,_,_,_,_=m.compile()
    assert result['path']==next_requested['path']
    assert result['orientation']==next_requested['orientation']
    assert m.recipe()==next_requested


def test_auto_speed_caps_table_support_and_rejects_unresolved_limits():
    from scripts.brush_speed_adaptation import adapt_speed
    m=PathModel();requested=m.recipe();requested['timing']['speed_mm_s']=20.
    requested['timing']['speed_knots_s_mm_s']=[[0,20],[1,20]]
    settings=m.settings()
    result,_,_,_,report=adapt_speed(requested,settings)
    assert result['timing']['speed_mm_s']==settings['feedforward.json']['speed_mm_s']
    assert report['planned_max_writing_speed_mm_s']<=10+1e-6
    m.segment_magnetic[2]=323.
    with pytest.raises(ValueError,match='未能'):
        adapt_speed(m.recipe(),m.settings(),max_iterations=0)


def test_local_speed_rhythm_is_smooth_shared_and_does_not_change_ink_commands(tmp_path):
    import copy
    m=PathModel();before=copy.deepcopy(m.recipe());k=3
    m.node_speeds[k:k+2]=[4.,5.];m.segment_speeds[k]=.8;m.speed_positions[k]=.7
    result=m.recipe();knots=np.array(result['timing']['speed_knots_s_mm_s']);d=arc(m.points());q=d[m.indices]/d[-1]
    assert result['path']==before['path']
    assert result['magnetic_target']==before['magnetic_target']
    assert result['orientation']==before['orientation']
    assert np.interp(q[k],knots[:,0],knots[:,1])==pytest.approx(4.)
    assert np.interp(q[k]+.7*(q[k+1]-q[k]),knots[:,0],knots[:,1])==pytest.approx(.8)
    assert np.interp(q[k+1],knots[:,0],knots[:,1])==pytest.approx(5.)
    values=m.displayed_local_speeds();assert values[k,2]==pytest.approx(values[k+1,0])
    path=tmp_path/'local-speed.json';path.write_text(json.dumps(m.state()))
    restored=PathModel.restore(path);assert restored.recipe()['timing']==result['timing']
    m.node_speeds[:]=None;m.segment_speeds[:]=None
    assert m.recipe()['timing']==before['timing']


def test_local_speed_split_delete_and_validation():
    m=PathModel();k=3;m.node_speeds[k:k+2]=[4.,5.];m.segment_speeds[k]=1.;m.speed_positions[k]=.7
    count=len(m.nodes);m.add_point(k)
    assert len(m.node_speeds)==count+1
    assert len(m.segment_speeds)==count
    assert m.node_speeds[k+1] is not None
    assert all(value is not None for value in m.segment_speeds[k:k+2])
    m.delete_point(k+1)
    assert len(m.node_speeds)==count
    assert len(m.segment_speeds)==count-1
    m.node_speeds[k]=0
    with pytest.raises(ValueError,match='局部速度'):m.recipe()
    m.node_speeds[k]=4;m.speed_positions[k]=1
    with pytest.raises(ValueError,match='节奏位置'):m.recipe()


def test_local_rhythm_exports_through_adaptation(tmp_path):
    m=PathModel();m.node_speeds[3:5]=[3.,4.];m.segment_speeds[3]=1.2
    folder,summary=m.export(tmp_path)
    assert summary['auto_speed_adaptation'] is True
    restored=PathModel.restore(folder/'editor_state.json')
    assert np.array_equal(restored.node_speeds,m.node_speeds)
    assert np.array_equal(restored.segment_speeds,m.segment_speeds)
    assert summary['limits']['acceleration']<=m.settings()['settings.json']['max_accel_mm_s2']+1e-6


def test_cyg_profile_selection_persists_and_exports_paired_limits(tmp_path):
    import copy
    m=PathModel();original=m.settings();table=copy.deepcopy(original['feedforward.json'])
    table['speed_mm_s']=20.;table['high_speed_trial']=dict(authorized=True,measured_speed_mm_s=10.,requested_speed_limit_mm_s=20.,status='unmeasured_speed_extension')
    setup=copy.deepcopy(original['settings.json']);setup['max_accel_mm_s2']=400.
    entry=copy.deepcopy(original['entry_profile.json']);entry['angular_speed_deg_s']=40.;entry['angular_accel_deg_s2']=80.
    for name,value in [('feedforward_cyg.json',table),('settings_cyg.json',setup),('entry_profile_cyg.json',entry)]:
        (tmp_path/name).write_text(json.dumps(value))
    m.select_feedforward(tmp_path/'feedforward_cyg.json')
    m.base=copy.deepcopy(m.base);m.base['timing'].update(speed_mm_s=20.,accel_mm_s2=400.,angular_speed_deg_s=40.,angular_accel_deg_s2=80.)
    m.node_speeds[3:5]=[12,14];m.segment_speeds[3]=18.
    path=tmp_path/'draft.json';path.write_text(json.dumps(m.state()))
    restored=PathModel.restore(path)
    assert restored.settings()['settings.json']['max_accel_mm_s2']==400
    folder,summary=restored.export(tmp_path/'exports')
    assert json.loads((folder/'feedforward.json').read_text())['speed_mm_s']==20
    assert json.loads((folder/'settings.json').read_text())['max_accel_mm_s2']==400
    assert json.loads((folder/'entry_profile.json').read_text())['angular_accel_deg_s2']==80
    assert summary['limits']['acceleration']<=400+1e-6
    m.select_feedforward(m.folder/'feedforward.json')
    assert m.settings()['settings.json']['max_accel_mm_s2']==original['settings.json']['max_accel_mm_s2']


def test_endpoint_speed_mode_ignores_middle_and_fast_curve_matches_recipe(tmp_path):
    m=PathModel();m.node_speeds[3:5]=[4,8];m.segment_speeds[3]=.8
    m.use_endpoint_speeds();assert all(value is None for value in m.segment_speeds)
    m.nodes[5]+=[.2,.1]
    assert np.allclose(m.speed_curve(),m.recipe()['timing']['speed_knots_s_mm_s'])
    values=m.displayed_local_speeds();assert values[3,1]==pytest.approx(6,abs=.001)
    path=tmp_path/'state.json';path.write_text(json.dumps(m.state()))
    restored=PathModel.restore(path);assert restored.endpoint_speed_mode is True
    m.add_point(3);assert all(value is None for value in m.segment_speeds)


def test_temporary_hidden_nodes_restore_full_geometry_and_settings(tmp_path):
    m=PathModel();m.segment_magnetic[-3:]=[125.,130.,125.]
    m.node_speeds[-4:]=[2.,3.,2.,1.5];m.node_angles[-2]=[14.,-70.]
    before=m.recipe();state=m.state();first=len(m.nodes)-4
    m.set_test_range(first,len(m.nodes)-1)
    assert np.array_equal(m.test_points(),m.points()[m.indices[first]:])
    path=tmp_path/'partial.json';path.write_text(json.dumps(m.state()))
    restored=PathModel.restore(path)
    assert np.array_equal(restored.node_enabled,m.node_enabled)
    assert restored.recipe()==before  # Editing data is retained in full.
    restored.set_test_range(0,len(m.nodes)-1)
    assert restored.state()==state


def test_partial_export_crops_world_path_and_exact_segment_references(tmp_path):
    m=PathModel();first=len(m.nodes)-4;last=len(m.nodes)-1
    m.segment_magnetic[first:last]=[125.,130.,125.]
    m.node_speeds[first:last+1]=[2.,3.,2.,1.5]
    points=m.points();m.set_test_range(first,last)
    folder,summary=m.export(tmp_path)
    recipe=json.loads((folder/'recipe.json').read_text())
    assert np.allclose(recipe['path']['points_mm'],points[m.indices[first]:m.indices[last]+1])
    assert recipe['placement']==m.base['placement']
    assert summary['test_node_range']==[first,last]
    entry=json.loads((folder/'entry_profile.json').read_text())
    assert entry['segment_magnetic_targets']['values_uT']==[125.,130.,125.]
    assert entry['segment_magnetic_targets']['nodes_s'][0]==0
    assert entry['segment_magnetic_targets']['nodes_s'][-1]==1
    audit=json.loads((folder/'segment_target_audit.json').read_text())
    assert len(audit)==3
    assert all(r['actual_reference_min_uT']==r['requested_uT']==r['actual_reference_max_uT'] for r in audit)
    restored=PathModel.restore(folder/'editor_state.json')
    assert len(restored.nodes)==len(m.nodes)
    assert restored.test_node_range()==(first,last)


def test_hide_rejects_gaps_and_too_few_points_without_mutation():
    m=PathModel();before=m.node_enabled.copy()
    with pytest.raises(ValueError,match='连续区间'):m.hide_nodes({3})
    assert np.array_equal(m.node_enabled,before)
    with pytest.raises(ValueError,match='至少保留'):m.hide_nodes(range(len(m.nodes)-1))
    assert np.array_equal(m.node_enabled,before)
    m.hide_nodes({0,1});assert m.test_node_range()==(2,len(m.nodes)-1)
    m.set_test_range(2,3)
    with pytest.raises(ValueError,match='至少保留'):m.delete_point(2)
    with pytest.raises(ValueError):m.set_test_range(3,3)
    assert m.test_node_range()==(2,3)


def test_hidden_node_topology_and_legacy_state(tmp_path):
    m=PathModel();m.set_test_range(3,6)
    m.add_point(4);assert m.test_node_range()==(3,7)
    m.add_point(0);assert m.test_node_range()==(4,8)
    m.delete_point(1);assert m.test_node_range()==(3,7)
    m.delete_point(5);assert m.test_node_range()==(3,6)
    state=m.state();state.pop('node_enabled')
    path=tmp_path/'legacy.json';path.write_text(json.dumps(state))
    assert PathModel.restore(path).node_enabled.all()


def test_partial_preserves_inherited_angles_and_speed_requests():
    m=PathModel();first,last=len(m.nodes)-4,len(m.nodes)-2
    m.node_speeds[first:last+1]=[2.,3.,2.]
    angles=m.displayed_node_angles();full=m.speed_curve();distances=arc(m.points())
    lo,hi=distances[m.indices[[first,last]]]/distances[-1]
    m.set_test_range(first,last);effective=m.execution_model()
    assert np.allclose(effective.node_angles.astype(float),angles[first:last+1])
    partial=effective.speed_curve();q=np.linspace(0,1,100)
    assert np.allclose(np.interp(q,partial[:,0],partial[:,1]),np.interp(lo+q*(hi-lo),full[:,0],full[:,1]))


@pytest.mark.parametrize('prepend',[True,False])
def test_insert_new_endpoint_preserves_body_and_inherits_edge_settings(tmp_path,prepend):
    m=PathModel();m.segment_magnetic[:]=125.;m.node_speeds[:]=2.
    m.node_angles[0]=[12.,-10.];m.node_angles[-1]=[14.,-90.]
    old=m.points();nodes=m.nodes.copy();count=len(nodes)
    endpoint=0 if prepend else count;xy=nodes[0]+[-2.,0.] if prepend else nodes[-1]+[2.,0.]
    assert m.insert_point(endpoint,xy)==endpoint
    assert np.allclose(m.nodes[endpoint],xy)
    assert np.allclose(m.nodes[1:] if prepend else m.nodes[:-1],nodes)
    assert np.allclose(m.points()[1:] if prepend else m.points()[:-1],old)
    edge=0 if prepend else -1
    assert m.segment_magnetic[edge]==125. and m.node_speeds[edge]==2.
    assert np.allclose(m.node_angles[edge].astype(float),[12.,-10.] if prepend else [14.,-90.])
    folder,_=m.export(tmp_path)
    restored=PathModel.restore(folder/'editor_state.json')
    assert np.allclose(restored.nodes,m.nodes)
    assert restored.audit_targets(restored.compile()[2])


@pytest.mark.parametrize('node',[1,8])
def test_insert_arbitrary_xy_between_nodes_and_failure_is_atomic(node):
    m=PathModel();m.segment_magnetic[node-1]=125.
    old=m.nodes.copy();xy=(old[node-1]+old[node])/2+[.2,.4]
    m.insert_point(node,xy)
    assert np.allclose(m.nodes[node],xy)
    assert np.allclose(m.nodes[:node],old[:node])
    assert np.allclose(m.nodes[node+1:],old[node:])
    assert list(m.segment_magnetic[node-1:node+1])==[125.,125.]
    before=json.dumps(m.state(),sort_keys=True)
    with pytest.raises(ValueError,match='至少相隔'):m.insert_point(node,m.nodes[node-1])
    with pytest.raises(ValueError,match='有限'):m.insert_point(node,[float('nan'),0])
    assert json.dumps(m.state(),sort_keys=True)==before


def test_free_insert_can_bend_a_segment_too_short_for_a_midpoint(tmp_path):
    m=PathModel();m.base['path']['points_mm']=[[0,0],[.03,0],[2,1]]
    folder=tmp_path/'short';folder.mkdir();(folder/'recipe.json').write_text(json.dumps(m.base))
    small=PathModel(folder);small.insert_point(1,[.015,.1])
    assert np.allclose(small.nodes[1],[.015,.1])
    assert np.all(np.linalg.norm(np.diff(small.nodes,axis=0),axis=1)>=.02)


@pytest.mark.parametrize('prepend',[True,False])
def test_delete_endpoint_crops_profiles_and_keeps_remaining_attributes(tmp_path,prepend):
    m=PathModel();m.segment_magnetic[:]=125.;m.node_speeds[:]=2.
    m.node_angles[2]=[12.,-30.];m.node_angles[-2]=[14.,-80.]
    m.nodes[3]+=[.1,.2]
    old=m.points();old_nodes=m.nodes.copy();old_angles=m.node_angles.copy()
    a,b=(m.indices[1],len(old)-1) if prepend else (0,m.indices[-2])
    m.delete_point(0 if prepend else len(m.nodes)-1)
    assert np.allclose(m.points(),old[a:b+1])
    assert np.allclose(m.nodes,old_nodes[1:] if prepend else old_nodes[:-1])
    assert np.array_equal(m.node_angles,old_angles[1:] if prepend else old_angles[:-1])
    assert all(v==125. for v in m.segment_magnetic)
    assert all(v==2. for v in m.node_speeds)
    assert m.indices[0]==0 and m.indices[-1]==len(m.original)-1
    folder,_=m.export(tmp_path)
    assert np.allclose(PathModel.restore(folder/'editor_state.json').points(),m.points())


def test_endpoint_topology_respects_hidden_range_and_minimum_path(tmp_path):
    m=PathModel();m.set_test_range(3,6);count=len(m.nodes)
    m.insert_point(0,m.nodes[0]+[-1,0]);assert m.test_node_range()==(4,7)
    m.insert_point(len(m.nodes),m.nodes[-1]+[1,0]);assert m.test_node_range()==(4,7)
    m.delete_point(0);assert m.test_node_range()==(3,6)
    m.delete_point(len(m.nodes)-1);assert m.test_node_range()==(3,6)
    assert len(m.nodes)==count
    m=PathModel();m.base['path']['points_mm']=[[0,0],[2,1],[4,0]]
    folder=tmp_path/'minimal';folder.mkdir();(folder/'recipe.json').write_text(json.dumps(m.base))
    small=PathModel(folder);small.delete_point(len(small.nodes)-1)
    assert len(small.nodes)==2
    before=small.state()
    with pytest.raises(ValueError,match='至少保留两个'):small.delete_point(0)
    assert small.state()==before


@pytest.mark.parametrize('operation',['prepend','append','delete_start','delete_end'])
def test_legacy_tail_heading_remains_valid_after_endpoint_changes(operation):
    m=PathModel();m.base['orientation']['heading_knots_s_deg']=[[.6,None],[.8,-45.],[1.,-90.]]
    m.node_angles[-2]=[14.,-80.]
    old=m.displayed_node_angles();manual=m.node_angles.copy()
    if operation=='prepend':m.insert_point(0,m.nodes[0]+[-1,0]);retained=m.node_angles[1:]
    elif operation=='append':m.insert_point(len(m.nodes),m.nodes[-1]+[1,0]);retained=m.node_angles[:-1]
    elif operation=='delete_start':m.delete_point(0);retained=m.node_angles;old=old[1:];manual=manual[1:]
    else:m.delete_point(len(m.nodes)-1);retained=m.node_angles;old=old[:-1];manual=manual[:-1]
    inherited=np.equal(manual,None)
    assert np.allclose(retained[inherited].astype(float),old[inherited])
    assert np.array_equal(retained[~inherited],manual[~inherited])
    assert 'heading_knots_s_deg' not in m.recipe()['orientation']
    m.compile()
