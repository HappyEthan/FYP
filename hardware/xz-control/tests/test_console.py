import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from xz_control.protocol import Simulator, move_command, parse_status, motion_profile, profile_sample
from xz_control.app import QApplication, Window, Link, STYLE

class ProtocolTests(unittest.TestCase):
    def test_acceleration_validation_and_profile(self):
        for accel in (0, -1, 2147483648, float('nan'), True):
            with self.assertRaises(ValueError):
                move_command('REL', 'SIM', 1000, 0, 1000, 10, {'x':0,'z':0}, accel, 1000)
        p = motion_profile(1000, 1000, 5000)
        self.assertAlmostEqual(p['ramp_time'], .2)
        self.assertAlmostEqual(p['cruise_distance'], 800)
        self.assertEqual(profile_sample(p, .1, 5000), (25, 500))
        self.assertEqual(profile_sample(p, .5, 5000), (400, 1000))
        self.assertEqual(profile_sample(p, 2, 5000), (1000, 0))
        short = motion_profile(50, 1000, 5000)
        self.assertEqual(short['peak'], 500)
        self.assertEqual(short['cruise_distance'], 0)

    def test_demo_cruise_deceleration_and_order_time(self):
        s=Simulator(); s.command('ZERO ALL'); s.command('ARM')
        s.command('MOVE REL XZ 1000 -1000 1000 1000 5000 5000')
        s.tick(.1); self.assertEqual((s.s['x'], s.s['vx'], s.s['z']), (25,500,0))
        s.tick(.4); self.assertEqual((s.s['x'], s.s['vx']), (400,1000))
        s.tick(.6); self.assertAlmostEqual(s.s['vx'],500)
        s.tick(.2); self.assertEqual(s.s['x'],1000)
        self.assertAlmostEqual(s.s['vz'],-500)
        s.tick(10); self.assertEqual((s.s['x'],s.s['z'],s.s['busy']), (1000,-1000,0))

    def test_relative_endpoint_bounds(self):
        with self.assertRaises(ValueError):
            move_command('REL','SIM',100,0,10,10,{'x':2147483600,'z':0})
        with self.assertRaises(ValueError):
            move_command('ABS','XZ',2147483647,0,10,10,{'x':-1,'z':0})
        with self.assertRaises(ValueError):
            move_command('REL','SIM',10,0,0,10,{'x':0,'z':0})

    def test_speed_above_old_cap_and_numeric_boundaries(self):
        current = {'x':0, 'z':0}
        self.assertEqual(move_command('REL','SIM',10,0,5000,12000,current),
                         'MOVE REL SIM 10 0 5000 12000 1000 1000')
        for speed in (0, -1, 2147483648, float('inf'), float('nan')):
            with self.assertRaises(ValueError):
                move_command('REL','SIM',10,0,speed,10,current)

    def test_full_numeric_ranges_and_large_move(self):
        command=move_command('ABS','SIM',2000000,-2000000,200000,150000,{'x':0,'z':0})
        self.assertIn('2000000 -2000000 200000 150000',command)
        parse_status(dict(Simulator().s,x=-2147483648,tx=2147483647))
        for mode,x,current in [('ABS',2147483648,0),('REL',100,2147483600),('ABS',-2147483648,0)]:
            with self.assertRaises(ValueError):move_command(mode,'SIM',x,0,10,10,{'x':current,'z':0})

    def test_status_rejects_incompatible_or_corrupt(self):
        s=Simulator().s
        for change in ({'protocol':'OLD'},{'x':'10'},{'vx':float('nan')},{'armed':2}):
            with self.assertRaises(ValueError): parse_status(dict(s,**change))

    def test_demo_orders_and_stop(self):
        for order, first, second in [('XZ','x','z'),('ZX','z','x')]:
            s=Simulator(); s.command('ZERO ALL'); s.command('ARM')
            s.command(f'MOVE REL {order} 20 20 10 10 1000 1000')
            s.tick(1); self.assertEqual(s.s[first],10); self.assertEqual(s.s[second],0)
            s.command('STOP'); s.tick(100); self.assertEqual(s.s[second],0)
            self.assertEqual(s.s['refx'],0)

