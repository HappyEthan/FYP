import numpy as np
import pytest

from brushbot.stroke_classification.features import FeatureConfig, prepare_sensor, extract
from brushbot.stroke_recognition.core import SegmentConfig, StrokeSegmenter, SensorBuffer


def rows(n=1000, start=0):
    return [dict(seq=i, sensor_t_us=i*3000, dBx_uT=80+20*np.sin(i/30),
                 dBy_uT=30+15*np.cos(i/70), valid=True, baseline_id='a')
            for i in range(start, start+n)]


def test_boundaries_backdate_and_do_not_include_debounce_tail():
    seg = StrokeSegmenter(SegmentConfig(100, 60, 40, 120))
    events = []
    for i in range(50):
        events += seg.feed(i, i*.01, 120 if 5 <= i < 25 else 20)
    down = next(e for e in events if e['type'] == 'down')
    up = next(e for e in events if e['type'] == 'up')
    assert down['first'] == 5
    assert down['confirmed_seq'] == 9
    assert up['first'] == 5 and up['last'] == 24
    assert up['confirmed_seq'] == 37
    assert seg.state == 'idle'


def test_short_low_excursion_and_stationary_contact_keep_one_stroke():
    seg = StrokeSegmenter(SegmentConfig(100, 60, 20, 80))
    events = []
    for i in range(80):
        amplitude = 30 if i < 5 or 20 <= i < 24 or i >= 60 else 130
        events += seg.feed(i, i*.01, amplitude)
    assert sum(e['type'] == 'down' for e in events) == 1
    assert sum(e['type'] == 'up_cancelled' for e in events) == 1
    assert next(e for e in events if e['type'] == 'up')['last'] == 59


def test_rearm_requires_release_and_two_strokes_are_separate():
    seg = StrokeSegmenter(SegmentConfig(100, 60, 10, 30))
    seg.reset(wait_for_up=True)
    events = []
    for i in range(60):
        high = i < 10 or 20 <= i < 30 or 40 <= i < 50
        events += seg.feed(i, i*.01, 120 if high else 10)
    assert [e['first'] for e in events if e['type'] == 'down'] == [20, 40]
    assert [e['last'] for e in events if e['type'] == 'up'] == [29, 49]


def test_short_high_spike_does_not_create_stroke_and_interrupt_is_not_up():
    seg = StrokeSegmenter(SegmentConfig(100, 60, 40, 120))
    events = []
    for i in range(15):
        events += seg.feed(i, i*.01, 120 if i == 2 or i >= 8 else 10)
    assert sum(e['type'] == 'down' for e in events) == 1
    event = seg.interrupt('断流')
    assert event['type'] == 'interrupted' and event['first'] == 8
    assert seg.state == 'waiting_up'


@pytest.mark.parametrize('args', [(20, 30), (np.nan, 0), (20, -1), (20, 10, -1, 10)])
def test_invalid_thresholds_rejected(args):
    with pytest.raises(ValueError):
        SegmentConfig(*args).validate()


def test_trimmed_buffer_keeps_continuous_ema_and_original_features():
    source = rows()
    config = FeatureConfig()
    buf = SensorBuffer(config, idle_capacity=120)
    for row in source:
        buf.append(row)
        if row['seq'] == 500:
            buf.pin(500)
    assert len(buf) <= 620
    actual = extract(buf.snapshot(500, 900), 500, 900, config)
    expected = extract(prepare_sensor(source[:901], config), 500, 900, config)
    for key in actual['representations']:
        np.testing.assert_allclose(actual['representations'][key], expected['representations'][key],
                                   atol=1e-10, equal_nan=True)
    buf.release()
    assert len(buf) == 120


def test_invalid_gap_and_baseline_reset_require_new_warmup():
    buf = SensorBuffer(FeatureConfig())
    source = rows(250)
    for row in source[:150]:
        buf.append(row)
    assert buf.ready
    bad = dict(source[150], sensor_t_us=source[150]['sensor_t_us']+1000, valid=False)
    assert not buf.append(bad).valid
    assert not buf.ready
    for row in source[151:]:
        buf.append(row)
    assert not buf.ready
    gap = dict(seq=250, sensor_t_us=900000, dBx_uT=30, dBy_uT=20, baseline_id='a')
    assert buf.append(gap).break_before
    assert not buf.ready
    changed = dict(gap, seq=251, sensor_t_us=903000, baseline_id='new')
    assert buf.append(changed).break_before


def test_device_clock_wrap_keeps_time_and_filter_continuous():
    source = rows(200)
    for row in source:
        row['sensor_t_us'] = (2**32-300000 + row['seq']*3000) % 2**32
    buf = SensorBuffer(FeatureConfig())
    for row in source:
        buf.append(row)
    assert buf.ready
    record = buf.snapshot(110, 190)
    assert not record['breaks'][1:].any()
    np.testing.assert_allclose(extract(record,110,190)['amplitude'],
                               extract(prepare_sensor(source),110,190)['amplitude'])
