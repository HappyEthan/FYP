#!/usr/bin/env python3
"""Native XY path editor. Editing and preflight never connect to hardware."""
import copy
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
if os.environ.get('WAYLAND_DISPLAY') and not os.environ.get('QT_QPA_PLATFORM'):
    os.environ['QT_QPA_PLATFORM']='wayland'
from PyQt5 import QtCore,QtGui,QtWidgets as W
import pyqtgraph as pg
from scripts.brush_path_editor_model import PathModel,arc
from scripts.brush_editor_interaction import SelectionViewBox,DraggablePoint,selected_in_rect,shifted_speeds
from scripts.brush_rhythm_dialog import RhythmDialog
from scripts.brush_path_editor_ui import EditorLayout
from brushbot.experiments.archive import DEFAULT_ARCHIVE_ROOT, ExperimentArchive
from brushbot.experiments.reproduce import archive_path, read_json as read_data_json, verify
DRAFT=ROOT/'outputs/brush_path_editor/draft_v3.json'

class SpeedDialog(W.QDialog):
    def __init__(self,model,segment=0,parent=None):
        super().__init__(parent);self.candidate=copy.deepcopy(model);self.candidate.use_endpoint_speeds()
        self.loading=False;self.point_selection=set();self.speed_handles=[];self._speed_drag=None
        self.speed_distances=arc(self.candidate.points());self.speed_cap=self.candidate.settings()['feedforward.json']['speed_mm_s']
        self.speed_history=[self.candidate.node_speeds.copy()]
        self.setWindowTitle('精确速度设置');self.resize(1100,760)
        layout=W.QVBoxLayout(self)
        note=W.QLabel('每行只调段首和段尾速度，段内平滑过渡；相邻段共用端点。蓝色继承，橙色手动设置。\nShift＋拖框选择多个圆点，按住Ctrl追加框选；拖动选中点可整体上下调速，横轴绑定路径端点。')
        note.setWordWrap(True);layout.addWidget(note)
        profile=self.candidate.settings()['feedforward.json'];profile_note=W.QLabel(f'允许速度：大于0至{self.speed_cap:g} mm/s。'+(' 高速试验：磁响应映射仍使用10 mm/s标定数据，20 mm/s未重新标定。' if profile.get('high_speed_trial') else ''))
        profile_note.setWordWrap(True);layout.addWidget(profile_note)
        self.table=W.QTableWidget(0,5);self.table.setHorizontalHeaderLabels(['段','节点','段长 mm','段首 mm/s','段尾 mm/s'])
        self.table.horizontalHeader().setSectionResizeMode(W.QHeaderView.Stretch);self.table.setSelectionBehavior(W.QAbstractItemView.SelectRows);self.table.setSelectionMode(W.QAbstractItemView.SingleSelection)
        self.table.cellChanged.connect(self.cell_changed);self.table.itemSelectionChanged.connect(self.selection_changed);layout.addWidget(self.table,1)
        tools=W.QHBoxLayout();layout.addLayout(tools)
        self.box_button=W.QPushButton('框选速度端点');self.box_button.setCheckable(True);tools.addWidget(self.box_button)
        clear=W.QPushButton('取消框选');clear.clicked.connect(lambda:self.set_point_selection(set()));tools.addWidget(clear)
        tools.addWidget(W.QLabel('Δ速度 mm/s'));self.delta_speed=W.QDoubleSpinBox();self.delta_speed.setRange(-20,20);self.delta_speed.setDecimals(2);tools.addWidget(self.delta_speed)
        translate=W.QPushButton('平移选中点');translate.clicked.connect(lambda:self.translate_selection(self.delta_speed.value()));tools.addWidget(translate)
        for label,callback in [('撤销调速',self.undo_speed),('选中段恢复继承',self.inherit),('自动适速预览',self.preview)]:
            button=W.QPushButton(label);button.clicked.connect(callback);tools.addWidget(button)
        self.view=SelectionViewBox();self.view.rectangleSelected.connect(self.select_rect);self.box_button.toggled.connect(lambda value:setattr(self.view,'box_select',value))
        self.plot=pg.PlotWidget(viewBox=self.view,background='#faf9f4');self.plot.setMinimumHeight(240);self.plot.setLabel('bottom','沿路径距离',units='mm');self.plot.setLabel('left','速度',units='mm/s');self.plot.addLegend();self.plot.showGrid(x=True,y=True,alpha=.2)
        self.request_curve=self.plot.plot(pen=pg.mkPen('#1473c9',width=2),name='请求速度');self.actual_curve=self.plot.plot(pen=pg.mkPen('#239563',width=2),name='预检后规划速度');self.selected_curve=self.plot.plot(pen=pg.mkPen('#e39b24',width=4),name='选中段请求')
        layout.addWidget(self.plot,1);self.error=W.QLabel();self.error.setWordWrap(True);layout.addWidget(self.error)
        box=W.QDialogButtonBox(W.QDialogButtonBox.Save|W.QDialogButtonBox.Cancel);box.button(W.QDialogButtonBox.Save).setText('保存首尾速度');box.button(W.QDialogButtonBox.Cancel).setText('取消');box.accepted.connect(self.save);box.rejected.connect(self.reject);layout.addWidget(box)
        self.speed_timer=QtCore.QTimer(self);self.speed_timer.setSingleShot(True);self.speed_timer.setInterval(25);self.speed_timer.timeout.connect(self.draw_speed)
        self.refresh();self.table.selectRow(max(0,min(segment,len(model.nodes)-2)))
    def refresh(self):
        self.loading=True;row=self.table.currentRow();m=self.candidate;self.table.setRowCount(len(m.nodes)-1)
        offset=m.stroke_node_offset()
        for k in range(len(m.nodes)-1):
            for col,value in enumerate([k+1,f'{offset+k} → {offset+k+1}',f'{self.speed_distances[m.indices[k+1]]-self.speed_distances[m.indices[k]]:.3f}','','']):
                item=W.QTableWidgetItem(str(value))
                if col<3:item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
                self.table.setItem(k,col,item)
        self.loading=False
        if row>=0:self.table.selectRow(min(row,self.table.rowCount()-1))
        if len(self.speed_handles)!=len(m.nodes):
            for handle in self.speed_handles:self.plot.removeItem(handle)
            self.speed_handles=[]
            self.loading=True
            for k in range(len(m.nodes)):
                handle=DraggablePoint(pos=(0,0),size=13,movable=True,symbol='o',brush='#f6c65a',pen='#9a5c00');handle.setZValue(20)
                handle.dragStarted.connect(lambda item,k=k:self.begin_speed_drag(k));handle.pointClicked.connect(lambda item,add,k=k:self.click_point(k,add));handle.sigPositionChanged.connect(lambda item,k=k:self.drag_speed(k,item));handle.sigPositionChangeFinished.connect(self.finish_speed_drag)
                self.plot.addItem(handle);self.speed_handles.append(handle)
                label=pg.TextItem(str(offset+k),color='#38404a',anchor=(.5,1.4));label.setParentItem(handle)
            self.loading=False
        self.draw_speed()
    def draw_speed(self):
        m=self.candidate;self.curve_knots=m.speed_curve(self.speed_cap,self.speed_distances)
        self.node_values=np.interp(self.speed_distances[m.indices]/self.speed_distances[-1],self.curve_knots[:,0],self.curve_knots[:,1])
        self.loading=True
        for k,handle in enumerate(self.speed_handles):handle.setPos(float(self.speed_distances[m.indices[k]]),float(self.node_values[k]))
        for k in range(len(m.nodes)-1):
            for col,node in [(3,k),(4,k+1)]:
                item=self.table.item(k,col);item.setText(f'{self.node_values[node]:.3f}');item.setForeground(QtGui.QColor('#1473c9' if m.node_speeds[node] is None else '#b96a00'))
        self.loading=False
        self.request_curve.setData(self.curve_knots[:,0]*self.speed_distances[-1],self.curve_knots[:,1]);self.actual_curve.setData([],[]);self.paint_selection();self.selection_changed()
    def paint_selection(self):
        for k,handle in enumerate(self.speed_handles):
            handle.setVisible(bool(self.candidate.node_enabled[k]))
            handle.setBrush('#60a5fa' if k in self.point_selection else '#f6c65a');handle.setPen(pg.mkPen('#1d4ed8' if k in self.point_selection else '#9a5c00',width=2 if k in self.point_selection else 1))
    def set_point_selection(self,indices):
        self.point_selection=set(indices);self.paint_selection();self.error.setText(f'已选中{len(self.point_selection)}个速度端点，可拖动或输入Δ速度整体平移。')
    def select_rect(self,bounds,add=False):
        points=np.column_stack([self.speed_distances[self.candidate.indices],self.node_values]);found=selected_in_rect(points,bounds)&set(np.flatnonzero(self.candidate.node_enabled));self.set_point_selection(self.point_selection|found if add else found)
    def click_point(self,k,add=False):
        self.set_point_selection((self.point_selection^{k}) if add else (self.point_selection if k in self.point_selection else {k}))
    def begin_speed_drag(self,k):
        if k not in self.point_selection:self.set_point_selection({k})
        self._speed_drag=dict(anchor=k,values=self.node_values.copy(),indices=set(self.point_selection))
    def drag_speed(self,k,handle):
        if self.loading:return
        if self._speed_drag is None:self.begin_speed_drag(k)
        context=self._speed_drag;values=shifted_speeds(context['values'],context['indices'],handle.pos().y()-context['values'][k],self.speed_cap)
        for node in context['indices']:self.candidate.node_speeds[node]=float(values[node])
        self.loading=True
        for node in context['indices']:self.speed_handles[node].setPos(float(self.speed_distances[self.candidate.indices[node]]),float(values[node]))
        self.loading=False
        if not self.speed_timer.isActive():self.speed_timer.start()
    def finish_speed_drag(self,*args):
        self.speed_timer.stop();self._speed_drag=None;self.draw_speed();self.remember_speed();self.error.setText('速度端点已修改；绿色规划曲线需重新预览。')
    def translate_selection(self,delta):
        if not self.point_selection:self.error.setText('先框选需要平移的速度端点。');return
        values=shifted_speeds(self.node_values,self.point_selection,delta,self.speed_cap)
        for k in self.point_selection:self.candidate.node_speeds[k]=float(values[k])
        self.draw_speed();self.remember_speed()
    def remember_speed(self):
        values=self.candidate.node_speeds.copy()
        if not np.array_equal(values,self.speed_history[-1]):self.speed_history.append(values)
        self.speed_history=self.speed_history[-100:]
    def undo_speed(self):
        if len(self.speed_history)>1:self.speed_history.pop();self.candidate.node_speeds=self.speed_history[-1].copy();self.draw_speed()
    def selection_changed(self):
        if self.loading:return
        row=self.table.currentRow()
        if row<0 or not hasattr(self,'curve_knots'):return
        ends=self.speed_distances[self.candidate.indices[row:row+2]];q0,q1=ends/self.speed_distances[-1];knots=self.curve_knots
        q=np.unique(np.r_[q0,knots[(knots[:,0]>q0)&(knots[:,0]<q1),0],q1]);self.selected_curve.setData(q*self.speed_distances[-1],np.interp(q,knots[:,0],knots[:,1]))
    def cell_changed(self,row,column):
        if self.loading or column<3:return
        before=self.candidate.node_speeds.copy()
        try:
            text=self.table.item(row,column).text().strip();value=None if text in ('','继承') else float(text)
            if value is not None and (not np.isfinite(value) or not 0<value<=self.speed_cap):raise ValueError(f'速度须大于0且不超过{self.speed_cap:g} mm/s')
            self.candidate.node_speeds[row+(column==4)]=value;self.draw_speed();self.remember_speed()
        except Exception as exc:self.candidate.node_speeds=before;self.draw_speed();self.error.setText('未修改：'+str(exc))
    def inherit(self):
        row=self.table.currentRow()
        if row>=0:self.candidate.node_speeds[row:row+2]=None;self.draw_speed();self.remember_speed()
    def preview(self):
        self.finish_speed_drag();self.error.setText('正在自动适速预检……');W.QApplication.processEvents()
        try:
            _,plan,_,_,_=self.candidate.compile();st=plan.strokes[0];speed=np.linalg.norm(np.diff(st.xy,axis=0),axis=1)*1000/np.diff(st.t)
            first,last=self.candidate.test_node_range();start,end=self.speed_distances[self.candidate.indices[[first,last]]]
            distance=start+(st.s[:-1]+st.s[1:])/2*(end-start)
            self.actual_curve.setData(distance,speed);self.error.setText(f'预检通过：书写{st.t[-1]:.2f}秒，局部适速{self.candidate.last_speed_adaptation["iterations"]}次。绿色为规划值，尚未执行。')
        except Exception as exc:self.actual_curve.setData([],[]);self.error.setText('预检未通过：'+str(exc))
    def save(self):
        try:self.finish_speed_drag();self.candidate.recipe();self.accept()
        except Exception as exc:self.error.setText('未保存：'+str(exc))

