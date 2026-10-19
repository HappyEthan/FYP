"""Analytical checks for the offline benchmark; no hardware imports."""
import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np


class BenchmarkChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = Path(__file__).with_name("analyze.py")

    def module(self):
        self.assertTrue(self.path.exists(), "offline benchmark is not implemented yet")
        spec = importlib.util.spec_from_file_location("direction_benchmark", self.path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def test_known_piecewise_response_and_inverse_units(self):
        m = self.module()
        curve = m.Curve([5, 10, 13], [100, 200, 350])
        self.assertAlmostEqual(curve.forward(7), 140)
        self.assertAlmostEqual(curve.forward(12), 300)
        self.assertAlmostEqual(curve.inverse(300)[0], 12)
        self.assertAlmostEqual(40 - curve.inverse(300)[0], 28)

    def test_inverse_does_not_clip_or_extrapolate(self):
        m = self.module()
        curve = m.Curve([5, 10, 13], [100, 200, 350])
        for value, status in [(99, "below_range"), (351, "above_range")]:
            depth, actual_status = curve.inverse(value)
            self.assertIsNone(depth)
            self.assertEqual(actual_status, status)
        self.assertEqual(curve.inverse(100), (5.0, "ok"))
        self.assertEqual(curve.inverse(350), (13.0, "ok"))
        self.assertIsNone(curve.forward(14))

    def test_nonmonotone_or_duplicate_nodes_are_rejected(self):
        m = self.module()
        for depths, values in [([5, 10, 13], [100, 300, 200]),
                               ([5, 10, 13], [100, 100, 300]),
                               ([5, 5, 13], [100, 200, 300])]:
            with self.assertRaises(ValueError):
                m.Curve(depths, values)

    def test_affine_fit_and_x_identity(self):
        m = self.module()
        x = m.Curve([5, 10, 13], [100, 200, 350])
        y = m.Curve([5, 10, 13], [180, 380, 680])
        model, k, b = m.affine_curve(x, y)
        self.assertAlmostEqual(k, 2)
        self.assertAlmostEqual(b, -20)
        self.assertAlmostEqual(model.inverse(580)[0], 12)
        identity, k, b = m.affine_curve(x, x)
        self.assertTrue(np.array_equal(identity.values, x.values))
        self.assertEqual(k, 1)
        self.assertEqual(b, 0)

    def test_metrics_keep_failures_and_weight_strokes_equally(self):
        m = self.module()
        rows = [dict(run_id="a", inverse_status="ok", z_error_mm=2.,
                     forward_error_uT=20.)] * 10
        rows += [dict(run_id="b", inverse_status="ok", z_error_mm=0.,
                      forward_error_uT=0.)]
        rows += [dict(run_id="c", inverse_status="above_range", z_error_mm=None,
                      forward_error_uT=30.)]
        result = m.summarize(rows)
        self.assertAlmostEqual(result["run_balanced_coverage"], 2/3)
        self.assertEqual(result["valid_runs"], 2)
        self.assertEqual(result["total_runs"], 3)
        self.assertAlmostEqual(result["z_rmse_mm_valid_only"], 2 ** .5)
        self.assertAlmostEqual(result["forward_rmse_uT"], (1300/3) ** .5)

    def test_training_test_overlap_is_detected(self):
        m = self.module()
        m.ensure_disjoint(["a", "b"], ["c"])
        with self.assertRaises(AssertionError):
            m.ensure_disjoint(["a", "b"], ["b", "c"])

    def test_low_sensitivity_is_reported_in_mm(self):
        m = self.module()
        curve = m.Curve([5, 10, 13], [100, 200, 215])
        self.assertAlmostEqual(curve.noise_depth_scale(12), 4)


if __name__ == "__main__":
    unittest.main()
