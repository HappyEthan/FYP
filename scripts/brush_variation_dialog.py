"""Advanced random-variation settings and offline planning previews."""
import copy
import numpy as np
from PyQt5 import QtCore,QtWidgets as W
import pyqtgraph as pg
from brushbot.experiments.stroke_variation import DEFAULT_PARAMETERS
from brushbot.planning import cancellable_planning, PlanningCancelled


_RUNNING_PREVIEWS = set()


def _finish_workers_on_exit():
    for worker in list(_RUNNING_PREVIEWS):
        worker.requestInterruption()
    for worker in list(_RUNNING_PREVIEWS):
        worker.wait()


class VariationPreviewWorker(QtCore.QThread):
    """Compile a detached candidate; widgets are only updated on the GUI thread."""
    def __init__(self, model):
        super().__init__()
        self.model = model
        self.result = None
        self.error = None

    def run(self):
        try:
            with cancellable_planning(self.isInterruptionRequested):
                self.result = self.model.compile_workspace()
        except PlanningCancelled:
            self.error = '预检已取消'
        except Exception as exc:
            self.error = str(exc)


class VariationDialog(W.QDialog):
    def __init__(self,model,parent=None):
        super().__init__(parent)
        self.candidate=copy.deepcopy(model);self.last_result=None;self._loading=True
        self._worker=None;self._closed=False;self._apply_when_ready=False
        app=W.QApplication.instance()
        if not getattr(app,'_brush_variation_shutdown_hook',False):
            app.aboutToQuit.connect(_finish_workers_on_exit)
            app._brush_variation_shutdown_hook=True
        self.setWindowTitle('随机变化');self.resize(1120,740);self.setMinimumSize(900,600)
        outer=W.QVBoxLayout(self)
        note=W.QLabel('每次生成重新随机抽样；数值是幅度上限。路径首尾固定，只改变笔内形状。\n预览、导出与试写使用同一份结果；这里显示规划路径和磁目标，实测响应需实际采集。')
        note.setWordWrap(True);outer.addWidget(note)
        row=W.QHBoxLayout();outer.addLayout(row,1)
        controls=W.QWidget();controls.setMaximumWidth(350);form=W.QVBoxLayout(controls);row.addWidget(controls)
        self.enabled=W.QCheckBox('启用随机变化');self.xy_enabled=W.QCheckBox('路径 XY 随机变化');self.magnetic_enabled=W.QCheckBox('磁目标随机变化')
        config=getattr(model,'random_variation',None) or {};options=config.get('options',{})
        for box,key,default in [(self.enabled,'enabled',False),(self.xy_enabled,'xy_enabled',True),(self.magnetic_enabled,'magnetic_enabled',True)]:
            box.setChecked(options.get(key,default));form.addWidget(box);box.toggled.connect(self.sync_options)
        params=config.get('parameters',DEFAULT_PARAMETERS);self.fields={};grid=W.QFormLayout();form.addLayout(grid)
        for key,label,percentage in [('xy_relative_max','路径相对上限 (%)',True),('xy_absolute_max_mm','路径绝对上限 (mm)',False),
                                     ('magnetic_global_max','整笔磁目标上限 (%)',True),('magnetic_local_max','局部磁目标上限 (%)',True)]:
            spin=W.QDoubleSpinBox();spin.setDecimals(3);spin.setRange(0.,49. if key.startswith('magnetic') else 100.);spin.setSingleStep(.1 if percentage else .01)
            spin.setValue(params[key]*(100 if percentage else 1));spin.setProperty('percentage',percentage)
            self.fields[key]=spin;grid.addRow(label,spin);spin.valueChanged.connect(self.sync_options)
        self.generate_button=W.QPushButton('生成本次变化');self.generate_button.clicked.connect(self.generate);form.addWidget(self.generate_button)
        self.preview_button=W.QPushButton('预检并更新预览');self.preview_button.clicked.connect(self.preview);form.addWidget(self.preview_button)
        self.seed=W.QLineEdit();self.seed.setReadOnly(True);self.seed.setPlaceholderText('尚未生成');form.addWidget(W.QLabel('本次随机种子'));form.addWidget(self.seed)
        self.stroke_box=W.QComboBox()
        for key,name in model.stroke_entries():self.stroke_box.addItem(name,key)
        self.stroke_box.setCurrentIndex(max(0,model.stroke_order.index(model.stroke_id)))
        self.stroke_box.currentIndexChanged.connect(self.draw_result);form.addWidget(W.QLabel('查看笔画'));form.addWidget(self.stroke_box)
        self.status=W.QLabel();self.status.setWordWrap(True);form.addWidget(self.status)
        self.statistics=W.QLabel();self.statistics.setWordWrap(True);form.addWidget(self.statistics);form.addStretch()
        tabs=W.QTabWidget();row.addWidget(tabs,1)
        self.path_plot=pg.PlotWidget(background='#faf9f4');self.path_plot.setAspectLocked(True);self.path_plot.addLegend()
        self.path_plot.setLabel('bottom','纸面 X',units='mm');self.path_plot.setLabel('left','纸面 Y',units='mm')
        self.path_before=self.path_plot.plot(pen=pg.mkPen('#8b949e',width=2,style=QtCore.Qt.DashLine),name='标准路径')
        self.path_after=self.path_plot.plot(pen=pg.mkPen('#1473c9',width=2),name='本次规划路径')
        tabs.addTab(self.path_plot,'规划路径')
        self.target_plot=pg.PlotWidget(background='#faf9f4');self.target_plot.addLegend();self.target_plot.setLabel('bottom','归一化进度');self.target_plot.setLabel('left','磁响应目标',units='μT')
        self.target_curves={}
        for name,label,color,dash in [('standard_g_ff_uT','标准名义目标','#87919c',True),('execution_g_ff_uT','本次名义目标','#1473c9',False),
                                      ('standard_g_ref_uT','标准控制目标','#c9a27b',True),('execution_g_ref_uT','本次控制目标','#d47719',False)]:
            self.target_curves[name]=self.target_plot.plot(pen=pg.mkPen(color,width=2,style=QtCore.Qt.DashLine if dash else QtCore.Qt.SolidLine),name=label)
        tabs.addTab(self.target_plot,'磁响应目标')
        buttons=W.QDialogButtonBox(W.QDialogButtonBox.Apply|W.QDialogButtonBox.Cancel)
        self.apply_button=buttons.button(W.QDialogButtonBox.Apply)
        buttons.button(W.QDialogButtonBox.Apply).setText('应用设置');buttons.button(W.QDialogButtonBox.Apply).clicked.connect(self.accept)
        buttons.rejected.connect(self.reject);outer.addWidget(buttons)
        self._loading=False;self.sync_options()
        if self.candidate.variation_status()['state']=='ready':QtCore.QTimer.singleShot(0,self.preview)

    def sync_options(self,*args):
        if self._loading or self._worker is not None or self._closed:return
        try:
            parameters={key:spin.value()/(100 if spin.property('percentage') else 1) for key,spin in self.fields.items()}
            self.candidate.set_variation_options(enabled=self.enabled.isChecked(),xy_enabled=self.xy_enabled.isChecked(),magnetic_enabled=self.magnetic_enabled.isChecked(),parameters=parameters)
            state=self.candidate.variation_status();self.seed.setText(state.get('seed',''))
            messages=dict(off='已关闭：使用标准路径和标准磁目标。',missing='请生成本次随机变化。',stale='标准数据或参数已变化，请重新生成。',ready='已生成：可预检并查看实际生效幅度。')
            self.status.setText(messages[state['state']]);self.generate_button.setEnabled(self.enabled.isChecked())
            self.preview_button.setEnabled(state['state']=='ready')
            self.last_result=None;self.statistics.clear()
            self.path_after.setData([],[])
            for curve in self.target_curves.values():curve.setData([],[])
        except ValueError as exc:self.status.setText(str(exc));self.preview_button.setEnabled(False)

    def generate(self):
        if self._worker is not None or self._closed:return
        self.sync_options()
        try:
            if not self.enabled.isChecked() or not (self.xy_enabled.isChecked() or self.magnetic_enabled.isChecked()):raise ValueError('请启用随机变化，并至少选择一项')
            self.candidate.generate_variation();self.preview()
        except ValueError as exc:self.status.setText('未生成：'+str(exc))

    def preview(self):
        if self._worker is not None or self._closed:return
        self.last_result=None
        self.statistics.clear()
        self.path_after.setData([],[])
        for curve in self.target_curves.values():curve.setData([],[])
        self.status.setText('正在后台预检全部笔画；可取消，预检通过后才能应用。')
        worker=VariationPreviewWorker(copy.deepcopy(self.candidate))
        self._worker=worker;_RUNNING_PREVIEWS.add(worker)
        self.set_busy(True)
        worker.finished.connect(self.preview_finished)
        worker.finished.connect(lambda worker=worker:_RUNNING_PREVIEWS.discard(worker))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def set_busy(self,busy):
        for widget in (self.enabled,self.xy_enabled,self.magnetic_enabled,*self.fields.values(),self.apply_button):
            widget.setEnabled(not busy)
        self.generate_button.setEnabled(not busy and self.enabled.isChecked())
        self.preview_button.setEnabled(not busy and self.candidate.variation_status()['state']=='ready')

    def preview_finished(self):
        worker=self._worker;self._worker=None
        if self._closed:return
        self.set_busy(False)
        try:
            if worker.error is not None:raise ValueError(worker.error)
            self.candidate=worker.model;self.last_result=worker.result
            self.seed.setText(self.candidate.variation_status().get('seed',''))
            self.preview_button.setEnabled(True);self.status.setText('完整预检通过；当前结果已冻结，导出与试写不会重新抽样。')
            self.draw_result()
            if self._apply_when_ready:super().accept()
        except (ValueError,KeyError,TypeError) as exc:
            self.last_result=None;self.status.setText('预检未通过：'+str(exc))
        finally:self._apply_when_ready=False

    def draw_result(self,*args):
        if self.last_result is None:return
        key=self.stroke_box.currentData();arrays=self.candidate._variation_arrays
        before=arrays[key+'_standard_xy_mm'];after=arrays[key+'_execution_xy_mm']
        self.path_before.setData(before[:,0],before[:,1]);self.path_after.setData(after[:,0],after[:,1])
        for suffix,curve in self.target_curves.items():
            prefix=suffix.split('_g_')[0]
            curve.setData(arrays[key+'_'+prefix+'_s'],arrays[key+'_'+suffix])
        stat=self.candidate.last_variation['statistics'][key];scale=self.candidate.last_variation['scales'][key]
        self.statistics.setText(f"实际最大路径偏移：{stat['max_displacement_mm']:.4f} mm\n实际最大磁目标变化：{100*stat['max_magnetic_relative_change']:.3f}%\n路径生效比例：{scale['xy']:.4g}\n磁目标生效比例：{scale['magnetic']:.4g}"+ ('\n缩小原因：'+scale['reasons'][-1] if scale['reasons'] else ''))

    def accept(self):
        if self._worker is not None or self._closed:return
        if self.enabled.isChecked() and self.last_result is None:
            self._apply_when_ready=True;self.preview();return
        super().accept()

    def done(self,result):
        self._closed=True
        if self._worker is not None:self._worker.requestInterruption()
        super().done(result)
