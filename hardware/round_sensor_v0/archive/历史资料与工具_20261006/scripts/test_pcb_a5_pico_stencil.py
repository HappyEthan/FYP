"""变更白名单与故障注入：不能把布局、电气或工艺层误改藏在钢网修订里。"""
import copy
import json
import unittest
from build_pcb_a5_pico_stencil import BASE, make_candidate, u1_index, verify


class StencilTests(unittest.TestCase):
    def setUp(self):
        self.base = json.loads(BASE.read_text())
        self.good = make_candidate(self.base)

    def change_item(self, doc, kind, field, value, match=lambda v: True):
        i = u1_index(doc)
        parts = doc['shape'][i].split('#@$')
        for j, s in enumerate(parts):
            v = s.split('~')
            if v[0] == kind and match(v):
                v[field] = value
                parts[j] = '~'.join(v)
                doc['shape'][i] = '#@$'.join(parts)
                return
        self.fail('未找到测试目标')

    def test_valid(self):
        r = verify(self.base, self.good)
        self.assertFalse(r['制造放行'])
        self.assertEqual(r['窗口与名义孔口投影相交数量'], 8)

    def test_reject_electrical_and_geometry_changes(self):
        cases = [('PAD', 7, '3V3'), ('PAD', 4, '5'), ('PAD', 17, '0'),
                 ('PAD', 18, '0'), ('VIA', 5, '0.3'), ('VIA', 4, '3V3'),
                 ('TEXT', 10, '错误文字'), ('LIB', 1, '4000')]
        for kind, field, value in cases:
            with self.subTest(kind=kind, field=field):
                bad = copy.deepcopy(self.good)
                self.change_item(bad, kind, field, value)
                with self.assertRaises(AssertionError): verify(self.base, bad)

    def test_reject_window_layer_and_shape(self):
        for field, value in [(1, '1'), (3, 'M 0 0 L 1 0 L 1 1 Z')]:
            bad = copy.deepcopy(self.good)
            self.change_item(bad, 'SOLIDREGION', field, value, lambda v: v[5] == 'gge991701')
            with self.assertRaises(AssertionError): verify(self.base, bad)

    def test_reject_rules_and_board_shapes(self):
        bad = copy.deepcopy(self.good)
        bad['DRCRULE'] = {}
        with self.assertRaises(AssertionError): verify(self.base, bad)
        bad = copy.deepcopy(self.good)
        bad['shape'].append('VIA~0~0~2.4~GND~0.6~bad~0')
        with self.assertRaises(AssertionError): verify(self.base, bad)

    def test_reject_missing_window(self):
        bad = copy.deepcopy(self.good)
        i = u1_index(bad)
        bad['shape'][i] = '#@$'.join(s for s in bad['shape'][i].split('#@$') if 'gge991701' not in s)
        with self.assertRaises(AssertionError): verify(self.base, bad)


if __name__ == '__main__':
    unittest.main()
