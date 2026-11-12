import os,sys,csv,json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from xz_control.app import QApplication,Window
from xz_control.experiment import Experiment
from xz_control.protocol import Simulator
from xz_control.sensor import SensorPanel

class ExperimentTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.sent=[];self.healthy=True
  self.s=dict(Simulator().s,armed=1,refx=1,refz=1)
  self.e=Experiment(self.sent.append,lambda:self.s,lambda:self.healthy);self.e.timer.stop()
 def tearDown(self):self.e.abort('test teardown');self.tmp.cleanup()
 def start(self):self.e.start(self.tmp.name,(100,20),(50,20),(1000,1000),{})
 def test_csv_preserves_raw_corrected_and_baseline_xyz(self):
  self.start();self.complete(0,20)
  self.e.sample(time.monotonic(),(103,-18,295),'B',dict(baseline_uT=(100,-20,300),calibration_id=2))
  self.e.sample(time.monotonic(),(1,2,3),'B')
  self.e.close_csv()
  with (self.e.folder/'magnetic_xyz.csv').open() as f:rows=list(csv.DictReader(f))
  self.assertEqual([float(rows[0][f'magnetic_{a}_uT']) for a in 'xyz'],[103,-18,295])
  self.assertEqual([float(rows[0][f'corrected_magnetic_{a}_uT']) for a in 'xyz'],[3,2,-5])
  self.assertEqual([float(rows[0][f'baseline_{a}_uT']) for a in 'xyz'],[100,-20,300])
  self.assertEqual(rows[0]['calibration_id'],'2')
  self.assertEqual(rows[1]['calibration_id'],'0')
  self.assertEqual(float(rows[1]['corrected_magnetic_z_uT']),3)
 def complete(self,x,z):
  self.e.packet({'type':'ack','cmd':'MOVE'})
  self.s.update(busy=1);self.e.packet(self.s)
  self.e.packet({'type':'done'})
  self.s.update(x=x,z=z,tx=x,tz=z,busy=0);self.e.packet(self.s)
  self.e.tick()
 def test_exact_order_and_recording_window(self):
  self.start();self.assertEqual(self.sent[0],'MOVE ABS SIM 0 20 50 20 1000 1000')
  self.e.sample(time.monotonic(),(9,9,9),'B');self.assertEqual(self.e.count,0)
  self.complete(0,20);self.assertEqual(self.e.stage,'record_ready');self.assertEqual(len(self.sent),1)
  self.e.tick();self.assertEqual(len(self.sent),1)
  self.e.sample(time.monotonic(),(1,2,999),'ΔB');self.e.tick()
  self.assertEqual(self.sent[1],'MOVE ABS SIM 100 20 50 20 1000 1000')
  self.s.update(vx=42.5, vz=0, tx=100, tz=20, busy=1, phase=3)
  self.e.sample(time.monotonic(),(3,4,888),'ΔB')
  self.complete(100,20)
  self.assertEqual(self.sent[2],'MOVE ABS SIM 100 0 50 20 1000 1000')
  self.assertIsNone(self.e.file);self.e.sample(time.monotonic(),(5,6,7),'ΔB')
  self.complete(100,0);self.assertEqual(self.sent[3],'MOVE ABS SIM 0 0 50 20 1000 1000')
  self.complete(0,0);self.assertFalse(self.e.active)
  with (self.e.folder/'magnetic_xyz.csv').open() as f:rows=list(csv.DictReader(f))
  self.assertEqual(len(rows),2);self.assertEqual(rows[1]['magnetic_y_uT'],'4')
  self.assertEqual(rows[0]['magnetic_z_uT'],'999');self.assertEqual(rows[1]['magnetic_z_uT'],'888');self.assertEqual(rows[0]['signal_kind'],'ΔB')
  meta=json.loads((self.e.folder/'metadata.json').read_text())
  self.assertEqual(meta['status'],'complete');self.assertTrue(meta['returned_to_zero'])
  self.assertEqual(rows[1]['motor_vx_pps'],'42.5')
  self.assertEqual(rows[1]['motor_target_x_pulses'],'100')
  self.assertEqual(rows[1]['motor_remaining_x_pulses'],'100')
  self.assertEqual(rows[1]['motor_phase'],'3');self.assertEqual(rows[1]['motor_fault'],'NONE')
  self.assertEqual(rows[1]['experiment_stage'],'scan_x')
  with (self.e.folder/'controller.csv').open() as f:states=list(csv.DictReader(f))
  self.assertEqual(len(states),8);self.assertEqual(meta['controller_samples'],8)
  self.assertEqual({r['experiment_stage'] for r in states},{'position_z','scan_x','return_z','return_x'})
  self.assertEqual(states[-1]['motor_x_pulses'],'0');self.assertEqual(states[-1]['motor_z_pulses'],'0')
  events=[json.loads(line) for line in (self.e.folder/'events.jsonl').read_text().splitlines()]
  self.assertEqual([e['payload']['command'] for e in events if e['event']=='command_requested'],self.sent)
  self.assertEqual(events[-1]['event'],'complete');self.assertEqual(meta['events'],len(events))
  self.assertIsNone(self.e.controller_file);self.assertIsNone(self.e.event_file)
 def test_sensor_loss_retains_partial_and_never_returns(self):
  self.start();self.complete(0,20);self.e.sample(time.monotonic(),(1,2,3),'B');self.e.tick()
  self.healthy=False;self.e.tick()
  self.assertFalse(self.e.active);self.assertEqual(self.sent[-1],'STOP');n=len(self.sent)
  self.e.packet({'type':'done'});self.e.tick();self.assertEqual(len(self.sent),n)
  meta=json.loads((self.e.folder/'metadata.json').read_text())
  self.assertEqual(meta['status'],'aborted');self.assertEqual(meta['samples'],1)
  events=[json.loads(line) for line in (self.e.folder/'events.jsonl').read_text().splitlines()]
  self.assertEqual(events[-1]['payload']['command'],'STOP')
  self.assertIsNone(self.e.controller_file);self.assertIsNone(self.e.event_file)
 def test_no_ack_no_transition_and_wrong_endpoint_abort(self):
  self.start();self.e.packet({'type':'done'});self.e.packet(self.s);self.e.tick()
  self.assertEqual(len(self.sent),1)
  self.complete(1,20);self.assertEqual(self.sent[-1],'STOP');self.assertFalse(self.e.active)
 def test_preflight_and_file_failure_do_not_move(self):
  self.s['x']=1
  with self.assertRaises(ValueError):self.start()
  self.s['x']=0
  with patch('pathlib.Path.open',side_effect=OSError('disk full')):
   with self.assertRaises(OSError):self.start()
  self.assertEqual(self.sent,[]);self.assertFalse(self.e.active)
 def test_save_failure_stops_before_return(self):
  self.start();self.complete(0,20);self.e.sample(time.monotonic(),(1,2,3),'B');self.e.tick()
  with patch.object(self.e,'save_meta',side_effect=OSError('disk full')):self.complete(100,20)
  self.assertEqual(self.sent[-1],'STOP');self.assertEqual(len(self.sent),3)
 def test_large_experiment_endpoints(self):
  self.e.start(self.tmp.name,(2000000,-2000000),(200000,150000),(1000,1000),{})
  self.assertEqual(self.sent[0],'MOVE ABS SIM 0 -2000000 200000 150000 1000 1000')
  self.assertIn('MOVE ABS SIM 2000000 -2000000',self.e.commands[1])
  self.assertEqual(self.e.commands[-1],'MOVE ABS SIM 0 0 200000 150000 1000 1000')
 def test_sensor_timestamps_and_backlog_saved(self):
  self.start();self.complete(0,20)
  self.e.sample(time.monotonic(),(1,2,3),'B',dict(device_time_us=1234567,
      device_clock_segment=0,device_clock_reset=0,relative_transport_lag_s=3.1,
      serial_pending_bytes=9999,read_batch_id=12,host_poll_gap_s=3.2))
  self.e.abort('test timing')
  with (self.e.folder/'magnetic_xyz.csv').open() as f:row=next(csv.DictReader(f))
  self.assertEqual(row['device_time_us'],'1234567');self.assertEqual(row['relative_transport_lag_s'],'3.1')
  self.assertEqual(row['serial_pending_bytes'],'9999');self.assertEqual(row['host_poll_gap_s'],'3.2')
 def test_plot_aggregation_clear_pause_never_reduce_recording(self):
  self.start();self.complete(0,20)
  panel=SensorPanel(lambda:None);panel.timer.stop();panel.display_timer.stop()
  panel.sample_received.connect(self.e.sample)
  origin=time.monotonic()
  for k in range(5000):
   panel.feed(f'{k*3000},{k},{-k},3\n'.encode(),origin+k*.003)
   if k==1000:panel.plot.pause(True)
   if k==2000:panel.plot.clear()
   if k==3000:panel.plot.pause(False)
  self.e.abort('end of synthetic capture')
  with (self.e.folder/'magnetic_xyz.csv').open() as f:rows=list(csv.DictReader(f))
  self.assertEqual(len(rows),5000);self.assertEqual(rows[-1]['magnetic_x_uT'],'4999.0')
  self.assertLessEqual(len(panel.plot.samples.bins),202)
 def test_controller_log_failure_aborts(self):
  self.start()
  with patch.object(self.e,'controller_writer') as writer:
   writer.writerow.side_effect=OSError('disk full')
   self.e.packet(self.s)
  self.assertFalse(self.e.active);self.assertEqual(self.sent[-1],'STOP')
  self.assertIsNone(self.e.file);self.assertIsNone(self.e.controller_file);self.assertIsNone(self.e.event_file)
 def test_all_files_prepared_before_motion(self):
  original=Path.open
  def fail_controller(path,*args,**kwargs):
   if path.name=='controller.csv':raise OSError('cannot create controller log')
   return original(path,*args,**kwargs)
  with patch.object(Path,'open',fail_controller):
   with self.assertRaises(OSError):self.start()
  self.assertEqual(self.sent,[]);self.assertFalse(self.e.active);self.assertIsNone(self.e.file)
 def test_window_locks_manual_controls_and_stop_aborts(self):
  w=Window();w.toggle_connection();w.command('ZERO ALL');w.command('ARM')
  w.experiment.sensor_alive=lambda:True
  w.experiment.start(self.tmp.name,(100,20),(50,20),(1000,1000),{})
  self.assertFalse(w.execute.isEnabled());self.assertFalse(w.jog_buttons[0].isEnabled())
  self.assertFalse(w.zeros[0].isEnabled());self.assertFalse(w.sensor.connect_btn.isEnabled())
  self.assertTrue(w.stop.isEnabled())
  w.command('STOP');self.assertFalse(w.experiment.active);self.assertFalse(w.s['armed']);w.close()

if __name__=='__main__':unittest.main()
