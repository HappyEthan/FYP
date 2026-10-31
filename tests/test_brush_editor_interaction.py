import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
import pytest
from PyQt5 import QtCore,QtWidgets
from scripts.brush_editor_interaction import SelectionViewBox,selected_in_rect,shifted_speeds
from scripts.brush_path_editor_model import PathModel
import scripts.edit_brush_path as ui


@pytest.fixture(scope='module')
def app():
    application=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield application


def test_rect_selection_and_common_speed_delta():
    assert selected_in_rect([[0,0],[1,2],[3,4]],(.5,2,1,3))=={1}
    values=np.array([2.,19.,10.])
    assert np.allclose(shifted_speeds(values,{0,1},5,20),[3,20,10])
    assert np.allclose(shifted_speeds(values,{0,1},-5,20),[.05,17.05,10])


def test_rectangle_gesture_emits_data_bounds(app):
    view=SelectionViewBox();plot=ui.pg.PlotWidget(viewBox=view);plot.show();app.processEvents()
    events=[];view.rectangleSelected.connect(lambda bounds,add:events.append((bounds,add)))
    class Event:
        def button(self):return QtCore.Qt.LeftButton
        def modifiers(self):return QtCore.Qt.ShiftModifier|QtCore.Qt.ControlModifier
        def buttonDownScenePos(self):return view.mapViewToScene(QtCore.QPointF(1,2))
        def scenePos(self):return view.mapViewToScene(QtCore.QPointF(3,4))
        def isFinish(self):return True
        def accept(self):self.accepted=True
    event=Event();view.mouseDragEvent(event)
    assert event.accepted and events[0][1]
    assert np.allclose(events[0][0],[1,3,2,4])
    plot.close()


def test_group_path_drag_is_lightweight_and_undoable(app,tmp_path,monkeypatch):
    monkeypatch.setattr(ui,'DRAFT',tmp_path/'draft.json')
    model=PathModel();win=ui.Editor(model);before=model.nodes.copy();win.set_path_selection({3,4});win.begin_path_drag(3)
    def forbidden(*args,**kwargs):raise AssertionError('heavy pose/calibration work in drag hot path')
    with monkeypatch.context() as patch:
        patch.setattr(model,'settings',forbidden);patch.setattr(model,'displayed_node_angles',forbidden)
        win.handles[3].setPos(*(before[3]+[.1,.05]));win.draw_path_drag()
    assert np.allclose(model.nodes[[3,4]]-before[[3,4]],[.1,.05])
    assert np.array_equal(model.nodes[:3],before[:3])
    win.drag_finished();win.undo();assert np.allclose(model.nodes,before)
    win.close()


def test_endpoint_only_speed_group_drag_and_table_sync(app,tmp_path,monkeypatch):
    model=PathModel();model.segment_speeds[2]=.8
    dialog=ui.SpeedDialog(model,2)
    assert dialog.table.columnCount()==5
    assert len(dialog.speed_handles)==len(model.nodes)
    assert all(v is None for v in dialog.candidate.segment_speeds)
    before=dialog.node_values.copy();dialog.set_point_selection({3,4});dialog.begin_speed_drag(3)
    def forbidden(*args,**kwargs):raise AssertionError('disk IO in speed drag hot path')
    with monkeypatch.context() as patch:
        patch.setattr(dialog.candidate,'settings',forbidden)
        dialog.speed_handles[3].setPos(dialog.speed_distances[model.indices[3]],before[3]+.1)
        dialog.draw_speed()
    dialog.finish_speed_drag()
    assert np.allclose(dialog.node_values[[3,4]]-before[[3,4]],.1)
    assert dialog.table.item(2,4).text()==dialog.table.item(3,3).text()
    dialog.undo_speed();assert np.allclose(dialog.node_values,before)
    assert model.segment_speeds[2]==.8  # Dialog cancellation leaves caller intact.
    dialog.close()


