"""Thread-safe storage for the latest exhibition monitor snapshot."""

from __future__ import annotations

from copy import deepcopy
from threading import RLock

from PyQt5 import QtCore


class ExhibitionStateStore(QtCore.QObject):
    """Keep one immutable-in-practice copy of the most recent snapshot.

    The gateway may call :meth:`update_snapshot` from its receiver thread.
    ``changed`` is a Qt signal, so Qt queues delivery to GUI-thread slots
    when a receiver belongs to the GUI thread.
    """

    changed = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lock = RLock()
        self._snapshot = None

    def update_snapshot(self, snapshot: dict) -> None:
        """Replace the latest snapshot and notify observers."""
        copied = deepcopy(snapshot)
        with self._lock:
            self._snapshot = copied
        self.changed.emit()

    def snapshot(self) -> dict | None:
        """Return a deep copy of the latest snapshot, if one exists."""
        with self._lock:
            return deepcopy(self._snapshot)
