import copy
import numpy as np
import pytest


def settings():
    return dict(origin_x_mm=-200.,origin_y_mm=500.,wait_z_mm=130.,contact_z_mm=37.,
        vertical_rpy_rad=[0.,.2617993877991494,0.],filter={'kind':'ema','alpha':.3},
        installation_id='fixture',sensor_mount_id='fixture',tcp_name='TCP_brush',ucs_name='Base',
        tool_coord_si=[0.]*6,user_coord_si=[0.]*6,max_depth_mm=18.,
        workspace_min_mm=[-400,400,17],workspace_max_mm=[100,600,150],
        max_xy_speed_mm_s=30.,max_z_speed_mm_s=13.,max_accel_mm_s2=200.,max_step_mm=2.,
        verified=False)


def table():
    s = settings()
    return dict(version=1,calibration_id='fixture',approved=False,
        feature='filtered_dBxy_norm_uT',amplitude_uT=[20.,40.,80.],depth_mm=[5.,10.,12.],
        context={k:s[k] for k in ('vertical_rpy_rad','filter','installation_id','sensor_mount_id',
                     'tcp_name','ucs_name','tool_coord_si','user_coord_si','contact_z_mm')},
        directions=['+x'],speed_mm_s=10.,source_runs=['fixture'],
        transient_approved=False)


def test_lookup_and_no_extrapolation():
    from brushbot.feedforward import lookup_depth_m
    assert lookup_depth_m(table(),np.array([30.,50.])).tolist() == pytest.approx([.0075,.0105])
    for g in ([19.],[81.],[float('nan')]):
        with pytest.raises(ValueError):
            lookup_depth_m(table(),np.array(g))


@pytest.mark.parametrize('field,value', [('amplitude_uT',[20,20,80]),
    ('depth_mm',[5,4,12]),('depth_mm',[5,float('nan'),12]),('approved','false')])
def test_invalid_table(field,value):
    from brushbot.feedforward import validate_table
    t=table(); t[field]=value
    with pytest.raises(ValueError): validate_table(t)


def test_synthetic_generation_is_independent(tmp_path,monkeypatch):
    from scripts.generate_strokeplan import generate
    monkeypatch.chdir(tmp_path)
    p=generate(targets_uT=[30.,70.,30.])
    p.validate()
    assert not hasattr(p.strokes[0],'z_ff')
    assert p.meta['source']=='synthetic'
    st=p.strokes[0]
    v=np.diff(st.xy[:,0])/np.diff(st.t)
    assert v.max() <= .01000001
    assert st.xy[-1,0]==pytest.approx(.2)


def test_compilation_uses_independent_tables_without_mutating_plan():
    from scripts.generate_strokeplan import generate
    from brushbot.strokeplan_compile import compile_target_plan
    p=generate(targets_uT=[30.]); before=copy.deepcopy(p)
    a,ph=compile_target_plan(p,table(),settings())
    other=table(); other['depth_mm']=[6.,11.,13.]
    b,bph=compile_target_plan(p,other,settings())
    mask=np.array(ph)=='measure_00'
    assert np.allclose(a[mask,2],.0295)
    assert np.allclose(b[np.array(bph)=='measure_00',2],.0285)
    assert np.allclose(a[0],a[-1])
    assert p.meta==before.meta
    assert np.array_equal(p.strokes[0].g_target,before.strokes[0].g_target)


def test_time_interpolate_then_lookup():
    from brushbot.target_strokeplan import Stroke,StrokePlan
    from brushbot.strokeplan_compile import sample_stroke
    st=Stroke(np.array([0.,1.]),np.array([[0.,0.],[.01,0.]]),
              np.array([0.,1.]),np.array([20.,80.]))
    ts,xy,g,depth=sample_stroke(st,table(),.02)
    assert len(ts)==51 and ts[-1]==1.
    assert xy[25,0]==pytest.approx(.005)
    assert g[25]==50.
    assert depth[25]==pytest.approx(.0105)


def test_pause_is_preserved_on_time_grid():
    from brushbot.target_strokeplan import Stroke
    from brushbot.strokeplan_compile import sample_stroke
    st=Stroke(np.array([0.,.5,.5,1.]),np.array([[0.,0.],[.01,0.],[.01,0.],[.02,0.]]),
              np.array([0.,1.,2.,3.]),np.array([30.,30.,30.,30.]))
    ts,xy,g,depth=sample_stroke(st,table(),.02)
    assert ts[-1]==3. and len(ts)==151
    assert np.allclose(xy[50:101,0],.01)


def test_non_grid_endpoint_is_held_not_time_scaled():
    from brushbot.target_strokeplan import Stroke
    from brushbot.strokeplan_compile import sample_stroke
    st=Stroke(np.array([0.,1.]),np.array([[0.,0.],[.01,0.]]),
              np.array([0.,1.01]),np.array([30.,30.]))
    ts,xy,_,_=sample_stroke(st,table(),.02)
    assert ts[-1]==pytest.approx(1.02)
    assert xy[-2,0]==pytest.approx(.01/1.01)
    assert xy[-1,0]==.01


def test_exact_grid_endpoint_does_not_gain_a_tick_from_float_roundoff():
    from brushbot.target_strokeplan import Stroke
    from brushbot.strokeplan_compile import sample_stroke
    st = Stroke(np.array([0., 1.]), np.array([[0., 0.], [.01, 0.]]),
                np.array([0., 510 * .04]), np.array([30., 30.]))
    ts, _, _, _ = sample_stroke(st, table(), .02)
    assert len(ts) == 1021
    assert ts[-1] == pytest.approx(20.4)


@pytest.mark.parametrize('mutation',['orientation','filter','mount','outside','direction','workspace','speed'])
def test_compile_rejects_incompatible_or_unsafe_inputs(mutation):
    from scripts.generate_strokeplan import generate
    from brushbot.strokeplan_compile import compile_target_plan
    p=generate(targets_uT=[30.]); s=settings()
    if mutation=='orientation': s['vertical_rpy_rad']=[0,0,0]
    if mutation=='filter': s['filter']['alpha']=.1
    if mutation=='mount': s['sensor_mount_id']='different'
    if mutation=='outside': p.strokes[0].g_target[:]=100.
    if mutation=='direction': p.strokes[0].xy[:,0]*=-1
    if mutation=='workspace': s['workspace_max_mm'][0]=-100
    if mutation=='speed': p.strokes[0].t /= 2
    with pytest.raises(ValueError): compile_target_plan(p,table(),s)


def test_candidate_execution_gate():
    from brushbot.feedforward import require_execution_approval
    t=table(); s=settings()
    with pytest.raises(ValueError): require_execution_approval(t,s)
    t['approved']=True
    with pytest.raises(ValueError): require_execution_approval(t,s)
    t['transient_approved']=True; s['verified']=True
    require_execution_approval(t,s)
