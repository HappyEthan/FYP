import csv
import tempfile
import unittest
import time
from unittest.mock import patch
from pathlib import Path
from xz_workbench.recording import Frame, SensorDecoder, Recorder, BaselineCollector

HEADER='seq,sensor_t_us,device_time_unwrapped_us,device_clock_segment,sensor_t_s,host_rx_ns,host_elapsed_s,stage,motor_x_pulses,motor_z_pulses,motor_target_x_pulses,motor_target_z_pulses,motor_busy,motor_phase,motor_fault,Bx_uT,By_uT,Bz_uT,dBx_uT,dBy_uT,dBz_uT,sample_valid,invalid_reason'.split(',')


class RecordingTests(unittest.TestCase):
    def test_decoder_partial_lines_wrap_reset_and_bad_lines(self):
        decoder=SensorDecoder()
        self.assertEqual(decoder.feed(b'4294967290,1,2',1),[])
        frames=decoder.feed(b',3\n10,2,3,4\n5,3,4,5\nnan,1,2,3\n6,nan,2,3\n',2)
        self.assertEqual(len(frames),3)
        self.assertEqual(frames[1].unwrapped_us,4294967306)
        self.assertEqual((frames[2].segment,frames[2].unwrapped_us),(1,5))
        self.assertEqual(decoder.bad_lines,2)

    def test_baseline_requires_valid_samples_and_keeps_xyz(self):
        b=BaselineCollector(0,duration=2)
        for i in range(20): b.add(Frame(i,i,0,i,10,20,30))
        self.assertFalse(b.ready(1))
        self.assertEqual(b.finish(2)['baseline'],(10.,20.,30.))
        with self.assertRaises(ValueError): BaselineCollector(0).finish(2)

    def test_saved_csv_has_original_schema_deltas_and_preserved_spike(self):
        with tempfile.TemporaryDirectory() as td:
            recorder=Recorder(td,(10,20,30),{'demo':True})
            state={'x':12,'z':-5,'tx':100,'tz':-5,'busy':1,'phase':3,'fault':'NONE'}
            for i,bx in enumerate([11,12,2012,12,11]):
                recorder.append(Frame(i*1000,i*1000,0,1000000000+i*1000000,bx,22,33),'step_001',state)
            path=recorder.close('completed')
            with (path/'sensor.csv').open(encoding='utf-8-sig') as f:
                reader=csv.DictReader(f); rows=list(reader)
                self.assertEqual(reader.fieldnames,HEADER)
            self.assertEqual(len(rows),5)
            self.assertEqual(float(rows[0]['dBx_uT']),1.)
            self.assertEqual(float(rows[2]['Bx_uT']),2012.)
            self.assertEqual(rows[2]['sample_valid'],'0')
            self.assertEqual(rows[0]['motor_x_pulses'],'12')
            self.assertEqual(rows[-1]['stage'],'step_001')

    def test_interrupted_file_and_metadata_are_retained(self):
        with tempfile.TemporaryDirectory() as td:
            r=Recorder(td,(0,0,0),{})
            r.append(Frame(10,10,0,1000,1,2,3),'manual_idle',{})
            path=r.close('aborted','传感器断流')
            self.assertTrue((path/'sensor.csv').exists())
            self.assertIn('传感器断流',(path/'metadata.json').read_text())
            self.assertTrue((path/'sensor.csv').read_bytes().startswith(b'\xef\xbb\xbf'))

    def test_writer_io_failure_is_reported_and_partial_file_retained(self):
        with tempfile.TemporaryDirectory() as td:
            r=Recorder(td,(0,0,0),{})
            with patch.object(r,'_row',side_effect=OSError('disk full')):
                for i in range(3): r.append(Frame(i,i,0,1000+i,1,2,3),'manual_idle',{})
                deadline=time.monotonic()+2
                while r.error is None and time.monotonic()<deadline: time.sleep(.01)
                self.assertIn('disk full',r.error or '')
                with self.assertRaises(OSError): r.close('aborted','write failed')
            self.assertTrue((r.path/'sensor.csv').exists())
            self.assertIn('aborted',(r.path/'metadata.json').read_text())


if __name__=='__main__': unittest.main()
