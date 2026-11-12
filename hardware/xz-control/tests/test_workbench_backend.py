import csv
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from xz_workbench.backend import Worker
from xz_workbench.model import Recipe, Step
from xz_control.protocol import Simulator


class BrokenSensor:
    @property
    def in_waiting(self): raise OSError('sensor unplugged')
    def read(self,n): raise OSError('sensor unplugged')
    def close(self): pass


class FirmwarePort:
    """Serial boundary using the real protocol simulator and newline JSON frames."""
    def __init__(self,split_delay=0):
        self.sim=Simulator(); self.buffer=bytearray(); self.writes=[]
        self.last=time.monotonic(); self.closed=False
        self.split_delay=split_delay; self.status_due=None
    def emit(self,packets):
        for p in packets: self.buffer.extend((json.dumps(p)+'\n').encode())
    @property
    def in_waiting(self):
        now=time.monotonic()
        if self.status_due is not None:
            if now>=self.status_due: self.emit([self.sim.s.copy()]); self.status_due=None
        else: self.emit(self.sim.tick(now-self.last))
        self.last=now
        return len(self.buffer)
    def read(self,n):
        data=bytes(self.buffer[:n]); del self.buffer[:n]; return data
    def write(self,data):
        line=data.decode().strip(); self.writes.append(line)
        if line=='HELLO':
            self.emit([dict(type='hello',protocol='XZ1',move_accel=True,jog_continuous=True,numeric_ranges=True)])
            if self.split_delay: self.status_due=time.monotonic()+self.split_delay
            else: self.emit([self.sim.s.copy()])
        else: self.emit(self.sim.command(line))
        return len(data)
    def close(self): self.closed=True


