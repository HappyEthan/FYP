"""Region rhythm editor. Planning runs in a worker; gestures only redraw arrays."""
import copy
import uuid
import numpy as np
from PyQt5 import QtCore,QtWidgets as W
import pyqtgraph as pg
from scripts.brush_path_editor_model import arc
from scripts.brush_editor_interaction import SelectionViewBox,DraggablePoint,selected_in_rect
from scripts.brush_rhythm import PRESETS,rhythm_knots,validate_regions,slowdown_reasons

COLORS={'顿笔':'#d38b24','行笔':'#2486bf','收笔':'#9465b1'}
_RUNNING_PREVIEWS=set()


def _finish_workers_on_exit():
    for worker in list(_RUNNING_PREVIEWS):worker.wait()


def compute_preview(model):
    """Only operates on a detached model; the live editor and draft stay untouched."""
    distances=arc(model.points());first,last=model.test_node_range()
    lo,hi=distances[model.indices[[first,last]]]/distances[-1]
    index=model.stroke_order.index(model.stroke_id)
    reference,*_=model.compile({'entry_reverse_mm':0.} if index else None,reference_only=True)
    _,plan,compiled,_,_=model.compile_workspace()
    stroke=plan.strokes[index]
    return dict(reference=reference['timing'],lo=float(lo),hi=float(hi),
        actual_distance=distances[-1]*(lo+(hi-lo)*(stroke.s[:-1]+stroke.s[1:])/2),
        actual_speed=np.linalg.norm(np.diff(stroke.xy,axis=0),axis=1)*1000/np.diff(stroke.t),
        progress=lo+(hi-lo)*stroke.s,t=stroke.t.copy(),
        total_duration=float(compiled['t_s'][-1]),writing_duration=sum(float(s.t[-1]) for s in plan.strokes),
        report=copy.deepcopy(model.last_speed_adaptation))


class PreviewWorker(QtCore.QThread):
    resultReady=QtCore.pyqtSignal(int,object)
    def __init__(self,model,revision):
        super().__init__();self.model=model;self.revision=revision
    def run(self):
        try:result=compute_preview(self.model)
        except Exception as exc:result={'error':str(exc)}
        self.resultReady.emit(self.revision,result)


