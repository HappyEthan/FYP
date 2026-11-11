"""Standalone five-page magnetic classification workbench."""
from dataclasses import asdict,replace
from datetime import datetime
import json
from pathlib import Path
import uuid

import numpy as np
from PyQt5 import QtWidgets as W,QtCore as C,QtGui as G

from . import LABELS,FAMILIES
from .data import unique_experiments,load_single_csv
from .features import FeatureConfig
from .jobs import ImportThread,TrainingProcess
from .plots import Plot
from .predict import predict_strokes
from .store import ModelStore,write_json
from .theme import STYLE
from .training import TrainConfig
from .analysis_ui import AnalysisPanel
from .space_ui import SpaceExplorer


class ExperimentDirectoryDialog(W.QFileDialog):
    """Qt directory picker with Ctrl/Shift selection of several experiments."""
    def __init__(self,parent=None,directory=''):
        super().__init__(parent,'选择实验目录（Ctrl / Shift 多选）',directory)
        self.setOption(W.QFileDialog.DontUseNativeDialog,True)
        self.setFileMode(W.QFileDialog.Directory)
        self.setOption(W.QFileDialog.ShowDirsOnly,True)
        self.setLabelText(W.QFileDialog.Accept,'导入选中目录')
        for view in self.findChildren(W.QListView)+self.findChildren(W.QTreeView):
            if isinstance(view.model(),W.QFileSystemModel):
                view.setSelectionMode(W.QAbstractItemView.ExtendedSelection)

    def accept(self):
        paths=self.selectedFiles()
        if paths and all(Path(path).is_dir() for path in paths):
            # QFileDialog's default accept navigates into a selected directory.
            W.QDialog.accept(self)


def label(text,name=None):
    item=W.QLabel(text)
    if name:item.setObjectName(name)
    item.setWordWrap(True)
    return item


def button(text,callback=None,primary=False):
    item=W.QPushButton(text);item.setCursor(C.Qt.PointingHandCursor)
    if primary:item.setObjectName('primary')
    if callback:item.clicked.connect(callback)
    return item


def table(headers):
    item=W.QTableWidget(0,len(headers));item.setHorizontalHeaderLabels(headers)
    item.verticalHeader().hide();item.setAlternatingRowColors(True)
    item.setSelectionBehavior(W.QAbstractItemView.SelectRows)
    item.setSelectionMode(W.QAbstractItemView.SingleSelection)
    item.setEditTriggers(W.QAbstractItemView.NoEditTriggers)
    item.horizontalHeader().setSectionResizeMode(W.QHeaderView.Stretch)
    item.verticalHeader().setDefaultSectionSize(44)
    return item


def set_row(widget,row,values):
    for col,value in enumerate(values):
        item=W.QTableWidgetItem(str(value));item.setToolTip(str(value));widget.setItem(row,col,item)


def panel(title=None):
    frame=W.QFrame();frame.setObjectName('panel')
    layout=W.QVBoxLayout(frame);layout.setContentsMargins(17,16,17,16);layout.setSpacing(12)
    if title:layout.addWidget(label(title,'section'))
    return frame,layout


def scroll_page(widget):
    area=W.QScrollArea();area.setWidgetResizable(True);area.setFrameShape(W.QFrame.NoFrame)
    widget.setObjectName('scrollPage');widget.setStyleSheet('QWidget#scrollPage { background:#0d121c; }')
    area.setWidget(widget)
    return area


class AdvancedDialog(W.QDialog):
    def __init__(self,config,parent=None):
        super().__init__(parent);self.setWindowTitle('高级训练设置');self.resize(560,680)
        self.config=config;layout=W.QVBoxLayout(self)
        layout.addWidget(label('候选参数只在每轮训练数据内部选择。','muted'))
        form=W.QFormLayout();layout.addLayout(form)
        self.fields={}
        for key,title,values in [('cs','C候选',config.cs),('gammas','RBF gamma候选',config.gammas),
                                 ('direction_weights','F2方向权重候选',config.direction_weights if config.direction_weights is not None else config.weights),
                                 ('difference_weights','F4差分权重候选',config.difference_weights if config.difference_weights is not None else config.weights),
                                 ('late_weights','F3分数融合幅值权重',config.late_weights)]:
            edit=W.QLineEdit(', '.join(map(str,values)));self.fields[key]=edit;form.addRow(title,edit)
        self.kernel_checks={};row=W.QHBoxLayout()
        for k in ('linear','rbf'):
            check=W.QCheckBox(k);check.setChecked(k in config.kernels);row.addWidget(check);self.kernel_checks[k]=check
        form.addRow('分类器核',row)
        self.rep_checks={}
        for title,names,selected in [('幅值表示',('A0','A1','A2','A4'),config.amplitudes),('方向表示',('D1','D2','D3'),config.directions)]:
            row=W.QHBoxLayout()
            for key in names:
                check=W.QCheckBox(key);check.setChecked(key in selected);row.addWidget(check);self.rep_checks[key]=check
            form.addRow(title,row)
        self.alpha=W.QDoubleSpinBox();self.alpha.setRange(.01,1);self.alpha.setSingleStep(.05);self.alpha.setValue(config.feature_config.alpha)
        self.threshold=W.QDoubleSpinBox();self.threshold.setRange(.01,1000);self.threshold.setValue(config.feature_config.direction_threshold);self.threshold.setSuffix(' µT')
        self.coverage=W.QDoubleSpinBox();self.coverage.setRange(.5,1);self.coverage.setSingleStep(.01);self.coverage.setValue(config.feature_config.direction_coverage)
        form.addRow('EMA系数',self.alpha);form.addRow('方向幅值阈值',self.threshold);form.addRow('方向有效覆盖下限',self.coverage)
        self.robust=W.QCheckBox('执行数学偏移／相对方向旋转对照');self.robust.setChecked(config.robustness);layout.addWidget(self.robust)
        layout.addWidget(label('时间轴固定128点。基准采用每笔前10%原生EMA中位数扣除。A3缺少独立共同参考响应，暂不启用。','notice'))
        layout.addWidget(label('A0 原水平 · A1 扣基准 · A2 形状 · A4 相邻差分\nD1 相对角 · D2 相邻转角 · D3 相对方向sin/cos','muted'))
        self.error=label('');layout.addWidget(self.error);layout.addStretch()
        buttons=W.QDialogButtonBox(W.QDialogButtonBox.Ok|W.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)

    def accept(self):
        try:
            vals={k:tuple('scale' if x.strip()=='scale' else float(x.strip()) for x in v.text().split(',')) for k,v in self.fields.items()}
            self.result_config=replace(self.config,**vals,kernels=tuple(k for k,c in self.kernel_checks.items() if c.isChecked()),
                amplitudes=tuple(k for k in ('A0','A1','A2','A4') if self.rep_checks[k].isChecked()),
                directions=tuple(k for k in ('D1','D2','D3') if self.rep_checks[k].isChecked()),
                robustness=self.robust.isChecked(),feature_config=FeatureConfig(alpha=self.alpha.value(),
                direction_threshold=self.threshold.value(),direction_coverage=self.coverage.value())).validate()
        except (ValueError,TypeError) as exc:self.error.setText(str(exc));return
        super().accept()