def until(predicate,seconds=4):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        if predicate(): return
        time.sleep(.015)
    raise AssertionError('等待工作台状态超时')


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.worker=Worker(); self.worker.start()
        self.worker.submit('connect_motor',port='DEMO')
        until(lambda:self.worker.snapshot().get('ready'))
        self.worker.submit('zero',axis='ALL')
        until(lambda:(self.worker.snapshot().get('status') or {}).get('refx')==1)
        self.worker.submit('arm')
        until(lambda:(self.worker.snapshot().get('status') or {}).get('armed')==1)

    def tearDown(self): self.worker.shutdown()

    def test_demo_motion_never_opens_serial_and_finishes_recipe(self):
        with patch('serial.Serial',side_effect=AssertionError('demo opened hardware')):
            self.worker.submit('run',recipe=Recipe('demo',[Step('relative','X',.1)]))
            until(lambda:(self.worker.snapshot().get('status') or {}).get('x')==25 and self.worker.snapshot().get('owner') is None)

    def test_function_recording_waits_for_sensor_and_preserves_csv(self):
        self.worker.submit('connect_sensor',port='DEMO',baud=115200)
        until(lambda:self.worker.snapshot().get('sensor_alive'))
        self.worker.submit('baseline',seconds=.12)
        until(lambda:self.worker.snapshot().get('baseline') is not None)
        with tempfile.TemporaryDirectory() as td:
            self.worker.submit('run_record',root=td,recipe=Recipe('small',[Step('relative','X',.1)]))
            until(lambda:list(Path(td).glob('*/metadata.json')) and not self.worker.snapshot().get('recording') and (self.worker.snapshot().get('status') or {}).get('x')==25)
            until(lambda:any('completed' in p.read_text() for p in Path(td).glob('*/metadata.json')))
            path=next(Path(td).glob('*/sensor.csv'))
            with path.open(encoding='utf-8-sig') as f: rows=list(csv.DictReader(f))
            self.assertGreater(len(rows),1)
            self.assertIn('step_001',{r['stage'] for r in rows})
            self.assertTrue(all(r['motor_fault']=='NONE' for r in rows))

    def test_missing_sensor_prevents_run_and_capture(self):
        with tempfile.TemporaryDirectory() as td:
            self.worker.submit('run_record',root=td,recipe=Recipe('x',[Step('relative','X',1)]))
            until(lambda:bool(self.worker.snapshot().get('notice')))
            self.assertEqual(self.worker.snapshot()['status']['x'],0)
            self.assertFalse(list(Path(td).iterdir()))

    def test_quick_press_and_release_cannot_start_late_jog(self):
        self.worker.submit('jog',axis='X',direction=1)
        self.worker.submit('release')
        until(lambda:self.worker.snapshot().get('owner') is None)
        time.sleep(.1)
        self.assertIsNone(self.worker.snapshot().get('owner'))

    def test_failed_baseline_keeps_devices_connected(self):
        self.worker.submit('connect_sensor',port='DEMO',baud=115200)
        until(lambda:self.worker.snapshot().get('sensor_alive'))
        self.worker.submit('baseline',seconds=.001)
        until(lambda:'不足' in self.worker.snapshot().get('notice',''))
        self.assertTrue(self.worker.snapshot()['ready'])
        self.assertTrue(self.worker.snapshot()['sensor_alive'])

    def test_unrecorded_sensor_failure_does_not_interrupt_motor(self):
        with patch('xz_workbench.backend.open_port',return_value=BrokenSensor()):
            self.worker.submit('connect_sensor',port='/dev/test-sensor',baud=115200)
            until(lambda:'sensor unplugged' in self.worker.snapshot().get('notice',''))
            self.assertTrue(self.worker.snapshot()['ready'])
            self.assertEqual(self.worker.snapshot()['status']['armed'],1)

    def test_real_transport_handshake_and_movement_use_one_serial_owner(self):
        self.worker.submit('disconnect_motor')
        until(lambda:not self.worker.snapshot().get('ready'))
        port=FirmwarePort()
        with patch('xz_workbench.backend.open_port',return_value=port):
            self.worker.submit('connect_motor',port='/dev/test-motor')
            until(lambda:self.worker.snapshot().get('ready') and self.worker.snapshot().get('pending') is None)
            self.assertIn('HELLO',port.writes)
            self.assertIn('DISARM',port.writes)
            self.assertEqual(self.worker.snapshot()['status']['armed'],0)
            self.worker.submit('zero',axis='ALL')
            until(lambda:self.worker.snapshot()['status']['refx']==1)
            self.worker.submit('arm')
            until(lambda:self.worker.snapshot()['status']['armed']==1)
            self.worker.submit('run',recipe=Recipe('short',[Step('relative','X',.1)]))
            until(lambda:self.worker.snapshot()['status']['x']==25 and self.worker.snapshot()['owner'] is None)
            self.assertTrue(any(c.startswith('MOVE ABS') for c in port.writes))

    def test_hello_and_initial_status_can_arrive_in_separate_reads(self):
        self.worker.submit('disconnect_motor'); until(lambda:not self.worker.snapshot().get('ready'))
        port=FirmwarePort(split_delay=.2)
        with patch('xz_workbench.backend.open_port',return_value=port):
            self.worker.submit('connect_motor',port='/dev/test-motor')
            until(lambda:'HELLO' in port.writes)
            time.sleep(.1)
            self.assertFalse(port.closed,'完整握手尚在进行，不应因 status 晚到关闭串口')
            until(lambda:self.worker.snapshot().get('ready'))


class PreparationTests(unittest.TestCase):
    def test_waiting_for_first_sample_reserves_motion_owner(self):
        worker=Worker(); state=Simulator().s.copy(); state.update(armed=1,refx=1,refz=1)
        worker.engine.connect(state); worker.baseline=(0,0,0); worker.last_sensor=time.monotonic()
        with tempfile.TemporaryDirectory() as td:
            try:
                worker._start_record(td,Recipe('pending',[Step('relative','X',1)]))
                self.assertFalse(worker.engine.idle())
                with self.assertRaises(ValueError): worker.engine.move(Step('relative','Z',1))
            finally:
                worker._end_record('aborted','test end'); worker.shutdown()


if __name__=='__main__': unittest.main()
