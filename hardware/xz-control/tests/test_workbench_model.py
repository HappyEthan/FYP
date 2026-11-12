import json
import tempfile
import unittest
from pathlib import Path

from xz_workbench.model import AxisConfig, Step, Recipe, plan_steps, save_recipe, load_recipe


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.cfg = AxisConfig()

    def test_relative_absolute_zero_and_wait(self):
        recipe = Recipe('扫描', [Step('relative', 'X', 10, 2, 4),
                                 Step('relative', 'Z', -5, 1, 2),
                                 Step('wait', duration=.5), Step('zero', 'X')])
        steps = plan_steps(recipe, {'x': 250, 'z': 500}, self.cfg)
        self.assertEqual([(s.x, s.z) for s in steps], [(2750,500),(2750,-750),(2750,-750),(0,-750)])
        self.assertEqual(steps[0].command, 'MOVE ABS SIM 2750 500 500 250 1000 500')
        self.assertEqual(steps[2].duration, .5)

    def test_disabled_steps_do_not_move_and_ids_stay_stable(self):
        steps = plan_steps(Recipe('x',[Step('relative','X',100,enabled=False),Step('absolute','Z',4)]),{'x':0,'z':0},self.cfg)
        self.assertEqual(len(steps),1)
        self.assertEqual((steps[0].index,steps[0].x,steps[0].z),(2,0,1000))

    def test_invalid_values_rejected_before_any_motion(self):
        for step in [Step('relative','X',float('nan')),Step('relative','X',.0001),
                     Step('absolute','Q',1),Step('wait',duration=-1),
                     Step('relative','X',1,speed=0),Step('absolute','X',1e20)]:
            with self.subTest(step=step),self.assertRaises(ValueError):
                plan_steps(Recipe('bad',[step]),{'x':0,'z':0},self.cfg)

    def test_calibration_and_direction_are_not_confused(self):
        cfg=AxisConfig(x_ppmm=200,z_ppmm=100,x_right=-1)
        self.assertEqual(cfg.direction('right'),('X',-1))
        self.assertEqual(cfg.direction('up'),('Z',-1))
        step=plan_steps(Recipe('x',[Step('relative','Z',2)]),{'x':0,'z':0},cfg)[0]
        self.assertEqual(step.z,200)

    def test_soft_bounds_are_checked_in_current_coordinate_frame(self):
        cfg=AxisConfig(x_min=-2,x_max=2)
        with self.assertRaises(ValueError):
            plan_steps(Recipe('x',[Step('relative','X',3)]),{'x':0,'z':0},cfg)

    def test_recipe_round_trip_and_changed_config_detection(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'流程.json'
            recipe=Recipe('织物',[Step('relative','X',3)],self.cfg.to_dict())
            save_recipe(path,recipe)
            loaded=load_recipe(path)
            self.assertEqual(loaded.name,'织物')
            self.assertEqual(loaded.steps[0].value,3)
            self.assertFalse(loaded.config_changed(self.cfg))
            self.assertTrue(loaded.config_changed(AxisConfig(x_ppmm=100)))
            path.write_text(json.dumps({'version':99,'name':'x','steps':[]}))
            with self.assertRaises(ValueError): load_recipe(path)


if __name__=='__main__': unittest.main()
