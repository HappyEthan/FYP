import math

import pytest

from brushbot.exhibition_monitor.pressure_practice import (
    PracticeConfig,
    PressurePracticeEngine,
)


TEMPLATE = {
    "S": ((0.0, 0.0), (1.0, 0.0)),
    "Z": ((0.0, 0.0), (1.0, 1.0)),
}


def down(engine, t):
    return engine.update(150.0, t)


def up(engine, t):
    return engine.update(0.0, t)


def start_s(engine):
    engine.update(150.0, 0.0)
    return engine.update(150.0, 0.08)


def finish_s(engine):
    start_s(engine)
    state = engine.state
    for index in range(1, 10):
        state = engine.update(300.0, 0.08 + index * 0.2)
    return state


def test_first_down_starts_s_and_pressure_controls_speed():
    engine = PressurePracticeEngine(TEMPLATE)
    assert engine.state.status == "idle_wait_s_down"
    assert engine.update(150.0, 0.0).status == "idle_wait_s_down"
    assert engine.update(150.0, 0.08).status == "s_writing"
    state = engine.update(300.0, 0.18)
    assert state.progress == pytest.approx(0.08)
    assert state.pen_down is True


def test_low_pressure_pauses_without_clearing_progress():
    engine = PressurePracticeEngine(TEMPLATE)
    start_s(engine)
    writing = engine.update(300.0, 0.18)
    assert writing.progress > 0
    paused = engine.update(0.0, 0.18)
    assert paused.status == "s_writing"
    paused = engine.update(0.0, 0.26)
    assert paused.status == "s_paused"
    assert paused.progress == pytest.approx(writing.progress)


def test_s_completion_enters_one_second_pause():
    engine = PressurePracticeEngine(TEMPLATE)
    finish_s(engine)
    assert engine.state.status == "s_finished_pause"
    assert engine.update(0.0, 2.39).status == "s_finished_pause"
    assert engine.update(0.0, 2.49).status == "wait_z_down"


def test_pause_with_existing_up_allows_next_down_to_start_z():
    engine = PressurePracticeEngine(TEMPLATE)
    finish_s(engine)
    engine.update(0.0, 2.39)
    assert engine.update(0.0, 2.49).status == "wait_z_down"
    assert engine.update(150.0, 2.49).status == "wait_z_down"
    assert engine.update(150.0, 2.59).status == "z_writing"


def test_high_pressure_through_pause_requires_up_then_down_before_z():
    engine = PressurePracticeEngine(TEMPLATE)
    finish_s(engine)
    assert engine.update(300.0, 2.49).status == "wait_z_up"
    assert engine.update(300.0, 2.5).status == "wait_z_up"
    assert engine.update(0.0, 2.5).status == "wait_z_up"
    assert engine.update(0.0, 2.58).status == "wait_z_down"
    assert engine.update(150.0, 2.58).status == "wait_z_down"
    assert engine.update(150.0, 2.66).status == "z_writing"


def test_z_completion_enters_done_and_does_not_loop():
    engine = PressurePracticeEngine(TEMPLATE)
    finish_s(engine)
    engine.update(0.0, 2.39)
    engine.update(0.0, 2.49)
    engine.update(150.0, 2.49)
    engine.update(150.0, 2.59)
    for index in range(1, 10):
        state = engine.update(300.0, 2.59 + index * 0.2)
    assert state.status == "done"
    state = engine.update(300.0, 100.0)
    assert state.status == "done"
    assert state.progress == pytest.approx(1.0)
    assert state.active_letter == "Z"


def test_invalid_pressure_does_not_advance_progress():
    engine = PressurePracticeEngine(TEMPLATE)
    start_s(engine)
    before = engine.update(300.0, 0.18).progress
    for value, t in ((None, 10.0), (math.nan, 10.5), (math.inf, 11.0)):
        state = engine.update(value, t)
        assert state.progress == pytest.approx(before)
    assert engine.update(300.0, 11.1).progress > before


def test_default_config_and_boundary_pressure_are_deterministic():
    config = PracticeConfig()
    assert config.threshold_uT == 100.0
    engine = PressurePracticeEngine(TEMPLATE, config)
    engine.update(110.0, 0.0)
    assert engine.update(110.0, 0.08).status == "s_writing"
    state = engine.update(100.0, 0.18)
    assert state.status == "s_writing"
