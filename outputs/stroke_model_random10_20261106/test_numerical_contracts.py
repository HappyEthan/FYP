"""Small independent numeric checks; not changes to the application test suite."""
import unittest
import numpy as np
from analysis_utils import scalar_ema, make_feature, choose_kernel

class NumericalContracts(unittest.TestCase):
    def test_scalar_magnitude_before_filter(self):
        bx=np.array([3.,-3.,3.]);by=np.array([4.,4.,-4.])
        np.testing.assert_allclose(scalar_ema(np.hypot(bx,by)),[5.,5.,5.])

    def test_invalid_sample_restarts_and_does_not_fabricate(self):
        out=scalar_ema(np.array([10.,20.,np.nan,40.,50.]))
        np.testing.assert_allclose(out,[10.,13.,np.nan,40.,43.],equal_nan=True)

    def test_gap_break_restarts_filter(self):
        out=scalar_ema([10.,20.,40.,50.],break_before=[False,False,True,False])
        np.testing.assert_allclose(out,[10.,13.,40.,43.])

    def test_time_baseline_and_offset_invariance(self):
        t=np.linspace(10.,20.,101);a=100.+2.*(t-10.)
        f,b=make_feature(t,a)
        self.assertAlmostEqual(b,101.)
        np.testing.assert_allclose(f,2.*np.linspace(0,10,128)-1.,atol=1e-12)
        shifted,b2=make_feature(t,a+300.)
        np.testing.assert_allclose(shifted,f,atol=1e-12)
        self.assertAlmostEqual(b2,b+300.)

    def test_invalid_feature_input_rejected(self):
        for t,a in [([0,0,1],[1,2,3]),([0,1],[1,np.nan]),([0],[1])]:
            with self.assertRaises(ValueError):make_feature(t,a)

    def test_prefer_linear_within_two_percent(self):
        self.assertEqual(choose_kernel(.8,.82),'linear')
        self.assertEqual(choose_kernel(.8,.821),'rbf')
        self.assertEqual(choose_kernel(.9,.8),'linear')

if __name__=='__main__':unittest.main()
