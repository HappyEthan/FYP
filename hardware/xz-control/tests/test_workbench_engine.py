import unittest
from xz_control.protocol import Simulator
from xz_workbench.model import AxisConfig, Recipe, Step
from xz_workbench.engine import Engine


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.time=10.; self.sent=[]; self.events=[]
        self.e=Engine(self.sent.append,lambda:self.time,self.events.append)
        self.status=Simulator().s.copy()
        self.status.update(x=0,z=0,tx=0,tz=0,armed=1,refx=1,refz=1)
        self.e.connect(self.status)

    def finish(self,x,z):
        self.e.packet({'type':'ack','cmd':'MOVE'})
        self.e.packet({'type':'done'})
        self.status.update(x=x,z=z,tx=x,tz=z,busy=0)
        self.e.packet(self.status.copy()); self.e.tick()

    def test_sequence_requires_ack_done_and_matching_status(self):
        self.e.run(Recipe('x',[Step('relative','X',2),Step('relative','Z',-1)]))
        self.assertEqual(len(self.sent),1)
        self.status.update(x=500,tx=500,busy=0)
        self.e.packet(self.status.copy()); self.e.tick()
        self.assertEqual(len(self.sent),1)
        self.e.packet({'type':'done'}); self.e.tick()
        self.assertEqual(len(self.sent),1)
        self.finish(500,0)
        self.assertEqual(self.sent[-1],'MOVE ABS SIM 500 -250 250 250 500 500')
        self.finish(500,-250)
        self.assertIsNone(self.e.owner)
        self.assertTrue(any(e['type']=='complete' for e in self.events))

    def test_wrong_endpoint_aborts_remaining_steps(self):
        self.e.run(Recipe('x',[Step('relative','X',2),Step('relative','X',3)]))
        self.finish(499,0)
        self.assertEqual(self.sent[-1],'STOP')
        self.assertIsNone(self.e.owner)

    def test_wait_is_nonblocking_and_stop_cancels_it(self):
        self.e.run(Recipe('x',[Step('wait',duration=1),Step('relative','X',1)]))
        self.assertEqual(self.sent,[])
        self.e.stop('用户中止')
        self.time+=1.1; self.e.packet(self.status.copy()); self.e.tick()
        self.assertFalse(any(s.startswith('MOVE') for s in self.sent))

    def test_gui_lease_expiration_releases_jog(self):
        self.e.jog('X',1)
        self.assertEqual(self.sent[-1],'JOG X 1 250 500')
        self.e.packet({'type':'ack','cmd':'JOG'})
        self.time+=.11; self.e.keep(); self.e.tick()
        self.assertEqual(self.sent[-1],'JKEEP')
        self.time+=.26; self.e.tick()
        self.assertEqual(self.sent[-1],'JEND')

    def test_zero_requires_idle_and_no_recording(self):
        self.e.recording=True
        with self.assertRaises(ValueError): self.e.zero('ALL')
        self.e.recording=False; self.e.jog('X',1)
        with self.assertRaises(ValueError): self.e.zero('X')

    def test_ack_timeout_and_stale_link_stop_motion(self):
        self.e.run(Recipe('x',[Step('relative','X',1)]))
        self.time+=2.1; self.e.packet(self.status.copy()); self.e.tick()
        self.assertEqual(self.sent[-1],'STOP')
        self.assertIsNone(self.e.owner)

    def test_loaded_configuration_mismatch_cannot_run_silently(self):
        recipe=Recipe('x',[Step('relative','X',1)],AxisConfig(x_ppmm=100).to_dict())
        with self.assertRaises(ValueError): self.e.run(recipe)
        self.assertEqual(self.sent,[])

    def test_motion_cannot_be_started_twice(self):
        self.e.jog('X',1)
        with self.assertRaises(ValueError): self.e.jog('Z',1)
        self.assertEqual(len(self.sent),1)

    def test_late_done_after_stop_does_not_restart_sequence(self):
        self.e.run(Recipe('x',[Step('relative','X',1),Step('relative','Z',1)]))
        self.e.stop('stop')
        self.finish(250,0)
        self.assertEqual(sum(c.startswith('MOVE') for c in self.sent),1)

    def test_rezero_clears_coordinate_boundaries(self):
        self.e.config=AxisConfig(x_min=-1,x_max=2)
        self.e.zero('X')
        self.assertEqual(self.sent[-1],'ZERO X')
        self.assertIsNone(self.e.config.x_max)

    def test_idle_recording_fault_stops_and_reports_abort(self):
        self.e.recording=True
        self.status['fault']='LINK_TIMEOUT'
        self.e.packet(self.status.copy())
        self.assertEqual(self.sent[-1],'STOP')
        self.assertTrue(any(e['type']=='stopped' for e in self.events))

    def test_idle_recording_does_not_require_armed(self):
        self.e.recording=True; self.status['armed']=0
        self.e.packet(self.status.copy())
        self.assertEqual(self.sent,[])

    def test_recorded_reference_invalidation_is_not_silently_accepted(self):
        self.e.recording=True; self.status['refx']=0
        self.e.packet(self.status.copy())
        self.assertEqual(self.sent[-1],'STOP')


if __name__=='__main__': unittest.main()