class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion'); cls.app.setStyleSheet(STYLE)

    def setUp(self): self.w=Window()
    def tearDown(self): self.w.close()

    def test_demo_never_opens_serial_and_buttons_follow_state(self):
        w=self.w
        with patch('xz_control.app.serial.Serial', side_effect=AssertionError('Must not open hardware')):
            w.toggle_connection()
            self.assertFalse(w.arm.isEnabled()); self.assertFalse(w.execute.isEnabled())
            w.command('ZERO ALL'); self.assertTrue(w.arm.isEnabled())
            w.command('ARM'); self.assertTrue(w.execute.isEnabled())
            w.start_move(); self.assertFalse(w.execute.isEnabled()); self.assertTrue(w.stop.isEnabled())
            self.assertFalse(w.zeros[0].isEnabled())
            w.command('STOP'); self.assertFalse(w.arm.isEnabled())
            self.assertFalse(w.s['busy']); self.assertFalse(w.s['armed'])

    def test_disconnect_invalidates_positions(self):
        w=self.w; w.toggle_connection(); w.command('ZERO ALL'); w.command('ARM')
        w.link.close(); self.assertIsNone(w.s)
        self.assertFalse(w.execute.isEnabled()); self.assertEqual(w.position['x'].text(),'—')

    def test_gui_sends_speed_above_old_cap(self):
        w=self.w; w.toggle_connection(); w.command('ZERO ALL'); w.command('ARM')
        w.inputs['x'][1].setValue(5000); w.inputs['z'][1].setValue(12000)
        with patch.object(w.link, 'send', wraps=w.link.send) as send:
            w.start_move()
            send.assert_called_once_with('MOVE REL XZ 10 10 5000 12000 1000 1000')

    def test_gui_acceleration_and_short_move_hint(self):
        w=self.w; w.toggle_connection(); w.command('ZERO ALL'); w.command('ARM')
        w.inputs['x'][0].setValue(1000); w.inputs['x'][1].setValue(1000)
        w.accels['x'].setValue(5000); w.accels['z'].setValue(2000)
        self.assertIn('恒速 800.0 脉冲', w.profile_note.text())
        w.inputs['x'][0].setValue(50)
        self.assertIn('峰值约 500.0', w.profile_note.text())
        with patch.object(w.link, 'send', wraps=w.link.send) as send:
            w.start_move()
            send.assert_called_once_with('MOVE REL XZ 50 10 1000 10 5000 2000')
        self.assertFalse(w.accels['x'].isEnabled())

    def test_handshake_requires_acceleration_support(self):
        class Port:
            in_waiting=100
            def __init__(self, supported):
                self.data = ('{"type":"hello","protocol":"XZ1","numeric_ranges":true,"move_accel":' + supported + '}\n').encode()
            def write(self,b): return len(b)
            def read(self,n): data=self.data; self.data=b''; return data
            def close(self): pass
        for supported in ('false','true'):
            link=Link(); link.active=True; link.ser=Port(supported)
            link.tick(); self.assertEqual(link.ready, supported=='true')
            link.close(); link.timer.stop()

    def test_gui_large_targets_and_experiment_ranges(self):
        w=self.w;w.toggle_connection();w.command('ZERO ALL');w.command('ARM')
        w.inputs['x'][0].setValue(2000000);w.inputs['z'][0].setValue(-2000000)
        w.exp_targets['x'].setValue(2000000);w.exp_targets['z'].setValue(-2000000)
        self.assertEqual(w.exp_targets['x'].value(),2000000)
        self.assertEqual(w.exp_targets['z'].value(),-2000000)
        with patch.object(w.link,'send',return_value=True) as send:
            w.start_move();send.assert_called_once_with('MOVE REL XZ 2000000 -2000000 10 10 1000 1000')

    def test_old_firmware_handshake_times_out(self):
        class Port:
            in_waiting=0
            def write(self,b): return len(b)
            def read(self,n): return b''
            def close(self): pass
        link=Link(); link.active=True; link.ser=Port(); link.started=-100
        link.tick(); self.assertFalse(link.active); self.assertFalse(link.ready)

    def test_pending_ack_timeout_closes_connection(self):
        w=self.w; w.toggle_connection(); w.pending='MOVE'; w.pending_at=-100
        w.guard_pending(); self.assertFalse(w.link.active)

    def test_return_zero_preserves_reference_targets_and_uses_order_and_speed(self):
        w=self.w; w.toggle_connection(); w.command('ZERO ALL'); w.command('ARM')
        for order in ('XZ', 'ZX', 'SIM'):
            w.command('MOVE ABS SIM 20 -30 100 100 1000 1000')
            for p in w.link.sim.tick(1): w.on_packet(p)
            w.coord.setCurrentIndex(w.coord.findData('REL'))
            w.inputs['x'][0].setValue(77); w.inputs['z'][0].setValue(-88)
            w.inputs['x'][1].setValue(40); w.inputs['z'][1].setValue(60)
            w.order.setCurrentIndex(w.order.findData(order))
            with patch.object(w.link, 'send', wraps=w.link.send) as send:
                w.return_zero.click()
                send.assert_called_once_with(f'MOVE ABS {order} 0 0 40 60 1000 1000')
            self.assertEqual((w.s['x'], w.s['z']), (20, -30))
            self.assertFalse(w.return_zero.isEnabled())
            for _ in range(3):
                for p in w.link.sim.tick(1): w.on_packet(p)
            self.assertEqual((w.s['x'], w.s['z'], w.s['busy']), (0, 0, 0))
            self.assertEqual((w.s['refx'], w.s['refz']), (1, 1))
            self.assertEqual(w.coord.currentData(), 'REL')
            self.assertEqual((w.inputs['x'][0].value(), w.inputs['z'][0].value()), (77, -88))

    def test_return_zero_requires_reference_arm_idle_and_no_fault(self):
        w=self.w
        self.assertFalse(w.return_zero.isEnabled())
        w.toggle_connection(); self.assertFalse(w.return_zero.isEnabled())
        w.command('ZERO ALL'); self.assertFalse(w.return_zero.isEnabled())
        w.command('ARM'); self.assertTrue(w.return_zero.isEnabled())
        w.on_packet(dict(w.s, fault='LINK_TIMEOUT')); self.assertFalse(w.return_zero.isEnabled())
        w.command('CLEAR'); self.assertFalse(w.return_zero.isEnabled())

    def test_return_zero_beyond_old_distance_limit(self):
        w=self.w; w.toggle_connection(); w.command('ZERO ALL'); w.command('ARM')
        w.on_packet(dict(w.s, x=10001, tx=10001))
        with patch('xz_control.app.QMessageBox.warning') as warning, patch.object(w.link, 'send') as send:
            w.return_zero.click()
            warning.assert_not_called(); send.assert_called_once_with('MOVE ABS XZ 0 0 10 10 1000 1000')

if __name__ == '__main__': unittest.main()
