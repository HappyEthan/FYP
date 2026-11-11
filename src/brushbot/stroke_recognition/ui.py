"""Dark desktop for shared training history and live stroke predictions."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading

import numpy as np
from PyQt5 import QtCore as C, QtGui as G, QtWidgets as W
import pyqtgraph as pg
from serial.tools import list_ports

from brushbot.stroke_classification.store import ModelStore
from brushbot.stroke_classification.theme import STYLE, COLORS
from .controller import LiveController
from .core import SegmentConfig


EXTRA_STYLE = '''
QWidget#liveRoot { background:#0d121c; }
QFrame#sidebar { background:#101826; border:1px solid #253047; border-radius:10px; }
QLabel#hero { font-size:27px; font-weight:600; color:#edf4ff; }
QLabel#bigPrediction { font-size:46px; font-weight:600; color:#8cb8ff; padding:8px 0; }
QLabel#finalPrediction { font-size:32px; font-weight:600; color:#77dfc5; padding:4px 0; }
QLabel#badge { background:#1c2c42; color:#a9c8f5; border-radius:12px; padding:5px 12px; }
QLabel#errorMessage { background:#31202c; color:#f1b3c1; border:1px solid #644050; border-radius:6px; padding:8px 12px; }
QStatusBar { background:#0d121c; color:#8fa2bd; border-top:1px solid #253047; }
QToolButton { color:#b6cae6; background:#1c2c42; border:1px solid #33445f; border-radius:5px; padding:5px 9px; }
QToolButton:hover { background:#2a3d5b; }
'''


def label(text='', name=None):
    item = W.QLabel(text)
    item.setWordWrap(True)
    item.setTextFormat(C.Qt.PlainText)
    if name:
        item.setObjectName(name)
    return item


def button(text, callback, name=None):
    item = W.QPushButton(text)
    item.setCursor(C.Qt.PointingHandCursor)
    item.clicked.connect(callback)
    if name:
        item.setObjectName(name)
    return item


def card(title):
    frame = W.QFrame()
    frame.setObjectName('panel')
    layout = W.QVBoxLayout(frame)
    layout.setContentsMargins(17,15,17,15)
    layout.setSpacing(9)
    layout.addWidget(label(title,'section'))
    return frame,layout


def table(headers):
    item = W.QTableWidget(0,len(headers))
    item.setHorizontalHeaderLabels(headers)
    item.verticalHeader().hide()
    item.setEditTriggers(W.QAbstractItemView.NoEditTriggers)
    item.setSelectionBehavior(W.QAbstractItemView.SelectRows)
    item.setAlternatingRowColors(True)
    item.horizontalHeader().setSectionResizeMode(W.QHeaderView.Stretch)
    item.verticalHeader().setDefaultSectionSize(34)
    return item


class RecognizerWindow(W.QMainWindow):
    def __init__(self, store, output_root, *, controller=None, settings=None):
        super().__init__()
        self.setWindowTitle('磁响应 · 实时笔画识别')
        self.resize(1510,960)
        self.setMinimumSize(1130,760)
        self.setStyleSheet(STYLE+EXTRA_STYLE)
        self.store = ModelStore(store)
        self.output_root = Path(output_root)
        self.controller = controller or LiveController(output_root)
        self.settings = settings or C.QSettings('Brushbot','LiveStrokeRecognizer')
        self._imports = ThreadPoolExecutor(max_workers=1,thread_name_prefix='stroke-import')
        self._import_future = None
        self._tree_signature = None
        self._history_signature = self._changes_signature = None
        self._model_labels = ()
        self._closing = False
        self._shutdown_done = threading.Event()
        self._notice = ''
        self._build()
        self._restore_settings()
        self.refresh_history()
        self.refresh_ports()
        self.apply_configuration()
        last = (self.settings.value('task_id',''),self.settings.value('model_id',''))
        item = self._find_model(last)
        if item:
            self.history.setCurrentItem(item)
            self.load_selected_model()
        self.timer = C.QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(50)
        self.history_timer = C.QTimer(self)
        self.history_timer.timeout.connect(self.refresh_history)
        self.history_timer.start(2000)
        self.poll()

    def _build(self):
        root = W.QWidget(objectName='liveRoot')
        self.setCentralWidget(root)
        outer = W.QHBoxLayout(root)
        outer.setContentsMargins(18,18,18,12)
        outer.setSpacing(18)
        sidebar = W.QFrame(objectName='sidebar')
        sidebar.setMinimumWidth(300)
        sidebar.setMaximumWidth(365)
        side = W.QVBoxLayout(sidebar)
        side.setContentsMargins(15,15,15,15)
        side.setSpacing(12)
        side.addWidget(label('BRUSH · LIVE','eyebrow'))
        side.addWidget(label('模型与传感器','brand'))
        scroll = W.QScrollArea()
        scroll.setWidgetResizable(True)
        content = W.QWidget()
        controls = W.QVBoxLayout(content)
        controls.setContentsMargins(0,0,4,0)
        controls.setSpacing(13)
        scroll.setWidget(content)
        side.addWidget(scroll,1)
        self._build_history(controls)
        self._build_connection(controls)
        self._build_configuration(controls)
        controls.addStretch()
        outer.addWidget(sidebar)

        body = W.QVBoxLayout()
        body.setSpacing(13)
        header = W.QHBoxLayout()
        titles = W.QVBoxLayout()
        titles.addWidget(label('实时笔画识别','hero'))
        titles.addWidget(label('观察书写中的判断变化，提笔后锁定整笔结果。','subtitle'))
        header.addLayout(titles,1)
        self.state_label = label('等待连接','badge')
        self.state_label.setAlignment(C.Qt.AlignCenter)
        self.state_label.setMinimumWidth(125)
        header.addWidget(self.state_label)
        body.addLayout(header)
        self.model_label = label('请选择历史模型，或导入训练工作台导出的成果包。','muted')
        body.addWidget(self.model_label)
        toolbar = W.QHBoxLayout()
        self.start_button = button('开始识别',lambda:self.controller.command('start'),'primary')
        self.stop_button = button('停止',lambda:self.controller.command('stop'))
        toolbar.addWidget(self.start_button)
        toolbar.addWidget(self.stop_button)
        toolbar.addSpacing(12)
        toolbar.addWidget(label('识别间隔'))
        self.interval = W.QComboBox()
        for interval in (100,200,500):
            self.interval.addItem(f'{interval} ms · {1000/interval:g} Hz',interval)
        self.interval.currentIndexChanged.connect(self.apply_configuration)
        toolbar.addWidget(self.interval)
        self.rate_label = label('采样 —  ·  更新 —','muted')
        toolbar.addWidget(self.rate_label,1)
        self.open_folder_button = button('会话记录',self.open_session_folder)
        toolbar.addWidget(self.open_folder_button)
        body.addLayout(toolbar)
        self.error_label = label('', 'errorMessage')
        self.error_label.hide()
        body.addWidget(self.error_label)

        middle = W.QHBoxLayout()
        middle.setSpacing(13)
        left = W.QVBoxLayout()
        graph_card, graph_layout = card('实时磁响应')
        toggles = W.QHBoxLayout()
        self.channel_checks = []
        for text,color in zip(('ΔBx','ΔBy','|ΔBxy|'),COLORS):
            check = W.QCheckBox(text)
            check.setChecked(True)
            check.setStyleSheet(f'color:{color}')
            toggles.addWidget(check)
            self.channel_checks.append(check)
        toggles.addStretch()
        self.amplitude_label = label('— µT','muted')
        toggles.addWidget(self.amplitude_label)
        graph_layout.addLayout(toggles)
        self.plot = pg.PlotWidget(background='#101925')
        self.plot.setMinimumHeight(250)
        self.plot.showGrid(x=True,y=True,alpha=.12)
        self.plot.setLabel('bottom','相对当前时间',units='s',color='#96a6bf')
        self.plot.setLabel('left','磁响应',units='µT',color='#96a6bf')
        for axis in ('left','bottom'):
            self.plot.getAxis(axis).setTextPen('#96a6bf')
            self.plot.getAxis(axis).setPen('#33445f')
        self.curves = [self.plot.plot(pen=pg.mkPen(color,width=1.8)) for color in COLORS[:3]]
        for check,curve in zip(self.channel_checks,self.curves):
            check.toggled.connect(curve.setVisible)
        self.down_line = pg.InfiniteLine(angle=0,pen=pg.mkPen('#6a8bb5',style=C.Qt.DashLine))
        self.up_line = pg.InfiniteLine(angle=0,pen=pg.mkPen('#626e85',style=C.Qt.DashLine))
        self.start_line = pg.InfiniteLine(angle=90,pen=pg.mkPen('#77dfc5',width=1.5))
        self.end_line = pg.InfiniteLine(angle=90,pen=pg.mkPen('#e7b777',style=C.Qt.DashLine))
        for line in (self.down_line,self.up_line,self.start_line,self.end_line):
            self.plot.addItem(line)
        self.start_line.hide(); self.end_line.hide()
        graph_layout.addWidget(self.plot,1)
        graph_layout.addWidget(label('实线：本笔起点　虚线：提笔候选或已完成笔的终点','muted'))
        left.addWidget(graph_card,3)

        self.tabs = W.QTabWidget()
        self.history_table = table(('笔画','最终类别','时长','状态','使用模型'))
        self.changes_table = table(('已写时间','当时识别为','说明'))
        self.history_table.setMinimumHeight(185)
        self.tabs.addTab(self.history_table,'已完成笔画')
        self.tabs.addTab(self.changes_table,'本笔判断变化')
        left.addWidget(self.tabs,2)
        middle.addLayout(left,1)

        right = W.QVBoxLayout()
        current_card,current_layout = card('当前笔画 · 暂定')
        current_card.setMinimumWidth(235)
        current_card.setMaximumWidth(300)
        self.current_label = label('—','bigPrediction')
        self.current_label.setAlignment(C.Qt.AlignCenter)
        self.current_detail = label('落笔后开始定时识别','muted')
        self.current_detail.setAlignment(C.Qt.AlignCenter)
        current_layout.addWidget(self.current_label)
        current_layout.addWidget(self.current_detail)
        right.addWidget(current_card)
        final_card,final_layout = card('上一笔 · 最终结果')
        self.final_label = label('—','finalPrediction')
        self.final_label.setAlignment(C.Qt.AlignCenter)
        self.final_detail = label('完整笔画识别后锁定','muted')
        self.final_detail.setAlignment(C.Qt.AlignCenter)
        final_layout.addWidget(self.final_label)
        final_layout.addWidget(self.final_detail)
        right.addWidget(final_card)
        score_card,score_layout = card('当前判别分数')
        self.score_table = table(('类别','SVM分数'))
        self.score_table.setMinimumHeight(230)
        self.score_table.setSelectionMode(W.QAbstractItemView.NoSelection)
        score_layout.addWidget(self.score_table,1)
        score_layout.addWidget(label('分数随当前片段更新','muted'))
        right.addWidget(score_card,1)
        middle.addLayout(right)
        body.addLayout(middle,1)
        outer.addLayout(body,1)
        self.statusBar().showMessage('先选择模型，再连接传感器并采集空载基线。')

    def _build_history(self, layout):
        layout.addWidget(label('模型历史','section'))
        row = W.QHBoxLayout()
        self.refresh_button = button('刷新',self.refresh_history)
        self.import_button = button('导入模型',self.choose_import)
        row.addWidget(self.refresh_button); row.addWidget(self.import_button)
        layout.addLayout(row)
        self.history = W.QTreeWidget()
        self.history.setHeaderLabels(('训练记录 / 模型','类型'))
        self.history.setMinimumHeight(180)
        self.history.setMaximumHeight(250)
        self.history.setColumnWidth(0,205)
        self.history.itemDoubleClicked.connect(lambda *args:self.load_selected_model())
        self.history.itemSelectionChanged.connect(self._selection_changed)
        layout.addWidget(self.history)
        self.load_button = button('使用选中模型',self.load_selected_model)
        layout.addWidget(self.load_button)
        self.store_label = label('', 'muted')
        self.store_label.setMaximumHeight(45)
        layout.addWidget(self.store_label)
        layout.addWidget(button('选择模型库目录',self.choose_store))

    def _build_connection(self, layout):
        layout.addWidget(label('传感器连接','section'))
        row = W.QHBoxLayout()
        self.port = W.QComboBox()
        self.port.setEditable(True)
        self.port.setMinimumContentsLength(10)
        row.addWidget(self.port,1)
        row.addWidget(button('扫描',self.refresh_ports))
        layout.addLayout(row)
        self.baud = W.QComboBox()
        self.baud.setEditable(True)
        self.baud.addItems(('115200','230400','460800','921600'))
        baud_row = W.QHBoxLayout()
        baud_row.addWidget(label('波特率')); baud_row.addWidget(self.baud,1)
        layout.addLayout(baud_row)
        row = W.QHBoxLayout()
        self.connect_button = button('连接',self.toggle_connection)
        self.baseline_button = button('取空载基线',lambda:self.controller.command('baseline'))
        self.baseline_button.setToolTip('保持毛笔悬空、静止约1秒；完成后等待连续预热。')
        row.addWidget(self.connect_button); row.addWidget(self.baseline_button)
        layout.addLayout(row)
        self.baseline_label = label('基线未采集','muted')
        layout.addWidget(self.baseline_label)

    def _build_configuration(self, layout):
        layout.addWidget(label('分笔设置','section'))
        grid = W.QGridLayout()
        self.down_threshold = W.QDoubleSpinBox()
        self.up_threshold = W.QDoubleSpinBox()
        for spin in (self.down_threshold,self.up_threshold):
            spin.setRange(0,100000)
            spin.setDecimals(1)
            spin.setSuffix(' µT')
        self.down_ms = W.QSpinBox(); self.up_ms = W.QSpinBox()
        for spin in (self.down_ms,self.up_ms):
            spin.setRange(0,2000); spin.setSuffix(' ms')
        for i,(text,spin) in enumerate((('落笔阈值',self.down_threshold),('提笔阈值',self.up_threshold),
                                        ('落笔确认',self.down_ms),('提笔确认',self.up_ms))):
            grid.addWidget(label(text),i,0); grid.addWidget(spin,i,1)
        layout.addLayout(grid)
        self.threshold_confirm = W.QCheckBox('已通过预览确认阈值')
        self.threshold_confirm.setToolTip('先观察悬空与轻触信号，设置合适阈值后勾选。')
        layout.addWidget(self.threshold_confirm)
        self.apply_button = button('应用分笔设置',self.apply_configuration)
        layout.addWidget(self.apply_button)
        layout.addWidget(label('书写中调整设置，将在下一笔生效。','muted'))

    def _restore_settings(self):
        for name,default in (('down_threshold',100.),('up_threshold',60.),('down_ms',40),('up_ms',120)):
            getattr(self,name).setValue(float(self.settings.value(name,default)) if 'threshold' in name
                                        else int(self.settings.value(name,default)))
        self.threshold_confirm.setChecked(self.settings.value('threshold_confirmed',False,type=bool))
        interval = int(self.settings.value('interval_ms',100))
        index = self.interval.findData(interval)
        if index>=0:
            self.interval.setCurrentIndex(index)
        self.port.setEditText(self.settings.value('port',''))
        self.baud.setCurrentText(str(self.settings.value('baud','115200')))

    def _save_settings(self):
        self.settings.setValue('store',str(self.store.root))
        for name in ('down_threshold','up_threshold','down_ms','up_ms'):
            self.settings.setValue(name,getattr(self,name).value())
        self.settings.setValue('threshold_confirmed',self.threshold_confirm.isChecked())
        self.settings.setValue('interval_ms',self.interval.currentData())
        self.settings.setValue('port',self.port.currentText())
        self.settings.setValue('baud',self.baud.currentText())
        self.settings.sync()

    def _find_model(self, key):
        for i in range(self.history.topLevelItemCount()):
            parent = self.history.topLevelItem(i)
            for j in range(parent.childCount()):
                item = parent.child(j)
                if item.data(0,C.Qt.UserRole)==key:
                    return item
        return None

    def refresh_history(self, *args):
        tasks = self.store.list_tasks()
        signature = repr([(t['id'],t.get('favorite'),t['name'],
                           [(m['id'],m.get('name'),m.get('deleted'),m.get('bundle_sha256')) for m in t['models']])
                          for t in tasks])
        if signature != self._tree_signature:
            old = self.history.currentItem()
            key = old.data(0,C.Qt.UserRole) if old else None
            self.history.clear()
            for task in tasks:
                parent = W.QTreeWidgetItem([('★ ' if task.get('favorite') else '')+task['name'],''])
                parent.setToolTip(0,str(task.get('created_at','')))
                self.history.addTopLevelItem(parent)
                for model in task['models']:
                    if model.get('deleted'):
                        continue
                    item = W.QTreeWidgetItem([model.get('name',model['id']),model.get('family','')])
                    item.setData(0,C.Qt.UserRole,(task['id'],model['id']))
                    metrics = model.get('metrics',{})
                    detail = (f"原评估准确率 {metrics.get('accuracy',0):.2%} · "
                              f"Macro-F1 {metrics.get('macro_f1',0):.3f}")
                    item.setToolTip(0,detail)
                    parent.addChild(item)
                parent.setExpanded(True)
            if key:
                item = self._find_model(key)
                if item:
                    self.history.setCurrentItem(item)
            self._tree_signature = signature
        self.store_label.setText(f'共享模型库 · {self.store.root.name}')
        self.store_label.setToolTip(str(self.store.root))
        self._selection_changed()
        snap = self.controller.snapshot()
        active = snap.get('model')
        if active:
            available = any(t['id']==active['task_id'] and any(m['id']==active['model_id'] and
                not m.get('deleted') and m.get('bundle_sha256')==active['sha256'] for m in t['models']) for t in tasks)
            self.controller.command('availability',token=active['token'],available=available)

    def _selection_changed(self):
        item = self.history.currentItem()
        self.load_button.setEnabled(bool(item and item.data(0,C.Qt.UserRole)))

    def load_selected_model(self):
        item = self.history.currentItem()
        key = item.data(0,C.Qt.UserRole) if item else None
        if not key:
            return
        self.settings.setValue('task_id',key[0]); self.settings.setValue('model_id',key[1])
        self.controller.command('load_model',root=self.store.root,task_id=key[0],model_id=key[1])
        self._notice = '正在加载模型…'

    def choose_store(self):
        path = W.QFileDialog.getExistingDirectory(self,'选择训练工作台使用的模型库',str(self.store.root))
        if path:
            self.store = ModelStore(path)
            self._tree_signature = None
            self.refresh_history()
            self.settings.setValue('store',str(self.store.root))

    def choose_import(self):
        path,_ = W.QFileDialog.getOpenFileName(self,'导入模型成果包','','模型成果包 (*.zip)')
        if path:
            self.import_package(path)

    def import_package(self, path):
        if self._import_future:
            return
        self._import_future = self._imports.submit(self.store.import_package,path)
        self.import_button.setEnabled(False)
        self._notice = '正在导入模型成果包…'

    def refresh_ports(self):
        current = self.port.currentText()
        self.port.clear()
        self.port.addItems([p.device for p in list_ports.comports()])
        if current:
            self.port.setEditText(current)

    def toggle_connection(self):
        if self.controller.snapshot()['connected']:
            self.controller.command('disconnect')
        else:
            try:
                baud = int(self.baud.currentText())
                if baud<=0:
                    raise ValueError()
            except ValueError:
                self._notice = '请输入有效波特率'
                return
            self.controller.command('connect',port=self.port.currentText(),baud=baud)

    def apply_configuration(self, *args):
        if not hasattr(self,'threshold_confirm'):
            return
        try:
            config = SegmentConfig(self.down_threshold.value(),self.up_threshold.value(),
                                   self.down_ms.value(),self.up_ms.value()).validate()
            self.controller.command('configure',config=config,interval_ms=self.interval.currentData() or 100,
                                    thresholds_confirmed=self.threshold_confirm.isChecked())
            self._notice = '设置已提交；当前笔完成后生效' if self.controller.snapshot().get('current') else '分笔设置已应用'
        except ValueError as exc:
            self._notice = str(exc)

    def poll(self):
        if self._closing:
            return
        if self._import_future and self._import_future.done():
            future,self._import_future = self._import_future,None
            try:
                task = future.result()
                self._notice = f"已导入：{task['name']}"
                self.refresh_history()
            except Exception as exc:
                self._notice = f'导入失败：{exc}'
            self.import_button.setEnabled(True)
        self.render_snapshot(self.controller.snapshot())

    def render_snapshot(self, snap):
        model,current = snap.get('model'),snap.get('current')
        labels = tuple(model['labels']) if model else ()
        if labels != self._model_labels:
            self._model_labels = labels
            self.score_table.setRowCount(len(labels))
        if model:
            metrics = model.get('metrics',{})
            self.model_label.setText(f"{model['name']}  ·  {len(labels)}类  ·  原评估准确率 {metrics.get('accuracy',0):.2%}")
            if snap.get('pending_model'):
                self.model_label.setText(self.model_label.text()+f"\n下一笔：{snap['pending_model']['name']}")
        self.start_button.setEnabled(bool(snap.get('ready') and not snap.get('running')))
        self.stop_button.setEnabled(bool(snap.get('running')))
        self.baseline_button.setEnabled(bool(snap.get('connected') and not snap.get('calibrating')))
        self.connect_button.setText('断开' if snap.get('connected') else '连接')
        self.port.setEnabled(not snap.get('connected'))
        self.baud.setEnabled(not snap.get('connected'))
        self.open_folder_button.setEnabled(bool(snap.get('session_path')))
        if snap.get('calibrating'):
            self.baseline_label.setText('正在采集空载基线，请保持悬空静止…')
        elif snap.get('baseline_ready'):
            count = min(snap['warmup_count'],snap['warmup_required'])
            self.baseline_label.setText(f"基线就绪 · 连续预热 {count}/{snap['warmup_required']}")
        else:
            self.baseline_label.setText('连接后保持毛笔悬空，再取基线')
        states = {'idle':'等待落笔','waiting_up':'等待离纸确认','down_pending':'确认落笔',
                  'writing':'正在书写','up_pending':'确认提笔'}
        state = ('加载模型中' if snap.get('model_loading') else
                 states.get(snap.get('state'),'待开始') if snap.get('running') else
                 '准备就绪' if snap.get('ready') else '等待连接' if not snap.get('connected') else '预览 / 待设置')
        self.state_label.setText(state)
        self.rate_label.setText(f"采样 {snap.get('sample_rate_hz',0):.0f} Hz  ·  更新 {snap.get('actual_hz',0)} Hz")
        error = snap.get('error','')
        self.error_label.setVisible(bool(error))
        self.error_label.setText(error)
        if current:
            self.current_label.setText(current.get('label') or '采集中')
            description = f"第 {current['stroke_id']} 笔 · {current['duration']:.2f} s"
            if current.get('error'):
                description += '\n'+current['error']
            self.current_detail.setText(description)
        else:
            self.current_label.setText('等待落笔' if snap.get('running') else '—')
            self.current_detail.setText(f"每 {snap.get('interval_ms',100):g} ms 更新 · 中途结果可变化")
        final = snap.get('latest_final')
        self.final_label.setText(final['label'] if final else '—')
        self.final_detail.setText(f"第 {final['stroke_id']} 笔 · {final['duration']:.2f} s · 已锁定" if final else '完整笔画识别后锁定')
        scores = current.get('scores') if current else None
        for i,name in enumerate(labels):
            self.score_table.setItem(i,0,W.QTableWidgetItem(name))
            value = f'{scores[i]:.3f}' if scores is not None and i<len(scores) else '—'
            cell = W.QTableWidgetItem(value)
            cell.setTextAlignment(C.Qt.AlignRight|C.Qt.AlignVCenter)
            if current and current.get('predicted')==i:
                cell.setForeground(G.QColor('#77dfc5'))
            self.score_table.setItem(i,1,cell)
        self._render_tables(snap)
        self._render_plot(snap)
        path = snap.get('session_path')
        status = f'自动保存 · {path}' if path else self._notice or '选择模型并连接传感器后开始。'
        if snap.get('pending_configuration'):
            status += '  ·  新设置将在下一笔生效'
        if snap.get('model_loading'):
            status += '  ·  正在加载模型'
        self.statusBar().showMessage(status)

    def _render_tables(self, snap):
        history = snap.get('history',[])
        signature = repr(history)
        if signature != self._history_signature:
            self.history_table.setRowCount(len(history))
            statuses = {'locked':'已锁定','finalizing':'最终识别中','interrupted':'已中断','unavailable':'无法识别'}
            for i,row in enumerate(history):
                cells = (str(row['stroke_id']),row.get('label') or '—',f"{row['duration']:.2f} s",
                         statuses.get(row['status'],row['status']),row.get('model_name',''))
                for j,text in enumerate(cells):
                    item = W.QTableWidgetItem(text)
                    item.setToolTip(row.get('error') or row.get('model_name',''))
                    self.history_table.setItem(i,j,item)
            self.history_table.scrollToBottom()
            self._history_signature = signature
        changes = snap.get('changes',[])
        signature = repr(changes)
        if signature != self._changes_signature:
            self.changes_table.setRowCount(len(changes))
            for i,row in enumerate(changes):
                for j,text in enumerate((f"{row['duration']:.2f} s",row.get('label') or '采集中',row.get('error') or '暂定')):
                    self.changes_table.setItem(i,j,W.QTableWidgetItem(text))
            self.changes_table.scrollToBottom()
            self._changes_signature = signature

    def _render_plot(self, snap):
        traces = snap.get('traces',[])
        if traces:
            data = np.asarray(traces,dtype=float)
            origin = data[-1,0]
            take = data[:,0]>=origin-10
            for i,curve in enumerate(self.curves):
                curve.setData(data[take,0]-origin,data[take,i+1],connect='finite')
            self.plot.setXRange(-10,0,padding=.01)
            amplitude = data[-1,3]
            self.amplitude_label.setText(f'{amplitude:.1f} µT' if np.isfinite(amplitude) else '等待基线')
            current = snap.get('current')
            reference = current or snap.get('latest_final')
            self.start_line.setVisible(bool(reference and 'first_t' in reference))
            if reference and 'first_t' in reference:
                self.start_line.setValue(reference['first_t']-origin)
                if not current:
                    self.end_line.setValue(reference['first_t']+reference['duration']-origin)
            self.end_line.setVisible(bool(reference and not current and 'first_t' in reference))
        config = snap.get('config',{})
        self.down_line.setValue(config.get('down_threshold',100))
        self.up_line.setValue(config.get('up_threshold',60))

    def open_session_folder(self):
        path = self.controller.snapshot().get('session_path')
        if path:
            G.QDesktopServices.openUrl(C.QUrl.fromLocalFile(path))

    def closeEvent(self, event):
        if self._shutdown_done.is_set():
            event.accept()
            return
        event.ignore()
        if self._closing:
            return
        self._closing = True
        self.timer.stop(); self.history_timer.stop()
        self._save_settings()
        self.setEnabled(False)
        self.statusBar().showMessage('正在完成已提交的最终识别并保存会话…')
        def shutdown():
            try:
                self._imports.shutdown(wait=True,cancel_futures=True)
                self.controller.close()
            finally:
                self._shutdown_done.set()
        threading.Thread(target=shutdown,name='stroke-shutdown',daemon=True).start()
        self._close_timer = C.QTimer(self)
        self._close_timer.timeout.connect(self._finish_close)
        self._close_timer.start(40)

    def _finish_close(self):
        if self._shutdown_done.is_set():
            self._close_timer.stop()
            self.close()
