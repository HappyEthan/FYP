import numpy as np
import pytest

from brushbot.experiments.acquisition import SampleHub


class QueueSource:
    def __init__(self, batches):
        self.batches = list(batches)

    def read_frames(self):
        return self.batches.pop(0) if self.batches else []


def _frame(t_us, values, host_rx_ns=None):
    frame = {"sensor_t_us": t_us, "B_uT": list(values)}
    if host_rx_ns is not None:
        frame["host_rx_ns"] = host_rx_ns
    return frame


def _policy(**updates):
    policy = {
        "baseline_min_samples": 3,
        "baseline_window_s": 0.02,
        "baseline_max_std_uT": [1, 1, 1],
        "baseline_max_drift_uT_s": 10,
        "airborne_confirmed": True,
        "pose_static": True,
        "filter": {"kind": "ema", "alpha": 0.5},
    }
    policy.update(updates)
    return policy


def test_baseline_subtraction_and_sensor_time_preserved():
    source = QueueSource([[_frame(2522423, [11, 22, 33])]])
    hub = SampleHub(source, clock_ns=lambda: 9000000)
    rows = hub.poll_once()
    assert rows[0]["sensor_t_us"] == 2522423
    assert rows[0]["host_rx_ns"] == 9000000
    assert np.allclose(rows[0]["B_uT"], [11, 22, 33])
    assert rows[0]["dBx_uT"] is None


def test_source_receive_time_does_not_consult_fallback_clock():
    source = QueueSource([[_frame(1, [1, 2, 3], host_rx_ns=123)]])

    def unexpected_clock_call():
        raise AssertionError("fallback clock must not replace source receive time")

    row = SampleHub(source, clock_ns=unexpected_clock_call).poll_once()[0]
    assert row["host_rx_ns"] == 123


def test_two_subscribers_do_not_consume_each_others_samples():
    source = QueueSource([[
        _frame(1, [1, 2, 3]),
        _frame(2, [4, 5, 6]),
    ]])
    hub = SampleHub(source, clock_ns=lambda: 10)
    hub.poll_once()
    assert [row["seq"] for row in hub.take_since(0)] == [1, 2]
    assert [row["seq"] for row in hub.take_since(1)] == [2]
    assert [row["seq"] for row in hub.take_since(0)] == [1, 2]


def test_take_since_checks_only_the_new_tail_for_a_recent_cursor():
    class CountingRow(dict):
        reads = 0

        def __getitem__(self, key):
            if key == "seq":
                type(self).reads += 1
            return super().__getitem__(key)

    hub = SampleHub(QueueSource([]), clock_ns=lambda: 0, max_samples=20_000)
    hub._rows.extend(CountingRow(seq=seq) for seq in range(1, 10_001))
    CountingRow.reads = 0

    rows = hub.take_since(9_999)

    assert [row["seq"] for row in rows] == [10_000]
    # One extra lookup checks whether the cursor predates the retained window.
    assert CountingRow.reads <= 4


def test_polling_continues_when_display_takes_no_samples():
    source = QueueSource([
        [_frame(1, [1, 1, 1])],
        [_frame(2, [2, 2, 2])],
    ])
    hub = SampleHub(source, clock_ns=lambda: 10)
    hub.poll_once()
    hub.poll_once()  # display is paused: no take_since call between polls
    assert [row["seq"] for row in hub.take_since(0)] == [1, 2]


def test_history_rolls_without_fault_when_reader_keeps_up():
    source = QueueSource([[_frame(seq, [1, 2, 3])]
                          for seq in range(1, 9)])
    hub = SampleHub(source, clock_ns=lambda: 10, max_samples=3)
    cursor = 0

    for expected in range(1, 9):
        hub.poll_once()
        rows = hub.take_since(cursor)
        assert [row["seq"] for row in rows] == [expected]
        cursor = rows[-1]["seq"]

    assert hub.fault is None
    assert [row["seq"] for row in hub._rows] == [6, 7, 8]


def test_reader_is_told_when_its_cursor_was_overwritten():
    source = QueueSource([[_frame(seq, [1, 2, 3])
                           for seq in range(1, 6)]])
    hub = SampleHub(source, clock_ns=lambda: 10, max_samples=3)
    hub.poll_once()

    assert hub.fault is None
    with pytest.raises(RuntimeError, match="sample_buffer_overflow"):
        hub.take_since(1)
    assert [row["seq"] for row in hub.take_since(2)] == [3, 4, 5]


def test_qualified_baseline_is_frozen_and_applied_to_future_samples():
    baseline_frames = [
        _frame(0, [10.0, 20.0, 30.0], 0),
        _frame(10_000, [10.1, 20.0, 29.9], 10_000_000),
        _frame(20_000, [9.9, 20.0, 30.1], 20_000_000),
    ]
    source = QueueSource([baseline_frames, [_frame(30_000, [12, 24, 36], 30_000_000)]])
    hub = SampleHub(source, clock_ns=lambda: 0)
    baseline_rows = hub.poll_once()
    result = hub.set_baseline(baseline_rows, _policy())
    assert result["baseline_id"] == 0
    assert result["B0_uT"] == pytest.approx([10, 20, 30])
    row = hub.poll_once()[0]
    assert row["baseline_id"] == 0
    assert [row["dBx_uT"], row["dBy_uT"], row["dBz_uT"]] == pytest.approx([2, 4, 6])


