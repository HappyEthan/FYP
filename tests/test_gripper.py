import pytest

from brushbot.gripper import (
    Gripper, GripperCommandError, GripperProtocolError, GripperTimeoutError,
)


class FakeClient:
    def __init__(self, replies=None):
        self.replies = list(replies or [])
        self.calls = []

    def HRApp(self, name, param):
        self.calls.append((name, param))
        return self.replies.pop(0) if self.replies else ["0", "GRIPPEROK"]


def query(value):
    return ["0", "GRIPPEROK", str(value)]


def test_absolute_commands_and_units():
    client = FakeClient()
    gripper = Gripper(client)
    gripper.open(speed=20, force=40)
    gripper.close()
    gripper.move_to_width(10)
    assert client.calls == [
        ("hr_gri_plugins", "GripperAbsCatchMove,1,1000,20,40"),
        ("hr_gri_plugins", "GripperAbsCatchMove,1,0,30,30"),
        ("hr_gri_plugins", "GripperAbsCatchMove,1,105,30,30"),
    ]
    assert Gripper.raw_to_width(1000) == 95.0
    assert Gripper.width_to_raw(95) == 1000


def test_relative_stop_and_clear_fault_commands():
    client = FakeClient()
    gripper = Gripper(client, gid=2)
    gripper.move_rel(-9.5, speed=10, force=20)
    gripper.stop()
    gripper.clear_fault()
    assert [call[1] for call in client.calls] == [
        "GripperRelCatchMove,2,-100,10,20",
        "GripperStop,2",
        "GripperClearFault,2",
    ]


@pytest.mark.parametrize("kwargs", [
    {"speed": 0}, {"speed": 101}, {"force": 19}, {"force": 101},
])
def test_motion_parameter_validation(kwargs):
    with pytest.raises(ValueError):
        Gripper(FakeClient()).open(**kwargs)


def test_width_validation_happens_before_command():
    client = FakeClient()
    with pytest.raises(ValueError):
        Gripper(client).move_to_width(95.1)
    assert not client.calls


def test_command_error_is_readable_and_preserves_code():
    gripper = Gripper(FakeClient([["60002"]]))
    with pytest.raises(GripperCommandError, match="RS485") as caught:
        gripper.open()
    assert caught.value.code == 60002


def test_read_connected_state():
    client = FakeClient([
        ["0", "GRIPPEROK", "GRIPPEROK"], query(0), query(1),
        query(105), query(0),
    ])
    state = Gripper(client).read()
    assert state.connected is True
    assert state.moving is False
    assert state.caught is True
    assert state.catch_state == 1
    assert state.raw_position == 105
    assert state.width_mm == pytest.approx(9.975)
    assert state.error_code == 0


def test_read_disconnected_state_does_not_issue_more_queries():
    client = FakeClient([["0", "GRIPPERFAIL", "60000"]])
    state = Gripper(client).read()
    assert state.connected is False
    assert state.moving is None
    assert state.error_code == 60000
    assert len(client.calls) == 1


def test_malformed_query_reply_raises_protocol_error():
    with pytest.raises(GripperProtocolError):
        Gripper(FakeClient([["0", "GRIPPEROK"]])).is_moving()


def test_wait_done_polls_then_returns_state():
    client = FakeClient([
        query(1), query(0),
        ["0", "GRIPPEROK", "GRIPPEROK"], query(0), query(0),
        query(1000), query(0),
    ])
    gripper = Gripper(client, sleep=lambda _: None)
    state = gripper.wait_done(timeout=1)
    assert state.width_mm == 95.0


def test_wait_timeout_stops_gripper():
    ticks = iter([0.0, 1.0])
    client = FakeClient([query(1), ["0", "GRIPPEROK"]])
    gripper = Gripper(client, clock=lambda: next(ticks), sleep=lambda _: None)
    with pytest.raises(GripperTimeoutError):
        gripper.wait_done(timeout=0.5)
    assert client.calls[-1][1] == "GripperStop,1"
