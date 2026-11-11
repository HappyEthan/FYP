"""Cooperative cancellation for offline planning, independent of Qt/hardware."""
from contextlib import contextmanager
from contextvars import ContextVar


class PlanningCancelled(RuntimeError):
    pass


_cancelled = ContextVar('planning_cancelled', default=None)


def check_cancelled():
    callback = _cancelled.get()
    if callback is not None and callback():
        raise PlanningCancelled('预检已取消')


@contextmanager
def cancellable_planning(cancelled):
    token = _cancelled.set(cancelled)
    try:
        check_cancelled()
        yield
    finally:
        _cancelled.reset(token)