def test_diagnostic_rebaseline_records_quality_without_rejecting_noise_or_drift():
    rows = [
        {"seq": i + 1, "sensor_t_us": i * 10_000,
         "host_rx_ns": i * 10_000_000,
         "B_uT": [10.0 + 10.0 * i, 20.0 - 5.0 * i, 30.0],
         "valid": True}
        for i in range(3)
    ]
    hub = SampleHub(QueueSource([]), clock_ns=lambda: 0)

    first = hub.set_baseline(rows, _policy(), enforce_quality=False)
    second = hub.set_baseline(rows, _policy(), enforce_quality=False)

    assert first["baseline_id"] == 0
    assert second["baseline_id"] == 1
    assert first["std_uT"][0] > _policy()["baseline_max_std_uT"][0]
    assert abs(first["drift_uT_s"][0]) > _policy()["baseline_max_drift_uT_s"]


@pytest.mark.parametrize(
    ("update", "message"),
    [
        ({"airborne_confirmed": False}, "airborne"),
        ({"pose_static": False}, "pose_static"),
        ({"baseline_min_samples": 4}, "samples"),
        ({"baseline_max_std_uT": [0.01, 0.01, 0.01]}, "standard deviation"),
    ],
)
def test_baseline_failure_never_sets_ready(update, message):
    rows = [
        {"seq": i + 1, "sensor_t_us": i * 10_000,
         "host_rx_ns": i * 10_000_000, "B_uT": [10 + 0.1 * i, 20, 30],
         "valid": True}
        for i in range(3)
    ]
    hub = SampleHub(QueueSource([]), clock_ns=lambda: 0)
    with pytest.raises(ValueError, match=message):
        hub.set_baseline(rows, _policy(**update))
    assert hub.baseline_ready is False


def test_running_hub_rejects_rebaseline():
    hub = SampleHub(QueueSource([]), clock_ns=lambda: 0)
    hub.set_running(True)
    with pytest.raises(RuntimeError, match="running"):
        hub.set_baseline([], _policy())


def test_each_valid_sample_updates_filter_once_and_repeated_control_reads_do_not():
    class CountingFilter:
        def __init__(self):
            self.calls = 0

        def reset(self):
            self.calls = 0

        def update(self, value):
            self.calls += 1
            return np.asarray(value, dtype=float)

    filt = CountingFilter()
    base = [
        _frame(0, [10, 20, 30], 0),
        _frame(10_000, [10, 20, 30], 10_000_000),
        _frame(20_000, [10, 20, 30], 20_000_000),
    ]
    source = QueueSource([base, [
        _frame(30_000, [11, 22, 33], 30_000_000),
        _frame(40_000, [float("nan"), 1, 2], 40_000_000),
    ]])
    hub = SampleHub(source, clock_ns=lambda: 45_000_000, control_filter=filt)
    hub.set_baseline(hub.poll_once(), _policy())
    warmed_calls = filt.calls
    rows = hub.poll_once()
    assert rows[1]["valid"] is False
    assert filt.calls == warmed_calls + 1
    first = hub.latest_control(45_000_000)
    second = hub.latest_control(45_000_000)
    assert first == second
    assert filt.calls == warmed_calls + 1


def test_timestamp_rollback_faults_instead_of_stitching_samples():
    source = QueueSource([[
        _frame(20, [1, 2, 3]),
        _frame(10, [1, 2, 3]),
    ]])
    hub = SampleHub(source, clock_ns=lambda: 100)
    rows = hub.poll_once()
    assert rows[1]["valid"] is False
    assert rows[1]["invalid_reason"] == "sensor_time_rollback"
    assert hub.fault == "sensor_time_rollback"


def test_declared_uint32_timer_wrap_preserves_raw_time_and_valid_stream():
    # Exact consecutive device times from the aborted 中 stroke: delta = 4000 us.
    source = QueueSource([[_frame(t, [1, 2, 3]) for t in [4294963739, 443, 4443]]])
    source.sensor_time_modulus_us = 2**32
    hub = SampleHub(source, clock_ns=lambda: 100, abort_on_invalid_running_sample=True)
    hub.set_running(True)
    rows = hub.poll_once()
    assert [r['sensor_t_us'] for r in rows] == [4294963739, 443, 4443]
    assert all(r['valid'] for r in rows)
    assert hub.fault is None


@pytest.mark.parametrize('times, declared', [
    ([20000, 10000], True), ([4000, 4000], True),
    ([4294963739, 443], False), ([4292967296, 443], True),
])
def test_wrap_support_does_not_accept_resets_duplicates_or_undeclared_clocks(times, declared):
    source = QueueSource([[_frame(t, [1, 2, 3]) for t in times]])
    if declared:
        source.sensor_time_modulus_us = 2**32
    hub = SampleHub(source, clock_ns=lambda: 100)
    rows = hub.poll_once()
    assert rows[-1]['valid'] is False
    assert hub.fault == 'sensor_time_rollback'


def test_frames_after_timestamp_rollback_do_not_reenter_valid_stream():
    source = QueueSource([[
        _frame(20, [1, 2, 3]),
        _frame(10, [1, 2, 3]),
        _frame(30, [1, 2, 3]),
    ]])
    hub = SampleHub(source, clock_ns=lambda: 100)
    rows = hub.poll_once()
    assert [row["valid"] for row in rows] == [True, False, False]
    assert rows[2]["invalid_reason"] == "sensor_time_faulted"


def test_stale_control_sample_is_rejected():
    base = [
        _frame(0, [1, 2, 3], 0),
        _frame(10_000, [1, 2, 3], 10_000_000),
        _frame(20_000, [1, 2, 3], 20_000_000),
    ]
    source = QueueSource([base, [_frame(30_000, [2, 3, 4], 30_000_000)]])
    hub = SampleHub(source, clock_ns=lambda: 0)
    hub.set_baseline(hub.poll_once(), _policy(sensor_max_age_s=0.01))
    hub.poll_once()
    with pytest.raises(RuntimeError, match="stale"):
        hub.latest_control(50_000_001)
