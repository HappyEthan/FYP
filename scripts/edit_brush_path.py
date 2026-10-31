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
from scripts.brush_path_editor_model import PathModel,DEFAULT,arc
from scripts.brush_editor_interaction import SelectionViewBox,DraggablePoint,selected_in_rect,shifted_speeds
from scripts.brush_rhythm_dialog import RhythmDialog
DRAFT=ROOT/'outputs/brush_path_editor/draft_v3.json'

class SpeedDialog(W.QDialog):
    def __init__(self,model,segment=0,parent=None):
        super().__init__(parent);self.candidate=copy.deepcopy(model);self.candidate.use_endpoint_speeds()
        self.loading=False;self.point_selection=set();self.speed_handles=[];self._speed_drag=None
        self.speed_distances=arc(self.candidate.points());self.speed_cap=self.candidate.settings()['feedforward.json']['speed_mm_s']
        self.speed_history=[self.candidate.node_speeds.copy()]
        self.setWindowTitle('高级精确速度 — 段首、段尾 mm/s');self.resize(1100,760)
        layout=W.QVBoxLayout(self)
        note=W.QLabel('每行只调段首和段尾速度，段内平滑过渡；相邻段共用端点。蓝色继承，橙色手动设置。\nShift＋拖框选择多个圆点，按住Ctrl追加框选；拖动选中点可整体上下调速，横轴绑定路径端点。')
        note.setWordWrap(True);layout.addWidget(note)
        profile=self.candidate.settings()['feedforward.json'];profile_note=W.QLabel(f'允许速度：大于0至{self.speed_cap:g} mm/s。'+(' _cyg高速试验：原磁响应映射仍为10 mm/s数据，20 mm/s未重新标定。' if profile.get('high_speed_trial') else ''))
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

class SegmentOrientationDialog(W.QDialog):
    def __init__(self,model,segment,parent=None):
        super().__init__(parent);self.segment=segment
        self.setWindowTitle(f'第{segment+1}段笔杆角度：节点{segment} → 节点{segment+1}')
        layout=W.QVBoxLayout(self);form=W.QFormLayout();layout.addLayout(form);self.fields=[]
        displayed=model.displayed_node_angles()
        for node,col,label in [(segment,0,'段首倾角 °'),(segment+1,0,'段尾倾角 °'),(segment,1,'段首朝向 °'),(segment+1,1,'段尾朝向 °')]:
            field=W.QLineEdit('' if model.node_angles[node,col] is None else format(model.node_angles[node,col],'.12g'))
            field.setPlaceholderText(f'继承当前方案（约{displayed[node,col]:.2f}°），留空沿用')
            form.addRow(label,field);self.fields.append((node,col,field))
        note=W.QLabel('倾角：偏离竖直的角度，须大于0°且小于30°。\n朝向：右0°、上90°、左±180°、下−90°。\n段内平滑过渡；相邻段共用端点，修改会同步影响相邻段。\n同一段首尾填相同值表示保持；留空恢复继承原方案。')
        note.setWordWrap(True);layout.addWidget(note)
        self.error=W.QLabel();layout.addWidget(self.error)
        box=W.QDialogButtonBox(W.QDialogButtonBox.Save|W.QDialogButtonBox.Cancel);box.button(W.QDialogButtonBox.Save).setText('保存此段角度');box.button(W.QDialogButtonBox.Cancel).setText('取消')
        box.accepted.connect(self.save);box.rejected.connect(self.reject);layout.addWidget(box)
    def save(self):
        try:
            self.values=[]
            for node,col,field in self.fields:
                value=None if not field.text().strip() else float(field.text())
                if value is not None and (not np.isfinite(value) or (col==0 and not 0<value<30)):raise ValueError('倾角须在0°和30°之间；朝向须为有限数值')
                self.values.append((node,col,value))
            self.accept()
        except Exception as exc:self.error.setText(str(exc))

