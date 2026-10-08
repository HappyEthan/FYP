"""独立解析五页候选的实际导线/引脚/标签；不等价于原生 ERC 或硬件验证。"""
from collections import defaultdict
import copy
import hashlib
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'easyeda_std/uart_min_candidate'


def check(doc,expected,profile='uart'):
    pins={};labels=defaultdict(set);nc=set();edges=[];ids=[];refs=set();unbound=[];bindings={}
    for k,page in enumerate(doc['schematics']):
        def node(x,y):return k,float(x),float(y)
        for s in page['dataStr']['shape']:
            v=s.split('~')
            if v[0]=='LIB':
                h,*body=s.split('#@$');r=next(t.split('~')[12] for t in body if t.startswith('T~P~'))
                assert r not in refs,'重复位号';refs.add(r);ids.append(v[6])
                a=v[3].split('`');attrs=dict(zip(a[::2],a[1::2]))
                if not attrs.get('package'):unbound.append(r)
                header=h.split('~')
                bindings[r]=(attrs.get('package',''),header[15] if len(header)>15 else '')
                for t in body:
                    if not t.startswith('P~'):continue
                    pp=t.split('^^');cfg=pp[0].split('~');dot=pp[1].split('~');num=pp[4].split('~')[4]
                    assert cfg[3]==num and node(cfg[4],cfg[5])==node(*dot),'引脚号或坐标错误'
                    name=r+'.'+num;assert name not in pins; pins[name]=node(*dot);ids.append(cfg[7])
            elif v[0]=='W':
                p=list(map(float,v[1].split()));points=[node(x,y) for x,y in zip(p[::2],p[1::2])]
                edges.extend(zip(points,points[1:]));ids.append(v[6])
            elif v[0]=='N':labels[node(v[1],v[2])].add(v[5]);ids.append(v[6])
            elif v[0]=='O':nc.add(node(v[1],v[2]));ids.append(v[3])
            elif v[0]=='J':labels[node(v[1],v[2])]  # 显式连接点加入几何节点。
    assert len(ids)==len(set(ids)),'电气图元 ID 重复'
    assert set(pins)==set(expected),'引脚集合与预期不一致'
    nodes=set(pins.values())|set(labels)|nc|{p for ab in edges for p in ab};parent={p:p for p in nodes}
    def find(p):
        if parent[p]!=p:parent[p]=find(parent[p])
        return parent[p]
    def union(a,b):parent[find(a)]=find(b)
    for a,b in edges:
        assert a[1]==b[1] or a[2]==b[2],'非正交电气导线'
        for p in nodes:
            if p[0]!=a[0]:continue
            cross=(p[1]-a[1])*(b[2]-a[2])-(p[2]-a[2])*(b[1]-a[1])
            if abs(cross)<1e-9 and min(a[1],b[1])<=p[1]<=max(a[1],b[1]) and min(a[2],b[2])<=p[2]<=max(a[2],b[2]):union(a,p)
    names=defaultdict(set);group=defaultdict(list)
    for p,ns in labels.items():names[find(p)].update(ns)
    assert all(len(v)<=1 for v in names.values()),'异名网络被导线短接'
    for n,p in pins.items():group[find(p)].append(n)
    actual={}
    for n,p in pins.items():
        r=find(p);ns=names[r]
        if p in nc:
            assert not ns and len(group[r])==1,'NC 引脚仍连入网络'
            actual[n]=None
        elif ns:actual[n]=next(iter(ns))
        else:
            values={expected[x] for x in group[r]}
            assert len(group[r])>=2 and len(values)==1 and None not in values,('悬空或错误局部接线',n,group[r])
            actual[n]=next(iter(values))
    assert actual==expected, {n:(expected[n],actual[n]) for n in pins if expected[n]!=actual[n]}
    if profile=='usb_keep':
        assert 'J3' not in refs and not refs&{'U7','R12','C22'},'旧测试点或 UART 附加电路残留'
        assert {'J1','R1','R2','R3','R4','D1','D2','D3','U2','U3','J4','SW2','SW3'}<=refs
        required={'J4.1':'3V3','J4.2':'GND','J4.3':'I2C_SDA','J4.4':'I2C_SCL',
                  'U1.25':'USB_DM_SOC','U1.26':'USB_DP_SOC','U1.49':None,'U1.50':None}
        for sw,net in [('SW2','BOOT_N'),('SW3','MCU_EN')]:
            required.update({sw+'.1':net,sw+'.2':net,sw+'.3':'GND',sw+'.4':'GND'})
        for n,net in required.items():assert actual[n]==net,('关键脚位错误',n)
        nets=defaultdict(list)
        for n,net in actual.items():
            if net is not None:nets[net].append(n)
        single={n:v for n,v in nets.items() if len(v)==1}
        assert not single,('孤立单引脚网络',single)
        assert len(refs)==43 and not unbound
        assert bindings['J4']==('笔头四线_焊线焊盘候选','fbf5a25068d7429988f18f56283e2018'),'笔头焊盘封装引用不匹配'
        for r in ('SW2','SW3'):
            assert bindings[r]==('按键_EVPBB_官方铜焊盘','08b07527ca8b41d891fac02ca34a03d1'),('按键封装引用不匹配',r)
        return {'状态':'局部改版接线检查通过；笔头电源接3V3','元件数':len(refs),'引脚数':len(pins),
                '网络数':len(nets),'待绑定封装':sorted(unbound),'网络':dict(nets),
                '已知阻断':['PCB未同步；钢网输出、布局布线、DRC和实物未验证；禁止生产'],
                '验证边界':'本函数只检查序列化接线与引用；原生观察另见原生验证进度.json',
                '原生ERC':False,'PCB已同步':False,'制造放行':False}
    assert profile=='uart'
    forbidden={'J3','R1','R2','R4','D2','D3'}
    assert not refs&forbidden,'旧 USB/下载焊盘未删除'
    required={'J1.1':'EXT_5V','J1.2':'GND','J1.3':'UART_TX_EXT','J1.4':'UART_RX_EXT',
        'U1.25':None,'U1.26':None,'U1.49':'UART_TX','U1.50':'UART_RX',
        'U7.1':'UART_TX','U7.6':'UART_TX_BUF','U7.3':'UART_RX_EXT','U7.4':'UART_RX',
        'U7.5':'3V3','U7.2':'GND','R3.1':'UART_TX_EXT','R3.2':'UART_TX_BUF',
        'R12.1':'UART_RX_EXT','R12.2':'GND','C22.1':'3V3','C22.2':'GND',
        'U6.1':'UART_TX_EXT','U6.2':'UART_RX_EXT','U6.3':'GND',
        'U4.A2':'EXT_5V','Q1.2':'EXT_5V','D4.2':'EXT_5V'}
    for sw,net in [('SW2','BOOT_N'),('SW3','MCU_EN')]:
        for p in ['1','2']:required[sw+'.'+p]=net
        for p in ['3','4']:required[sw+'.'+p]='GND'
    for n,net in required.items():assert actual[n]==net,('关键脚位错误',n)
    nets=defaultdict(list)
    for n,net in actual.items():
        if net is not None:nets[net].append(n)
    assert all(len(v)>=2 for v in nets.values()),'孤立单引脚网络'
    assert len(refs)==40 and set(unbound)=={'J1','U7','SW2','SW3'}
    return {'状态':'本地序列化接线检查通过','元件数':len(refs),'引脚数':len(pins),
            '网络数':len(nets),'待绑定封装':sorted(unbound),'网络':dict(nets),
            '原生ERC':False,'PCB已同步':False,'制造放行':False}


