"""Stable exhibition task/status vocabulary."""

from enum import Enum


class RobotState(str, Enum):
    OFFLINE = "OFFLINE"
    READY = "READY"
    PREPARING = "PREPARING"
    WRITING = "WRITING"
    DIPPING = "DIPPING"
    RETURNING = "RETURNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    FAULT = "FAULT"


class TaskState(str, Enum):
    ACCEPTED = "ACCEPTED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    FAULT = "FAULT"
