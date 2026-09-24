"""Application construction kept separate for tests and embedding."""

from PyQt5 import QtWidgets

from .window import ExhibitionWindow


def create_application(argv=None):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(argv or [])
    window = ExhibitionWindow()
    return app, window