class Regression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc=json.loads((OUT/'原理图_UART小型化候选.json').read_text())
        cls.expected=json.loads((OUT/'预期接线.json').read_text())

    def test_good(self):self.assertEqual(check(self.doc,self.expected)['元件数'],40)

    def test_wire_break_rejected(self):
        d=copy.deepcopy(self.doc);s=d['schematics'][2]['dataStr']['shape']
        s[:]=[x for x in s if not (x.startswith('W~') and x.split('~')[1]=='680 300 760 300')]
        with self.assertRaises(AssertionError):check(d,self.expected)

    def test_short_rejected(self):
        d=copy.deepcopy(self.doc);d['schematics'][2]['dataStr']['shape'].append('W~1135 300 1135 350~#008800~1~0~none~ggeFault~0')
        with self.assertRaises(AssertionError):check(d,self.expected)

    def test_swapped_connector_rejected(self):
        e=copy.deepcopy(self.expected);e['J1.3'],e['J1.4']=e['J1.4'],e['J1.3']
        with self.assertRaises(AssertionError):check(self.doc,e)

    def test_wrong_buffer_pin_rejected(self):
        e=copy.deepcopy(self.expected);e['U7.4'],e['U7.6']=e['U7.6'],e['U7.4']
        with self.assertRaises(AssertionError):check(self.doc,e)

    def test_sensors_preserved(self):
        old=json.loads((ROOT/'archive/pcb_cloud_cleanup_20260918/1-Schematic_圆形传感板_SCH_A5.json').read_text())
        before=[s.replace('圆形传感板 · SCH-A5 · 2026-09-16','圆形传感板 · UART 小型化候选 · 2026-09-18') for s in old['schematics'][1]['dataStr']['shape']]
        self.assertEqual(before,self.doc['schematics'][1]['dataStr']['shape'])

    def test_power_preserved(self):
        old=json.loads((ROOT/'archive/pcb_cloud_cleanup_20260918/1-Schematic_圆形传感板_SCH_A5.json').read_text())
        before=[s.replace('USB_5V','EXT_5V').replace('G=2接USB','G=2接外部5V').replace('USB 充电仍可工作。','外部 5V 充电仍可工作。').replace('圆形传感板 · SCH-A5 · 2026-09-16','圆形传感板 · UART 小型化候选 · 2026-09-18') for s in old['schematics'][3]['dataStr']['shape']]
        self.assertEqual(before,self.doc['schematics'][3]['dataStr']['shape'])


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Regression))
    if not result.wasSuccessful():raise SystemExit(1)
    source=OUT/'原理图_UART小型化候选.json'
    report=check(json.loads(source.read_text()),json.loads((OUT/'预期接线.json').read_text()))
    report['SHA256']=hashlib.sha256(source.read_bytes()).hexdigest();report['回归测试数']=result.testsRun
    (OUT/'接线检查.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='网络'},ensure_ascii=False,indent=2))
