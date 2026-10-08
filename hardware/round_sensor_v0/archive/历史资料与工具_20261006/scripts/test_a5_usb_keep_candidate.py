"""保留 USB 改版的保留性与错误注入测试；不代替原生 ERC。"""
import copy
import json
import unittest
import build_a5_usb_keep_candidate as b
from check_a5_uart_candidate import check
from build_a5_uart_candidate import ref


class Regression(unittest.TestCase):
    def setUp(self):self.doc,self.expected,self.old=b.make()

    @staticmethod
    def without_link_ids(obj):
        doc=copy.deepcopy(obj)
        pages=doc['schematics'] if 'schematics' in doc else [doc]
        for page in pages:
            shapes=page['dataStr']['shape']
            for i,s in enumerate(shapes):
                if not s.startswith('LIB~'):continue
                h,*body=s.split('#@$');v=h.split('~');v[10]=''
                shapes[i]='#@$'.join(['~'.join(v)]+body)
        return doc

    def test_candidate(self):
        result=check(self.doc,self.expected,'usb_keep')
        self.assertEqual(result['元件数'],43)
        self.assertFalse(result['制造放行'])
        self.assertEqual(result['待绑定封装'],[])
        self.assertTrue(result['已知阻断'])

    def test_button_real_library_references(self):
        for pg in self.doc['schematics']:
            for s in pg['dataStr']['shape']:
                if s.startswith('LIB~') and ref(s) in {'SW2','SW3'}:
                    h=s.split('#@$')[0].split('~')
                    self.assertEqual(h[7],'e7abd9d2c1264c45b3d5eb49e7f359e5')
                    self.assertEqual(h[15],'08b07527ca8b41d891fac02ca34a03d1')
                    self.assertEqual({p.split('^^')[0].split('~')[3] for p in s.split('#@$') if p.startswith('P~')},{'1','2','3','4'})

    def test_wrong_button_library_rejected(self):
        pg=self.doc['schematics'][4]
        pg['dataStr']['shape']=[s.replace('08b07527ca8b41d891fac02ca34a03d1','incorrect-library') for s in pg['dataStr']['shape']]
        with self.assertRaises(AssertionError):check(self.doc,self.expected,'usb_keep')

    def test_usb_and_power_exactly_preserved(self):
        for i in [2,3]:
            self.assertEqual(self.without_link_ids(self.doc['schematics'][i]),
                             self.without_link_ids(self.old['schematics'][i]))

    def test_sensor_page_only_appended(self):
        old=self.old['schematics'][1]['dataStr']['shape']
        new=copy.deepcopy(self.doc['schematics'][1]);new['dataStr']['shape']=new['dataStr']['shape'][:len(old)]
        old_page=copy.deepcopy(self.old['schematics'][1]);old_page['dataStr']['shape']=old
        self.assertEqual(self.without_link_ids(new),self.without_link_ids(old_page))

    def test_all_retained_components_preserve_geometry_and_bindings(self):
        def parts(doc):return {ref(s):s for p in doc['schematics'] for s in p['dataStr']['shape'] if s.startswith('LIB~')}
        def without_link_id(s):
            h,*body=s.split('#@$');v=h.split('~');v[10]=''
            return '#@$'.join(['~'.join(v)]+body)
        old=parts(self.old);new=parts(self.doc)
        self.assertEqual(set(old)-set(new),{'J3'})
        self.assertEqual(set(new)-set(old),{'SW2','SW3','J4'})
        for r in set(old)&set(new):self.assertEqual(without_link_id(old[r]),without_link_id(new[r]),r)

    def test_existing_pcb_link_ids_are_preserved(self):
        cloud=json.loads(b.CLOUD_LINK_SOURCE.read_text())
        def ids(doc):
            return {ref(s):s.split('#@$')[0].split('~')[10]
                    for p in doc['schematics'] for s in p['dataStr']['shape']
                    if s.startswith('LIB~')}
        before=ids(cloud);after=ids(self.doc)
        self.assertEqual(set(before)-set(after),{'J3'})
        for r in set(before)&set(after):self.assertEqual(after[r],before[r],r)
        for r in {'J4','SW2','SW3'}:self.assertEqual(after[r],'',r)

    def test_wrong_pen_signal_rejected(self):
        e=copy.deepcopy(self.expected);e['J4.3'],e['J4.4']=e['J4.4'],e['J4.3']
        with self.assertRaises(AssertionError):check(self.doc,e,'usb_keep')

    def test_short_rejected(self):
        self.doc['schematics'][1]['dataStr']['shape'].append('W~1045 610 1045 650~#008800~1~0~none~ggeInjectedShort~0')
        with self.assertRaises(AssertionError):check(self.doc,self.expected,'usb_keep')

    def test_missing_button_wire_rejected(self):
        shapes=self.doc['schematics'][4]['dataStr']['shape']
        wire=next(s for s in shapes if s.startswith('W~310 770 '))
        shapes.remove(wire)
        with self.assertRaises(AssertionError):check(self.doc,self.expected,'usb_keep')

    def test_cannot_silently_power_pen(self):
        self.doc['schematics'][1]['dataStr']['shape']=[s.replace('3V3','USB_5V') if s.startswith('N~') and float(s.split('~')[2])==530 else s for s in self.doc['schematics'][1]['dataStr']['shape']]
        e=copy.deepcopy(self.expected);e['J4.1']='USB_5V'
        with self.assertRaises(AssertionError):check(self.doc,e,'usb_keep')

    def test_pen_supply_is_same_3v3_rail(self):
        result=check(self.doc,self.expected,'usb_keep')
        self.assertIn('J4.1',result['网络']['3V3'])
        self.assertIn('U1.2',result['网络']['3V3'])
        self.assertNotIn('TIP_VCC_PENDING',result['网络'])

    def test_native_readback_connections_and_bindings(self):
        native=json.loads((b.OUT/'原生回读_全部封装绑定.json').read_text())
        result=check(native,self.expected,'usb_keep')
        self.assertEqual(result['待绑定封装'],[])
        self.assertEqual(result['网络数'],21)

    def test_wrong_pen_library_rejected(self):
        pg=self.doc['schematics'][1]
        pg['dataStr']['shape']=[s.replace('fbf5a25068d7429988f18f56283e2018','incorrect-library') for s in pg['dataStr']['shape']]
        with self.assertRaises(AssertionError):check(self.doc,self.expected,'usb_keep')


if __name__=='__main__':unittest.main(verbosity=2)
