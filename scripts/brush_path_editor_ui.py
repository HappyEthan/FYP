"""Compact, selection-driven interface for the native brush path editor."""
import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets as W
import pyqtgraph as pg

from scripts.brush_editor_interaction import SelectionViewBox, DraggablePoint


class StatusLabel(W.QLabel):
    """Keep the complete message available while drawing a single compact line."""
    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setPen(self.palette().color(QtGui.QPalette.WindowText))
        text = self.fontMetrics().elidedText(self.text(), QtCore.Qt.ElideRight, self.width())
        painter.drawText(self.rect(), QtCore.Qt.AlignVCenter, text)


class EditorLayout:
    def action(self, menu, text, callback, shortcut=None):
        action = menu.addAction(text)
        action.triggered.connect(lambda checked=False: callback())
        if shortcut:
            action.setShortcut(shortcut)
        return action

    def build_ui(self):
        self.setWindowTitle('毛笔路径编辑器')
        self.resize(1440, 860)
        self.setMinimumSize(960, 640)
        self.setStyleSheet('''
            QMainWindow, QScrollArea { background: #f5f6f8; }
            QToolBar { background: white; border: 0; border-bottom: 1px solid #dfe3e8;
                       spacing: 8px; padding: 8px; }
            QToolBar QToolButton { padding: 7px 16px; border-radius: 5px; }
            QToolBar QToolButton:hover { background: #edf2f7; }
            QGroupBox { background: white; border: 1px solid #dfe3e8; border-radius: 6px;
                        margin-top: 12px; padding: 12px 8px 8px; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; }
            QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox { min-height: 26px; }
            QPushButton { padding: 5px 10px; }
            QStatusBar { background: white; border-top: 1px solid #dfe3e8; }
        ''')
        files = self.menuBar().addMenu('文件')
        open_action = self.action(files, '打开路径…', self.open_recipe, 'Ctrl+O')
        self.action(files, '打开实验存档…', self.open_experiment_file)
        self.action(files, '实验记录…', self.show_experiment_records)
        self.action(files, '恢复编辑存档…', self.open_state)
        save_action = self.action(files, '保存', self.save_state, 'Ctrl+S')
        files.addSeparator()
        self.action(files, '导出实验版本', self.export_version)
        edit = self.menuBar().addMenu('编辑')
        undo_action = self.action(edit, '撤销', self.undo, 'Ctrl+Z')
        self.action(edit, '恢复载入状态', self.reset)
        edit.addSeparator()
        self.path_box_button = edit.addAction('框选节点')
        self.path_box_button.setCheckable(True)
        self.path_box_button.setToolTip('也可按住 Shift 拖框，Ctrl 追加选择')
        self.action(edit, '取消选择', self.clear_edit_mode)
        experiments = self.menuBar().addMenu('实验')
        self.action(experiments, '预检', self.preflight)
        self.action(experiments, '测试范围…', self.show_test_ranges)
        self.action(experiments, '恢复当前笔画完整范围', self.restore_all_points)
        advanced = self.menuBar().addMenu('高级设置')
        self.action(advanced, '运笔节奏…', self.edit_speed)
        self.action(advanced, '精确速度…', self.edit_precise_speed)
        self.action(advanced, '载入前馈表…', self.open_feedforward)

        self.toolbar = self.addToolBar('常用操作')
        self.toolbar.setMovable(False)
        self.toolbar.setContextMenuPolicy(QtCore.Qt.PreventContextMenu)
        for text, source in [('打开', open_action), ('保存', save_action), ('撤销', undo_action)]:
            action = self.toolbar.addAction(text)
            action.triggered.connect(source.trigger)
            action.setToolTip(source.text().replace('…', '') + '  ' + source.shortcut().toString())
        self.add_menu = W.QMenu(self)
        self.action(self.add_menu, '在选中段中间插点', self.add_point)
        self.action(self.add_menu, '按坐标添加…', lambda: self.show_add_points(False))
        self.action(self.add_menu, '图中点选添加', lambda: self.show_add_points(True))
        self.add_button = W.QToolButton()
        self.add_button.setText('添加点')
        self.add_button.setMenu(self.add_menu)
        self.add_button.setPopupMode(W.QToolButton.InstantPopup)
        self.toolbar.addWidget(self.add_button)
        self.toolbar.addAction('全图', self.full_view)
        spacer = W.QWidget()
        spacer.setSizePolicy(W.QSizePolicy.Expanding, W.QSizePolicy.Preferred)
        self.toolbar.addWidget(spacer)
        self.toolbar.addAction('试写', self.launch_trial).setToolTip('保存、预检并导出全部笔画，然后打开试写终端')

        self.splitter = W.QSplitter()
        self.setCentralWidget(self.splitter)
        self.path_view = SelectionViewBox(enableMenu=False)
        self.path_view.rectangleSelected.connect(self.select_path_rect)
        self.path_box_button.toggled.connect(lambda value: setattr(self.path_view, 'box_select', value))
        self.plot = pg.PlotWidget(viewBox=self.path_view, background='#faf9f4')
        self.plot.setLabel('bottom', 'X', units='mm')
        self.plot.setLabel('left', 'Y', units='mm')
        self.plot.setToolTip('拖动节点编辑路径；点击线段编辑参数；Shift 拖框，Ctrl 追加选择；滚轮缩放')
        self.plot.showGrid(x=True, y=True, alpha=.18)
        self.plot.setAspectLocked(True)
        self.plot.scene().sigMouseClicked.connect(self.add_point_at_click)
        self.plot.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.plot.customContextMenuRequested.connect(self.show_path_menu)
        self.plot.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.delete_shortcut = W.QShortcut(QtGui.QKeySequence.Delete, self.plot)
        self.delete_shortcut.setContext(QtCore.Qt.WidgetWithChildrenShortcut)
        self.delete_shortcut.activated.connect(self.delete_selected_points)
        self.escape_shortcut = W.QShortcut(QtGui.QKeySequence('Escape'), self)
        self.escape_shortcut.activated.connect(self.clear_edit_mode)
        self.splitter.addWidget(self.plot)
        self.curve = self.plot.plot(pen=pg.mkPen('#1473c9', width=3))
        self.hidden_curve = self.plot.plot(pen=pg.mkPen('#c4c4c4', width=1, style=QtCore.Qt.DotLine))
        self.selected = self.plot.plot(pen=pg.mkPen('#e39b24', width=5))
        self.compiled = self.plot.plot(pen=pg.mkPen('#24a27b', width=1, style=QtCore.Qt.DashLine))
        for curve in (self.curve, self.selected):
            curve.setCurveClickable(True, width=12)
            curve.sigClicked.connect(self.select_segment_at_click)
        self.other_stroke_curves = []
        self.other_stroke_labels = []
        self.pending_handle = DraggablePoint(size=16, movable=True, symbol='d', pen='#7c3aed', brush='#c4b5fd')
        self.plot.addItem(self.pending_handle)
        self.pending_handle.setVisible(False)
        self.pending_handle.sigPositionChangeFinished.connect(self.move_pending_point)
        self.pending_label = pg.TextItem('新笔画起点', color='#7c3aed', anchor=(.5, 1.4))
        self.pending_label.setParentItem(self.pending_handle)

        side = W.QWidget()
        right = W.QVBoxLayout(side)
        right.setContentsMargins(12, 12, 12, 12)
        right.setSpacing(12)
        scroll = W.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(side)
        scroll.setMinimumWidth(320)
        scroll.setFrameShape(W.QFrame.NoFrame)
        self.splitter.addWidget(scroll)
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, False)
        self.splitter.setStretchFactor(0, 7)
        self.splitter.setStretchFactor(1, 3)
        self.splitter.setSizes([1000, 410])
        stroke_row = W.QHBoxLayout()
        stroke_row.addWidget(W.QLabel('当前笔画'))
        self.stroke_selector = W.QComboBox()
        self.stroke_selector.currentIndexChanged.connect(self.switch_stroke)
        stroke_row.addWidget(self.stroke_selector, 1)
        plus = W.QToolButton()
        plus.setText('＋')
        plus.setToolTip('新建独立笔画')
        stroke_menu = W.QMenu(plus)
        self.new_stroke_button = self.action(stroke_menu, '在末尾新建笔画', self.begin_independent_stroke)
        self.first_stroke_button = self.action(stroke_menu, '在最前新建笔画', self.begin_first_stroke)
        plus.setMenu(stroke_menu)
        plus.setPopupMode(W.QToolButton.InstantPopup)
        stroke_row.addWidget(plus)
        right.addLayout(stroke_row)
        self.stroke_note = W.QLabel()
        right.addWidget(self.stroke_note)
        segment_row = W.QHBoxLayout()
        segment_row.addWidget(W.QLabel('路径段'))
        self.segment_selector = W.QComboBox()
        self.segment_selector.currentIndexChanged.connect(self.choose_segment)
        segment_row.addWidget(self.segment_selector, 1)
        right.addLayout(segment_row)

        self.inspector = W.QStackedWidget()
        self.segment_panel = W.QGroupBox('路径段参数')
        segment_form = W.QFormLayout(self.segment_panel)
        self.segment_fields = {}
        for column, label in [(1, '段长 mm'), (2, '路径角 °'), (5, '磁目标 μT')]:
            field = W.QLineEdit()
            field.editingFinished.connect(lambda col=column: self.commit_segment_field(col))
            self.segment_fields[column] = field
            segment_form.addRow(label, field)
        self.magnetic_inherit = W.QCheckBox('沿用原磁目标曲线')
        self.magnetic_inherit.toggled.connect(self.change_magnetic_mode)
        segment_form.addRow(self.magnetic_inherit)
        angle_title = W.QLabel('笔杆角度（°）')
        angle_title.setStyleSheet('font-weight:600; margin-top:12px')
        segment_form.addRow(angle_title)
        for column, label in [(6, '段首倾角'), (7, '段尾倾角'), (8, '段首朝向'), (9, '段尾朝向')]:
            field = W.QLineEdit()
            field.setToolTip('留空继承；倾角大于 0°、小于 30°；朝向右 0°、上 90°。相邻段共用端点。')
            field.editingFinished.connect(lambda col=column: self.commit_segment_field(col))
            self.segment_fields[column] = field
            segment_form.addRow(label, field)
        self.inspector.addWidget(self.segment_panel)
        self.point_panel = W.QGroupBox('节点坐标')
        point_form = W.QFormLayout(self.point_panel)
        self.point_x = self.coordinate_spin()
        self.point_y = self.coordinate_spin()
        self.point_x.editingFinished.connect(self.commit_point_coordinates)
        self.point_y.editingFinished.connect(self.commit_point_coordinates)
        point_form.addRow('X mm', self.point_x)
        point_form.addRow('Y mm', self.point_y)
        self.inspector.addWidget(self.point_panel)
        self.multi_panel = W.QGroupBox('整体平移')
        multi_form = W.QFormLayout(self.multi_panel)
        self.delta_x = self.coordinate_spin()
        self.delta_y = self.coordinate_spin()
        multi_form.addRow('ΔX mm', self.delta_x)
        multi_form.addRow('ΔY mm', self.delta_y)
        move = W.QPushButton('应用平移')
        move.clicked.connect(lambda: self.translate_path_selection([self.delta_x.value(), self.delta_y.value()]))
        multi_form.addRow(move)
        self.inspector.addWidget(self.multi_panel)
        right.addWidget(self.inspector)
        self.build_add_panel(right)
        self.detail = W.QLabel()
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet('color:#687481')
        right.addWidget(self.detail)
        right.addStretch(1)
        self.build_parameter_table(edit)
        self.build_test_panel()
        self.status = StatusLabel()
        self.status.setSizePolicy(W.QSizePolicy.Ignored, W.QSizePolicy.Preferred)
        self.statusBar().addWidget(self.status, 1)
        self.save_status = W.QLabel('自动保存已启用')
        self.statusBar().addPermanentWidget(self.save_status)
        self.speed_status = W.QLabel(self)
        self.speed_status.hide()

    def coordinate_spin(self):
        field = W.QDoubleSpinBox()
        field.setRange(-10000, 10000)
        field.setDecimals(4)
        field.setSingleStep(.1)
        field.setKeyboardTracking(False)
        return field

    def build_add_panel(self, right):
        self.add_panel = W.QGroupBox('添加点')
        form = W.QFormLayout(self.add_panel)
        self.insert_mode = W.QComboBox(self.add_panel)
        self.insert_mode.addItems(['末尾新笔画', '当前笔画', '最前新笔画'])
        self.insert_mode.hide()
        self.insert_order_label = W.QLabel('插入编号')
        self.insert_order = W.QSpinBox()
        self.insert_order.setToolTip('插在此编号之前；选择最大编号可末尾追加')
        form.addRow(self.insert_order_label, self.insert_order)
        self.insert_x = self.coordinate_spin()
        self.insert_y = self.coordinate_spin()
        form.addRow('X mm', self.insert_x)
        form.addRow('Y mm', self.insert_y)
        self.insert_button = W.QPushButton('按坐标添加')
        self.insert_button.clicked.connect(self.insert_coordinate_point)
        form.addRow(self.insert_button)
        self.click_insert_button = W.QPushButton('图中点选添加')
        self.click_insert_button.setCheckable(True)
        self.click_insert_button.toggled.connect(self.toggle_click_insert)
        form.addRow(self.click_insert_button)
        self.cancel_start_button = W.QPushButton('取消独立起点')
        self.cancel_start_button.clicked.connect(self.cancel_independent_start)
        form.addRow(self.cancel_start_button)
        done = W.QPushButton('完成添加')
        done.clicked.connect(self.finish_adding)
        form.addRow(done)
        self.insert_mode.currentIndexChanged.connect(self.update_insert_mode)
        self.path_box_button.toggled.connect(lambda enabled: self.click_insert_button.setChecked(False) if enabled else None)
        right.addWidget(self.add_panel)
        self.add_panel.hide()

    def build_parameter_table(self, edit_menu):
        self.table = W.QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(['点序号', '段长 mm', '路径角 °', '终点 X', '终点 Y', '磁目标 μT',
                                             '段首倾角 °', '段尾倾角 °', '段首朝向 °', '段尾朝向 °'])
        self.table.horizontalHeader().setSectionResizeMode(W.QHeaderView.Stretch)
        self.table.setSelectionBehavior(W.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(W.QAbstractItemView.SingleSelection)
        self.table.cellChanged.connect(self.cell_changed)
        self.table.itemSelectionChanged.connect(self.table_segment_selected)
        self.parameter_dock = W.QDockWidget('参数表', self)
        self.parameter_dock.setAllowedAreas(QtCore.Qt.BottomDockWidgetArea)
        self.parameter_dock.setWidget(self.table)
        self.addDockWidget(QtCore.Qt.BottomDockWidgetArea, self.parameter_dock)
        self.parameter_dock.hide()
        edit_menu.addAction(self.parameter_dock.toggleViewAction())

    def build_test_panel(self):
        self.test_dock = W.QDockWidget('测试范围', self)
        self.test_dock.setAllowedAreas(QtCore.Qt.LeftDockWidgetArea | QtCore.Qt.RightDockWidgetArea)
        body = W.QWidget()
        form = W.QFormLayout(body)
        self.test_note = W.QLabel()
        self.test_note.setWordWrap(True)
        form.addRow(self.test_note)
        self.test_first = W.QSpinBox()
        self.test_last = W.QSpinBox()
        form.addRow('当前笔画起点', self.test_first)
        form.addRow('当前笔画终点', self.test_last)
        for label, callback in [('应用当前笔画范围', self.apply_test_range), ('使用框选连续区间', self.test_selection),
                                ('使用选中路径段', self.test_selected_segment), ('隐藏选中点', self.hide_selected_points),
                                ('恢复当前笔画完整范围', self.restore_all_points)]:
            button = W.QPushButton(label)
            button.clicked.connect(callback)
            form.addRow(button)
        self.execution_ranges = W.QLabel()
        self.execution_ranges.setWordWrap(True)
        form.addRow('本次试写全部笔画', self.execution_ranges)
        self.test_dock.setWidget(body)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, self.test_dock)
        self.test_dock.hide()

    def show_test_ranges(self):
        self.test_dock.show()
        self.test_dock.raise_()

    def show_add_points(self, click=False):
        if self.model.pending_point is None:
            self.insert_mode.setCurrentIndex(1)
            if self.add_panel.isHidden():
                row = max(0, self.table.currentRow())
                self.insert_order.setValue(self.model.stroke_node_offset() + row + 1)
                midpoint = (self.model.nodes[row] + self.model.nodes[row + 1]) / 2
                self.insert_x.setValue(float(midpoint[0]))
                self.insert_y.setValue(float(midpoint[1]))
        self.reveal_add_panel()
        self.click_insert_button.setChecked(click)
        self.update_insert_mode()
        if not click:
            self.insert_x.setFocus()

    def reveal_add_panel(self):
        self.inspector.hide()
        self.add_panel.show()
        self.detail.setText('按坐标添加，或启用图中点选；完成后返回参数编辑。')

    def finish_adding(self):
        if self.model.pending_point is not None:
            self.message('请添加第二个点完成新笔画，或取消独立起点。')
            return
        self.click_insert_button.setChecked(False)
        self.add_panel.hide()
        self.inspector.show()
        self.selection_changed()

    def clear_edit_mode(self):
        self.click_insert_button.setChecked(False)
        self.path_box_button.setChecked(False)
        self.set_path_selection(set())
        if self.model.pending_point is None:
            self.add_panel.hide()
            self.inspector.show()

    def choose_segment(self, index):
        if index >= 0:
            if self.model.pending_point is None and not self.add_panel.isHidden():
                self.finish_adding()
            self.point_selection = set()
            self.paint_path_selection()
            self.table.selectRow(index)
            self.selection_changed()

    def table_segment_selected(self):
        self.point_selection = set()
        self.paint_path_selection()
        self.selection_changed()

    def sync_inspector(self):
        """Read already-rendered values; never compile or load settings during drags."""
        row = self.table.currentRow()
        self.segment_selector.blockSignals(True)
        self.segment_selector.setCurrentIndex(row)
        self.segment_selector.blockSignals(False)
        if len(self.point_selection) == 1:
            node = next(iter(self.point_selection))
            self.inspector.setCurrentWidget(self.point_panel)
            self.point_panel.setTitle(f'节点 {self.model.stroke_node_offset() + node}')
            self.point_x.setValue(float(self.model.nodes[node, 0]))
            self.point_y.setValue(float(self.model.nodes[node, 1]))
        elif len(self.point_selection) > 1:
            self.inspector.setCurrentWidget(self.multi_panel)
            self.multi_panel.setTitle(f'整体平移 · {len(self.point_selection)} 个点')
        elif row >= 0:
            self.inspector.setCurrentWidget(self.segment_panel)
            self.segment_panel.setTitle(f'路径段 {self.table.item(row, 0).text()}')
            inherited = self.model.segment_magnetic[row] is None
            self.magnetic_inherit.blockSignals(True)
            self.magnetic_inherit.setChecked(inherited)
            self.magnetic_inherit.blockSignals(False)
            for column, field in self.segment_fields.items():
                text = self.table.item(row, column).text()
                if column >= 6:
                    node = row + (column in (7, 9))
                    col = 0 if column in (6, 7) else 1
                    value = self.model.node_angles[node, col]
                    field.setText('' if value is None else format(value, '.12g'))
                    field.setPlaceholderText(f'继承 · 约 {text}°')
                elif column == 5:
                    field.setText('' if inherited else format(self.model.segment_magnetic[row], '.12g'))
                    field.setPlaceholderText(f'原曲线中点 {text} μT')
                    field.setEnabled(not inherited)
                else:
                    field.setText(text)
                field.setModified(False)

    def commit_point_coordinates(self):
        if len(self.point_selection) != 1:
            return
        node = next(iter(self.point_selection))
        values = self.model.nodes[node].copy()
        for axis, field in enumerate((self.point_x, self.point_y)):
            if round(float(values[axis]), 4) != field.value():
                values[axis] = field.value()
        if np.array_equal(self.model.nodes[node], values):
            return
        before = self.snapshot()
        try:
            self.model.nodes[node] = values
            self.model.validate()
            self.refresh(True)
            self.remember()
            self.message('节点坐标已保存，可撤销。')
        except Exception as exc:
            self.restore_snapshot(before)
            self.refresh(True)
            self.fail(exc)

    def commit_segment_field(self, column):
        field = self.segment_fields[column]
        row = self.table.currentRow()
        if row < 0 or not field.isModified():
            return
        self.set_segment_value(column, field.text().strip())

    def set_segment_value(self, column, text):
        row = self.table.currentRow()
        if row < 0:
            return
        # The formatted table value may equal the new explicit value. Still commit:
        # inherited magnetic/angle values must become explicit on user request.
        self.table.blockSignals(True)
        self.table.item(row, column).setText(text)
        self.table.blockSignals(False)
        self.cell_changed(row, column)

    def change_magnetic_mode(self, inherited):
        row = self.table.currentRow()
        if row >= 0:
            self.set_segment_value(5, '' if inherited else self.table.item(row, 5).text())

    def select_segment_at_click(self, curve, event):
        if event.button() != QtCore.Qt.LeftButton or self.click_insert_button.isChecked():
            return
        point = self.path_view.mapSceneToView(event.scenePos())
        pixels = np.asarray(self.path_view.viewPixelSize())
        points = self.model.points() / pixels
        start, end = points[:-1], points[1:]
        vector = end - start
        q = np.array([point.x(), point.y()]) / pixels
        t = np.clip(np.sum((q - start) * vector, axis=1) / np.maximum(np.sum(vector * vector, axis=1), 1e-20), 0, 1)
        edge = np.argmin(np.sum((start + t[:, None] * vector - q) ** 2, axis=1))
        row = int(np.clip(np.searchsorted(self.model.indices, edge, side='right') - 1, 0, len(self.model.nodes) - 2))
        self.choose_segment(row)
        event.accept()

    def show_path_menu(self, position):
        menu = W.QMenu(self.plot)
        if self.point_selection:
            self.action(menu, '删除选中节点', self.delete_selected_points)
        self.action(menu, '在选中段中间插点', self.add_point)
        self.action(menu, '按坐标添加…', lambda: self.show_add_points(False))
        menu.addSeparator()
        box = menu.addAction(self.path_box_button.text())
        box.setCheckable(True)
        box.setChecked(self.path_box_button.isChecked())
        box.toggled.connect(self.path_box_button.setChecked)
        self.action(menu, '取消选择 / 退出添加', self.clear_edit_mode)
        self.action(menu, '全图', self.full_view)
        menu.exec_(self.plot.mapToGlobal(position))

    def commit_pending_edits(self):
        # Toolbar buttons and shortcuts need not take focus from the editor.
        # Explicitly finish it before saving, checking, or exporting a version.
        self._edit_failed = False
        focused = self.focusWidget()
        if focused is not None:
            focused.clearFocus()
        return not self._edit_failed
