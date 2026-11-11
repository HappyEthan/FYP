"""Dark desktop palette, scoped to the classifier window."""
BACKGROUND='#0d121c'
PANEL='#141d2b'
TEXT='#e4ebf5'
MUTED='#96a6bf'
COLORS=('#82afff','#66d9c4','#e7b777','#c19bf5','#f08eab','#91c984','#c4cfdf')

STYLE='''
QMainWindow, QDialog { background: #0d121c; color: #e4ebf5; }
QWidget { color: #e4ebf5; font-family: "Noto Sans CJK SC", "Microsoft YaHei", sans-serif; font-size: 13px; }
QWidget#sidebar { background:#101826; border-right:1px solid #253047; }
QLabel#brand { font-size:22px; font-weight:600; color:#ecf2ff; }
QLabel#eyebrow { color:#82afff; font-size:11px; letter-spacing:2px; }
QLabel#title { font-size:25px; font-weight:600; }
QLabel#subtitle, QLabel#muted { color:#96a6bf; }
QLabel#section { font-size:15px; font-weight:600; }
QLabel#status { background:#101826; border-top:1px solid #253047; padding:9px 18px; color:#a8b8d1; }
QLabel#notice { background:#19263a; color:#bbcee9; border-radius:7px; padding:10px 12px; }
QFrame#panel, QGroupBox { background:#141d2b; border:1px solid #26334a; border-radius:9px; }
QGroupBox { margin-top:13px; padding:18px 12px 12px; }
QGroupBox::title { subcontrol-origin:margin; left:13px; padding:0 5px; color:#c1d0e6; }
QListWidget#navigation { background:transparent; border:none; outline:none; padding:8px; }
QListWidget#navigation::item { padding:14px 13px; margin:4px 0; border-radius:7px; color:#9eafc9; }
QListWidget#navigation::item:selected { background:#223552; color:#deebff; }
QListWidget#navigation::item:hover { background:#1a2940; }
QPushButton { background:#213049; border:1px solid #344661; border-radius:6px; padding:8px 14px; color:#dce7f7; }
QPushButton:hover { background:#2a3d5b; border-color:#5b7da8; }
QPushButton:pressed { background:#17253a; }
QPushButton:disabled { background:#17202e; border-color:#263246; color:#62718a; }
QPushButton#primary { background:#82afff; color:#0c1930; border:1px solid #82afff; font-weight:600; }
QPushButton#primary:hover { background:#a0c1ff; }
QPushButton#primary:disabled { background:#2b3d58; border-color:#2b3d58; color:#7c90af; }
QPushButton#danger { color:#f1a7b6; }
QTableWidget, QTreeWidget, QListWidget, QTextEdit, QPlainTextEdit { background:#141d2b; alternate-background-color:#182334; border:1px solid #28364d; border-radius:7px; gridline-color:#28364d; selection-background-color:#263e60; selection-color:#edf4ff; }
QHeaderView::section { background:#192538; color:#a8bad5; border:none; border-bottom:1px solid #30405a; padding:10px 8px; }
QTableWidget::item, QTreeWidget::item { padding:7px; border:none; }
QTreeWidget::item:selected { background:#263e60; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { background:#0f1826; color:#e4ebf5; border:1px solid #33445f; border-radius:5px; padding:6px 9px; min-height:20px; selection-background-color:#3e5f8b; }
QComboBox::drop-down { border:none; width:24px; }
QComboBox QAbstractItemView { background:#182538; selection-background-color:#304c72; }
QCheckBox { spacing:9px; padding:4px; }
QCheckBox::indicator { width:17px; height:17px; border:1px solid #607591; border-radius:4px; background:#101a29; }
QCheckBox::indicator:checked { background:#82afff; border-color:#b5d0ff; image:url(none); }
QTabWidget::pane { border:none; background:transparent; padding-top:10px; }
QTabBar::tab { background:#141f30; color:#a4b6cf; padding:10px 18px; border-bottom:2px solid transparent; }
QTabBar::tab:selected { background:#1c2d46; color:#cde0ff; border-bottom:2px solid #82afff; }
QProgressBar { background:#1c293d; border:none; border-radius:5px; color:#c7d8ee; min-height:12px; text-align:center; }
QProgressBar::chunk { background:#82afff; border-radius:5px; }
QScrollArea { border:none; background:transparent; }
QScrollBar:vertical { background:#121c2a; width:10px; margin:0; }
QScrollBar::handle:vertical { background:#3a4b64; min-height:32px; border-radius:5px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QScrollBar:horizontal { background:#121c2a; height:10px; margin:0; }
QScrollBar::handle:horizontal { background:#3a4b64; min-width:32px; border-radius:5px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width:0; }
QTableCornerButton::section { background:#192538; border:none; }
QSplitter::handle { background:#223149; width:2px; }
QToolTip { background:#21324a; color:#e4ebf5; border:1px solid #526b8e; padding:5px; }
QMenu { background:#182538; border:1px solid #3b506d; padding:5px; }
QMenu::item { padding:7px 18px; }
QMenu::item:selected { background:#304c72; }
'''
