"""Interactive saved-PCA inspection; filters never fit or move sample coordinates."""
from pathlib import Path
import numpy as np
from PyQt5 import QtWidgets as W,QtCore as C
from .plots import Plot
from .theme import COLORS


class SpaceExplorer(W.QWidget):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.bundle=None;self.predictions={};self.new=None;self.selected_index=None;self.camera=(30,-60);self.rendered_three=False;self.run_names={}
        layout=W.QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(7)
        row=W.QHBoxLayout()
        self.dimension=W.QComboBox();self.dimension.addItems(['二维投影','可旋转三维投影'])
        self.plane=W.QComboBox();self.plane.addItems(['PC1–PC2','PC1–PC3','PC2–PC3'])
        self.branch=W.QComboBox();self.branch.addItems(['幅值分支','方向分支']);self.branch.hide()
        self.run=W.QComboBox();self.run.addItem('高亮实验：全部',None);self.run.setToolTip('高亮所选实验，其余实验变淡以保留分布背景')
        for item in (self.dimension,self.plane,self.branch,self.run):row.addWidget(item)
        reset=W.QPushButton('重置视角');reset.clicked.connect(self.reset_view);row.addWidget(reset)
        self.front=W.QComboBox();self.front.addItems(['3D正视方向…','PC1–PC2','PC1–PC3','PC2–PC3']);self.front.currentIndexChanged.connect(self.front_view);row.addWidget(self.front);layout.addLayout(row)
        row=W.QHBoxLayout();self.class_checks=[]
        self.class_row=row
        self.only_errors=W.QCheckBox('仅看留出错分');self.supports=W.QCheckBox('支持向量')
        row.addWidget(self.only_errors);row.addWidget(self.supports)
        self.size=W.QSlider(C.Qt.Horizontal);self.size.setRange(15,90);self.size.setValue(38);self.size.setMaximumWidth(75)
        self.opacity=W.QSlider(C.Qt.Horizontal);self.opacity.setRange(10,100);self.opacity.setValue(80);self.opacity.setMaximumWidth(75)
        row.addWidget(W.QLabel('大小'));row.addWidget(self.size);row.addWidget(W.QLabel('透明度'));row.addWidget(self.opacity);row.addStretch();layout.addLayout(row)
        self.legend_row=W.QHBoxLayout();layout.addLayout(self.legend_row)
        split=W.QSplitter();self.plot=Plot(toolbar=True);split.addWidget(self.plot)
        right=W.QWidget();rl=W.QVBoxLayout(right);rl.setContentsMargins(6,0,0,0)
        self.samples=W.QComboBox();self.samples.setSizeAdjustPolicy(W.QComboBox.AdjustToMinimumContentsLengthWithIcon);self.samples.setMinimumContentsLength(12)
        rl.addWidget(self.samples)
        self.details=W.QLabel('点击样本或从列表选择，查看曲线与留出预测。');self.details.setWordWrap(True);self.details.setTextInteractionFlags(C.Qt.TextSelectableByMouse);rl.addWidget(self.details)
        self.detail_tabs=W.QTabWidget();self.curve=Plot();self.scores=Plot()
        curve_page=W.QWidget();cl=W.QVBoxLayout(curve_page);cl.setContentsMargins(0,0,0,0)
        self.curve_mode=W.QComboBox();self.curve_mode.addItems(['基准扣除后幅值','相邻差分'])
        cl.addWidget(self.curve_mode);cl.addWidget(self.curve)
        self.detail_tabs.addTab(curve_page,'磁响应');self.detail_tabs.addTab(self.scores,'逐类分数');rl.addWidget(self.detail_tabs,1)
        split.addWidget(right);split.setSizes([760,320]);layout.addWidget(split,1)
        self.footer=W.QLabel('投影用于观察特征分布，不是完整决策边界；分类仍使用完整特征。');self.footer.setWordWrap(True);self.footer.setObjectName('muted');layout.addWidget(self.footer)
        self.plot.pointSelected.connect(self.select_sample);self.plot.classToggled.connect(self.toggle_class)
        for control in (self.dimension,self.plane,self.branch,self.run):control.currentIndexChanged.connect(self.redraw)
        for control in (self.only_errors,self.supports):control.toggled.connect(self.redraw)
        self.size.valueChanged.connect(self.redraw);self.opacity.valueChanged.connect(self.redraw)
        self.samples.currentIndexChanged.connect(self.sample_from_list);self.curve_mode.currentIndexChanged.connect(self.show_details)

    def set_source(self,bundle,predictions=None,new=None,run_names=None):
        changed=self.bundle is not bundle
        if new is not self.new:self.selected_index=None
        self.bundle=bundle;self.new=new
        if run_names is not None:self.run_names=run_names
        elif changed:self.run_names={s.run_id:Path(s.source_metadata.get('path',s.run_id)).stem for s in bundle['training_strokes']}
        if predictions is not None:self.predictions={(p['run_id'],p['stroke']):p for p in predictions}
        elif changed:self.predictions={}
        if changed:
            self.selected_index=None;self.camera=(30,-60);self.rendered_three=False
            self.details.setText('点击样本或从列表选择，查看曲线与留出预测。')
            self.curve.empty('选择样本查看磁响应曲线');self.scores.empty('选择样本查看留出判别分数')
            self.branch.setVisible(bundle['model'].candidate.family=='F3')
            self.branch.blockSignals(True);self.branch.setCurrentIndex(0);self.branch.blockSignals(False)
            for check in self.class_checks:
                self.legend_row.removeWidget(check);check.deleteLater()
            self.class_checks=[]
            for i,name in enumerate(bundle['labels']):
                check=W.QCheckBox(name);check.setStyleSheet(f'color: {COLORS[i]};');check.setChecked(True);check.toggled.connect(self.redraw)
                self.class_checks.append(check);self.legend_row.addWidget(check)
            self.run.blockSignals(True);self.run.clear();self.run.addItem('高亮实验：全部',None)
            for run in sorted({s.run_id for s in bundle['training_strokes']}):self.run.addItem(self.run_names.get(run,run),run)
            self.run.blockSignals(False)
        self.only_errors.setEnabled(bool(self.predictions));self.redraw()
        if new:self.show_new_details()

    def errors(self):
        return np.array([self.predictions.get((s.run_id,s.index),{}).get('predicted',s.label)!=s.label for s in self.bundle['training_strokes']])

    def visible_indices(self):
        if self.bundle is None:return np.array([],dtype=int)
        selected=[i for i,c in enumerate(self.class_checks) if c.isChecked()]
        mask=np.isin([s.label for s in self.bundle['training_strokes']],selected)
        if self.only_errors.isChecked() and self.predictions:mask &= self.errors()
        return np.flatnonzero(mask)

    def toggle_class(self,index):
        if 0<=index<len(self.class_checks):self.class_checks[index].toggle()

    def redraw(self,*args):
        if self.bundle is None:return
        if self.rendered_three and self.plot.figure.axes:
            ax=self.plot.figure.axes[0]
            if hasattr(ax,'elev'):self.camera=(ax.elev,ax.azim)
        three=self.dimension.currentIndex()==1;self.plane.setEnabled(not three);self.front.setEnabled(three)
        branch=self.branch.currentIndex() if self.bundle['model'].candidate.family=='F3' else 0
        new=self.new['branch_projections'][branch] if self.new else None
        visible=np.zeros(len(self.bundle['training_strokes']),dtype=bool);visible[self.visible_indices()]=True
        self.plot.space(self.bundle,three,new,branch,plane=((0,1),(0,2),(1,2))[self.plane.currentIndex()],
            visible=visible,highlighted_run=self.run.currentData(),errors=self.errors(),selected=self.selected_index,
            supports_visible=self.supports.isChecked(),size=self.size.value(),opacity=self.opacity.value()/100,view=self.camera)
        self.rendered_three=three
        self.samples.blockSignals(True);self.samples.clear();self.samples.addItem('查看新样本 ★' if self.new else '选择图中样本…',None)
        for i in self.visible_indices():
            s=self.bundle['training_strokes'][i];wrong=' ×' if self.errors()[i] else ''
            self.samples.addItem(f'{self.run_names.get(s.run_id,s.run_id)} · 第{s.index}笔 · {self.bundle["labels"][s.label]}{wrong}',int(i))
        if self.selected_index is not None:
            index=self.samples.findData(self.selected_index)
            self.samples.setCurrentIndex(max(0,index))
            if index<0:self.selected_index=None;self.details.setText('所选样本已被筛选隐藏，请重新选择。');self.curve.empty('选择一个可见样本');self.scores.empty('选择一个可见样本')
        self.samples.blockSignals(False)
        self.footer.setText(f'显示 {int(visible.sum())}/{len(visible)} 笔 · 颜色＝真实类别，×＝留出错分，星形＝新样本。\n点的位置来自最终模型PCA；错分来自当轮留出预测。投影重叠不代表分类失败，投影分开也不保证新实验识别正确。')

    def reset_view(self):
        self.camera=(30,-60);self.rendered_three=False;self.redraw()

    def front_view(self,index):
        if index==0:return
        self.camera=((90,-90),(0,-90),(0,0))[index-1];self.rendered_three=False;self.redraw()
        self.front.blockSignals(True);self.front.setCurrentIndex(0);self.front.blockSignals(False)

    def sample_from_list(self,*args):
        index=self.samples.currentData()
        if index is not None:self.select_sample(index)
        elif self.new:
            self.selected_index=None;self.redraw();self.show_new_details()

    def select_sample(self,index):
        if index not in self.visible_indices():return
        self.selected_index=int(index);self.redraw();self.show_details()

    def show_details(self,*args):
        if self.bundle is None:return
        if self.selected_index is None:
            if self.new:self.show_new_details()
            return
        s=self.bundle['training_strokes'][self.selected_index];p=self.predictions.get((s.run_id,s.index));name=self.bundle['labels'][s.label]
        text=f'实验：{self.run_names.get(s.run_id,s.run_id)}\n第{s.index}笔 · 真实类别：{name}'
        if p:
            text+=f'\n留出预测：{self.bundle["labels"][p["predicted"]]} · '+('正确' if p['predicted']==s.label else '错分')
            self.scores.scores(p['scores'],p['predicted'])
        else:self.scores.empty('未提供该样本的留出判别分数')
        self.details.setText(text+'\n分数不是概率；留出预测来自当轮模型。')
        self.curve.curve(s,'difference' if self.curve_mode.currentIndex()==1 else 'processed')

    def show_new_details(self):
        p=self.new
        if not p:return
        self.details.setText(f'新样本：{p["run_id"]} · 第{p["stroke"]}笔\n最终模型预测：{self.bundle["labels"][p["predicted"]]}\n星形位置使用保存的PCA变换。分数不是概率。')
        self.scores.scores(p['scores'],p['predicted'])
        # The caller may provide a raw stroke for the linked curve, without refitting anything.
        if hasattr(self,'new_stroke') and self.new_stroke is not None:self.curve.curve(self.new_stroke,'difference' if self.curve_mode.currentIndex()==1 else 'processed')
        else:self.curve.empty('点击训练样本查看其磁响应曲线')

    def empty(self,message):
        self.bundle=None;self.new=None;self.selected_index=None;self.plot.empty(message);self.curve.empty(message);self.scores.empty(message);self.details.setText(message)