class Editor(EditorLayout,W.QMainWindow):
    def __init__(self,model=None):
        super().__init__();self.model=model or PathModel();self.handles=[];self.history=[];self.loading=False
        self.point_selection=set();self._path_drag_context=None
        self.path_timer=QtCore.QTimer(self);self.path_timer.setSingleShot(True);self.path_timer.setInterval(20);self.path_timer.timeout.connect(self.draw_path_drag)
        self.build_ui()
        self.archive=ExperimentArchive()
        self.archive.cleanup_stale()
        self.install_model(self.model)

    def message(self,text):
        self.status.setText(text.replace('\n','  ·  '));self.status.setToolTip(text)
    def fail(self,exc):
        self._edit_failed=True;self.message('未通过：'+str(exc));W.QMessageBox.warning(self,'路径未通过',str(exc))
    def install_model(self,model,*,preserve_parameters=False):
        self.click_insert_button.setChecked(False);self.add_panel.hide();self.inspector.show()
        if not preserve_parameters:model.use_endpoint_speeds()
        self.model=model;self.initial_state=self.snapshot();self.history=[self.snapshot()];self.rebuild_handles();self.refresh();self.full_view()
        self.message('拖动节点编辑路径，点击线段调整磁目标和笔杆角度。')
        self.status.setToolTip('当前来源：'+str(model.folder))
    def rebuild_handles(self):
        self.point_selection=set();self._path_drag_context=None
        for h in self.handles:self.plot.removeItem(h)
        self.handles=[];self.loading=True
        for k,p in enumerate(self.model.nodes):
            h=DraggablePoint(pos=tuple(p),size=13,movable=True,symbol='o',pen='#9a5c00',brush='#f6c65a')
            h.dragStarted.connect(lambda item,k=k:self.begin_path_drag(k))
            h.pointClicked.connect(lambda item,add,k=k:self.click_path_point(k,add))
            h.sigPositionChanged.connect(lambda item,k=k:self.drag(k,item))
            h.sigPositionChangeFinished.connect(self.drag_finished)
            self.plot.addItem(h);self.handles.append(h)
            label=pg.TextItem(str(self.model.stroke_node_offset()+k),color='#38404a',anchor=(.5,1.4));label.setParentItem(h)
        self.loading=False
    def refresh(self,sync_handles=False):
        self.refresh_strokes()
        variation=self.model.writing_variation
        self.variation_status.setText('随机扰动：'+variation['profile']['name'] if variation['enabled'] else '随机扰动：关闭')
        self.variation_status.setToolTip('高级设置 → 书写随机扰动；关闭后恢复标准执行。')
        self.speed_status.setStyleSheet('color:#8a5b00')
        self.speed_status.setText('自动适速已启用：预检或导出时，按当前XY、磁目标和笔杆角度重算局部限速。')
        p=self.model.points();self.draw_test_path(p)
        first,last=self.model.test_node_range()
        offset=self.model.stroke_node_offset()
        self.insert_order.setRange(offset,offset+len(self.model.nodes))
        self.insert_order.setSuffix(f' / {offset+len(self.model.nodes)}（末端追加）')
        for spin,value in [(self.test_first,first),(self.test_last,last)]:spin.setRange(offset,offset+len(self.model.nodes)-1);spin.setValue(offset+value)
        self.test_note.setText(f'当前笔画有效点 {offset+first} → {offset+last}；隐藏 {len(self.model.nodes)-(last-first+1)} 个点。导出执行所有笔画各自的有效区间，按点序号递增，笔间悬空转移。')
        self.compiled.setData([],[])
        selected=self.table.currentRow();self.table.blockSignals(True);self.table.setRowCount(len(self.model.nodes)-1)
        inherited=self.model.inherited_segment_values();angles=self.model.displayed_node_angles()
        for k,(a,b) in enumerate(zip(self.model.indices[:-1],self.model.indices[1:])):
            delta=self.model.nodes[k+1]-self.model.nodes[k]
            values=[f'{offset+k}→{offset+k+1}',f'{arc(p[a:b+1])[-1]:.3f}',f'{np.rad2deg(np.arctan2(delta[1],delta[0])):.2f}',
                    f'{self.model.nodes[k+1,0]:.3f}',f'{self.model.nodes[k+1,1]:.3f}',
                    f'{inherited[k,1]:.2f}' if self.model.segment_magnetic[k] is None else f'{self.model.segment_magnetic[k]:.2f}']
            for node,col in [(k,0),(k+1,0),(k,1),(k+1,1)]:
                v=self.model.node_angles[node,col]
                values.append(f'{angles[node,col] if v is None else v:.2f}')
            for c,v in enumerate(values):
                item=W.QTableWidgetItem(v)
                if c==5:
                    original=self.model.segment_magnetic[k] is None
                    item.setForeground(QtGui.QColor('#1473c9' if original else '#b96a00'))
                    item.setToolTip(('原曲线中点显示值，尚未覆盖原曲线。' if original else '整段控制目标严格使用填写值，不混入原曲线；名义Z另行平滑，实际响应由反馈调节。')+f'\n原曲线：起点 {inherited[k,0]:.2f} / 中点 {inherited[k,1]:.2f} / 终点 {inherited[k,2]:.2f} μT。\n留空恢复原曲线；数值可保存，但低于标定范围禁止执行。')
                if c>=6:
                    node=k+(c in (7,9));anglecol=0 if c in (6,7) else 1
                    item.setForeground(QtGui.QColor('#1473c9' if self.model.node_angles[node,anglecol] is None else '#b96a00'))
                    item.setToolTip('蓝色为继承当前方案的参考值，橙色为手动设置。留空恢复继承；相邻段共用节点。倾角偏离竖直，朝向右0°、上90°、下−90°。')
                if c==0:item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
                if not first<=k<last:
                    item.setBackground(QtGui.QColor('#eeeeee'));item.setForeground(QtGui.QColor('#999999'))
                    item.setToolTip('本次隐藏，不参与预检、导出和试写；数值保留。')
                self.table.setItem(k,c,item)
        selected=max(0,min(selected,len(self.model.nodes)-2))
        self.table.selectRow(selected)
        self.table.blockSignals(False)
        self.segment_selector.blockSignals(True);self.segment_selector.clear()
        for k in range(len(self.model.nodes)-1):self.segment_selector.addItem(f'{offset+k} → {offset+k+1}')
        self.segment_selector.setCurrentIndex(selected);self.segment_selector.blockSignals(False)
        if sync_handles:
            self.loading=True
            for h,position in zip(self.handles,self.model.nodes):h.setPos(*position)
            self.loading=False
        self.selection_changed();self.paint_path_selection()
    def refresh_strokes(self):
        self.stroke_selector.blockSignals(True);self.stroke_selector.clear()
        for key,name in self.model.stroke_entries():self.stroke_selector.addItem(f'{name}（起点 {self.model.stroke_node_offset(key)}）',key)
        self.stroke_selector.setCurrentIndex(self.stroke_selector.findData(self.model.stroke_id));self.stroke_selector.blockSignals(False)
        for curve in self.other_stroke_curves:self.plot.removeItem(curve)
        for label in self.other_stroke_labels:self.plot.removeItem(label)
        self.other_stroke_curves=[];self.other_stroke_labels=[]
        for state in self.model.other_strokes:
            other=PathModel.from_state(state);p=other.points()
            curve=self.plot.plot(p[:,0],p[:,1],pen=pg.mkPen('#a78bba',width=2,style=QtCore.Qt.DashLine))
            self.other_stroke_curves.append(curve)
            offset=self.model.stroke_node_offset(other.stroke_id)
            for k,xy in enumerate(other.nodes):
                label=pg.TextItem(str(offset+k),color='#9475aa',anchor=(.5,1.4));label.setPos(*xy)
                self.plot.addItem(label);self.other_stroke_labels.append(label)
        self.loading=True
        self.pending_handle.setVisible(self.model.pending_point is not None)
        if self.model.pending_point is not None:
            self.pending_handle.setPos(*self.model.pending_point);self.pending_label.setText(f'{self.model.pending_node_number()}（新笔画起点）')
            self.insert_mode.setCurrentIndex(2 if self.model.pending_stroke_position=='start' else 0)
        self.loading=False
        self.stroke_note.setText(f'共 {len(self.model.stroke_order)} 笔 · 当前 {len(self.model.nodes)} 个节点'+(' · 新笔画待完成' if self.model.pending_point is not None else ''))
        self.stroke_note.setToolTip('蓝色为当前笔画，紫色虚线为其他笔画；按点编号顺序试写，笔间抬笔转移。')
        ranges=[]
        for key,name in self.model.stroke_entries():
            other=self.model if key==self.model.stroke_id else PathModel.from_state(next(s for s in self.model.other_strokes if s['stroke_id']==key))
            first,last=other.test_node_range();offset=self.model.stroke_node_offset(key)
            ranges.append(f'{name}：点 {offset+first} → {offset+last}')
        self.execution_ranges.setText('\n'.join(ranges))
        self.update_insert_mode()
    def update_insert_mode(self):
        independent=self.insert_mode.currentIndex()!=1 or self.model.pending_point is not None
        self.insert_order.setEnabled(not independent);self.insert_order_label.setEnabled(not independent)
        self.insert_mode.setEnabled(self.model.pending_point is None)
        self.stroke_selector.setEnabled(self.model.pending_point is None)
        self.cancel_start_button.setEnabled(self.model.pending_point is not None)
        self.cancel_start_button.setVisible(self.model.pending_point is not None)
        self.insert_order.setVisible(not independent);self.insert_order_label.setVisible(not independent)
        self.add_panel.setTitle('添加点 · '+self.insert_mode.currentText())
        if self.model.pending_point is not None:self.reveal_add_panel()
        self.first_stroke_button.setEnabled(self.model.pending_point is None)
        self.new_stroke_button.setEnabled(self.model.pending_point is None)
    def begin_independent_stroke(self):
        self.insert_mode.setCurrentIndex(0);self.reveal_add_panel();self.click_insert_button.setChecked(True)
        self.message('已有独立起点，请点击第二个点完成新笔画；也可取消独立起点重新放置。' if self.model.pending_point is not None else '在图中空白处点击第一个点，再点击第二个点生成独立笔画；也可以填写X/Y后按坐标添加。与原笔画之间不连线。')
    def begin_first_stroke(self):
        self.insert_mode.setCurrentIndex(2);self.reveal_add_panel();self.click_insert_button.setChecked(True)
        self.message('在空白处添加两个点，组成排在所有旧笔画之前的新首笔；新笔从0编号，原笔画坐标和参数保留。')
    def cancel_independent_start(self):
        if self.model.pending_point is None:return
        self.model.pending_point=None;self.rebuild_handles();self.refresh();self.remember();self.message('已取消独立起点；已有笔画和编号保留，可撤销。')
    def move_pending_point(self,*args):
        if self.loading or self.model.pending_point is None:return
        self.model.pending_point=[self.pending_handle.pos().x(),self.pending_handle.pos().y()]
        self.remember();self.message('独立起点已移动并保存；添加第二个点形成新笔画。')
    def switch_stroke(self,index):
        if index<0:return
        key=self.stroke_selector.itemData(index)
        if key==self.model.stroke_id:return
        before=self.snapshot()
        try:
            self.model.switch_stroke(key);self.rebuild_handles();self.refresh(True);self.insert_order.setValue(self.model.stroke_node_offset()+len(self.model.nodes));self.remember()
            self.message(f'已切换编辑「{self.model.stroke_name}」；各笔参数独立保存，试写仍按序号从第一笔开始。')
        except Exception as exc:self.restore_snapshot(before);self.refresh();self.fail(exc)
    def paint_path_selection(self):
        for k,handle in enumerate(self.handles):
            handle.setVisible(bool(self.model.node_enabled[k]))
            handle.setBrush('#60a5fa' if k in self.point_selection else '#f6c65a');handle.setPen(pg.mkPen('#1d4ed8' if k in self.point_selection else '#9a5c00',width=2 if k in self.point_selection else 1))
    def draw_test_path(self,p):
        first,last=self.model.test_node_range();active=p[self.model.indices[first]:self.model.indices[last]+1]
        self.curve.setData(active[:,0],active[:,1]);self.hidden_curve.setData(p[:,0],p[:,1]);self.hidden_curve.setVisible(not self.model.node_enabled.all())
    def change_test_range(self,first,last):
        try:
            self.model.set_test_range(first,last);self.point_selection=set()
            offset=self.model.stroke_node_offset()
            self.refresh();self.remember();self.message(f'当前笔画执行点 {offset+first} → {offset+last}，本笔其他点暂时隐藏；其他笔画保持各自范围。请重新预检、导出。')
        except Exception as exc:self.fail(exc)
    def apply_test_range(self):
        offset=self.model.stroke_node_offset();self.change_test_range(self.test_first.value()-offset,self.test_last.value()-offset)
    def test_selection(self):
        if len(self.point_selection)<2:self.message('先框选至少两个点；将测试最小编号至最大编号之间的完整连续区间。');return
        self.change_test_range(min(self.point_selection),max(self.point_selection))
    def test_selected_segment(self):
        row=self.table.currentRow()
        if row<0:self.message('先在表格中选择要测试的一段。');return
        self.change_test_range(row,row+1)
    def hide_selected_points(self):
        if not self.point_selection:self.message('先点击或框选需要隐藏的点。');return
        try:
            self.model.hide_nodes(self.point_selection);self.point_selection=set()
            self.refresh();self.remember();self.message('选中点已暂时隐藏，不参与本次试写；可恢复全部点或撤销。')
        except Exception as exc:self.fail(exc)
    def restore_all_points(self):self.change_test_range(0,len(self.model.nodes)-1)
    def set_path_selection(self,indices):
        self.point_selection=set(indices);self.paint_path_selection();self.selection_changed()
        self.message(f'已选中 {len(self.point_selection)} 个节点；可拖动移动，Delete 删除。' if self.point_selection else '选择已清除。')
    def select_path_rect(self,bounds,add=False):
        found=selected_in_rect(self.model.nodes,bounds)&set(np.flatnonzero(self.model.node_enabled));self.set_path_selection(self.point_selection|found if add else found)
    def click_path_point(self,k,add=False):
        self.table.blockSignals(True);self.table.selectRow(min(k,len(self.model.nodes)-2));self.table.blockSignals(False)
        self.set_path_selection((self.point_selection^{k}) if add else (self.point_selection if k in self.point_selection else {k}))
        self.insert_order.setValue(self.model.stroke_node_offset()+k+1)
        self.insert_x.setValue(float(self.model.nodes[k,0]));self.insert_y.setValue(float(self.model.nodes[k,1]))
    def begin_path_drag(self,k):
        if k not in self.point_selection:self.set_path_selection({k})
        self._path_drag_context=dict(anchor=k,nodes=self.model.nodes.copy(),indices=sorted(self.point_selection))
    def drag(self,k,item):
        if self.loading:return
        if self._path_drag_context is None:self.begin_path_drag(k)
        context=self._path_drag_context;nodes=context['nodes'].copy();delta=np.array([item.pos().x(),item.pos().y()])-nodes[k]
        nodes[context['indices']]+=delta;before=self.model.nodes;self.model.nodes=nodes
        try:self.model.validate()
        except ValueError:self.model.nodes=before
        if not self.path_timer.isActive():self.path_timer.start()
    def draw_path_drag(self):
        p=self.model.points();self.draw_test_path(p);self.compiled.setData([],[])
        self.loading=True
        for handle,position in zip(self.handles,self.model.nodes):handle.setPos(*position)
        self.loading=False
        self.table.blockSignals(True)
        for k,(a,b) in enumerate(zip(self.model.indices[:-1],self.model.indices[1:])):
            delta=self.model.nodes[k+1]-self.model.nodes[k]
            for column,value in [(1,f'{arc(p[a:b+1])[-1]:.3f}'),(2,f'{np.rad2deg(np.arctan2(delta[1],delta[0])):.2f}'),(3,f'{self.model.nodes[k+1,0]:.3f}'),(4,f'{self.model.nodes[k+1,1]:.3f}')]:self.table.item(k,column).setText(value)
        self.table.blockSignals(False)
        self.selection_changed();self.speed_status.setText('拖动预览中；松开后刷新姿态和磁目标。执行前将重新自动适速。')
    def drag_finished(self,*args):
        self.path_timer.stop();self._path_drag_context=None;self.refresh(True);self.remember();self.message('路径已修改并保存；请自动适速预检后重新导出。')
    def translate_path_selection(self,delta):
        if not self.point_selection:self.message('先框选需要平移的路径点。');return
        before=self.model.nodes.copy();self.model.nodes[sorted(self.point_selection)]+=np.asarray(delta,float)
        try:self.model.validate()
        except ValueError as exc:self.model.nodes=before;self.message('未平移：'+str(exc));return
        self.refresh(True);self.remember();self.message('选中路径点已整体平移，可撤销。')
    def snapshot(self):
        return copy.deepcopy(self.model.__dict__)
    def restore_snapshot(self,state):
        self.model.__dict__=copy.deepcopy(state)

    def remember(self):
        state=self.snapshot()
        if json.dumps(self.model.state(),sort_keys=True)!=self._state_json(self.history[-1]):self.history.append(state)
        self.history=self.history[-100:];self.autosave()
    def _state_json(self,state):
        model=PathModel.__new__(PathModel);model.__dict__=state
        return json.dumps(model.state(),sort_keys=True)
    def autosave(self):
        DRAFT.parent.mkdir(parents=True,exist_ok=True);tmp=DRAFT.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.model.state(),ensure_ascii=False,indent=2)+'\n');tmp.replace(DRAFT)
        self.save_status.setText('已自动保存')
    def cell_changed(self,row,column):
        if column==0:return
        before=self.snapshot()
        try:
            text=self.table.item(row,column).text().strip()
            if column in (5,6,7,8,9) and text in ('','继承'):value=None
            else:
                value=float(text)
                if not np.isfinite(value):raise ValueError('数值必须有限')
            if column in (1,2):
                d=self.model.nodes[row+1]-self.model.nodes[row]
                p=self.model.points();a,b=self.model.indices[row:row+2];length=arc(p[a:b+1])[-1]
                angle=float(np.rad2deg(np.arctan2(d[1],d[0])))
                self.model.set_segment(row,np.linalg.norm(d)*(value/length) if column==1 else np.linalg.norm(d), value if column==2 else angle)
            elif column==5:
                if value is not None:
                    amplitudes=self.model.settings()['feedforward.json']['amplitude_uT']
                    if not 0<=value<=amplitudes[-1]:raise ValueError(f'磁目标输入范围 0–{amplitudes[-1]:.2f} μT')
                self.model.segment_magnetic[row]=value
            elif column>=6:
                node=row+(column in (7,9));anglecol=0 if column in (6,7) else 1
                if value is not None and anglecol==0 and not 0<value<30:raise ValueError('倾角必须大于0°且小于30°')
                self.model.node_angles[node,anglecol]=value
            else:self.model.nodes[row+1,column-3]=value
            self.model.validate();self.refresh(sync_handles=True);self.remember();self.message('已修改；XY、磁目标或笔杆角度变化可能使原速度超限，请重新预检。')
        except Exception as exc:self.restore_snapshot(before);self.refresh(sync_handles=True);self.fail(exc)
    def selection_changed(self):
        k=self.table.currentRow()
        if k<0 or k>=len(self.model.nodes)-1:return
        p=self.model.points();a,b=self.model.indices[k:k+2];seg=p[a:b+1];first,last=self.model.test_node_range()
        self.selected.setData(seg[:,0] if first<=k<last and not self.point_selection else [],seg[:,1] if first<=k<last and not self.point_selection else [])
        offset=self.model.stroke_node_offset()
        self.detail.setText('Shift 拖框多选 · Delete 删除节点' if self.point_selection else f'节点 {offset+k} → {offset+k+1} · '+('参与试写' if first<=k<last else '本次不执行'))
        self.sync_inspector()
    def undo(self):
        if len(self.history)>1:
            self.history.pop();self.restore_snapshot(self.history[-1]);self.rebuild_handles();self.refresh(True);self.autosave();self.message('已撤销。')
    def edit_orientation(self):
        self.choose_segment(max(0,self.table.currentRow()))
        self.segment_fields[6].setFocus()
    def edit_precise_speed(self):
        dialog=SpeedDialog(self.model,max(0,self.table.currentRow()),self)
        if dialog.exec_()!=W.QDialog.Accepted:return
        self.model.use_endpoint_speeds();self.model.node_speeds=dialog.candidate.node_speeds.copy()
        self.refresh();self.remember();self.message('首尾速度已保存；导出时将自动适速并预检。')
    def edit_speed(self):
        dialog=RhythmDialog(self.model,max(0,self.table.currentRow()),self,advanced_factory=SpeedDialog,selected_nodes=self.point_selection)
        if dialog.exec_()!=W.QDialog.Accepted:return
        self.model.use_endpoint_speeds()
        self.model.node_speeds=dialog.candidate.node_speeds.copy()
        self.model.segment_speeds=dialog.candidate.segment_speeds.copy()
        self.model.speed_positions=dialog.candidate.speed_positions.copy()
        self.model.rhythm_regions=copy.deepcopy(dialog.candidate.rhythm_regions)
        self.refresh();self.remember();self.message('区域运笔节奏已保存；预检参考按当前路径和配置缓存，导出时检查完整多笔轨迹。')
    def reset(self):
        self.restore_snapshot(self.initial_state);self.rebuild_handles();self.refresh(True);self.remember()
        self.message('已恢复本次载入的路径和参数，可撤销。')
    def add_point(self):
        row=self.table.currentRow()
        before=self.snapshot()
        try:
            node=self.model.add_point(row);self.rebuild_handles();self.refresh(True)
            self.table.selectRow(node-1);self.remember()
            self.message(f'已添加节点 {self.model.stroke_node_offset()+node}，两段继承原段磁目标，后续各笔序号顺延；请重新预检。')
        except Exception as exc:self.restore_snapshot(before);self.fail(exc)
    def toggle_click_insert(self,enabled):
        for curve in (self.curve,self.selected):curve.setCurveClickable(not enabled,width=12)
        if enabled:
            self.path_box_button.setChecked(False)
            self.message('点击空白处新建独立起点，再点击第二点生成新笔画。' if self.insert_mode.currentIndex()!=1 else f'点击图中任意位置，将在编号 {self.insert_order.value()} 插入新点；再次点击按钮退出添加模式。')
    def add_point_at_click(self,event):
        if not self.click_insert_button.isChecked() or event.button()!=QtCore.Qt.LeftButton:return
        if hasattr(event,'isAccepted') and event.isAccepted():return
        if not self.plot.getViewBox().sceneBoundingRect().contains(event.scenePos()):return
        position=self.path_view.mapSceneToView(event.scenePos())
        self.insert_x.setValue(position.x());self.insert_y.setValue(position.y())
        self.insert_coordinate_point()
    def insert_coordinate_point(self):
        before=self.snapshot()
        try:
            if self.insert_mode.currentIndex()!=1 or self.model.pending_point is not None:
                completed=self.model.add_independent_point([self.insert_x.value(),self.insert_y.value()],position='start' if self.insert_mode.currentIndex()==2 else 'end')
                self.rebuild_handles();self.refresh(True)
                if completed:
                    self.insert_mode.setCurrentIndex(1);self.insert_order.setValue(self.model.stroke_node_offset()+len(self.model.nodes));self.table.selectRow(0);self.set_path_selection({1})
                self.remember()
                self.message(f'已生成独立「{self.model.stroke_name}」，后续点追加到本笔画；可切换笔画。请重新预检。' if completed else '独立起点已保存（紫色菱形，可拖动）；添加第二个点形成新笔画。不会连接原路径。')
                return
            node=self.model.insert_point(self.insert_order.value()-self.model.stroke_node_offset(),[self.insert_x.value(),self.insert_y.value()])
            self.rebuild_handles();self.refresh(True);self.table.selectRow(max(0,node-1))
            self.set_path_selection({node});self.insert_order.setValue(self.model.stroke_node_offset()+node+1);self.remember()
            hidden='' if self.model.node_enabled[node] else '该点位于隐藏区间，恢复全部点后可显示、测试。'
            self.message(f'已在指定位置添加节点 {self.model.stroke_node_offset()+node}，后续各笔编号已顺延；可拖动调整或撤销，请重新预检。'+hidden)
        except Exception as exc:self.restore_snapshot(before);self.fail(exc)
    def delete_point(self):
        row=self.table.currentRow()
        if row<0:self.message('先在表格中选择一段，删除的是该段终点。');return
        before=self.snapshot()
        try:
            self.model.delete_point(row+1);self.rebuild_handles();self.refresh(True)
            self.table.selectRow(min(row,len(self.model.nodes)-2));self.remember()
            self.message('已删除节点；末端删除时同时去掉最后一段，中间删除时直连前后节点并保留前段磁目标。请重新预检。')
        except Exception as exc:self.restore_snapshot(before);self.fail(exc)
    def delete_selected_points(self):
        if not self.point_selection:self.message('先在图中点击或框选要删除的点，可选起点和末端点。');return
        before=self.snapshot()
        try:
            indices=sorted(self.point_selection,reverse=True)
            candidate=copy.deepcopy(self.model)
            for node in indices:candidate.delete_point(node)
            self.model=candidate;self.rebuild_handles();self.refresh(True);self.remember()
            self.message(f'已删除 {len(indices)} 个点并更新编号，支持撤销；请核对新起止点并重新预检。')
        except Exception as exc:self.restore_snapshot(before);self.fail(exc)
    def full_view(self):
        parts=[self.model.points(),*[PathModel.from_state(s).points() for s in self.model.other_strokes]]
        if self.model.pending_point is not None:parts.append(np.array([self.model.pending_point]))
        p=np.vstack(parts);self.plot.setRange(xRange=(p[:,0].min()-4,p[:,0].max()+4),yRange=(p[:,1].min()-5,p[:,1].max()+5),padding=.03)
    def open_recipe(self):
        path,_=W.QFileDialog.getOpenFileName(self,'打开路径或实验存档',str(ROOT/'runs/brush2/plans'),'路径与实验 (*.brushrun recipe.json);;实验存档 (*.brushrun);;路径文件 (recipe.json)')
        if path:
            try:
                if Path(path).suffix == '.brushrun':self.load_experiment(path);return
                folder=Path(path).parent
                if (folder/'bundle_manifest.json').is_file():self.load_experiment(folder);return
                state=folder/'editor_state.json';manifest=folder/'workspace_recipe.json'
                self.install_model(PathModel.restore(state) if state.exists() else PathModel(folder))
            except Exception as e:self.fail(e)
    def load_experiment(self,path):
        from scripts.brush_experiment_dialogs import ExperimentDataDialog
        path=archive_path(path)
        verify(path)
        metadata=read_data_json(path,'experiment.json')
        model=PathModel.from_state(read_data_json(path,'editor_state.json')) if metadata.get('editor_available') else None
        viewer=ExperimentDataDialog(path,self)
        if model is not None:self.install_model(model,preserve_parameters=True)
        previous=getattr(self,'experiment_viewer',None)
        if previous is not None:previous.close();previous.deleteLater()
        self.experiment_viewer=viewer
        if model is not None:
            self.autosave()
            self.show();self.raise_();self.activateWindow();self.plot.setFocus()
            self.message(f'已恢复到画板：{metadata["name"]}；全部 {len(model.stroke_order)} 笔路径、节点、磁目标、笔杆角度和速度已载入。历史磁响应可在“实验记录 → 查看数据”中查看。')
        else:
            viewer.show()
            self.message('已打开实验：'+metadata['name']+'；此专用实验可查看实测数据，没有可编辑路径。')
    def open_experiment_file(self):
        path,_=W.QFileDialog.getOpenFileName(self,'打开实验存档',str(self.archive.root),'毛笔实验存档 (*.brushrun)')
        if path:
            try:self.load_experiment(path)
            except Exception as exc:self.fail(exc)
    def show_experiment_records(self):
        from scripts.brush_experiment_dialogs import ExperimentRecordsDialog
        ExperimentRecordsDialog(self.archive,self.load_experiment,self).exec_()
    def open_state(self):
        path,_=W.QFileDialog.getOpenFileName(self,'恢复编辑存档',str(DRAFT.parent),'编辑存档 (*.json)')
        if path:
            try:self.install_model(PathModel.restore(path))
            except Exception as e:self.fail(e)
    def open_feedforward(self):
        path,_=W.QFileDialog.getOpenFileName(self,'选择前馈表',str(ROOT/'runs/brush2/plans'),'JSON (*.json)')
        if path:
            try:
                from brushbot.feedforward import validate_table
                validate_table(json.loads(Path(path).read_text()))
                self.model.select_feedforward(path);self.refresh();self.autosave();self.message('当前前馈表：'+path+'；请重新预检。')
            except Exception as e:self.fail(e)
    def save_state(self):
        if not self.commit_pending_edits():return
        self.autosave();self.message('已保存编辑存档：'+str(DRAFT))
    def edit_writing_variation(self):
        if not self.commit_pending_edits():return
        from scripts.brush_variation_dialog import WritingVariationDialog
        try:
            dialog=WritingVariationDialog(self.model,self)
            if dialog.exec_()!=W.QDialog.Accepted:return
            dialog.candidate._copy_variation_to(self.model)
            self.refresh();self.remember()
            self.message('书写随机设置已保存；预览结果用于下一次试写，执行中的运行保持原结果。')
        except Exception as exc:self.fail(exc)
    def show_speed_result(self,factor,duration):
        report=getattr(self.model,'last_speed_adaptation',None)
        if report is None:return
        note=(f'局部调整 {report["iterations"]} 次' if report['iterations'] else '请求上限已按设备能力约束') if report['adapted'] else '当前请求速度直接通过'
        self.speed_status.setText(f'自动适速：{note}  |  最高规划运笔速度：{report["planned_max_writing_speed_mm_s"]:.2f} mm/s  |  书写：{duration:.2f} s\n保留请求速度设置，导出使用通过预检的局部速度；未作全局时间缩放。')
        self.speed_status.setStyleSheet('color:#23764c;font-weight:600')
    def preflight(self):
        if not self.commit_pending_edits():return
        self.message('正在按当前路径自动适配速度并预检……');W.QApplication.processEvents()
        try:
            _,plan,c,settings,_=self.model.compile_workspace()
            duration=sum(float(st.t[-1]) for st in plan.strokes);self.show_speed_result(1.,duration)
            parts=[]
            for i,(st,row) in enumerate(zip(plan.strokes,self.model.last_workspace_strokes)):
                placement=row['recipe']['placement'];theta=np.deg2rad(placement['rotation_deg']);rot=np.array([[np.cos(theta),-np.sin(theta)],[np.sin(theta),np.cos(theta)]])
                xy=c['pose_m_rad'][c['phase']==f'measure_{i:02}',:2]*1000
                xy-=np.array([settings['settings.json']['origin_x_mm'],settings['settings.json']['origin_y_mm']])
                q=(xy-np.array(placement['origin_mm']))@rot/placement['scale']
                parts.extend([q,np.full((1,2),np.nan)])
            q=np.vstack(parts);self.compiled.setData(q[:,0],q[:,1],connect='finite')
            order=' → '.join(f'{row["stroke_name"]}[{row["point_range"][0]}–{row["point_range"][1]}]' for row in self.model.last_workspace_strokes)
            height=settings['entry_profile.json'].get('transfer_z_mm')
            self.message(f'全部 {len(plan.strokes)} 笔预检通过：{order}。书写 {duration:.2f} 秒，含悬空转移总计 {c["t_s"][-1]:.2f} 秒；转场 Z={height} mm（绝对高度）。未连接硬件。')
        except Exception as e:self.fail(e)
    def export_version(self):
        if not self.commit_pending_edits():return None
        self.message('正在自动适速并生成实验版本……');W.QApplication.processEvents()
        try:
            self.autosave();folder,s=self.model.export();self.show_speed_result(s['retiming_factor'],s['writing_duration_s'])
            order=' → '.join(f'{row["stroke_name"]}[{row["point_range"][0]}–{row["point_range"][1]}]' for row in s['execution_order'])
            self.message(f'预检通过，已导出：{folder}\n按顺序执行：{order}；笔间抬笔悬空转移。书写 {s["writing_duration_s"]:.2f} 秒；自动局部适速 {s["local_speed_iterations"]} 次。');return folder
        except Exception as e:self.fail(e);return None
    def launch_trial(self):
        if not self.commit_pending_edits():return
        self.autosave();stage=self.archive.new_stage(kind='launch')
        try:
            self.message('正在预检试写路径……');W.QApplication.processEvents()
            folder,summary=self.model.export(stage/'plan')
            self.show_speed_result(summary['retiming_factor'],summary['writing_duration_s'])
            command=[str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/run_edited_brush_path.py'),str(folder),
                     '--execute','--run-root',str(self.archive.root),'--consume-stage',str(stage)]
            shell=shlex.join(command)+'; read -r -p "终端结束，按回车关闭。"'
            subprocess.run(['gnome-terminal','--title=毛笔试写','--working-directory='+str(ROOT),'--','bash','-c',shell],check=True)
            # The exported plan stays frozen. Prepare a fresh repetition only
            # AFTER opening this trial, so a preview is never redrawn at launch.
            if self.model.writing_variation['enabled'] and not self.model.variation_locked:
                self.model.regenerate_writing_variation();self.refresh();self.autosave()
            self.message('试写终端已打开；成功后自动归档并命名，中断或错误数据保留在实验库的“临时失败实验”目录。')
        except Exception as exc:
            if stage.exists():self.archive.retain_stage(stage,reason='launch_failed',exception=exc)
            self.fail(exc)
    def closeEvent(self,event):
        if not self.commit_pending_edits():event.ignore();return
        self.autosave();event.accept()

