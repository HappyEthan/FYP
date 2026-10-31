import copy
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
import pytest
from PyQt5 import QtWidgets
from scripts.brush_path_editor_model import PathModel
from scripts.brush_rhythm import rhythm_factor,rhythm_knots,verified_reference,validate_regions
from scripts.brush_rhythm_dialog import RhythmDialog,compute_preview


def region(a=.2,b=.5,ratio=.3,label='顿笔',key='one'):
    return dict(id=key,start=a,end=b,label=label,ratio=ratio)


@pytest.fixture(scope='module')
def app():
    application=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield application


def test_region_blends_only_slow_down_and_overlap_uses_slowest():
    rows=[region(),region(.4,.7,.5,'收笔','two')]
    q=np.linspace(0,1,10001);factor=rhythm_factor(q,rows)
    assert factor.min()==pytest.approx(.3) and factor.max()==1.
    assert factor[0]==factor[-1]==1.
    assert rhythm_factor([.45],rows)[0]==pytest.approx(.3)
    timing=dict(speed_knots_s_mm_s=[[0,2],[.4,5],[1,3]])
    knots=rhythm_knots(timing,rows);base=np.interp(knots[:,0],[0,.4,1],[2,5,3])
    assert np.all(knots[:,1]<=base+1e-12) and np.all(knots[:,1]>.0)
    assert rhythm_factor([0,.5,1],[region(0,1,.5)])[0]==.5


@pytest.mark.parametrize('row',[region(ratio=1.1),region(ratio=0),region(a=.6,b=.4),region(a=-.1),region(ratio=float('nan'))])
def test_invalid_regions_are_rejected(row):
    with pytest.raises(ValueError):validate_regions([row])


def test_reference_cache_uses_geometry_magnetic_angles_and_settings_contents(monkeypatch):
    import scripts.brush_rhythm as rhythm
    import scripts.brush_speed_adaptation as adaptation
    rhythm._REFERENCE_CACHE.clear();calls=[]
    def fake(recipe,settings):
        calls.append(1);return copy.deepcopy(recipe),None,None,{},dict(iterations=0)
    monkeypatch.setattr(adaptation,'adapt_speed',fake)
    recipe=dict(path=[[0,0],[10,0]],magnetic=[125],angles=[15,-45]);settings=dict(limit=20,table=[66,69,125])
    first=verified_reference(recipe,settings);first[0]['path'][1][0]=99
    assert verified_reference(recipe,settings)[0]['path'][1][0]==10 and len(calls)==1
    for key,value in [('path',[[0,0],[11,0]]),('magnetic',[130]),('angles',[12,-45])]:
        altered=copy.deepcopy(recipe);altered[key]=value;verified_reference(altered,settings)
    changed=copy.deepcopy(settings);changed['table'][0]=65;verified_reference(recipe,changed)
    assert len(calls)==5


def test_rhythm_compiles_slower_without_changing_geometry_magnetic_or_angles(tmp_path):
    m=PathModel();m.segment_magnetic[-1]=125.
    m.add_independent_point([10,10]);m.add_independent_point([20,10])
    _,base,_,_,_=m.compile(reference_only=True)
    before=m.state();m.rhythm_regions=[region(0,1,.5)]
    _,slower,c,_,_=m.compile()
    assert slower.strokes[0].t[-1]>base.strokes[0].t[-1]*1.8
    for column in range(2):assert np.allclose(slower.strokes[0].xy[:,column],np.interp(slower.strokes[0].s,base.strokes[0].s,base.strokes[0].xy[:,column]))
    for column in range(3):assert np.allclose(slower.strokes[0].orientation[:,column],np.interp(slower.strokes[0].s,base.strokes[0].s,base.strokes[0].orientation[:,column]))
    assert np.allclose(c['g_ref_uT'][c['phase']=='measure_00'],125.)
    path=tmp_path/'draft.json';path.write_text(json.dumps(m.state()))
    restored=PathModel.restore(path);assert restored.rhythm_regions==m.rhythm_regions
    assert m.nodes.tolist()==before['nodes_mm']
    folder,summary=m.export(tmp_path/'exports')
    assert summary['execution_scope']=='all_strokes_in_order'
    assert json.loads((folder/'speed_adaptation.json').read_text())['strokes'][1]['rhythm_regions']==m.rhythm_regions


def test_rhythm_crop_keeps_only_intersecting_regions():
    m=PathModel();m.rhythm_regions=[region(0,1,.5)]
    m.set_test_range(3,5);partial=m.execution_model()
    assert partial.rhythm_regions==[region(0,1,.5)]
    m.rhythm_regions=[region(.99,1,.5)]
    assert m.execution_model().rhythm_regions==[]