def test_temporary_test_range_widgets_restore_and_undo(app,tmp_path,monkeypatch):
    monkeypatch.setattr(ui,'DRAFT',tmp_path/'draft.json')
    win=ui.Editor(PathModel());before=win.model.nodes.copy()
    win.set_path_selection({3,4,5});win.test_selection()
    assert win.model.test_node_range()==(3,5)
    assert not win.handles[0].isVisible() and win.handles[3].isVisible()
    assert np.allclose(win.curve.getData()[0],win.model.test_points()[:,0])
    assert '点 3 → 5' in win.test_note.text()
    assert not ui.PathModel.restore(ui.DRAFT).node_enabled[0]
    win.select_path_rect((-1000,1000,-1000,1000))
    assert win.point_selection=={3,4,5}  # Hidden handles cannot join a drag.
    win.restore_all_points();assert win.model.node_enabled.all()
    win.undo();assert win.model.test_node_range()==(3,5)
    win.test_first.setValue(4);win.test_last.setValue(6);win.apply_test_range()
    assert win.model.test_node_range()==(4,6)
    win.table.selectRow(4);win.test_selected_segment()
    assert win.model.test_node_range()==(4,5)
    assert np.array_equal(win.model.nodes,before)
    win.close()


def test_free_point_insert_endpoint_delete_and_undo(app,tmp_path,monkeypatch):
    monkeypatch.setattr(ui,'DRAFT',tmp_path/'draft.json')
    win=ui.Editor(PathModel());old=win.model.nodes.copy();count=len(old)
    win.insert_mode.setCurrentIndex(1)
    win.insert_order.setValue(count);win.insert_x.setValue(old[-1,0]+2);win.insert_y.setValue(old[-1,1])
    win.insert_coordinate_point()
    assert len(win.model.nodes)==count+1
    assert np.allclose(win.model.nodes[-1],old[-1]+[2,0],atol=.0001)
    assert win.point_selection=={count}
    win.delete_selected_points();assert np.allclose(win.model.nodes,old)
    win.set_path_selection({0});win.delete_selected_points()
    assert np.allclose(win.model.nodes,old[1:])
    win.undo();assert np.allclose(win.model.nodes,old)
    win.table.selectRow(len(win.model.nodes)-2);win.delete_point()
    assert np.allclose(win.model.nodes,old[:-1])
    win.undo();assert np.allclose(win.model.nodes,old)
    win.close()


def test_click_insert_uses_plot_coordinates_and_path_order(app,tmp_path,monkeypatch):
    monkeypatch.setattr(ui,'DRAFT',tmp_path/'draft.json')
    win=ui.Editor(PathModel());win.show();app.processEvents()
    win.insert_mode.setCurrentIndex(1)
    win.insert_order.setValue(3);xy=(win.model.nodes[2]+win.model.nodes[3])/2+[.1,.1]
    position=win.path_view.mapViewToScene(QtCore.QPointF(*xy))
    class Event:
        def button(self):return QtCore.Qt.LeftButton
        def scenePos(self):return position
    win.click_insert_button.setChecked(True);win.add_point_at_click(Event())
    assert np.allclose(win.model.nodes[3],xy,atol=.0001)
    assert win.insert_order.value()==4
    count=len(win.model.nodes);win.click_insert_button.setChecked(False);win.add_point_at_click(Event())
    assert len(win.model.nodes)==count
    win.close()


def test_batch_delete_all_rejects_without_partial_changes(app,tmp_path,monkeypatch):
    monkeypatch.setattr(ui,'DRAFT',tmp_path/'draft.json')
    win=ui.Editor(PathModel());before=win.model.state();errors=[]
    monkeypatch.setattr(win,'fail',lambda error:errors.append(str(error)))
    win.set_path_selection(set(range(len(win.model.nodes))))
    win.delete_selected_points()
    assert errors and '至少保留两个' in errors[0]
    assert win.model.state()==before
    win.close()


