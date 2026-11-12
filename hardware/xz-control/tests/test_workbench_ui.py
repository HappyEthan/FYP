import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication
from xz_control.protocol import Simulator
from xz_workbench.model import AxisConfig
from xz_workbench.ui import Window
import queue


class DeviceBoundary:
    def __init__(self):
        self.requests=[]; self.events=queue.Queue(); self.lease_count=0
        status=Simulator().s.copy(); status.update(armed=1,refx=1,refz=1)
        self.state=dict(ready=True,status=status,idle=True,pending=None,owner=None,
                        recording=False,record_owned=False,config=AxisConfig().to_dict(),calibrating=False)
    def submit(self,name,**payload): self.requests.append((name,payload))
    def lease(self): self.lease_count+=1
    def snapshot(self): return self.state.copy()
    def shutdown(self): pass


class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.worker=DeviceBoundary(); self.window=Window(self.worker)
        self.window.show(); self.window.activateWindow(); self.window.setFocus()
        self.app.processEvents(); self.window.poll()
        self.window.keyboard_enabled.setChecked(True)
    def tearDown(self): self.window.close(); self.app.processEvents()
    def key(self,kind,key,repeat=False):
        event=QKeyEvent(kind,key,Qt.NoModifier,'',repeat,1)
        self.app.sendEvent(self.window,event)

    def test_keyboard_holds_and_ignores_auto_repeat_release(self):
        self.key(QEvent.KeyPress,Qt.Key_Right)
        self.key(QEvent.KeyPress,Qt.Key_Right,True)
        self.key(QEvent.KeyRelease,Qt.Key_Right,True)
        self.assertEqual([n for n,_ in self.worker.requests].count('jog'),1)
        self.assertNotIn('release',[n for n,_ in self.worker.requests])
        self.key(QEvent.KeyRelease,Qt.Key_Right)
        self.assertEqual(self.worker.requests[-1][0],'release')

    def test_focus_loss_releases_jog(self):
        self.key(QEvent.KeyPress,Qt.Key_Up)
        self.app.sendEvent(self.window,QEvent(QEvent.WindowDeactivate))
        self.assertEqual(self.worker.requests[-1][0],'release')

    def test_mouse_fixed_mode_submits_one_distance_move(self):
        self.window.jog_mode.setCurrentIndex(1)
        self.window.distance.setValue(3)
        self.window.direction_pressed('up','mouse')
        self.window.direction_released('up','mouse')
        moves=[p for n,p in self.worker.requests if n=='move']
        self.assertEqual(len(moves),1)
        self.assertEqual((moves[0]['step'].axis,moves[0]['step'].value),('Z',-3))

    def test_recipe_rows_can_be_reordered_and_disabled(self):
        self.window.add_step(); self.window.add_step()
        self.window.table.cellWidget(0,4).setValue(5)
        self.window.table.cellWidget(1,4).setValue(9)
        self.window.table.selectRow(1); self.window.move_row(-1)
        recipe=self.window.read_recipe()
        self.assertEqual([s.value for s in recipe.steps],[9,5])

    def test_running_locks_zero_and_editor_but_not_stop(self):
        self.worker.state.update(owner='recipe',idle=False)
        self.window.poll()
        self.assertFalse(self.window.zero_x.isEnabled())
        self.assertFalse(self.window.table.isEnabled())
        self.assertTrue(self.window.stop_button.isEnabled())

    def test_connection_settings_open_on_demand(self):
        self.assertFalse(self.window.motor_ports.isVisible())
        self.window.devices_button.click(); self.app.processEvents()
        self.assertTrue(self.window.motor_ports.isVisible())
        self.window.device_dialog.close()

    def test_manual_and_function_pages_are_separate(self):
        self.assertFalse(self.window.table.isVisible())
        self.window.workspace_tabs.setCurrentIndex(1); self.app.processEvents()
        self.assertTrue(self.window.table.isVisible())

    def test_space_stops_while_parameter_panel_is_active(self):
        self.window.show_panel(self.window.settings_dialog)
        self.window.settings_dialog.activateWindow(); self.app.processEvents()
        event=QKeyEvent(QEvent.KeyPress,Qt.Key_Space,Qt.NoModifier)
        self.app.sendEvent(self.window.settings_dialog,event)
        self.assertIn('stop',[name for name,_ in self.worker.requests])


if __name__=='__main__': unittest.main()