class TrainerWindow(W.QMainWindow):
    def __init__(self,root,parent=None):
        super().__init__(parent);self.setWindowTitle('磁响应 · 笔画分类工作台')
        self.setStyleSheet(STYLE);self.resize(1420,900);self.setMinimumSize(1060,710)
        self.store=ModelStore(root);self.config=TrainConfig();self.experiments=[];self.import_jobs=[];self.failed_imports=[];self.recognition_generation=0
        self.recognition_experiments=[];self.single_strokes=[];self.predictions=[];self.recognition_strokes=[]
        self.loaded=None;self.bundle=None;self.result_bundle=None;self.result_task=None;self.result_model=None
        self.last_task_id=None;self.request_path=None;self.loading=False
        self.training_job=TrainingProcess(self);self.training_job.progressed.connect(self.on_progress);self.training_job.finished.connect(self.on_finished)
        outer=W.QWidget();self.setCentralWidget(outer);shell=W.QVBoxLayout(outer);shell.setContentsMargins(0,0,0,0);shell.setSpacing(0)
        body=W.QHBoxLayout();body.setSpacing(0);shell.addLayout(body,1)
        sidebar=W.QWidget();sidebar.setObjectName('sidebar');sidebar.setFixedWidth(196)
        sl=W.QVBoxLayout(sidebar);sl.setContentsMargins(12,24,12,18);sl.setSpacing(8)
        sl.addWidget(label('MAGNETIC LAB','eyebrow'));sl.addWidget(label('笔画分类','brand'));sl.addWidget(label('训练 · 观察 · 识别','muted'))
        self.navigation=W.QListWidget();self.navigation.setObjectName('navigation')
        for text in ('01    数据集','02    训练','03    训练结果','04    模型历史','05    模型识别'):self.navigation.addItem(text)
        sl.addWidget(self.navigation,1);sl.addWidget(label('七笔实验协议\n永字 → 横 → 竖','muted'))
        sl.addWidget(label('离线工作台\n原始实验只读','muted'));body.addWidget(sidebar)
        content=W.QWidget();cl=W.QVBoxLayout(content);cl.setContentsMargins(26,24,26,16);cl.setSpacing(14);body.addWidget(content,1)
        top=W.QHBoxLayout();self.page_title=label('数据集','title');top.addWidget(self.page_title);top.addStretch()
        top.addWidget(button('打开项目',self.open_project));top.addWidget(button('保存项目',self.save_project));cl.addLayout(top)
        self.page_subtitle=label('导入完整实验，选择参与训练的数据。','subtitle');cl.addWidget(self.page_subtitle)
        self.pages=W.QStackedWidget();cl.addWidget(self.pages,1)
        self.pages.addWidget(self.build_data());self.pages.addWidget(self.build_training());self.pages.addWidget(scroll_page(self.build_results()))
        self.pages.addWidget(self.build_history());self.pages.addWidget(scroll_page(self.build_prediction()))
        self.status=label('就绪 · 尚未启动训练','status');shell.addWidget(self.status)
        self.navigation.currentRowChanged.connect(self.navigate);self.navigation.setCurrentRow(0)
        self.refresh_history();self.update_selection()

    def navigate(self,index):
        titles=('数据集','训练','训练结果','模型历史','模型识别')
        subtitles=('导入后自动检查。勾选实验，再选择需要比较的模型。',
            '自由勾选模型方法；验证固定为整次实验留一。',
            '查看留出预测、错误来源及模型空间。',
            '一次训练，一条记录。展开查看、比较和加载模型。',
            '加载已保存模型，识别新实验或一条完整笔画。')
        if index<0:return
        self.pages.setCurrentIndex(index);self.page_title.setText(titles[index]);self.page_subtitle.setText(subtitles[index])

    def notify(self,text): self.status.setText(text)

    def error(self,text):
        self.notify(text);W.QMessageBox.warning(self,'操作未完成',str(text))

    def build_data(self):
        page=W.QWidget();layout=W.QVBoxLayout(page);layout.setContentsMargins(0,0,0,0);layout.setSpacing(14)
        row=W.QHBoxLayout();row.addWidget(button('＋ 导入实验',self.choose_import,True));row.addWidget(button('导入实验目录',self.choose_directory))
        row.addStretch();self.data_summary=label('未选择实验','section');row.addWidget(self.data_summary);layout.addLayout(row)
        split=W.QSplitter();layout.addWidget(split,1)
        left,ll=panel('实验清单');self.data_table=table(['使用','实验名称','笔数','状态'])
        self.data_table.horizontalHeader().setSectionResizeMode(0,W.QHeaderView.ResizeToContents)
        self.data_table.horizontalHeader().setSectionResizeMode(2,W.QHeaderView.ResizeToContents)
        self.data_table.itemChanged.connect(self.update_selection);self.data_table.itemSelectionChanged.connect(self.preview_data)
        ll.addWidget(self.data_table);split.addWidget(left)
        right,rl=panel('单笔曲线预览');r=W.QHBoxLayout()
        self.stroke_choice=W.QComboBox();self.stroke_choice.addItems([f'第{i+1}笔 · {l}' for i,l in enumerate(LABELS)])
        self.curve_mode=W.QComboBox();self.curve_mode.addItems(['实测幅值 EMA','基准扣除后幅值','相对方向'])
        r.addWidget(self.stroke_choice,1);r.addWidget(self.curve_mode);rl.addLayout(r)
        self.data_plot=Plot();rl.addWidget(self.data_plot,1);rl.addWidget(label('横轴：归一化时间0～1。模型只读取磁特征。','muted'))
        self.stroke_choice.currentIndexChanged.connect(self.preview_data);self.curve_mode.currentIndexChanged.connect(self.preview_data)
        split.addWidget(right);split.setSizes([490,570])
        self.import_diagnostics=label('七笔顺序：右点、横折钩、横撇、撇、捺、横、竖。','notice');layout.addWidget(self.import_diagnostics)
        row=W.QHBoxLayout();row.addStretch();row.addWidget(button('下一步：选择模型 →',lambda:self.navigation.setCurrentRow(1),True));layout.addLayout(row)
        return page

    def choose_import(self,recognition=False):
        paths,_=W.QFileDialog.getOpenFileNames(self,'选择实验存档',str(Path.cwd()/'runs/毛笔实验数据'),'实验存档 (*.brushrun)')
        if paths:self.import_paths(paths,recognition=bool(recognition))

    def choose_directory(self):
        dialog=ExperimentDirectoryDialog(self,str(Path.cwd()/'runs/毛笔实验数据'))
        if dialog.exec_()==W.QDialog.Accepted:
            self.import_paths(dialog.selectedFiles())

    def import_paths(self,paths,recognition=False,selected_paths=None):
        config=FeatureConfig(**self.bundle['feature_config']) if recognition and self.bundle else self.config.feature_config
        loaded_at_start=self.loaded;generation=self.recognition_generation
        count=(7,5) if recognition and self.bundle and len(self.bundle['labels'])==5 else 7
        job=ImportThread(paths,config,self,expected_count=count);self.import_jobs.append(job)
        self.notify('正在导入并自动检查实验…')
        def done(records,errors):
            if recognition:
                if self.loaded!=loaded_at_start or generation!=self.recognition_generation:
                    self.notify('导入期间模型已切换，本次待识别导入已丢弃，请重新添加');return
                try:self.recognition_experiments=unique_experiments(self.recognition_experiments+records)
                except ValueError as exc:errors.append(dict(path='重复来源',message=str(exc)))
                self.refresh_recognition_input()
            else:
                if config!=self.config.feature_config:
                    self.notify('导入期间预处理配置已改变，请重新导入');return
                success_paths={e.path for e in records}
                self.failed_imports=[e for e in self.failed_imports if str(Path(e['path']).resolve()) not in success_paths]
                known={e['path'] for e in self.failed_imports}
                self.failed_imports.extend(e for e in errors if e['path'] not in known)
                self.add_experiments(records)
                if selected_paths is not None:
                    chosen={str(Path(p).resolve()) for p in selected_paths}
                    for i,e in enumerate(self.experiments):self.data_table.item(i,0).setCheckState(C.Qt.Checked if e.path in chosen else C.Qt.Unchecked)
            if errors:
                text='\n'.join(f"{Path(e['path']).name}：{e['message']}" for e in errors)
                self.import_diagnostics.setText('未导入：'+text);self.notify(f'导入完成 · {len(errors)}份数据存在问题，详见数据集提示')
            else:self.notify(f'导入及自动检查完成 · {len(records)}份实验')
        job.imported.connect(done);job.finished.connect(lambda:self.import_jobs.remove(job) if job in self.import_jobs else None)
        job.start()

    def add_experiments(self,experiments):
        selected={e.run_id for e in self.selected_experiments()}
        old={e.run_id for e in self.experiments}
        try:self.experiments=unique_experiments(self.experiments+experiments)
        except ValueError as exc:self.error(str(exc));return
        self.data_table.blockSignals(True);self.data_table.setRowCount(len(self.experiments)+len(self.failed_imports))
        for i,e in enumerate(self.experiments):
            item=W.QTableWidgetItem();item.setFlags(C.Qt.ItemIsEnabled|C.Qt.ItemIsUserCheckable|C.Qt.ItemIsSelectable)
            item.setCheckState(C.Qt.Checked if e.run_id in selected or e.run_id not in old else C.Qt.Unchecked)
            self.data_table.setItem(i,0,item)
            for col,text in enumerate((e.name,len(e.strokes),'可用'),1):self.data_table.setItem(i,col,W.QTableWidgetItem(str(text)))
            self.data_table.item(i,3).setForeground(G.QColor('#66d9c4'))
            self.data_table.item(i,1).setToolTip(e.path)
        for i,failure in enumerate(self.failed_imports,len(self.experiments)):
            item=W.QTableWidgetItem();item.setFlags(C.Qt.NoItemFlags);self.data_table.setItem(i,0,item)
            set_row(self.data_table,i,['',Path(failure['path']).stem,'—','有问题'])
            self.data_table.item(i,0).setFlags(C.Qt.NoItemFlags)
            self.data_table.item(i,3).setForeground(G.QColor('#f08eab'));self.data_table.item(i,3).setToolTip(failure['message'])
        self.data_table.blockSignals(False)
        if self.experiments:self.data_table.selectRow(0)
        self.update_selection()

    def selected_experiments(self):
        return [e for i,e in enumerate(self.experiments) if self.data_table.item(i,0) and self.data_table.item(i,0).checkState()==C.Qt.Checked]

    def update_selection(self,*args):
        ex=self.selected_experiments();n=len(ex);count=sum(len(e.strokes) for e in ex)
        self.data_summary.setText(f'已选 {n} 次实验 · {count} 笔')
        if hasattr(self,'training_summary'):
            self.training_summary.setText(f'{n} 次实验  /  {count} 笔训练数据')
            self.validation_label.setText(f'每轮 {max(0,n-1)} 次实验训练、1次测试，共 {n} 轮。\n同一次实验的七笔始终在同一侧。')
            busy=self.training_job.process.state()!=C.QProcess.NotRunning or (hasattr(self,'learning_panel') and self.analyses_busy())
            self.start_button.setEnabled(n>=3 and any(c.isChecked() for c in self.family_checks.values()) and not busy)

    def preview_data(self,*args):
        row=self.data_table.currentRow()
        if row<0 or row>=len(self.experiments):return
        i=self.stroke_choice.currentIndex();stroke=self.experiments[row].strokes[i]
        mode=('amplitude','processed','direction')[self.curve_mode.currentIndex()]
        self.data_plot.curve(stroke,mode)

    def build_training(self):
        page=W.QWidget();layout=W.QVBoxLayout(page);layout.setContentsMargins(0,0,0,0);layout.setSpacing(14)
        top,tl=panel('本次训练');self.training_summary=label('未选择训练数据','section');tl.addWidget(self.training_summary)
        self.task_name=W.QLineEdit();self.task_name.setPlaceholderText('训练名称（可选，完成后也可以重命名）');tl.addWidget(self.task_name);layout.addWidget(top)
        group,gl=panel('比较哪些模型');self.family_checks={}
        notes={'F0':'保留幅值或比较基准、形状处理','F1':'比较相对方向与相邻转角','F2':'合并幅值和方向特征','F3':'组合独立分支的判别分数','F4':'比较全笔幅值与变化率'}
        grid=W.QGridLayout();gl.addLayout(grid)
        for i,(key,name) in enumerate(FAMILIES.items()):
            check=W.QCheckBox(name);check.setChecked(True);check.toggled.connect(self.update_selection)
            self.family_checks[key]=check;grid.addWidget(check,i//2,(i%2)*2);grid.addWidget(label(notes[key],'muted'),i//2,(i%2)*2+1)
        layout.addWidget(group)
        fixed,fl=panel('整次实验留一验证 · 固定');self.validation_label=label('导入实验后显示轮数','muted');fl.addWidget(self.validation_label)
        row=W.QHBoxLayout();row.addWidget(button('高级设置…',self.advanced));row.addStretch();fl.addLayout(row);layout.addWidget(fixed)
        row=W.QHBoxLayout();self.start_button=button('开始训练',self.start_training,True);self.cancel_button=button('取消训练',self.cancel_training);self.cancel_button.setEnabled(False)
        row.addWidget(self.start_button);row.addWidget(self.cancel_button);row.addStretch();self.training_state=label('等待训练','muted');row.addWidget(self.training_state);layout.addLayout(row)
        self.progress=W.QProgressBar();self.progress.setRange(0,100);self.progress.setValue(0);layout.addWidget(self.progress)
        self.training_log=W.QPlainTextEdit();self.training_log.setReadOnly(True);self.training_log.setPlaceholderText('训练开始后显示当前模型、折数与保存状态。');self.training_log.setMaximumBlockCount(500);layout.addWidget(self.training_log,1)
        return page

    def advanced(self):
        dialog=AdvancedDialog(self.config,self)
        if dialog.exec_()!=W.QDialog.Accepted:return
        changed=dialog.result_config.feature_config!=self.config.feature_config
        self.config=dialog.result_config
        if changed and self.experiments:
            paths=[e.path for e in self.experiments];selected=[e.path for e in self.selected_experiments()]
            self.experiments=[];self.data_table.setRowCount(0)
            self.import_paths(paths,selected_paths=selected);self.notify('预处理设置已改变，正在自动重新导入')
        else:self.notify('高级设置已更新，只影响下次训练')
        self.update_selection()

    def start_training(self):
        if self.analyses_busy():self.notify('请等待分析完成后再开始正式训练');return
        if self.import_jobs:self.error('导入检查尚未完成，请稍候');return
        ex=self.selected_experiments()
        try:
            config=replace(self.config,families=tuple(k for k,c in self.family_checks.items() if c.isChecked())).validate()
            if len(ex)<3:raise ValueError('至少选择3次完整实验；分数融合至少4次')
        except ValueError as exc:self.error(str(exc));return
        request=dict(paths=[e.path for e in ex],sources=[(e.run_id,e.source_hash) for e in ex],config=asdict(config),root=str(self.store.root),
                     name=self.task_name.text().strip() or datetime.now().strftime('训练 %m-%d %H:%M'))
        self.request_path=self.store.root/'requests'/(uuid.uuid4().hex+'.json');write_json(self.request_path,request)
        self.training_log.clear();self.training_state.setText('准备数据…');self.progress.setRange(0,0)
        self.start_button.setEnabled(False);self.cancel_button.setEnabled(True);self.last_task_id=None
        self.training_job.start(self.request_path);self.notify('训练进程已启动 · 使用提交时的数据与配置快照')

    def cancel_training(self):
        self.cancel_button.setEnabled(False);self.training_job.cancel();self.training_state.setText('正在取消…')

    def on_progress(self,event):
        message=event.get('message','')
        if event.get('fold'):message+=f"  {event['fold']}/{event['folds']}"
        if event.get('candidate'):message+=f"  候选 {event['candidate']}/{event['candidates']}"
        self.training_log.appendPlainText(message);self.training_state.setText(message)
        if event.get('task_id'):self.last_task_id=event['task_id']
        self.notify(message)

    def on_finished(self,success,message):
        self.progress.setRange(0,100);self.progress.setValue(100 if success else 0)
        self.cancel_button.setEnabled(False);self.update_selection();self.refresh_history()
        if success and self.last_task_id:
            task=self.store.metadata(self.last_task_id)
            if not any(not m.get('deleted') for m in task['models']):
                self.training_state.setText('条件不足 · 无可用模型');self.progress.setValue(0)
                self.research_notes.setPlainText(json.dumps(task.get('branches',{}),ensure_ascii=False,indent=2))
                self.notify('所选模型条件不足，没有保存可用模型；详见训练结果的研究记录')
                self.navigation.setCurrentRow(2);self.results_tabs.setCurrentWidget(self.research_notes);return
            self.training_state.setText('已完成并保存');self.notify('训练结果已保存，可在模型历史中加载')
            self.show_task_results(self.last_task_id);self.navigation.setCurrentRow(2)
        else:
            text=message or '训练未完成，请查看日志'
            self.training_log.appendPlainText(text);self.training_state.setText('已取消' if self.training_job.cancelled else '失败');self.notify(text.splitlines()[-1])

    def build_results(self):
        page=W.QWidget();layout=W.QVBoxLayout(page);layout.setContentsMargins(0,0,0,0);layout.setSpacing(12)
        row=W.QHBoxLayout();row.addWidget(label('查看模型','section'));self.result_selector=W.QComboBox();row.addWidget(self.result_selector,1)
        self.result_selector.currentIndexChanged.connect(self.select_result);row.addWidget(button('导出图表',self.export_figures));layout.addLayout(row)
        self.result_summary=label('完成训练，或从模型历史中选择一条记录。','notice');layout.addWidget(self.result_summary)
        self.results_tabs=W.QTabWidget();layout.addWidget(self.results_tabs,1)
        self.learning_panel=AnalysisPanel('learning');self.parameter_panel=AnalysisPanel('C')
        for widget,title in ((self.learning_panel,'学习曲线'),(self.parameter_panel,'参数验证')):
            widget.start_allowed=lambda:not self.analyses_busy() and self.training_job.process.state()==C.QProcess.NotRunning
            widget.candidateChosen.connect(self.apply_analysis_candidate);widget.busyChanged.connect(self.analysis_busy_changed)
            self.results_tabs.addTab(widget,title)
        self.matrix_plot=Plot();self.results_tabs.addTab(self.matrix_plot,'混淆矩阵')
        self.class_plot=Plot();self.results_tabs.addTab(self.class_plot,'类别表现')
        self.run_table=table(['留出实验','正确笔数','识别率']);self.results_tabs.addTab(self.run_table,'实验表现')
        self.space_explorer=SpaceExplorer()
        self.space_plot=self.space_explorer.plot;self.space_curve=self.space_explorer.curve
        self.space_dimension=self.space_explorer.dimension;self.space_branch=self.space_explorer.branch
        self.results_tabs.addTab(self.space_explorer,'模型空间')
        errors=W.QWidget();el=W.QVBoxLayout(errors)
        self.errors_table=table(['实验 / 笔画','真实类别','预测类别','结果']);self.errors_table.itemSelectionChanged.connect(self.show_error)
        el.addWidget(self.errors_table,1);self.error_origin=label('留出预测来自当轮模型。','muted');el.addWidget(self.error_origin)
        sp=W.QSplitter();self.error_curve=Plot();self.error_scores=Plot();sp.addWidget(self.error_curve);sp.addWidget(self.error_scores);el.addWidget(sp,2)
        self.results_tabs.addTab(errors,'逐笔与错分')
        pair=W.QWidget();pl=W.QVBoxLayout(pair);row=W.QHBoxLayout();self.pair_a=W.QComboBox();self.pair_b=W.QComboBox()
        self.pair_a.addItems(LABELS);self.pair_b.addItems(LABELS);self.pair_b.setCurrentIndex(1)
        self.pair_branch=W.QComboBox();self.pair_branch.addItems(['幅值分支','方向分支']);self.pair_branch.currentIndexChanged.connect(self.draw_pair);self.pair_branch.hide()
        row.addWidget(self.pair_a);row.addWidget(self.pair_b);row.addWidget(self.pair_branch);row.addStretch();pl.addLayout(row);self.pair_plot=Plot();pl.addWidget(self.pair_plot)
        self.pair_a.currentIndexChanged.connect(self.draw_pair);self.pair_b.currentIndexChanged.connect(self.draw_pair)
        self.results_tabs.addTab(pair,'两类判别')
        self.research_notes=W.QPlainTextEdit();self.research_notes.setReadOnly(True);self.results_tabs.addTab(self.research_notes,'研究记录')
        return page

    def show_task_results(self,task_id):
        task=self.store.metadata(task_id);self.result_selector.blockSignals(True);self.result_selector.clear()
        for m in sorted(task['models'],key=lambda m:m.get('rank') or 999):
            if not m.get('deleted'):self.result_selector.addItem(task['name']+' / '+m['name'],(task_id,m['id']))
        self.result_selector.blockSignals(False);self.select_result()
        self.navigation.setCurrentRow(2)

    def select_result(self,*args):
        pair=self.result_selector.currentData()
        if not pair:return
        try:
            task=self.store.metadata(pair[0]);m=next(m for m in task['models'] if m['id']==pair[1])
            self.result_bundle=self.store.load_bundle(*pair);self.result_task=task;self.result_model=m
            for widget in (self.learning_panel,self.parameter_panel):widget.set_source(self.store,task,m,self.result_bundle)
            for chooser in (self.pair_a,self.pair_b):
                chooser.blockSignals(True);chooser.clear();chooser.addItems(self.result_bundle['labels']);chooser.blockSignals(False)
            self.pair_b.blockSignals(True);self.pair_b.setCurrentIndex(1);self.pair_b.blockSignals(False)
            is_late=self.result_bundle['model'].candidate.family=='F3';self.space_branch.setVisible(is_late);self.pair_branch.setVisible(is_late)
            v=m['metrics'];rank=m.get('rank');recommend='优先试用' if rank==1 else f'候选 · 排序{rank}'
            self.result_summary.setText(f"{recommend}  ·  总错分 {v['errors']}/{v['total']}  ·  最差类别 {v['worst_recall']:.1%}  ·  最差实验 {v['worst_run_correct']}/{len(task['labels'])}\n仅用于同队列比较，成绩相同的模型并列。")
            self.matrix_plot.matrix(v);self.class_plot.quality(v)
            self.run_table.setRowCount(len(v['per_run']))
            names={s['run_id']:s['name'] for s in task['sources']}
            for row,(run,data) in enumerate(v['per_run'].items()):set_row(self.run_table,row,[names.get(run,run),f"{data['correct']}/{data['total']}",f"{data['correct']/data['total']:.1%}"])
            predictions=m['predictions'];self.errors_table.setRowCount(len(predictions))
            for i,r in enumerate(predictions):
                set_row(self.errors_table,i,[names.get(r['run_id'],r['run_id'])+f" · 第{r['stroke']}笔",LABELS[r['true']],LABELS[r['predicted']],
                                            '正确' if r['true']==r['predicted'] else '错分'])
                if r['true']!=r['predicted']:self.errors_table.item(i,3).setForeground(G.QColor('#f08eab'))
            self.draw_space();self.draw_pair()
            self.research_notes.setPlainText(json.dumps(dict(候选参数=m['candidate'],分支状态=task['branches'],条件项=task.get('conditions',{}),鲁棒性=m.get('robustness',[])),ensure_ascii=False,indent=2))
            if predictions:self.errors_table.selectRow(next((i for i,r in enumerate(predictions) if r['true']!=r['predicted']),0))
        except Exception as exc:self.error(str(exc))

    def show_error(self):
        row=self.errors_table.currentRow()
        if row<0 or self.result_model is None:return
        predictions=self.result_model['predictions']
        if row>=len(predictions):return
        r=predictions[row];stroke=self.result_bundle['training_strokes'][row]
        self.error_curve.curve(stroke,'processed');self.error_scores.scores(r['scores'],r['predicted'])
        self.error_origin.setText('原始留出预测与当轮分数 · '+r['run_id']+' · 不是最终模型回放训练数据的成绩')

    def analyses_busy(self):
        return any(widget.busy for widget in (self.learning_panel,self.parameter_panel))

    def analysis_busy_changed(self,*args):
        busy=self.analyses_busy();self.result_selector.setEnabled(not busy)
        for widget in (self.learning_panel,self.parameter_panel):
            if not widget.busy:widget.generate.setEnabled(not busy and widget.source is not None and len(widget.source[4]['labels'])==7)
        self.update_selection()

    def apply_analysis_candidate(self,payload):
        if self.analyses_busy() or self.training_job.process.state()!=C.QProcess.NotRunning:
            self.notify('请等待当前训练或分析结束后再应用候选');return
        candidate=payload['candidate'];values=dict(payload['train_config']);values['feature_config']=FeatureConfig(**values['feature_config'])
        base=TrainConfig(**values)
        updates=dict(cs=(candidate['C'],),kernels=(candidate['kernel'],),gammas=(candidate['gamma'],),families=(candidate['family'],))
        if candidate['family']=='F4':updates['difference_weights']=(candidate['weight'],)
        if candidate['family']=='F2':updates['direction_weights']=(candidate['weight'],)
        if candidate['family']=='F3':updates['late_weights']=(candidate['weight'],)
        if candidate['family']=='F0':updates['amplitudes']=(candidate['amplitude'],)
        if candidate['family'] in ('F1','F2','F3'):updates['directions']=(candidate['direction'],)
        changed=base.feature_config!=self.config.feature_config
        self.config=replace(base,**updates).validate()
        for key,check in self.family_checks.items():check.setChecked(key in self.config.families)
        if changed and self.experiments:
            paths=[e.path for e in self.experiments];selected=[e.path for e in self.selected_experiments()]
            self.experiments=[];self.data_table.setRowCount(0);self.import_paths(paths,selected_paths=selected)
        self.notify('候选及其原分析处理配置已写入下次训练设置；仅勾选对应模型，尚未启动训练。可在高级设置检查或修改。')

    def draw_space(self,*args):
        if self.result_bundle:self.space_explorer.set_source(self.result_bundle,self.result_model['predictions'],run_names={s['run_id']:s['name'] for s in self.result_task['sources']})

    def space_point(self,index):
        if self.result_bundle:self.space_explorer.select_sample(index)

    def draw_pair(self,*args):
        if self.result_bundle:self.pair_plot.pair(self.result_bundle,self.pair_a.currentIndex(),self.pair_b.currentIndex(),self.pair_branch.currentIndex())

    def export_figures(self):
        if not self.result_model:self.notify('请先选择一个已训练模型');return
        folder=W.QFileDialog.getExistingDirectory(self,'选择图表导出目录')
        if not folder:return
        for name,plot in [('confusion',self.matrix_plot),('per_class',self.class_plot),('model_space',self.space_plot),('pair_decision',self.pair_plot)]:
            for suffix in ('png','pdf'):
                plot.figure.savefig(Path(folder)/(self.result_model['id']+'_'+name+'.'+suffix),dpi=180,facecolor=plot.figure.get_facecolor())
        self.notify('图表已导出：'+folder)

    def build_history(self):
        page=W.QWidget();layout=W.QVBoxLayout(page);layout.setContentsMargins(0,0,0,0);layout.setSpacing(13)
        self.history=W.QTreeWidget();self.history.setHeaderLabels(['训练记录 / 模型','推荐','总错分','最差类别','最差实验','最新测试'])
        self.history.setSelectionMode(W.QAbstractItemView.ExtendedSelection);self.history.setAlternatingRowColors(True)
        self.history.setColumnWidth(0,310);self.history.setColumnWidth(1,100)
        for i in range(2,6):self.history.header().setSectionResizeMode(i,W.QHeaderView.ResizeToContents)
        self.history.itemDoubleClicked.connect(self.history_double_click);layout.addWidget(self.history,1)
        legacy_row=W.QHBoxLayout();legacy_row.addWidget(button('导入模型成果包',self.import_model_package));legacy_row.addWidget(button('导入已核验的历史五类基线',self.import_legacy));legacy_row.addStretch();layout.addLayout(legacy_row)
        row=W.QHBoxLayout()
        for text,callback in [('加载用于识别',self.load_selected),('收藏 / 取消收藏',self.favorite_selected),('重命名',self.rename_selected),
                              ('查看结果',self.view_selected),('导出',self.export_selected),('删除所选',self.delete_selected),('已删除模型',self.show_trash)]:
            row.addWidget(button(text,callback,text=='加载用于识别'))
        layout.addLayout(row);layout.addWidget(label('收藏记录置顶。删除只清理模型，可恢复；原始实验与训练数据保留。','notice'))
        return page

    def refresh_history(self):
        expanded={self.history.topLevelItem(i).data(0,C.Qt.UserRole)[0] for i in range(self.history.topLevelItemCount()) if self.history.topLevelItem(i).isExpanded()}
        self.history.clear();tasks=self.store.list_tasks()
        selected=self.model_selector.currentData() if hasattr(self,'model_selector') else None
        if hasattr(self,'model_selector'):self.model_selector.blockSignals(True);self.model_selector.clear()
        for task in tasks:
            live=[m for m in task['models'] if not m.get('deleted')]
            title=('★ ' if task.get('favorite') else '☆ ')+task['name']+f"   ·   {task['run_count']}次/{task['sample_count']}笔   ·   {len(live)}个模型   ·   "+task['created_at'][5:16].replace('T',' ')
            top=W.QTreeWidgetItem([title,'','','','','']);top.setFirstColumnSpanned(True);top.setToolTip(0,title)
            top.setData(0,C.Qt.UserRole,(task['id'],None));self.history.addTopLevelItem(top)
            top.setExpanded(task['id'] in expanded)
            top.setForeground(0,G.QColor('#dbe8ff'))
            for m in sorted(live,key=lambda m:m.get('rank') or 999):
                v=m['metrics'];latest=m.get('tests',[]);last=latest[-1].get('summary','') if latest else '未测试'
                child=W.QTreeWidgetItem([m['name'],'优先试用' if m.get('rank')==1 else '候选',f"{v['errors']}/{v['total']}",f"{v['worst_recall']:.1%}",f"{v['worst_run_correct']}/{len(task['labels'])}",last])
                child.setData(0,C.Qt.UserRole,(task['id'],m['id']));top.addChild(child)
                child.setToolTip(3,'最差类别：'+'、'.join(v['worst_classes']))
                self.model_selector.addItem(task['name']+' / '+m['name'],(task['id'],m['id']))
        if selected:
            for i in range(self.model_selector.count()):
                if self.model_selector.itemData(i)==selected:self.model_selector.setCurrentIndex(i);break
        self.model_selector.blockSignals(False)
        if self.loaded:
            try:self.store.model_path(*self.loaded)
            except (ValueError,FileNotFoundError):
                self.loaded=None;self.bundle=None;self.predictions=[];self.prediction_table.setRowCount(0)
                self.loaded_label.setText('当前模型已删除，请重新加载');self.predict_button.setEnabled(False)

    def selected_history(self):
        item=self.history.currentItem()
        return item.data(0,C.Qt.UserRole) if item else None

    def import_legacy(self):
        from .legacy import import_historical_baseline
        folder=Path(__file__).resolve().parents[3]/'outputs/stroke_model_random10_20261106'
        try:
            task=import_historical_baseline(self.store,folder);self.refresh_history();self.show_task_results(task['id'])
            self.notify('历史五类基线已只读导入；只能识别原五类，不能评价七类实验')
        except Exception as exc:self.error(str(exc))

    def import_model_package(self):
        path,_=W.QFileDialog.getOpenFileName(self,'导入本工具保存的模型成果包','','模型成果包 (*.zip)')
        if path:
            try:
                task=self.store.import_package(path);self.refresh_history();self.notify('模型成果包已导入：'+task['name'])
            except Exception as exc:self.error(str(exc))

    def history_double_click(self,item,column):
        task,model=item.data(0,C.Qt.UserRole)
        if model:self.load_model(task,model)
        else:item.setExpanded(not item.isExpanded())

    def load_selected(self):
        selected=self.selected_history()
        if selected and selected[1]:self.load_model(*selected)
        else:self.notify('请展开训练记录，选择其中一个模型')

    def favorite_selected(self):
        selected={i.data(0,C.Qt.UserRole)[0] for i in self.history.selectedItems()}
        for task in selected:self.store.favorite(task,not self.store.metadata(task).get('favorite',False))
        self.refresh_history()

    def rename_selected(self):
        selected=self.selected_history()
        if not selected:return
        task=self.store.metadata(selected[0]);name=task['name'] if selected[1] is None else next(m['name'] for m in task['models'] if m['id']==selected[1])
        text,ok=W.QInputDialog.getText(self,'重命名','名称',text=name)
        if ok:
            try:self.store.rename(selected[0],text,selected[1]);self.refresh_history()
            except ValueError as exc:self.error(str(exc))

    def view_selected(self):
        selected=self.selected_history()
        if selected:
            self.show_task_results(selected[0])
            if selected[1]:
                for i in range(self.result_selector.count()):
                    if self.result_selector.itemData(i)==selected:self.result_selector.setCurrentIndex(i);break

    def export_selected(self):
        selected=self.selected_history()
        if not selected:return
        path,_=W.QFileDialog.getSaveFileName(self,'导出完整模型与报告','stroke-models.zip','模型成果包 (*.zip)')
        if path:
            try:self.store.export(selected[0],path,selected[1]);self.notify('完整模型包已导出：'+path)
            except Exception as exc:self.error(str(exc))

    def delete_selected(self):
        if self.analyses_busy():self.notify('分析进行中，请结束后再删除模型');return
        items=[i.data(0,C.Qt.UserRole) for i in self.history.selectedItems()]
        if not items:return
        top={t for t,m in items if m is None}
        filtered=[(t,m) for t,m in items if m is None or t not in top]
        # Favorites remain protected during bulk cleanup; a single deliberate deletion remains possible.
        if len(filtered)>1:filtered=[x for x in filtered if not self.store.metadata(x[0]).get('favorite',False)]
        for task,model in filtered:self.store.delete(task,model)
        self.refresh_history();self.notify(f'已移入回收区：{len(filtered)}项；原始实验及训练数据保留')

    def show_trash(self):
        dialog=W.QDialog(self);dialog.setWindowTitle('已删除模型');dialog.resize(720,440);layout=W.QVBoxLayout(dialog)
        tree=W.QTreeWidget();tree.setHeaderLabels(['已删除项目','范围']);layout.addWidget(tree)
        def fill():
            tree.clear()
            for task in self.store.list_tasks(deleted=True):
                item=W.QTreeWidgetItem([task['name'],'整次训练']);item.setData(0,C.Qt.UserRole,(task['id'],None));tree.addTopLevelItem(item)
            for task in self.store.list_tasks():
                for m in task['models']:
                    if m.get('deleted') and not m.get('unavailable_in_package'):
                        item=W.QTreeWidgetItem([task['name']+' / '+m['name'],'单个模型']);item.setData(0,C.Qt.UserRole,(task['id'],m['id']));tree.addTopLevelItem(item)
        def restore():
            if tree.currentItem():
                task,model=tree.currentItem().data(0,C.Qt.UserRole);self.store.restore(task,model);fill();self.refresh_history()
        fill();layout.addWidget(button('恢复所选',restore,True));dialog.exec_()

    def build_prediction(self):
        page=W.QWidget();layout=W.QVBoxLayout(page);layout.setContentsMargins(0,0,0,0);layout.setSpacing(12)
        row=W.QHBoxLayout();self.model_selector=W.QComboBox();row.addWidget(self.model_selector,1);row.addWidget(button('加载所选模型',self.load_combo,True));layout.addLayout(row)
        self.loaded_label=label('请先加载一个模型。','notice');layout.addWidget(self.loaded_label)
        row=W.QHBoxLayout();row.addWidget(button('＋ 添加实验',lambda:self.choose_import(True)));row.addWidget(button('添加单笔CSV',self.import_single))
        row.addWidget(button('清空待识别数据',self.clear_recognition));row.addStretch();self.predict_button=button('开始识别',self.run_prediction,True);self.predict_button.setEnabled(False)
        row.addWidget(self.predict_button);row.addWidget(button('导出结果',self.export_predictions));layout.addLayout(row)
        self.recognition_summary=label('未添加待识别数据','muted');layout.addWidget(self.recognition_summary)
        self.prediction_table=table(['实验 / 笔画','任务标签','预测类别','结果']);self.prediction_table.itemSelectionChanged.connect(self.preview_prediction)
        layout.addWidget(self.prediction_table,1)
        self.prediction_tabs=W.QTabWidget();layout.addWidget(self.prediction_tabs,2)
        sp=W.QSplitter();self.prediction_curve=Plot();self.prediction_scores=Plot();sp.addWidget(self.prediction_curve);sp.addWidget(self.prediction_scores);self.prediction_tabs.addTab(sp,'曲线与逐类评分')
        self.prediction_explorer=SpaceExplorer()
        self.prediction_branch=self.prediction_explorer.branch;self.prediction_space=self.prediction_explorer.plot
        self.prediction_tabs.addTab(self.prediction_explorer,'模型空间位置')
        self.branch_details=W.QPlainTextEdit();self.branch_details.setReadOnly(True);self.prediction_tabs.addTab(self.branch_details,'评分来源')
        return page

    def load_combo(self):
        if self.model_selector.currentData():self.load_model(*self.model_selector.currentData())

    def load_model(self,task_id,model_id):
        try:
            self.bundle=self.store.load_bundle(task_id,model_id);self.loaded=(task_id,model_id)
            self.prediction_branch.setVisible(self.bundle['model'].candidate.family=='F3')
            task=self.store.metadata(task_id);model=next(m for m in task['models'] if m['id']==model_id)
            self.loaded_label.setText('当前模型：'+task['name']+' / '+model['name']+f" · {len(self.bundle['labels'])}类 · 固定已保存处理链")
            self.clear_recognition();self.predict_button.setEnabled(True);self.navigation.setCurrentRow(4)
            for i in range(self.model_selector.count()):
                if self.model_selector.itemData(i)==self.loaded:self.model_selector.setCurrentIndex(i);break
            self.notify('模型已加载 · 添加实验即可识别，无需重新训练')
        except Exception as exc:self.error(str(exc))

    def clear_recognition(self):
        self.recognition_generation+=1
        self.recognition_experiments=[];self.single_strokes=[];self.predictions=[];self.recognition_strokes=[];self.prediction_table.setRowCount(0)
        self.recognition_summary.setText('未添加待识别数据')
        self.prediction_curve.empty('添加实验或单笔数据');self.prediction_scores.empty('识别后显示各类判别分数');self.prediction_explorer.empty('识别后显示样本位置');self.branch_details.clear()

    def import_single(self):
        if not self.bundle:self.notify('请先加载模型');return
        path,_=W.QFileDialog.getOpenFileName(self,'选择保留写前采样的单笔CSV','','磁采样 (*.csv)')
        if path:
            try:
                stroke=load_single_csv(path,FeatureConfig(**self.bundle['feature_config']))
                if stroke.sample_id not in {s.sample_id for s in self.single_strokes}:self.single_strokes.append(stroke)
                self.refresh_recognition_input()
            except Exception as exc:self.error(str(exc))

    def refresh_recognition_input(self):
        count=sum(len(e.strokes) for e in self.recognition_experiments)+len(self.single_strokes)
        self.recognition_summary.setText(f'待识别：{len(self.recognition_experiments)}次实验、{len(self.single_strokes)}条单笔，共{count}笔')
        self.predictions=[];self.prediction_table.setRowCount(0)

    def run_prediction(self):
        if not self.bundle or not self.loaded:self.notify('请先加载一个模型');return
        if self.import_jobs:self.notify('正在导入检查，请稍候');return
        strokes=[s for e in self.recognition_experiments for s in e.strokes]+self.single_strokes
        if not strokes:self.notify('请先添加待识别数据');return
        try:
            predictions=predict_strokes(self.bundle,strokes)
            duplicated={e.run_id for e in self.recognition_experiments if e.sensor_hash in self.bundle['sensor_hashes']}
            for r in predictions:r['training_overlap'] |= r['run_id'] in duplicated
            self.predictions=predictions;self.recognition_strokes=strokes;self.prediction_table.setRowCount(len(predictions))
            names={e.run_id:e.name for e in self.recognition_experiments}
            for i,r in enumerate(predictions):
                outcome='超出模型类别范围' if r['unsupported'] else '训练数据回放' if r['training_overlap'] else '待核验' if r['correct'] is None else '正确' if r['correct'] else '错分'
                set_row(self.prediction_table,i,[names.get(r['run_id'],'单笔CSV')+f" · 第{r['stroke']}笔",'未知' if r['true_label'] is None else LABELS[r['true_label']],'—' if r['predicted'] is None else LABELS[r['predicted']],outcome])
            evaluable=[r for r in predictions if not r['training_overlap'] and r['correct'] is not None]
            summary=f"新数据正确 {sum(r['correct'] for r in evaluable)}/{len(evaluable)}" if evaluable else '回放／无标签，不计新数据准确率'
            if evaluable:summary+=f" · {sum(r['correct'] for r in evaluable)/len(evaluable):.1%}"
            unsupported=sum(r['unsupported'] for r in predictions)
            if unsupported:summary+='（仅已知类别）'+f' · {unsupported}笔超出类别范围，不计七类准确率'
            self.recognition_summary.setText(summary+f' · 共识别{len(predictions)}笔')
            task=self.store.metadata(self.loaded[0]);model=next(m for m in task['models'] if m['id']==self.loaded[1])
            test_id=datetime.now().strftime('%Y%m%d-%H%M%S-')+uuid.uuid4().hex[:6]
            test_record=dict(id=test_id,model_id=self.loaded[1],task_id=self.loaded[0],model_version=self.bundle['version'],
                feature_config=self.bundle['feature_config'],labels=self.bundle['labels'],summary=summary,created_at=datetime.now().isoformat(),
                sources=[dict(run_id=e.run_id,sensor_hash=e.sensor_hash,name=e.name) for e in self.recognition_experiments],predictions=predictions)
            write_json(self.store.model_path(*self.loaded)/'tests'/(test_id+'.json'),test_record)
            model.setdefault('tests',[]).append({k:v for k,v in test_record.items() if k!='predictions'});self.store.save(task)
            self.refresh_history();self.prediction_table.selectRow(0);self.notify('识别完成；测试单独保存，没有更新模型')
        except Exception as exc:self.error(str(exc))

    def preview_prediction(self):
        row=self.prediction_table.currentRow()
        if row<0 or row>=len(self.predictions):return
        result=self.predictions[row];stroke=self.recognition_strokes[row]
        if result['unsupported']:
            self.prediction_curve.curve(stroke,'processed');self.prediction_scores.empty('该笔画超出模型类别范围，不生成伪评分')
            self.prediction_explorer.empty('该笔画超出模型类别范围');self.branch_details.setPlainText('此历史模型只支持五类，横、竖不参与其准确率统计。');return
        self.prediction_curve.curve(stroke,'processed');self.prediction_scores.scores(result['scores'],result['predicted'])
        self.prediction_explorer.new_stroke=stroke
        self.prediction_explorer.set_source(self.bundle,new=result)
        order=np.argsort(result['scores'])[::-1]
        text=dict(预测类别=LABELS[result['predicted']],主要竞争类别=[LABELS[i] for i in order[:2]],
                  说明='判别分数不是概率。各模型量纲可能不同，不能直接跨模型比较数值大小。',
                  类别顺序=self.bundle['labels'],最终分数=result['scores'],分支原始分数=result['branch_scores'],模型参数=self.bundle['candidate'])
        if self.bundle['model'].candidate.family=='F3':
            text['分数变换均值']=[v.tolist() for v in self.bundle['model'].score_mean]
            text['分数变换尺度']=[v.tolist() for v in self.bundle['model'].score_scale]
        self.branch_details.setPlainText(json.dumps(text,ensure_ascii=False,indent=2))

    def export_predictions(self):
        if not self.predictions:return
        path,_=W.QFileDialog.getSaveFileName(self,'导出逐笔识别结果','stroke-predictions.json','识别结果 (*.json)')
        if path:write_json(path,dict(model=self.loaded,predictions=self.predictions));self.notify('识别结果已导出')

    def save_project(self):
        path,_=W.QFileDialog.getSaveFileName(self,'保存训练项目','stroke-project.json','训练项目 (*.json)')
        if path:
            selected={e.run_id for e in self.selected_experiments()}
            config=replace(self.config,families=tuple(k for k,c in self.family_checks.items() if c.isChecked()))
            write_json(path,dict(version=1,config=asdict(config),sources=[dict(path=e.path,selected=e.run_id in selected) for e in self.experiments],store=str(self.store.root)))
            self.notify('项目已保存：'+path)

    def open_project(self):
        if self.analyses_busy():self.notify('分析进行中，请结束后再切换项目');return
        if self.training_job.process.state()!=C.QProcess.NotRunning:self.notify('训练进行中，请结束本次任务后再切换项目');return
        if self.import_jobs:self.notify('导入检查进行中，请完成后再切换项目');return
        path,_=W.QFileDialog.getOpenFileName(self,'打开训练项目','','训练项目 (*.json)')
        if not path:return
        try:
            data=json.loads(Path(path).read_text());values=data['config'];values['feature_config']=FeatureConfig(**values['feature_config'])
            self.config=TrainConfig(**values).validate()
            for k,check in self.family_checks.items():check.setChecked(k in self.config.families)
            self.loaded=None;self.bundle=None;self.clear_recognition();self.predict_button.setEnabled(False)
            self.loaded_label.setText('请先加载一个模型。')
            if data.get('store'):self.store=ModelStore(data['store']);self.refresh_history()
            self.experiments=[];self.failed_imports=[];self.data_table.setRowCount(0)
            self.import_paths([x['path'] for x in data['sources']],selected_paths=[x['path'] for x in data['sources'] if x.get('selected',True)])
            self.notify('项目设置已打开，正在自动导入检查')
        except Exception as exc:self.error(str(exc))

    def closeEvent(self,event):
        for panel in (self.learning_panel,self.parameter_panel):
            if panel.busy:
                panel.cancel();panel.job.process.waitForFinished(1500);panel.job.kill_if_running();panel.job.process.waitForFinished(1000)
        if self.training_job.process.state()!=C.QProcess.NotRunning:
            answer=W.QMessageBox.question(self,'训练进行中','关闭窗口会取消本次训练，是否关闭？')
            if answer!=W.QMessageBox.Yes:event.ignore();return
            self.training_job.cancel();self.training_job.process.waitForFinished(1500);self.training_job.kill_if_running();self.training_job.process.waitForFinished(1000)
        for job in list(self.import_jobs):job.requestInterruption();job.wait()
        event.accept()
