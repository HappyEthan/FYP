"""Visual tokens for the exhibition monitor shell."""

COLORS = {
    "canvas": "#eee9dc",
    "surface": "#faf5e9",
    "ink": "#203f38",
    "primary": "#2d9c86",
    "secondary": "#74b8a7",
    "accent": "#b56b2f",
}


def stylesheet() -> str:
    return f"""
    QMainWindow, QWidget#monitor-page {{ background: {COLORS['canvas']}; color: {COLORS['ink']}; }}
    QWidget {{ color: {COLORS['ink']}; font-size: 14px; }}
    QLabel#title {{ font-size: 26px; font-weight: 700; }}
    QLabel#status {{ color: {COLORS['secondary']}; }}
    QFrame#xy-plot, QGroupBox {{ background: {COLORS['surface']}; border: 1px solid {COLORS['secondary']}; border-radius: 8px; }}
    QGroupBox {{ margin-top: 12px; padding: 18px 12px 12px; font-weight: 600; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; }}
    QLineEdit, QComboBox {{ background: {COLORS['surface']}; border: 1px solid {COLORS['secondary']}; border-radius: 5px; padding: 7px; min-height: 28px; }}
    QPushButton {{ background: {COLORS['primary']}; color: white; border: none; border-radius: 5px; padding: 8px 14px; min-height: 44px; font-weight: 600; }}
    QPushButton:hover {{ background: {COLORS['accent']}; }}
    QPushButton#capture-baseline {{ background: {COLORS['accent']}; }}
    """