class RhythmDialog(W.QDialog):
    def __init__(self,model,segment=0,parent=None,advanced_factory=None,selected_nodes=None):
        super().__init__(parent);self.candidate=copy.deepcopy(model);self.advanced_factory=advanced_factory
        app=W.QApplication.instance()
        if not getattr(app,'_brush_rhythm_shutdown_hook',False):
            app.aboutToQuit.connect(_finish_workers_on_exit);app._brush_rhythm_shutdown_hook=True
        self.candidate.use_endpoint_speeds();self.distances=arc(self.candidate.points());self.length=float(self.distances[-1])
        self.node_progress=self.distances[self.candidate.indices]/self.length
        self.selection=set(selected_nodes or {segment,min(segment+1,len(model.nodes)-1)})&set(np.flatnonzero(model.node_enabled))
        self.selected_region=None;self.clipboard=None;self.bands=[];self.reference=None;self.actual=None
        self.revision=0;self.loading=False;self._worker=None;self._preview_again=False;self._closed=False
        self.history=[self.snapshot()]
        self.setWindowTitle('区域运笔节奏 — 框选后调整顿笔、行笔、收笔');self.resize(1320,880)
        layout=W.QVBoxLayout(self)
        note=W.QLabel('在路径上框选至少两个点，再选择顿笔／行笔／收笔；滑块控制相对参考速度，日常无需填写mm/s。\n下方彩色节奏带可拖动两端或整体平移，路径高亮同步变化。参考速度经过预检，最终执行前仍检查完整多笔轨迹。')
        note.setWordWrap(True);layout.addWidget(note)
        split=W.QSplitter();layout.addWidget(split,1)
        self.path_view=SelectionViewBox();self.path_view.rectangleSelected.connect(self.select_rect)
        self.path_plot=pg.PlotWidget(viewBox=self.path_view,background='#faf9f4');self.path_plot.setAspectLocked(True);self.path_plot.showGrid(x=True,y=True,alpha=.2)
        self.path_plot.setLabel('bottom','当前笔画 X',units='mm');self.path_plot.setLabel('left','Y',units='mm')
        p=model.points();self.path_plot.plot(p[:,0],p[:,1],pen=pg.mkPen('#b5b5b5',width=1))
        active=model.test_points();self.path_plot.plot(active[:,0],active[:,1],pen=pg.mkPen('#1473c9',width=3))
        self.highlight=self.path_plot.plot(pen=pg.mkPen('#e39b24',width=6));self.handles=[]
        offset=model.stroke_node_offset()
        for k,xy in enumerate(model.nodes):
            handle=DraggablePoint(pos=tuple(xy),movable=False,size=10,brush='#f6c65a',pen='#9a5c00')
            handle.pointClicked.connect(lambda item,add,k=k:self.click_point(k,add));handle.setVisible(bool(model.node_enabled[k]))
            self.path_plot.addItem(handle);self.handles.append(handle)
            label=pg.TextItem(str(offset+k),color='#38404a',anchor=(.5,1.4));label.setParentItem(handle)
        split.addWidget(self.path_plot)
        side=W.QWidget();form=W.QVBoxLayout(side);split.addWidget(side);split.setSizes([780,500])
        box=W.QPushButton('框选路径区域');box.setCheckable(True);box.setChecked(True);self.path_view.box_select=True
        box.toggled.connect(lambda value:setattr(self.path_view,'box_select',value));form.addWidget(box)
        self.selection_note=W.QLabel();self.selection_note.setWordWrap(True);form.addWidget(self.selection_note)
        presets=W.QHBoxLayout();form.addLayout(presets)
        for label in PRESETS:
            button=W.QPushButton(label);button.clicked.connect(lambda checked=False,label=label:self.add_region(label));presets.addWidget(button)
        self.regions=W.QListWidget();self.regions.setMaximumHeight(155);self.regions.currentRowChanged.connect(self.choose_region);form.addWidget(self.regions)
        self.ratio_label=W.QLabel('先选择或创建节奏区域');form.addWidget(self.ratio_label)
        self.ratio=W.QSlider(QtCore.Qt.Horizontal);self.ratio.setRange(10,100);self.ratio.setValue(100);self.ratio.setEnabled(False)
        self.ratio.valueChanged.connect(self.change_ratio);self.ratio.sliderReleased.connect(self.finish_edit);form.addWidget(self.ratio)
        ends=W.QLabel('慢／重顿 ←　　　　　→ 快／流畅（参考100%）');form.addWidget(ends)
        row=W.QHBoxLayout();form.addLayout(row)
        for label,callback in [('复制节奏',self.copy_region),('粘贴到选区',self.paste_region),('删除选中节奏',self.delete_region)]:
            button=W.QPushButton(label);button.clicked.connect(callback);row.addWidget(button)
        row=W.QHBoxLayout();form.addLayout(row)
        for label,callback in [('撤销节奏',self.undo),('恢复默认节奏',self.reset_regions),('重新预检全部笔画',self.request_preview)]:
            button=W.QPushButton(label);button.clicked.connect(callback);row.addWidget(button)
        self.stats=W.QLabel();self.stats.setWordWrap(True);form.addWidget(self.stats)
        self.error=W.QLabel('正在后台计算预检参考……');self.error.setWordWrap(True);form.addWidget(self.error)
        advanced=W.QPushButton('高级：精确速度设置（mm/s）');advanced.clicked.connect(self.open_advanced);form.addWidget(advanced)
        form.addStretch()
        self.speed_plot=pg.PlotWidget(background='#faf9f4');self.speed_plot.setMinimumHeight(230);self.speed_plot.addLegend();self.speed_plot.showGrid(x=True,y=True,alpha=.2)
        self.speed_plot.setLabel('bottom','沿当前路径距离',units='mm');self.speed_plot.setLabel('left','速度',units='mm/s')
        self.reference_curve=self.speed_plot.plot(pen=pg.mkPen('#969696',width=1,style=QtCore.Qt.DashLine),name='预检参考（非全局最大值）')
        self.request_curve=self.speed_plot.plot(pen=pg.mkPen('#1473c9',width=2),name='节奏请求')
        self.actual_curve=self.speed_plot.plot(pen=pg.mkPen('#239563',width=2),name='完整预检后的速度')
        layout.addWidget(self.speed_plot,1)
        buttons=W.QDialogButtonBox(W.QDialogButtonBox.Save|W.QDialogButtonBox.Cancel)
        buttons.button(W.QDialogButtonBox.Save).setText('保存节奏草稿');buttons.button(W.QDialogButtonBox.Cancel).setText('取消')
        buttons.accepted.connect(self.save);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        self.draw_timer=QtCore.QTimer(self);self.draw_timer.setSingleShot(True);self.draw_timer.setInterval(20);self.draw_timer.timeout.connect(self.render)
        self.preview_timer=QtCore.QTimer(self);self.preview_timer.setSingleShot(True);self.preview_timer.setInterval(400);self.preview_timer.timeout.connect(self.finish_and_preview)
        self.rebuild_regions();self.render();QtCore.QTimer.singleShot(0,self.request_preview)

    def snapshot(self):
        return dict(regions=copy.deepcopy(self.candidate.rhythm_regions),nodes=self.candidate.node_speeds.copy(),
            segments=self.candidate.segment_speeds.copy(),positions=self.candidate.speed_positions.copy())
    def remember(self):
        before=self.history[-1];after=self.snapshot()
        if before['regions']!=after['regions'] or not np.array_equal(before['nodes'],after['nodes']) or not np.array_equal(before['segments'],after['segments']):self.history.append(after)
        self.history=self.history[-100:]
    def region(self):
        return next((r for r in self.candidate.rhythm_regions if r['id']==self.selected_region),None)
    def selection_bounds(self):
        if len(self.selection)<2:raise ValueError('请先在路径图中框选至少两个有效点')
        return float(self.node_progress[min(self.selection)]),float(self.node_progress[max(self.selection)])
    def select_rect(self,bounds,add=False):
        found=selected_in_rect(self.candidate.nodes,bounds)&set(np.flatnonzero(self.candidate.node_enabled))
        self.selection=self.selection|found if add else found;self.selected_region=None;self.render()
    def click_point(self,k,add=False):
        self.selection=(self.selection^{k}) if add else {k};self.selected_region=None;self.render()
    def add_region(self,label,ratio=None):
        try:
            start,end=self.selection_bounds()
            row=dict(id=uuid.uuid4().hex,start=start,end=end,label=label,ratio=float(PRESETS[label] if ratio is None else ratio))
            validate_regions([row])
            self.candidate.rhythm_regions.append(row);self.selected_region=row['id'];self.rebuild_regions();self.mark_changed();self.finish_edit()
        except Exception as exc:self.error.setText(str(exc))
    def rebuild_regions(self):
        self.loading=True;self.regions.clear()
        for row in self.candidate.rhythm_regions:
            self.regions.addItem(f'{row["label"]} · {row["ratio"]*100:.0f}% · 路径{row["start"]*100:.1f}–{row["end"]*100:.1f}%')
        for band in self.bands:self.speed_plot.removeItem(band)
        self.bands=[]
        for i,row in enumerate(self.candidate.rhythm_regions):
            color=pg.mkColor(COLORS[row['label']]);color.setAlpha(35)
            band=pg.LinearRegionItem(values=[row['start']*self.length,row['end']*self.length],bounds=(0,self.length),swapMode='block',brush=color)
            band.setZValue(-5);self.speed_plot.addItem(band);self.bands.append(band)
            band.sigRegionChanged.connect(lambda item,i=i:self.band_changed(i,item))
            band.sigRegionChangeFinished.connect(self.finish_edit)
        index=next((i for i,r in enumerate(self.candidate.rhythm_regions) if r['id']==self.selected_region),-1)
        self.regions.setCurrentRow(index);self.loading=False;self.choose_region(index)
    def choose_region(self,index):
        if self.loading:return
        self.selected_region=self.candidate.rhythm_regions[index]['id'] if 0<=index<len(self.candidate.rhythm_regions) else None
        self.render()
    def band_changed(self,index,band):
        if self.loading:return
        start,end=np.array(band.getRegion())/self.length
        if end-start<1e-5:
            row=self.candidate.rhythm_regions[index];band.blockSignals(True);band.setRegion([row['start']*self.length,row['end']*self.length]);band.blockSignals(False);return
        row=self.candidate.rhythm_regions[index];row.update(start=float(start),end=float(end));self.selected_region=row['id']
        self.loading=True;self.regions.setCurrentRow(index);self.loading=False
        self.mark_changed()
    def change_ratio(self,value):
        if self.loading or self.region() is None:return
        self.region()['ratio']=value/100.;self.mark_changed()
        if not self.ratio.isSliderDown():self.preview_timer.start()
    def mark_changed(self):
        self.revision+=1;self.actual=None;self.actual_curve.setData([],[])
        self.error.setText('节奏已修改，正在显示请求；停止拖动后自动检查完整轨迹。')
        if not self.draw_timer.isActive():self.draw_timer.start()
    def finish_edit(self,*args):
        self.draw_timer.stop();self.remember();self.render();self.preview_timer.start()
    def finish_and_preview(self):
        self.remember();self.render();self.request_preview()
    def copy_region(self):
        row=self.region()
        if row:self.clipboard=(row['label'],row['ratio']);self.error.setText('已复制节奏类型和强度；框选新区域后点击“粘贴到选区”。')
    def paste_region(self):
        if self.clipboard:self.add_region(*self.clipboard)
        else:self.error.setText('请先选择一个节奏区域并复制。')
    def delete_region(self):
        if self.region() is None:return
        self.candidate.rhythm_regions=[r for r in self.candidate.rhythm_regions if r['id']!=self.selected_region]
        self.selected_region=None;self.rebuild_regions();self.mark_changed();self.finish_edit()
    def reset_regions(self):
        self.candidate.rhythm_regions=[];self.selected_region=None;self.rebuild_regions();self.mark_changed();self.finish_edit()
    def undo(self):
        if len(self.history)<2:return
        self.history.pop();state=self.history[-1];self.candidate.rhythm_regions=copy.deepcopy(state['regions'])
        self.candidate.node_speeds=state['nodes'].copy();self.candidate.segment_speeds=state['segments'].copy();self.candidate.speed_positions=state['positions'].copy()
        self.selected_region=None;self.reference=None;self.rebuild_regions();self.mark_changed();self.render();self.preview_timer.start()
    def render(self):
        row=self.region()
        try:a,b=(row['start'],row['end']) if row else self.selection_bounds()
        except ValueError:a=b=0.
        p=self.candidate.points();d=arc(p)/self.length;mask=(d>=a)&(d<=b)
        q=np.unique(np.r_[a,d[mask],b]) if b>a else np.array([])
        self.highlight.setData(np.interp(q,d,p[:,0]),np.interp(q,d,p[:,1]))
        for k,handle in enumerate(self.handles):handle.setBrush('#60a5fa' if k in self.selection else '#f6c65a')
        offset=self.candidate.stroke_node_offset()
        self.selection_note.setText(f'当前选区：点 {offset+min(self.selection)}–{offset+max(self.selection)}（包含中间连续路径）' if len(self.selection)>=2 else '请框选至少两个点，或按住Ctrl逐个选点。')
        self.loading=True;self.ratio.setEnabled(row is not None)
        if row:self.ratio.setValue(round(row['ratio']*100));self.ratio_label.setText(f'{row["label"]}强度：参考速度的 {row["ratio"]*100:.0f}%')
        else:self.ratio_label.setText('选择或创建节奏区域后调整滑块')
        for i,region in enumerate(self.candidate.rhythm_regions):
            self.regions.item(i).setText(f'{region["label"]} · {region["ratio"]*100:.0f}% · 路径{region["start"]*100:.1f}–{region["end"]*100:.1f}%')
        self.loading=False
        if self.reference is None:self.stats.setText('参考规划计算中；当前尚无新的耗时和速度估计。');return
        timing=self.reference['reference'];lo,hi=self.reference['lo'],self.reference['hi']
        regions=[dict(r,start=(max(lo,r['start'])-lo)/(hi-lo),end=(min(hi,r['end'])-lo)/(hi-lo)) for r in self.candidate.rhythm_regions if min(hi,r['end'])-max(lo,r['start'])>=(hi-lo)*1e-5]
        knots=rhythm_knots(timing,regions);x=self.length*(lo+(hi-lo)*knots[:,0])
        self.request_curve.setData(x,knots[:,1]);ref=np.array(timing['speed_knots_s_mm_s']);self.reference_curve.setData(self.length*(lo+(hi-lo)*ref[:,0]),ref[:,1])
        if self.actual is not None:
            self.actual_curve.setData(self.actual['actual_distance'],self.actual['actual_speed'])
            duration=float(np.interp(b,self.actual['progress'],self.actual['t'])-np.interp(a,self.actual['progress'],self.actual['t']))
            mask=(self.actual['actual_distance']>=a*self.length)&(self.actual['actual_distance']<=b*self.length)
            values=self.actual['actual_speed'][mask]
            speed=f'{values.min():.2f}–{values.max():.2f} mm/s' if len(values) else '选区内不足一个采样间隔'
            self.stats.setText(f'选区预计耗时：{duration:.2f} s；预检后速度：{speed}\n全部笔画书写：{self.actual["writing_duration"]:.2f} s；含悬空转移共：{self.actual["total_duration"]:.2f} s')
        else:
            selected=np.unique(np.r_[a*self.length,x[(x>a*self.length)&(x<b*self.length)],b*self.length])
            speed=np.interp(selected,x,knots[:,1]);estimate=float(np.sum(np.diff(selected)*(1/speed[:-1]+1/speed[1:])*.5))
            self.stats.setText(f'选区请求估计：约 {estimate:.2f} s；实际速度和全部耗时等待完整预检。')
    def request_preview(self):
        if self._closed:return
        self.preview_timer.stop()
        if self._worker is not None:self._preview_again=True;return
        self.error.setText('后台预检中：参考规划缓存按XY、磁目标、笔杆角度和设备配置自动失效。')
        worker=PreviewWorker(copy.deepcopy(self.candidate),self.revision);self._worker=worker;_RUNNING_PREVIEWS.add(worker)
        worker.resultReady.connect(self.preview_ready);worker.finished.connect(self.preview_finished)
        worker.finished.connect(lambda worker=worker:_RUNNING_PREVIEWS.discard(worker));worker.finished.connect(worker.deleteLater);worker.start()
    def preview_ready(self,revision,result):
        if self._closed or revision!=self.revision:return
        if 'error' in result:self.actual=None;self.error.setText('预检未通过：'+result['error']);return
        self.reference=result;self.actual=result;self.render()
        reasons=slowdown_reasons(result['report'])
        self.error.setText('完整多笔轨迹预检通过。'+('局部降速原因：'+'、'.join(reasons)+'。' if reasons else '当前节奏通过既有限值。')+'顿笔通过短区间减速实现，没有新增原地停留。')
    def preview_finished(self):
        self._worker=None
        if self._preview_again and not self._closed:self._preview_again=False;self.request_preview()
    def open_advanced(self):
        if self.advanced_factory is None:return
        dialog=self.advanced_factory(self.candidate,max(0,min(self.selection,default=0)),self)
        if dialog.exec_()!=W.QDialog.Accepted:return
        self.candidate.node_speeds=dialog.candidate.node_speeds.copy();self.candidate.segment_speeds=dialog.candidate.segment_speeds.copy();self.candidate.speed_positions=dialog.candidate.speed_positions.copy()
        self.reference=None;self.mark_changed();self.finish_edit()
    def save(self):
        try:validate_regions(self.candidate.rhythm_regions);self.accept()
        except Exception as exc:self.error.setText('未保存：'+str(exc))
    def done(self,result):
        self._closed=True;self.draw_timer.stop();self.preview_timer.stop();super().done(result)
