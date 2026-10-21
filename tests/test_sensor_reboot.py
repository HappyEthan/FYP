"""A trial must never proceed on old frames or an unconfirmed board reset."""
import pytest

from brushbot.monitor.sources import SerialSource


ACK = b'# fw=fixed90 reboot requested\n'


class Clock:
    def __init__(self):
        self.t = 0.

    def now(self):
        return self.t

    def sleep(self, dt):
        self.t += dt


class Port:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.writes = []
        self.closed = False
        self.cleared = False

    def reset_input_buffer(self):
        self.cleared = True

    def write(self, payload):
        self.writes.append(payload)
        return len(payload)

    def flush(self):
        pass

    def close(self):
        self.closed = True

    def read(self, size):
        item = self.chunks.pop(0) if self.chunks else b''
        if isinstance(item, Exception):
            raise item
        return item


def reboot(src, clock):
    return src.reboot(timeout_s=.5, monotonic=clock.now, sleep=clock.sleep)


def test_reboot_requires_ack_then_ready_and_preserves_first_new_frame():
    src = SerialSource()
    port = Port([b'90000000,9,9,9\nREADY\n', ACK[:12], ACK[12:]+b'\nREADY\n',
                 b'100000,nan,2,3\n90000000,9,9,9\n200000,11,', b'22,33\n204000,12,23,34\n'])
    src._ser = port
    src._buf = b'old partial frame'
    clock = Clock()
    result = src.reboot(monotonic=clock.now, sleep=clock.sleep)
    assert clock.t < .1  # A successful restart must not wait out the timeout.
    assert port.writes == [b'REBOOT\n']
    assert port.cleared
    assert result['status'] == 'completed'
    assert result['first_frame_sensor_t_us'] == 200000
    assert result['ack_host_ns'] <= result['ready_host_ns'] <= result['completed_host_ns']
    assert [(r['sensor_t_us'], r['B_uT']) for r in src.read_frames()] == [
        (200000, [11., 22., 33.]), (204000, [12., 23., 34.])]


def test_reboot_reopens_usb_after_ack_without_sending_second_command(monkeypatch):
    src = SerialSource()
    old = Port([ACK, OSError('USB disconnected')])
    new = Port([b'# startup\nREA', b'DY\n200000,11,22,33\n'])
    src._ser = old
    attempts = []
    def reopen():
        attempts.append(True)
        if len(attempts) == 1:
            raise OSError('USB not enumerated yet')
        src._ser = new
    monkeypatch.setattr(src, 'start', reopen)
    result = reboot(src, Clock())
    assert old.closed
    assert old.writes == [b'REBOOT\n'] and new.writes == []
    assert result['reconnect_count'] == 1
    assert src.read_frames()[0]['sensor_t_us'] == 200000


@pytest.mark.parametrize('chunks', [
    [b'READY\n200000,11,22,33\n'],  # Old firmware never acknowledges REBOOT.
    [ACK, b'200000,11,22,33\n'],  # ACK alone is not a successful restart.
    [ACK, b'READY\n200000,nan,22,33\n'],
    [ACK, b'READY\n90000000,11,22,33\n'],  # Old uptime after READY.
])
def test_reboot_timeout_closes_port_and_rejects_unconfirmed_or_bad_startup(chunks):
    src = SerialSource()
    port = Port(chunks)
    src._ser = port
    with pytest.raises(RuntimeError, match='reboot'):
        reboot(src, Clock())
    assert port.closed and src._ser is None


def test_disconnect_before_ack_is_not_assumed_to_be_successful_reboot():
    src = SerialSource()
    port = Port([OSError('USB disconnected')])
    src._ser = port
    with pytest.raises(RuntimeError, match='acknowledg'):
        reboot(src, Clock())
    assert port.closed and src._ser is None


def test_reboot_requires_open_port():
    with pytest.raises(RuntimeError, match='not open'):
        reboot(SerialSource(), Clock())


def test_default_reboot_timeout_stops_after_five_seconds_without_ack():
    src = SerialSource()
    port = Port([])
    src._ser = port
    clock = Clock()
    with pytest.raises(RuntimeError, match='acknowledgment'):
        src.reboot(monotonic=clock.now, sleep=clock.sleep)
    assert clock.t == pytest.approx(5., abs=.011)
    assert port.closed and src._ser is None
