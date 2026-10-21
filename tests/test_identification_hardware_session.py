"""Exercise real session ownership against fake device boundaries; never connect."""
import copy
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest


@pytest.mark.parametrize('record_tcp', [False, True])
@pytest.mark.parametrize('interrupt', [False, True])
@pytest.mark.parametrize('worker_stopped', [False, True])
def test_session_reuses_devices_and_closes_once(monkeypatch, tmp_path, record_tcp, interrupt, worker_stopped):
    from scripts import run_z_identification as runner
    import brushbot.backends.huayan as huayan
    from brushbot.experiments.adapter import _coord_to_vendor
    setup = json.loads(runner.SETTINGS.read_text())
    events, robots, sockets, samplers, trials = [], [], [], [], []

    class Socket:
        def __init__(self):
            self.closed = False
            sockets.append(self)
        def settimeout(self, value):
            pass
        def close(self):
            assert not self.closed
            self.closed = True
    class Robot:
        def __init__(self, *args, **kwargs):
            robots.append(self)
            self.client = SimpleNamespace(raw_client=SimpleNamespace(tcp=Socket()))
            self.arm = SimpleNamespace()
    class Source:
        def __init__(self, *args):
            self.started = False
        def start(self):
            assert not self.started
            self.started = True
            events.append('serial_open')
        def stop(self):
            assert self.started
            self.started = False
            events.append('serial_close')
    class Lock:
        def __init__(self, *args):
            pass
        def acquire(self):
            events.append('lock')
        def release(self):
            events.append('unlock')
    class Sampler:
        def __init__(self, reader, **kwargs):
            self.reader = reader
            samplers.append(self)
    module, vendor = ModuleType('huayan_robot'), ModuleType('huayan_robot.vendor')
    module.HuayanRobot = Robot
    vendor.CPSClient = lambda _: SimpleNamespace(tcp=Socket())
    monkeypatch.setitem(sys.modules, 'huayan_robot', module)
    monkeypatch.setitem(sys.modules, 'huayan_robot.vendor', vendor)
    monkeypatch.setattr(runner, 'SerialSource', Source)
    monkeypatch.setattr(runner, 'RobotResourceLock', Lock)
    monkeypatch.setattr(runner, 'TCPPoseSampler', Sampler)
    monkeypatch.setattr(runner, '_report', lambda _: None)
    monkeypatch.setattr(runner, 'ElfinExperimentArm', lambda robot, s, **kw:
                        SimpleNamespace(robot=robot, setup=copy.deepcopy(s)))
    monkeypatch.setattr(huayan, 'HuayanBackend', lambda client, **kw:
                        SimpleNamespace(read=lambda: SimpleNamespace(tcp_pose=(0,)*6)))
    def read_coordinate(client, method, name):
        events.append(method)
        return _coord_to_vendor(setup['tool_coord_si' if 'TCP' in method else 'user_coord_si'])
    monkeypatch.setattr(runner, '_read_named_coordinate', read_coordinate)
    def factory(**kwargs):
        assert kwargs['source'].started
        assert not any(s.closed for s in sockets)
        trials.append(kwargs)
        return SimpleNamespace(), SimpleNamespace()
    def run(engine, hub, **kwargs):
        if record_tcp:
            assert kwargs['pose_sampler'].reader() == (0,)*6
        return {'state': 'END_WAIT', 'pose_capture': {'worker_stopped': worker_stopped}
                if record_tcp else None}
    monkeypatch.setattr(runner, 'run_recorded', run)
    def batch():
        with runner.hardware_session(setup, record_tcp=record_tcp) as session:
            for y in (500., 450.):
                current = dict(setup, origin_y_mm=y)
                code = runner.execute_hardware({}, current, b'{}', tmp_path,
                    record_tcp=record_tcp, stack_factory=factory, session=session)
                assert code == (2 if record_tcp and not worker_stopped else 0)
                if code:
                    break
            if interrupt:
                raise ConnectionResetError('test peer reset')
    if interrupt:
        with pytest.raises(ConnectionResetError):
            batch()
    else:
        batch()
    assert len(robots) == 1
    assert len(sockets) == (2 if record_tcp else 1)
    assert all(s.closed for s in sockets)
    if len(trials) == 2:
        assert trials[0]['source'] is trials[1]['source']
        assert trials[0]['clock'] is trials[1]['clock']
    expected_y = [500.] if record_tcp and not worker_stopped else [500., 450.]
    assert [t['arm'].setup['origin_y_mm'] for t in trials] == expected_y
    assert len(samplers) == (len(expected_y) if record_tcp else 0)
    assert events == ['lock', 'HRIF_ReadTCPByName', 'HRIF_ReadUCSByName',
                      'serial_open', 'serial_close', 'unlock']