def main():
    app=W.QApplication(sys.argv)
    model=None;experiment_path=None
    if '--open-experiment' in sys.argv:
        experiment_path=Path(sys.argv[sys.argv.index('--open-experiment')+1]).resolve()
        verify(experiment_path)
        if read_data_json(experiment_path,'experiment.json').get('editor_available'):
            model=PathModel.from_state(read_data_json(experiment_path,'editor_state.json'))
    elif '--resume' in sys.argv:
        draft=DRAFT if DRAFT.exists() else max([x for x in [DRAFT.with_name('draft.json'),DRAFT.with_name('draft_v2.json')] if x.exists()],key=lambda x:x.stat().st_mtime,default=DRAFT)
        if draft.exists():model=PathModel.restore(draft)
    if '--feedforward' in sys.argv:
        from brushbot.feedforward import validate_table
        path=Path(sys.argv[sys.argv.index('--feedforward')+1]).resolve()
        validate_table(json.loads(path.read_text()))
        model=model or PathModel();model.select_feedforward(path)
    win=Editor(model);win.show()
    if experiment_path is not None:win.load_experiment(experiment_path)
    if '--orientation-settings' in sys.argv:QtCore.QTimer.singleShot(0,win.edit_orientation)
    elif '--speed-settings' in sys.argv:QtCore.QTimer.singleShot(0,win.edit_speed)
    elif '--auto-preflight' in sys.argv:QtCore.QTimer.singleShot(0,win.preflight)
    return app.exec_()
if __name__=='__main__':sys.exit(main())
