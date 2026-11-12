import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import unittest
from unittest.mock import patch
from xz_control.app import QApplication, Window
from xz_control.sensor import SensorPanel, SensorParser, TimingTracker, DisplayEnvelope

class SensorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])

    def test_recalibration_averages_raw_xyz_without_altering_samples(self):
        p=SensorPanel(lambda:None); p.ser=type('Port',(),{'close':lambda s:None})()
        samples=[]; p.sample_received.connect(lambda t,v,k,d:samples.append((v,d)))
        self.addCleanup(p.disconnect); self.addCleanup(p.timer.stop); self.addCleanup(p.display_timer.stop)
        p.feed(b'0,100,-20,300\n',10)
        with patch('xz_control.sensor.time.monotonic',return_value=10): p.start_calibration()
        self.assertTrue(p.calibrating)
        for i in range(1,201):
            x=99 if i%2 else 101
            p.feed(f'{i*10000},{x},-20,300\n'.encode(),10+i*.01)
        self.assertFalse(p.calibrating); self.assertEqual(p.offset,(100,-20,300))
        self.assertEqual(p.calibration_snapshot()['samples'],200)
        self.assertEqual(samples[-1][0],(101,-20,300))
        self.assertEqual(samples[-1][1]['baseline_uT'],(100,-20,300))
        self.assertEqual(p.corrected((103,-18,295)),(3,2,-5))
        # Repeated calibration replaces the baseline using original input.
        with patch('xz_control.sensor.time.monotonic',return_value=12): p.start_calibration()
        for i in range(1,201): p.feed(f'{2000000+i*10000},110,-10,310\n'.encode(),12+i*.01)
        self.assertEqual(p.offset,(110,-10,310)); self.assertEqual(p.calibration_id,2)
        self.assertEqual(p.plot.samples.snapshot()[-1]['last'],[0,0])
        p.disconnect(); self.assertEqual(p.offset,(0,0,0)); self.assertEqual(p.calibration_id,0)

    def test_failed_recalibration_keeps_previous_baseline(self):
        p=SensorPanel(lambda:None); p.ser=type('Port',(),{'close':lambda s:None})()
        self.addCleanup(p.disconnect); self.addCleanup(p.timer.stop); self.addCleanup(p.display_timer.stop)
        p.offset=(10,20,30); p.calibration_id=1
        p.feed(b'0,11,21,31\n',10)
        with patch('xz_control.sensor.time.monotonic',return_value=10): p.start_calibration()
        p.feed(b'10000,11,21,31\n',10.01)
        p.feed(b'20000,11,21,31\n',11)
        self.assertFalse(p.calibrating); self.assertEqual(p.offset,(10,20,30))
        self.assertIn('保留',p.calibration_status.text())
        p.calibration_allowed=lambda:False
        with patch('xz_control.sensor.time.monotonic',return_value=11): p.start_calibration()
        self.assertFalse(p.calibrating)

    def test_calibration_disables_motion_and_experiment_start(self):
        w=Window(); self.addCleanup(w.close)
        w.toggle_connection(); w.command('ZERO ALL'); w.command('ARM')
        self.assertTrue(w.execute.isEnabled())
        p=w.sensor; p.ser=type('Port',(),{'close':lambda s:None})()
        p.feed(b'0,1,2,3\n',10)
        with patch('xz_control.sensor.time.monotonic',return_value=10): p.start_calibration()
        self.assertTrue(p.calibrating); self.assertFalse(w.execute.isEnabled())
        self.assertFalse(w.exp_start.isEnabled()); self.assertTrue(w.stop.isEnabled())
        self.assertTrue(all(not b.isEnabled() for b in w.jog_buttons))
        p.cancel_calibration('test'); self.assertTrue(w.execute.isEnabled())

    def test_long_running_display_is_bounded_and_preserves_peaks(self):
        e=DisplayEnvelope()
        for k in range(100000): e.append((k*.003,10000 if k==99990 else 1,-9000 if k==99990 else 2,3))
        data=e.snapshot()
        self.assertLessEqual(len(data),202)
        self.assertGreaterEqual(data[0]['end'],data[-1]['end']-10)
        self.assertEqual(max(b['high'][0] for b in data),10000)
        self.assertEqual(min(b['low'][1] for b in data),-9000)
        e.append((300.,77,88,0))
        self.assertNotEqual(data[-1]['last'],e.bins[-1]['last'])

    def test_actual_firmware_header_marks_raw_B(self):
        p=SensorParser()
        self.assertIsNone(p.parse('# now streaming: t_us,Bx_uT,By_uT,Bz_uT  @115200  (for monitor)'))
        self.assertEqual(p.parse('12345,1,2,3'),(1,2,3)); self.assertEqual(p.kind,'B')

    def test_device_time_lag_and_reset(self):
        t=TimingTracker()
        self.assertEqual(t.update(1000000,10)['relative_transport_lag_s'],0)
        self.assertAlmostEqual(t.update(1010000,13.01)['relative_transport_lag_s'],3)
        r=t.update(1000,14)
        self.assertEqual(r['device_clock_reset'],1);self.assertEqual(r['device_clock_segment'],1)
        self.assertEqual(r['relative_transport_lag_s'],0)
        self.assertIsNone(t.update(None,15)['relative_transport_lag_s'])

    def test_batched_samples_keep_distinct_device_times(self):
        p=SensorPanel(lambda:None);samples=[]
        p.sample_received.connect(lambda now,values,kind,timing:samples.append(timing))
        with patch.object(p.raw,'setText') as paint:
            p.feed(b'1000,1,2,3\n4000,4,5,6\n',10)
            paint.assert_not_called()
        self.assertEqual([r['device_time_us'] for r in samples],[1000,4000])
        self.assertEqual(samples[0]['read_batch_id'],samples[1]['read_batch_id'])
        p.feed(b'dBx:1,dBy:2,dBz:3\n',11)
        self.assertIsNone(samples[-1]['device_time_us'])
        p.timer.stop();p.display_timer.stop()

    def test_formats_and_invalid_values(self):
        p=SensorParser()
        self.assertEqual(p.parse('Ymin:-600,dBx:1.25,dBy:-2,dBz:3,Ymax:600'),(1.25,-2,3))
        self.assertEqual(p.kind,'ΔB')
        self.assertIsNone(p.parse('t_us,Bx,By,Bz'))
        self.assertEqual(p.parse('123000,4,5,6'),(4,5,6)); self.assertEqual(p.kind,'B')
        for line in ('123,nan,0,0','123,inf,0,0','OK ARM','{"x":1,"z":2}', '1,2,3', 'dBx:1,dBy:2'):
            self.assertIsNone(p.parse(line))

    def test_fragmented_overlong_and_status_stale(self):
        p=SensorPanel(lambda: None)
        p.feed(b't_us,dBx,dBy,dBz\n1000,1,',10)
        self.assertEqual(p.count,0)
        p.feed(b'2,3\n'+b'A'*1100+b'\n2000,4,5,6\n',10)
        self.assertEqual(p.count,2); self.assertEqual(p.last_values,(4,5,6))
        self.assertEqual(p.bad,1)
        class Port:
            def close(self): pass
        p.ser=Port(); p.started=9
        with patch('xz_control.sensor.time.monotonic',return_value=13): p.render_status()
        self.assertIn('过期',p.status.text()); self.assertIn('—',p.values.text())
        p.disconnect(); p.timer.stop(); p.display_timer.stop()

    def test_independent_connection_no_writes_and_motor_port_guard(self):
        class Port:
            in_waiting=0
            def __init__(self, **kwargs): self.port=None
            def open(self): pass
            def close(self): pass
            def read(self,n): return b''
            def write(self,data): raise AssertionError('sensor must never write')
        w=Window(); w.toggle_connection(); w.command('ZERO ALL'); w.command('ARM')
        w.sensor.ports.clear(); w.sensor.ports.addItem('C3','/dev/test-c3')
        with patch('xz_control.sensor.serial.Serial',Port):
            w.sensor.toggle(); w.sensor.poll()
            self.assertEqual(w.sensor.port,'/dev/test-c3')
            w.sensor.feed(b'Bx:1,By:2,Bz:3\n',10)
            w.sensor.disconnect(); self.assertTrue(w.link.ready); self.assertTrue(w.s['armed'])
        w.sensor.motor_port=lambda:'/dev/test-c3'
        with patch('xz_control.sensor.serial.Serial') as factory:
            w.sensor.toggle(); factory.assert_not_called()
        w.close()

    def test_motor_cannot_open_sensor_port(self):
        w=Window()
        class Port:
            port='/dev/test-c3'
            def close(self): pass
        w.sensor.ser=Port(); w.mode.setCurrentIndex(1)
        w.ports.clear(); w.ports.addItem('C3','/dev/test-c3')
        with patch('xz_control.app.QMessageBox.warning') as warning, patch.object(w.link,'connect_to') as connect:
            w.toggle_connection(); warning.assert_called_once(); connect.assert_not_called()
        w.close()

if __name__=='__main__': unittest.main()
