import os,sys,unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from xz_control.app import QApplication,Window
from xz_control.protocol import Simulator

class JogTests(unittest.TestCase):
 def test_continuous_jog_beyond_10000(self):
  s=Simulator();s.command('ZERO ALL');s.command('ARM');s.command('JOG X 1 2000 10000')
  for _ in range(70):s.command('JKEEP');s.tick(.1)
  self.assertGreater(s.s['x'],10000);self.assertTrue(s.s['busy'])
  s.command('JEND');s.tick(1);self.assertFalse(s.s['busy']);self.assertTrue(s.s['refx'])
 def test_z_button_direction_mapping(self):
  w=Window();w.toggle_connection();w.command('ZERO ALL');w.command('ARM')
  with patch.object(w.link,'send',return_value=True) as send:
   w.jog_buttons[2].pressed.emit()
   self.assertEqual(send.call_args.args[0],'JOG Z 1 10 1000')
   w.jog_button=None;w.pending=None;w.update_controls()
   w.jog_buttons[3].pressed.emit()
   self.assertEqual(send.call_args.args[0],'JOG Z -1 10 1000')
  w.close()
 @classmethod
 def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])
 def test_release_and_reuse(self):
  w=Window();w.toggle_connection();w.command('ZERO ALL');w.command('ARM')
  w.inputs['x'][1].setValue(500);w.accels['x'].setValue(5000)
  w.start_jog('x',1,w.jog_buttons[1]);self.assertFalse(w.execute.isEnabled())
  self.assertFalse(w.jog_buttons[2].isEnabled())
  for _ in range(4):
   w.link.sim.command('JKEEP')
   for p in w.link.sim.tick(.1):w.on_packet(p)
  self.assertGreater(w.s['x'],0);self.assertEqual(w.s['z'],0)
  w.end_jog()
  for p in w.link.sim.tick(1):w.on_packet(p)
  self.assertFalse(w.s['busy']);self.assertTrue(w.s['refx']);self.assertTrue(w.s['armed'])
  self.assertTrue(w.jog_buttons[0].isEnabled());w.close()
 def test_release_before_start_ack(self):
  w=Window();w.toggle_connection();w.command('ZERO ALL');w.command('ARM')
  with patch.object(w.link,'send',return_value=True) as send:
   w.start_jog('z',-1,w.jog_buttons[2]);self.assertEqual(w.pending,'JOG')
   w.end_jog();self.assertEqual(w.pending,'JEND')
   self.assertEqual(send.call_args_list[-1].args[0],'JEND')
   w.on_packet({'type':'ack','cmd':'JOG'});self.assertEqual(w.pending,'JEND')
  w.close()
 def test_deadman_and_no_automatic_resume(self):
  s=Simulator();s.command('ZERO ALL');s.command('ARM');s.command('JOG Z -1 100 1000')
  s.tick(.1);s.command('PING');s.tick(.3)
  self.assertEqual(s.s['fault'],'JOG_TIMEOUT');self.assertFalse(s.s['armed'])
  pos=s.s['z'];s.command('JKEEP');s.tick(1);self.assertEqual(s.s['z'],pos)
 def test_old_firmware_disables_only_jog(self):
  w=Window();w.toggle_connection();w.command('ZERO ALL');w.command('ARM')
  w.link.jog_supported=False;w.update_controls()
  self.assertTrue(w.execute.isEnabled());self.assertFalse(w.jog_buttons[0].isEnabled());w.close()

if __name__=='__main__':unittest.main()
