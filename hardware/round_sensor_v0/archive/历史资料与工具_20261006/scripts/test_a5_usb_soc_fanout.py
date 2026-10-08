import copy
import unittest

from build_a5_usb_soc_fanout import build, check, track, NETS, PREFIX
from audit_a5_routed_snapshot import routes, track_gap
from check_pcb_a5 import distance, shared_layer


def connected_groups(doc, copper, net):
    tracks, vias, _ = routes(doc)
    nodes = [dict(p, id=p['ref']+'.'+p['pin']) for p in copper if p['net']==net]
    nodes += [dict(t, kind='track') for t in tracks if t['net']==net]
    nodes += [dict(v, kind='via') for v in vias if v['net']==net]
    def bounds(n):
        ps=n['points'] if n['kind']=='track' else n['poly'];r=n.get('width',0)/2
        return min(x for x,y in ps)-r,max(x for x,y in ps)+r,min(y for x,y in ps)-r,max(y for x,y in ps)+r
    boxes=[bounds(n) for n in nodes]
    parent = list(range(len(nodes)))
    def root(i):
        while parent[i]!=i:
            parent[i]=parent[parent[i]]
            i=parent[i]
        return i
    def gap(a,b):
        if a['kind']=='track' and b['kind']=='track':
            return min(distance([x,y],[u,v]) for x,y in zip(a['points'],a['points'][1:])
                       for u,v in zip(b['points'],b['points'][1:]))-(a['width']+b['width'])/2
        if a['kind']=='track': return track_gap(a,b['poly'])
        if b['kind']=='track': return track_gap(b,a['poly'])
        return distance(a['poly'],b['poly'])
    for i,a in enumerate(nodes):
        for j,b in enumerate(nodes[:i]):
            x0,x1,y0,y1=boxes[i];u0,u1,v0,v1=boxes[j]
            if max(x0-u1,u0-x1,y0-v1,v0-y1)>1e-5:continue
            if shared_layer(a,b) and gap(a,b)<=1e-5:
                parent[root(i)]=root(j)
    # 只比较真实元件端点的连通组，不把撤掉的无端点悬空支线视为功能丢失。
    groups={}
    for i,n in enumerate(nodes):
        if n['kind']=='pad': groups.setdefault(root(i),set()).add(n['id'])
    return list(groups.values())


class UsbFanoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source,cls.doc,cls.copper,cls.removed,cls.added=build()

    def test_geometry_including_mechanical_holes(self):
        self.assertEqual(check(self.doc,self.copper)[0],[])

    def test_instances_and_global_rules_unchanged(self):
        lib=lambda d:[s for s in d['shape'] if s.startswith('LIB~')]
        self.assertEqual(lib(self.source),lib(self.doc))
        self.assertEqual(self.doc['DRCRULE']['Default'],self.source['DRCRULE']['Default'])
        self.assertEqual(set(self.doc['DRCRULE']['USB主控扇出']['nets']),NETS)

    def test_two_usb_nets_connected(self):
        for net in NETS:
            self.assertEqual(len(connected_groups(self.doc,self.copper,net)),1)

    def test_other_endpoint_connectivity_preserved(self):
        for net in {p['net'] for p in self.copper if p['net']} - NETS:
            old=connected_groups(self.source,self.copper,net)
            new=connected_groups(self.doc,self.copper,net)
            for group in old:
                self.assertTrue(any(group<=n for n in new), (net,group,new))

    def test_missing_usb_via_detected(self):
        doc=copy.deepcopy(self.doc)
        doc['shape']=[s for s in doc['shape'] if not (s.startswith('VIA~') and s.split('~')[4]=='USB_DP_SOC')]
        self.assertEqual(len(connected_groups(doc,self.copper,'USB_DP_SOC')),2)

    def test_mechanical_hole_regression_detected(self):
        doc=copy.deepcopy(self.doc)
        doc['shape']=[s for s in doc['shape'] if not(s.startswith('TRACK~') and s.split('~')[5]==PREFIX+'T6')]
        doc['shape'].append(track('GND','22',[(-1.35,-.7),(-3.0655654,-2.4155654),(-4.3200574,-2.4155654)],6,.254))
        self.assertTrue(any(c[0]=='线-机械孔' for c in check(doc,self.copper)[0]))


if __name__=='__main__': unittest.main()