def test_prepend_independent_stroke_preserves_old_strokes_and_export_order(tmp_path):
    m=PathModel();m.segment_magnetic[:]=125.;first=m.stroke_id
    m.rhythm_regions=[region(.2,.4,.7)]
    old_first=copy.deepcopy(m.state(False));old_count=len(m.nodes)
    m.add_independent_point([10,10]);m.add_independent_point([20,10]);second=m.stroke_id
    old_second=copy.deepcopy(m.state(False))
    m.add_independent_point([-5,10],position='start')
    assert m.pending_node_number()==0 and m.stroke_node_offset(first)==1
    path=tmp_path/'draft.json';path.write_text(json.dumps(m.state()));m=PathModel.restore(path)
    assert m.pending_stroke_position=='start'
    with pytest.raises(ValueError):m.compile_workspace()
    m.add_independent_point([0,10]);front=m.stroke_id
    assert m.stroke_order==[front,first,second]
    assert m.stroke_node_offset()==0 and m.stroke_node_offset(first)==2 and m.stroke_node_offset(second)==old_count+2
    assert m.rhythm_regions==[]
    m.switch_stroke(first);assert m.state(False)==old_first
    m.switch_stroke(second);assert m.state(False)==old_second
    folder,summary=m.export(tmp_path/'exports')
    assert [row['stroke_id'] for row in summary['execution_order']]==[front,first,second]
    assert summary['execution_order'][0]['point_range']==[0,1]
    restored=PathModel.restore(folder/'editor_state.json');assert restored.stroke_order==[front,first,second]


def test_region_gestures_are_lightweight_copyable_and_undoable(app,monkeypatch):
    monkeypatch.setattr(RhythmDialog,'request_preview',lambda self:None)
    m=PathModel();m.segment_magnetic[:]=125.;dialog=RhythmDialog(m,16)
    result=compute_preview(dialog.candidate);dialog.preview_ready(dialog.revision,result)
    dialog.add_region('顿笔');assert dialog.candidate.rhythm_regions[0]['ratio']==.3
    def forbidden(*args,**kwargs):raise AssertionError('planning or disk IO during region gesture')
    with monkeypatch.context() as patch:
        patch.setattr(dialog.candidate,'settings',forbidden);patch.setattr(dialog.candidate,'compile',forbidden);patch.setattr(dialog.candidate,'compile_workspace',forbidden)
        dialog.ratio.setValue(45);dialog.bands[0].setRegion([dialog.length*.6,dialog.length*.7]);dialog.render();dialog.finish_edit()
    assert dialog.candidate.rhythm_regions[0]['ratio']==.45
    assert dialog.candidate.rhythm_regions[0]['start']==pytest.approx(.6)
    x,y=dialog.highlight.getData();assert len(x)>2
    dialog.copy_region();dialog.selection={2,3};dialog.selected_region=None;dialog.paste_region()
    assert len(dialog.candidate.rhythm_regions)==2 and dialog.candidate.rhythm_regions[-1]['ratio']==.45
    dialog.undo();assert len(dialog.candidate.rhythm_regions)==1
    dialog.reset_regions();assert dialog.candidate.rhythm_regions==[]
    dialog.undo();assert len(dialog.candidate.rhythm_regions)==1
    assert m.rhythm_regions==[]
    dialog.reject()


def test_first_stroke_ui_cancel_undo_and_global_labels(app,tmp_path,monkeypatch):
    import scripts.edit_brush_path as ui
    monkeypatch.setattr(ui,'DRAFT',tmp_path/'draft.json')
    win=ui.Editor(PathModel());first=win.model.stroke_id;before=win.model.points().copy()
    win.begin_first_stroke();assert win.insert_mode.currentIndex()==2
    win.insert_x.setValue(-5);win.insert_y.setValue(10);win.insert_coordinate_point()
    assert win.pending_label.toPlainText().startswith('0')
    assert win.model.stroke_node_offset(first)==1
    win.cancel_independent_start();assert win.model.stroke_node_offset()==0
    win.undo();assert win.model.pending_stroke_position=='start' and win.model.pending_point is not None
    win.insert_x.setValue(0);win.insert_coordinate_point()
    assert win.model.stroke_order[0]==win.model.stroke_id
    assert win.table.item(0,0).text()=='0→1'
    win.model.switch_stroke(first);assert np.array_equal(win.model.points(),before)
    win.rebuild_handles();win.refresh()
    assert win.table.item(0,0).text()=='2→3'
    win.close()


def test_background_preview_uses_detached_copy_and_discards_stale_result(app,monkeypatch):
    import threading
    import time
    from PyQt5 import QtTest
    import scripts.brush_rhythm_dialog as ui
    release=threading.Event();started=threading.Event();jobs=[];main_thread=threading.get_ident()
    def compute(model):
        jobs.append((threading.get_ident(),copy.deepcopy(model.rhythm_regions)))
        if len(jobs)==1:
            started.set();release.wait(3)
            return {'error':'stale result'}
        return {'error':'latest result'}
    monkeypatch.setattr(ui,'compute_preview',compute)
    source=PathModel();dialog=RhythmDialog(source,16);dialog.request_preview()
    assert started.wait(2)
    dialog.add_region('收笔');dialog.preview_timer.stop();dialog.request_preview();release.set()
    deadline=time.monotonic()+4
    while time.monotonic()<deadline and ('latest result' not in dialog.error.text() or dialog._worker is not None):
        app.processEvents();QtTest.QTest.qWait(5)
    assert 'latest result' in dialog.error.text() and 'stale result' not in dialog.error.text()
    assert len(jobs)==2 and all(thread_id!=main_thread for thread_id,_ in jobs)
    assert jobs[0][1]==[] and jobs[1][1][0]['label']=='收笔'
    assert source.rhythm_regions==[]
    dialog.reject()
