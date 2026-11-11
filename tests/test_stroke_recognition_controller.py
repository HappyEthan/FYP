from collections import deque
import csv
import json
import time

import numpy as np
import pytest

from brushbot.stroke_recognition.core import SegmentConfig
from brushbot.stroke_recognition.history import load_model
from brushbot.stroke_recognition.controller import LiveController
from brushbot.stroke_recognition.replay import replay_final
from tests.test_stroke_recognition_inference import model_store


class FakeSource:
    def __init__(self, *args):
        self.frames = deque()
        self.bad_lines = 0
        self.stopped = False
    def start(self): pass
    def stop(self): self.stopped = True
    def read_frames(self):
        result = list(self.frames); self.frames.clear(); return result


class Rig:
    def __init__(self, root, model):
        self.now = 1.
        self.clock_us = 0
        self.source = FakeSource()
        self.ctrl = LiveController(root, source_factory=lambda *args:self.source,
                                   autostart=False, clock=lambda:self.now, baseline_duration=.01)
        self.ctrl.command('connect',port='fake',baud=115200)
        self.ctrl.command('set_model',model=model)
        self.ctrl.command('configure',config=SegmentConfig(50,20,12,30), interval_ms=20,
                          thresholds_confirmed=True)
        self.ctrl.command('baseline')
        self.ctrl.step()
        self.feed([0.]*10)
        self.feed([0.]*160)
        assert self.ctrl.snapshot()['ready']
        self.ctrl.command('start'); self.ctrl.step()
        self.feed([0.]*20)

    def feed(self, amplitudes):
        for offset in range(0,len(amplitudes),10):
            values = amplitudes[offset:offset+10]
            for value in values:
                self.source.frames.append(dict(sensor_t_us=self.clock_us, host_rx_ns=int(self.now*1e9),
                                               B_uT=[10+value,20.,30.]))
                self.clock_us += 3000
            self.now += .003*len(values)
            self.ctrl.step()

    def drain(self, count):
        until = time.monotonic()+5
        while time.monotonic()<until:
            self.ctrl.step()
            if sum(h['status']=='locked' for h in self.ctrl.snapshot()['history']) >= count:
                return
            time.sleep(.005)
        raise AssertionError(self.ctrl.snapshot())


def test_two_strokes_saved_and_replay_matches_frozen_model(tmp_path, model_store):
    store, task = model_store
    model = load_model(store,task['id'],task['models'][0]['id'])
    rig = Rig(tmp_path,model)
    try:
        for k in range(2):
            rig.feed((100+30*np.sin(np.linspace(0,5,120))).tolist())
            rig.feed([0.]*30)
        rig.drain(2)
        snap = rig.ctrl.snapshot()
        assert [h['stroke_id'] for h in snap['history']] == [1,2]
        assert snap['history'][0]['last'] < snap['history'][1]['first']
        path = snap['session_path']
    finally:
        rig.ctrl.close()
    results = replay_final(path)
    assert len(results)==2
    assert all(row['matches'] for row in results)
    meta = json.load(open(path+'/session.json'))
    assert meta['status']=='completed'
    assert len(meta['models'])==1


def test_disconnect_interrupts_current_stroke_without_final_prediction(tmp_path,model_store):
    store, task = model_store
    rig=Rig(tmp_path,load_model(store,task['id'],task['models'][0]['id']))
    try:
        rig.feed([100.]*40)
        rig.ctrl.command('disconnect');rig.ctrl.step()
        snap=rig.ctrl.snapshot()
        assert snap['history'][-1]['status']=='interrupted'
        assert not snap['connected']
        assert snap['history'][-1].get('predicted') is None
    finally: rig.ctrl.close()


def test_switch_model_applies_only_after_current_stroke(tmp_path,model_store):
    store,task=model_store
    first=load_model(store,task['id'],task['models'][0]['id'])
    second=load_model(store,task['id'],task['models'][-1]['id'])
    rig=Rig(tmp_path,first)
    try:
        rig.feed([100.]*30)
        rig.ctrl.command('set_model',model=second);rig.ctrl.step()
        assert rig.ctrl.snapshot()['model']['token']==first.token
        assert rig.ctrl.snapshot()['pending_model']['token']==second.token
        rig.feed([110.]*90);rig.feed([0.]*30)
        rig.feed([150.]*120);rig.feed([0.]*30)
        rig.drain(2)
        history=rig.ctrl.snapshot()['history']
        assert history[0]['model_token']==first.token
        assert history[1]['model_token']==second.token
    finally:rig.ctrl.close()


def test_stream_gap_aborts_and_requires_release_before_next_stroke(tmp_path,model_store):
    store,task=model_store
    rig=Rig(tmp_path,load_model(store,task['id'],task['models'][0]['id']))
    try:
        rig.feed([100.]*40)
        rig.clock_us += 100000
        rig.feed([100.]*160)
        snap=rig.ctrl.snapshot()
        assert snap['history'][-1]['status']=='interrupted'
        assert snap['current'] is None
        rig.feed([0.]*30);rig.feed([100.]*120);rig.feed([0.]*30)
        rig.drain(1)
        assert len(rig.ctrl.snapshot()['history'])==2
    finally:rig.ctrl.close()


def test_write_failure_stops_recognition_and_is_visible(tmp_path,model_store,monkeypatch):
    store,task=model_store
    rig=Rig(tmp_path,load_model(store,task['id'],task['models'][0]['id']))
    try:
        def fail(*args):raise OSError('disk full')
        monkeypatch.setattr(rig.ctrl.recorder,'sensor',fail)
        rig.feed([100.]*30)
        assert not rig.ctrl.snapshot()['running']
        assert 'disk full' in rig.ctrl.snapshot()['error']
    finally:rig.ctrl.close()


def test_unconfirmed_thresholds_and_missing_baseline_prevent_start(tmp_path):
    ctrl=LiveController(tmp_path,autostart=False)
    try:
        ctrl.command('start');ctrl.step()
        assert not ctrl.snapshot()['running']
        assert ctrl.snapshot()['error']
    finally:ctrl.close()