class Editor(W.QMainWindow):
    def __init__(self,model=None):
        super().__init__();self.model=model or PathModel();self.handles=[];self.history=[];self.loading=False
        self.point_selection=set();self._path_drag_context=None
        self.path_timer=QtCore.QTimer(self);self.path_timer.setSingleShot(True);self.path_timer.setInterval(20);self.path_timer.timeout.connect(self.draw_path_drag)
        self.setWindowTitle('毛笔路径编辑器 — 分段 XY / 磁目标 / 速度');self.resize(1600,900)
        central=W.QWidget();self.setCentralWidget(central);layout=W.QVBoxLayout(central)
        title=W.QLabel('毛笔路径编辑器  ·  XY 单位 mm，Y 向上，角度从 +X 逆时针计')
        title.setStyleSheet('font-size:19px;font-weight:600;padding:8px');layout.addWidget(title)
        tools=W.QHBoxLayout();layout.addLayout(tools)
        for label,callback in [('打开路径版本',self.open_recipe),('恢复编辑存档',self.open_state),('载入前馈表',self.open_feedforward),('局部速度',self.edit_speed),('自动适配速度',self.preflight),('选中段笔杆角度',self.edit_orientation),('撤销',self.undo),
            ('恢复原始路径',self.reset),('全图',self.full_view),('尾端放大',self.tail_view),('加载参考照片',self.open_photo)]:
            b=W.QPushButton(label);b.clicked.connect(callback);tools.addWidget(b)
        selection_tools=W.QHBoxLayout();layout.addLayout(selection_tools)
        self.path_box_button=W.QPushButton('框选路径端点');self.path_box_button.setCheckable(True);selection_tools.addWidget(self.path_box_button)
        clear=W.QPushButton('取消框选');clear.clicked.connect(lambda:self.set_path_selection(set()));selection_tools.addWidget(clear)
        selection_tools.addWidget(W.QLabel('ΔX mm'));self.delta_x=W.QDoubleSpinBox();self.delta_x.setRange(-100,100);self.delta_x.setDecimals(3);selection_tools.addWidget(self.delta_x)
        selection_tools.addWidget(W.QLabel('ΔY mm'));self.delta_y=W.QDoubleSpinBox();self.delta_y.setRange(-100,100);self.delta_y.setDecimals(3);selection_tools.addWidget(self.delta_y)
        move=W.QPushButton('平移选中路径点');move.clicked.connect(lambda:self.translate_path_selection([self.delta_x.value(),self.delta_y.value()]));selection_tools.addWidget(move)
        selection_tools.addWidget(W.QLabel('Shift＋拖框；按住Ctrl追加框选；拖动选中点整体移动。'))
        testtools=W.QHBoxLayout();layout.addLayout(testtools)
        testtools.addWidget(W.QLabel('分段测试：起点编号'))
        self.test_first=W.QSpinBox();testtools.addWidget(self.test_first)
        testtools.addWidget(W.QLabel('终点编号'));self.test_last=W.QSpinBox();testtools.addWidget(self.test_last)
        for label,callback in [('应用测试范围',self.apply_test_range),('仅测试框选范围',self.test_selection),('仅测试表格选中段',self.test_selected_segment),('隐藏选中点',self.hide_selected_points),('恢复全部点',self.restore_all_points)]:
            button=W.QPushButton(label);button.clicked.connect(callback);testtools.addWidget(button)
        self.test_note=W.QLabel();test_note=self.test_note;test_note.setWordWrap(True);layout.addWidget(test_note)
        splitter=W.QSplitter();layout.addWidget(splitter,1)
        self.path_view=SelectionViewBox();self.path_view.rectangleSelected.connect(self.select_path_rect);self.path_box_button.toggled.connect(lambda value:setattr(self.path_view,'box_select',value))
        self.plot=pg.PlotWidget(viewBox=self.path_view,background='#faf9f4');self.plot.setLabel('bottom','局部路径 X',units='mm');self.plot.setLabel('left','局部路径 Y',units='mm')
        self.plot.showGrid(x=True,y=True,alpha=.22);self.plot.setAspectLocked(True);self.plot.addLegend()
        self.plot.scene().sigMouseClicked.connect(self.add_point_at_click)
        splitter.addWidget(self.plot)
        self.original=self.plot.plot(pen=pg.mkPen('#9ca3af',width=2,style=QtCore.Qt.DashLine),name='载入版本')
        self.reference=self.plot.plot(pen=pg.mkPen('#b4b7c5',width=1,style=QtCore.Qt.DotLine),name='原路径 v5（参考）')
        ref=ROOT/'runs/brush2/plans/heng_80mm_html_return_v5/recipe.json'
        if ref.exists():
            rr=json.loads(ref.read_text());p=np.array(rr['path']['points_mm'])*rr['placement']['scale'];self.reference.setData(p[:,0],p[:,1])
        self.curve=self.plot.plot(pen=pg.mkPen('#1473c9',width=3),name='待导出的 XY 路径')
        self.hidden_curve=self.plot.plot(pen=pg.mkPen('#c4c4c4',width=1,style=QtCore.Qt.DotLine),name='完整编辑路径（隐藏段不执行）')
        self.selected=self.plot.plot(pen=pg.mkPen('#e39b24',width=5),name='选中段')
        self.compiled=self.plot.plot(pen=pg.mkPen('#24a27b',width=1,style=QtCore.Qt.DashLine),name='预检后的目标 XY')
        self.other_stroke_curves=[];self.other_stroke_labels=[]
        self.pending_handle=DraggablePoint(size=16,movable=True,symbol='d',pen='#7c3aed',brush='#c4b5fd')
        self.plot.addItem(self.pending_handle);self.pending_handle.setVisible(False)
        self.pending_handle.sigPositionChangeFinished.connect(self.move_pending_point)
        self.pending_label=pg.TextItem('新笔画起点',color='#7c3aed',anchor=(.5,1.4));self.pending_label.setParentItem(self.pending_handle)
        side=W.QWidget();right=W.QVBoxLayout(side)
        side_scroll=W.QScrollArea();side_scroll.setWidgetResizable(True);side_scroll.setWidget(side);side_scroll.setMinimumWidth(650);side_scroll.setFrameShape(W.QFrame.NoFrame)
        splitter.addWidget(side_scroll);splitter.setSizes([830,770])
        stroke_tools=W.QHBoxLayout();right.addLayout(stroke_tools)
        stroke_tools.addWidget(W.QLabel('当前编辑笔画'))
        self.stroke_selector=W.QComboBox();self.stroke_selector.currentIndexChanged.connect(self.switch_stroke);stroke_tools.addWidget(self.stroke_selector,1)
        self.new_stroke_button=W.QPushButton('新建独立笔画');self.new_stroke_button.clicked.connect(self.begin_independent_stroke);stroke_tools.addWidget(self.new_stroke_button)
        self.first_stroke_button=W.QPushButton('在最前新建独立笔画');self.first_stroke_button.clicked.connect(self.begin_first_stroke);right.addWidget(self.first_stroke_button)
        self.stroke_note=W.QLabel();self.stroke_note.setWordWrap(True);right.addWidget(self.stroke_note)
        helptext=W.QLabel('拖动圆点改变端点；点击表格选择一段。\n修改段长/角度：当前笔画的后续各段整体平移。\n修改端点 X/Y 或拖动：相邻两段随之变化。\n段长为曲线路径长度；角度为起终点连线方向。')
        helptext.setWordWrap(True);right.addWidget(helptext)
        self.orientation_note=W.QLabel();self.orientation_note.setWordWrap(True);right.addWidget(self.orientation_note)
        self.speed_status=W.QLabel();self.speed_status.setWordWrap(True);right.addWidget(self.speed_status)
        self.table=W.QTableWidget();self.table.setMinimumHeight(200);self.table.setColumnCount(10)
        self.table.setHorizontalHeaderLabels(['点序号','段长 mm','XY角度 °','终点 X','终点 Y','磁目标\nμT','段首倾角\n°','段尾倾角\n°','段首朝向\n°','段尾朝向\n°'])
        self.table.horizontalHeader().setSectionResizeMode(W.QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0,W.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setFixedHeight(44)
        self.table.setSelectionBehavior(W.QAbstractItemView.SelectRows);self.table.setSelectionMode(W.QAbstractItemView.SingleSelection)
        self.table.cellChanged.connect(self.cell_changed);self.table.itemSelectionChanged.connect(self.selection_changed)
        right.addWidget(self.table,1)
        pointtools=W.QHBoxLayout();right.addLayout(pointtools)
        for label,callback in [('选中段中间添加点',self.add_point),('删除选中段终点',self.delete_point),('删除图中选中点',self.delete_selected_points)]:
            button=W.QPushButton(label);button.clicked.connect(callback);pointtools.addWidget(button)
        inserttools=W.QGridLayout();right.addLayout(inserttools)
        self.insert_mode=W.QComboBox();self.insert_mode.addItems(['新建末尾独立笔画（不连接原笔画）','插入／追加到当前笔画','在最前新建独立笔画（原0点之前）'])
        inserttools.addWidget(self.insert_mode,0,0,1,6)
        self.insert_order_label=W.QLabel('新点插入编号');inserttools.addWidget(self.insert_order_label,1,0);self.insert_order=W.QSpinBox();inserttools.addWidget(self.insert_order,1,1)
        self.insert_x=W.QDoubleSpinBox();self.insert_y=W.QDoubleSpinBox()
        for col,(label,field) in enumerate([('X mm',self.insert_x),('Y mm',self.insert_y)]):
            field.setRange(-10000,10000);field.setDecimals(4);field.setSingleStep(.1)
            inserttools.addWidget(W.QLabel(label),1,2+col*2);inserttools.addWidget(field,1,3+col*2)
        self.insert_button=W.QPushButton('按坐标添加点');self.insert_button.clicked.connect(self.insert_coordinate_point);inserttools.addWidget(self.insert_button,2,0,1,3)
        self.click_insert_button=W.QPushButton('图中点选添加');self.click_insert_button.setCheckable(True);self.click_insert_button.toggled.connect(self.toggle_click_insert);inserttools.addWidget(self.click_insert_button,2,3,1,3)
        self.cancel_start_button=W.QPushButton('取消独立起点');self.cancel_start_button.clicked.connect(self.cancel_independent_start);inserttools.addWidget(self.cancel_start_button,3,0,1,6)
        self.insert_mode.currentIndexChanged.connect(self.update_insert_mode)
        self.path_box_button.toggled.connect(lambda enabled:self.click_insert_button.setChecked(False) if enabled else None)
        pointnote=W.QLabel('点序号跨笔画连续编号；插入／删除后自动顺延。新笔画第一点独立放置，第二点与它连接。\n新增点编号表示插在该序号前；末端追加编号显示在输入框后。执行时按各笔画最小序号依次写完，笔间抬笔悬空平移。')
        pointnote.setWordWrap(True);right.addWidget(pointnote)
        applymag=W.QPushButton('将选中段的显示数值设为整段磁目标')
        applymag.clicked.connect(self.apply_displayed_reference);right.addWidget(applymag)
        magnote=W.QLabel('蓝色为原曲线中点参考；橙色为整段恒定磁目标。\n留空恢复原曲线；执行目标须在前馈标定范围内。')
        magnote.setWordWrap(True);right.addWidget(magnote)
        self.detail=W.QLabel();self.detail.setWordWrap(True);right.addWidget(self.detail)
        self.photo=W.QLabel('可加载参考墨迹照片；图片仅供对照，不自动推断笔尖轨迹。');self.photo.setWordWrap(True);self.photo.setMinimumHeight(60);right.addWidget(self.photo)
        note=W.QLabel('XY、速度和磁目标均随版本保存并预检。\n超出标定或运动限值时禁止导出；图中路径不等同于实际墨迹。')
        note.setWordWrap(True);right.addWidget(note)
        bottom=W.QHBoxLayout();layout.addLayout(bottom)
        for label,callback in [('保存编辑存档',self.save_state),('自动适速并预检',self.preflight),
            ('导出全部笔画实验版本',self.export_version),('导出全部笔画并打开试写终端',self.launch_trial)]:
            b=W.QPushButton(label);b.clicked.connect(callback);bottom.addWidget(b)
        self.status=W.QLabel();self.status.setWordWrap(True);layout.addWidget(self.status)
        self.install_model(self.model)
        reference=ROOT/'outputs/brush_path_editor/reference_path.png'
        if reference.exists():self.show_photo(reference)

    def message(self,text):self.status.setText(text)
    def fail(self,exc):self.message('未通过：'+str(exc));W.QMessageBox.warning(self,'路径未通过',str(exc))
    def install_model(self,model):
        model.allow_low_response=False;model.lift_mm=np.zeros(len(model.nodes));model.use_endpoint_speeds()
        self.model=model;self.initial_state=self.snapshot();self.history=[self.snapshot()];self.rebuild_handles();self.refresh();self.full_view()
        self.message('当前来源：'+str(model.folder)+'\n编辑不会连接硬件。')
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
        self.speed_status.setStyleSheet('color:#8a5b00')
        self.speed_status.setText('自动适速已启用：预检或导出时，按当前XY、磁目标和笔杆角度重算局部限速。')
        orientation=self.model.base['orientation'].copy()
        if orientation.get('heading_knots_s_deg'):
            before=arc(self.model.original);after=arc(self.model.points())
            orientation['heading_knots_s_deg']=[(float(np.interp(s*before[-1],before,after)/after[-1]),angle) for s,angle in orientation['heading_knots_s_deg']]
        headings=orientation.get('heading_knots_s_deg')
        text='；'.join(f'{s*100:.1f}%：'+('自动朝向接入' if angle is None else f'{angle:g}°') for s,angle in headings) if headings else '倾斜方向自动跟随平滑后的XY切线'
        self.orientation_note.setText('每段笔杆角度在表格最后四列修改，留空继承；相邻段共用端点。\n'+f'原方案倾角 {orientation["tilt_deg"]:g}°；朝向角以右为0°、上为90°。\n'+text)
        p=self.model.points();self.draw_test_path(p);o=self.model.original;self.original.setData(o[:,0],o[:,1])
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
        self.table.blockSignals(False)
        if selected>=0:self.table.selectRow(selected)
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
        self.stroke_note.setText(f'共 {len(self.model.stroke_order)} 笔；蓝色为当前编辑的「{self.model.stroke_name}」，紫色虚线为其他笔画。执行顺序按点序号递增；每笔结束抬笔，悬空平移至下一笔起点后落笔。'+(' 新笔画尚缺第二个点，暂不能导出。' if self.model.pending_point is not None else ''))
        self.update_insert_mode()
    def update_insert_mode(self):
        independent=self.insert_mode.currentIndex()!=1 or self.model.pending_point is not None
        self.insert_order.setEnabled(not independent);self.insert_order_label.setEnabled(not independent)
        self.insert_mode.setEnabled(self.model.pending_point is None)
        self.stroke_selector.setEnabled(self.model.pending_point is None)
        self.cancel_start_button.setEnabled(self.model.pending_point is not None)
        self.first_stroke_button.setEnabled(self.model.pending_point is None)
        self.new_stroke_button.setEnabled(self.model.pending_point is None)
    def begin_independent_stroke(self):
        self.insert_mode.setCurrentIndex(0);self.click_insert_button.setChecked(True)
        self.message('已有独立起点，请点击第二个点完成新笔画；也可取消独立起点重新放置。' if self.model.pending_point is not None else '在图中空白处点击第一个点，再点击第二个点生成独立笔画；也可以填写X/Y后按坐标添加。与原笔画之间不连线。')
    def begin_first_stroke(self):
        self.insert_mode.setCurrentIndex(2);self.click_insert_button.setChecked(True)
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
        self.curve.setData(active[:,0],active[:,1]);self.hidden_curve.setData(p[:,0],p[:,1])
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
        self.point_selection=set(indices);self.paint_path_selection();self.message(f'已选中{len(self.point_selection)}个路径点，可拖动整体平移或输入ΔX/ΔY。')
    def select_path_rect(self,bounds,add=False):
        found=selected_in_rect(self.model.nodes,bounds)&set(np.flatnonzero(self.model.node_enabled));self.set_path_selection(self.point_selection|found if add else found)
    def click_path_point(self,k,add=False):
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
    def apply_displayed_reference(self):
        row=self.table.currentRow()
        if row<0:
            self.message('先在表格中选择一段。');return
        self.cell_changed(row,5)
    def selection_changed(self):
        k=self.table.currentRow()
        if k<0 or k>=len(self.model.nodes)-1:return
        p=self.model.points();a,b=self.model.indices[k:k+2];seg=p[a:b+1];first,last=self.model.test_node_range()
        self.selected.setData(seg[:,0] if first<=k<last else [],seg[:,1] if first<=k<last else [])
        offset=self.model.stroke_node_offset()
        self.detail.setText(f'段 {k+1}：节点 {offset+k} → {offset+k+1}；'+('本次执行；' if first<=k<last else '本次隐藏；')+f'起点 X={self.model.nodes[k,0]:.3f}，Y={self.model.nodes[k,1]:.3f} mm')
    def undo(self):
        if len(self.history)>1:
            self.history.pop();self.restore_snapshot(self.history[-1]);self.rebuild_handles();self.refresh(True);self.autosave();self.message('已撤销。')
    def edit_orientation(self):
        row=self.table.currentRow()
        if row<0:row=0;self.table.selectRow(row)
        dialog=SegmentOrientationDialog(self.model,row,self)
        if dialog.exec_()!=W.QDialog.Accepted:return
        before=self.snapshot()
        try:
            for node,col,value in dialog.values:self.model.node_angles[node,col]=value
            self.refresh();self.remember()
            self.message(f'第{row+1}段笔杆角度已保存，相邻段共用节点同步更新；请重新预检并导出。')
        except Exception as exc:self.restore_snapshot(before);self.refresh();self.fail(exc)
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
    def tail_view(self):
        p=self.model.points();q=p[p[:,0]>=p[:,0].max()-12]
        self.plot.setRange(xRange=(q[:,0].min()-1,q[:,0].max()+2),yRange=(q[:,1].min()-2,q[:,1].max()+2),padding=.03)
    def open_recipe(self):
        path,_=W.QFileDialog.getOpenFileName(self,'选择历史或新版本 recipe.json',str(ROOT/'runs/brush2/plans'),'Recipe (recipe.json)')
        if path:
            try:
                folder=Path(path).parent
                state=folder/'editor_state.json';manifest=folder/'workspace_recipe.json'
                self.install_model(PathModel.restore(state) if state.exists() and manifest.exists() else PathModel(folder))
            except Exception as e:self.fail(e)
    def open_state(self):
        path,_=W.QFileDialog.getOpenFileName(self,'恢复 draft.json 或 editor_state.json',str(DRAFT.parent),'JSON (*.json)')
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
        self.autosave();self.message('已保存编辑存档：'+str(DRAFT))
    def open_photo(self):
        path,_=W.QFileDialog.getOpenFileName(self,'参考照片',str(Path.home()),'图片 (*.png *.jpg *.jpeg)')
        if path:self.show_photo(path)
    def show_photo(self,path):
        pix=QtGui.QPixmap(str(path));self.photo.setPixmap(pix.scaled(400,100,QtCore.Qt.KeepAspectRatio,QtCore.Qt.SmoothTransformation))
    def show_speed_result(self,factor,duration):
        report=getattr(self.model,'last_speed_adaptation',None)
        if report is None:return
        note=(f'局部调整 {report["iterations"]} 次' if report['iterations'] else '请求上限已按设备能力约束') if report['adapted'] else '当前请求速度直接通过'
        self.speed_status.setText(f'自动适速：{note}  |  最高规划运笔速度：{report["planned_max_writing_speed_mm_s"]:.2f} mm/s  |  书写：{duration:.2f} s\n保留请求速度设置，导出使用通过预检的局部速度；未作全局时间缩放。')
        self.speed_status.setStyleSheet('color:#23764c;font-weight:600')
    def preflight(self):
        self.message('正在按当前路径自动适配速度并预检……');W.QApplication.processEvents()
        try:
            _,plan,c,settings,_=self.model.compile_workspace()
            duration=sum(float(st.t[-1]) for st in plan.strokes);self.show_speed_result(1.,duration)
            parts=[]
            for st,row in zip(plan.strokes,self.model.last_workspace_strokes):
                placement=row['recipe']['placement'];theta=np.deg2rad(placement['rotation_deg']);rot=np.array([[np.cos(theta),-np.sin(theta)],[np.sin(theta),np.cos(theta)]])
                q=(st.xy*1000-np.array(placement['origin_mm']))@rot/placement['scale']
                parts.extend([q,np.full((1,2),np.nan)])
            q=np.vstack(parts);self.compiled.setData(q[:,0],q[:,1],connect='finite')
            order=' → '.join(f'{row["stroke_name"]}[{row["point_range"][0]}–{row["point_range"][1]}]' for row in self.model.last_workspace_strokes)
            height=settings['entry_profile.json'].get('transfer_z_mm')
            self.message(f'全部 {len(plan.strokes)} 笔预检通过：{order}。书写 {duration:.2f} 秒，含悬空转移总计 {c["t_s"][-1]:.2f} 秒；转场 Z={height} mm（绝对高度）。未连接硬件。')
        except Exception as e:self.fail(e)
    def export_version(self):
        self.message('正在自动适速并生成实验版本……');W.QApplication.processEvents()
        try:
            folder,s=self.model.export();self.autosave();self.show_speed_result(s['retiming_factor'],s['writing_duration_s'])
            order=' → '.join(f'{row["stroke_name"]}[{row["point_range"][0]}–{row["point_range"][1]}]' for row in s['execution_order'])
            self.message(f'预检通过，已导出：{folder}\n按顺序执行：{order}；笔间抬笔悬空转移。书写 {s["writing_duration_s"]:.2f} 秒；自动局部适速 {s["local_speed_iterations"]} 次。');return folder
        except Exception as e:self.fail(e);return None
    def launch_trial(self):
        folder=self.export_version()
        if folder is None:return
        command=[str(ROOT/'.venv/bin/python'),str(ROOT/'scripts/run_edited_brush_path.py'),str(folder),'--execute']
        try:
            # Terminal only waits for the operator's run; no hardware connection at launch.
            shell=shlex.join(command)+'; read -r -p "终端结束，按回车关闭。"'
            subprocess.run(['gnome-terminal','--title=毛笔编辑路径试写 — 输入 run 开始','--working-directory='+str(ROOT),'--','bash','-c',shell],check=True)
        except Exception as e:self.fail(e)
    def closeEvent(self,event):
        self.autosave();event.accept()

def main():
    app=W.QApplication(sys.argv)
    model=None
    if '--resume' in sys.argv:
        draft=DRAFT if DRAFT.exists() else max([x for x in [DRAFT.with_name('draft.json'),DRAFT.with_name('draft_v2.json')] if x.exists()],key=lambda x:x.stat().st_mtime,default=DRAFT)
        if draft.exists():model=PathModel.restore(draft)
    if '--feedforward' in sys.argv:
        from brushbot.feedforward import validate_table
        path=Path(sys.argv[sys.argv.index('--feedforward')+1]).resolve()
        validate_table(json.loads(path.read_text()))
        model=model or PathModel();model.select_feedforward(path)
    win=Editor(model);win.show()
    if '--orientation-settings' in sys.argv:QtCore.QTimer.singleShot(0,win.edit_orientation)
    elif '--speed-settings' in sys.argv:QtCore.QTimer.singleShot(0,win.edit_speed)
    elif '--auto-preflight' in sys.argv:QtCore.QTimer.singleShot(0,win.preflight)
    return app.exec_()
if __name__=='__main__':sys.exit(main())