def test_new_stroke_default_addition_and_switching_undo(app,tmp_path,monkeypatch):
    monkeypatch.setattr(ui,'DRAFT',tmp_path/'draft.json')
    win=ui.Editor(PathModel());original=win.model.points().copy();first=win.model.stroke_id
    assert win.insert_mode.currentIndex()==0 and not win.insert_order.isEnabled()
    win.insert_x.setValue(10);win.insert_y.setValue(10);win.insert_coordinate_point()
    assert win.pending_handle.isVisible() and not win.stroke_selector.isEnabled()
    assert np.array_equal(win.model.points(),original) and len(win.model.other_strokes)==0
    win.pending_handle.setPos(11,10);win.move_pending_point()
    assert PathModel.restore(ui.DRAFT).pending_point==[11.,10.]
    win.insert_x.setValue(20);win.insert_coordinate_point()
    second=win.model.stroke_id
    assert win.stroke_selector.count()==2 and not win.pending_handle.isVisible()
    assert np.array_equal(win.model.nodes,[[11.,10.],[20.,10.]])
    assert len(win.other_stroke_curves)==1
    assert np.array_equal(np.column_stack(win.other_stroke_curves[0].getData()),original)
    offset=len(win.model.other_strokes[0]['nodes_mm'])
    assert win.insert_mode.currentIndex()==1 and win.insert_order.value()==offset+2
    assert win.table.item(0,0).text()==f'{offset}→{offset+1}'
    assert win.test_first.value()==offset and win.test_last.value()==offset+1
    dialog=ui.SpeedDialog(win.model)
    assert dialog.table.item(0,1).text()==f'{offset} → {offset+1}'
    dialog.close()
    win.insert_x.setValue(22);win.insert_y.setValue(11);win.insert_coordinate_point()
    assert np.array_equal(win.model.nodes,[[11.,10.],[20.,10.],[22.,11.]])
    win.stroke_selector.setCurrentIndex(win.stroke_selector.findData(first))
    assert np.array_equal(win.model.points(),original)
    win.stroke_selector.setCurrentIndex(win.stroke_selector.findData(second))
    assert np.array_equal(win.model.nodes[-1],[22.,11.])
    win.undo();assert win.model.stroke_id==first
    win.undo();assert win.model.stroke_id==second
    win.close()


def test_independent_point_cancel_restore_and_click_mode(app,tmp_path,monkeypatch):
    monkeypatch.setattr(ui,'DRAFT',tmp_path/'draft.json')
    win=ui.Editor(PathModel());win.show();app.processEvents();before=win.model.points().copy()
    win.begin_independent_stroke()
    class Event:
        def button(self):return QtCore.Qt.LeftButton
        def scenePos(self):return win.path_view.mapViewToScene(QtCore.QPointF(10,10))
        def isAccepted(self):return False
    win.add_point_at_click(Event())
    assert win.model.pending_point==[10.,10.]
    win.cancel_independent_start();assert win.model.pending_point is None
    assert np.array_equal(win.model.points(),before)
    win.undo();assert win.pending_handle.isVisible() and win.model.pending_point==[10.,10.]
    win.close()
    restored=ui.Editor(PathModel.restore(ui.DRAFT))
    assert restored.pending_handle.isVisible() and not restored.insert_mode.isEnabled()
    assert restored.model.pending_point==[10.,10.]
    restored.close()


def test_workspace_preflight_draws_disconnected_strokes_and_restores_export(app,tmp_path,monkeypatch):
    monkeypatch.setattr(ui,'DRAFT',tmp_path/'draft.json')
    model=PathModel();first=model.stroke_id;model.segment_magnetic[-1]=125.
    model.add_independent_point([10,10]);model.add_independent_point([20,10])
    win=ui.Editor(model);errors=[];monkeypatch.setattr(win,'fail',lambda e:errors.append(str(e)))
    win.preflight()
    assert not errors and '全部 2 笔预检通过' in win.status.text()
    x,y=win.compiled.getData();assert np.isnan(x).sum()==2 and np.isnan(y).sum()==2
    offset=win.model.stroke_node_offset()
    win.test_first.setValue(offset);win.test_last.setValue(offset+1);win.apply_test_range()
    assert win.model.test_node_range()==(0,1)
    folder,_=win.model.export(tmp_path/'exports')
    monkeypatch.setattr(ui.W.QFileDialog,'getOpenFileName',lambda *args:(str(folder/'recipe.json'),''))
    win.open_recipe()
    assert win.stroke_selector.count()==2 and first in win.model.stroke_order
    win.close()
