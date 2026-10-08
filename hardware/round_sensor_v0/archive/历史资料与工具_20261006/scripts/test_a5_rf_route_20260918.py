"""首段射频几何检查的针对性回归，不等同于RF仿真。"""
import copy
import unittest
import build_a5_rf_route_20260918 as rf


class RFRoute(unittest.TestCase):
    def setUp(self):
        self.source,self.doc,_,self.c,self.h,self.plane=rf.build()

    def audit(self,doc=None,plane=None):
        return rf.check(self.doc if doc is None else doc,self.c,self.h,
                        self.plane if plane is None else plane)['局部冲突']

    def test_baseline_and_preservation(self):
        self.assertFalse(self.audit())
        self.assertEqual(self.source['shape'],self.doc['shape'][:44])
        self.assertEqual(self.source['DRCRULE']['Default'],self.doc['DRCRULE']['Default'])

    def test_missing_rf_track_is_detected(self):
        doc=copy.deepcopy(self.doc)
        doc['shape']=[s for s in doc['shape'] if rf.PREFIX+'T0~' not in s]
        self.assertTrue(any(i[0]=='RF网络未连接' for i in self.audit(doc)))

    def test_ground_via_on_rf_pad_is_detected(self):
        doc=copy.deepcopy(self.doc)
        end=rf.pad_center(self.c,'C30','1')
        doc['shape']=[rf.via(end,0) if rf.PREFIX+'V0~' in s else s for s in doc['shape']]
        self.assertTrue(any(i[0]=='孔-焊盘' for i in self.audit(doc)))

    def test_reference_gap_is_detected(self):
        plane=copy.deepcopy(self.plane)
        # 减少上侧参考地边距，保留主控地孔覆盖。
        plane[2]=(plane[2][0],plane[2][1]+.7)
        plane[3]=(plane[3][0],plane[3][1]+.7)
        self.assertTrue(any(i[0]=='参考地3h边距不足' for i in self.audit(plane=plane)))


if __name__=='__main__': unittest.main()
