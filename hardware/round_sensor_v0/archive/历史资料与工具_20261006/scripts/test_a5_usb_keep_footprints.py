"""独立录入的铜焊盘尺寸与引脚分组复核。"""
import json
import unittest
from pathlib import Path

OUT=Path(__file__).resolve().parents[1]/'easyeda_std/usb_keep_min_candidate/footprints'


def pads(name):
    d=json.loads((OUT/(name+'.json')).read_text());out={}
    for s in d['shape']:
        if not s.startswith('PAD~'):continue
        v=s.split('~');assert v[1]=='RECT' and v[6]=='1' and float(v[9])==0
        out[v[8]]=tuple(round(z,4) for z in [(float(v[2])-400)*.254,(float(v[3])-300)*.254,float(v[4])*.254,float(v[5])*.254])
    return out


class Geometry(unittest.TestCase):
    def test_button_lands(self):
        self.assertEqual(pads('按键_EVPBB_官方铜焊盘'),{'1':(-1.325,-.375,.55,.55),'2':(-1.325,.375,.55,.55),
                      '3':(1.325,-.375,.55,.55),'4':(1.325,.375,.55,.55)})

    def test_central_no_exposed_copper(self):
        for x,y,w,h in pads('按键_EVPBB_官方铜焊盘').values():self.assertGreaterEqual(abs(x)-w/2,1.0)

    def test_button_paste_apertures(self):
        d=json.loads((OUT/'按键_EVPBB_官方铜焊盘.json').read_text())
        for s in d['shape']:
            if not s.startswith('PAD~'):continue
            v=s.split('~')
            self.assertAlmostEqual(float(v[17])*.254,-.05,places=5)
            for axis in (4,5):
                self.assertAlmostEqual((float(v[axis])+2*float(v[17]))*.254,.45,places=5)

    def test_pen_pad_pitch_and_number(self):
        self.assertEqual(pads('笔头四线_焊线焊盘候选'),{'1':(-1.35,0,.6,1.0),'2':(-.45,0,.6,1.0),
                       '3':(.45,0,.6,1.0),'4':(1.35,0,.6,1.0)})

    def test_pen_copper_gap_and_envelope(self):
        p=sorted(pads('笔头四线_焊线焊盘候选').values())
        for a,b in zip(p,p[1:]):self.assertAlmostEqual((b[0]-b[2]/2)-(a[0]+a[2]/2),.3)
        width=max(x+w/2 for x,y,w,h in p)-min(x-w/2 for x,y,w,h in p)
        height=max(y+h/2 for x,y,w,h in p)-min(y-h/2 for x,y,w,h in p)
        self.assertAlmostEqual(width,3.3);self.assertAlmostEqual(height,1.0)

    def test_pen_no_drilled_holes_or_connector(self):
        d=json.loads((OUT/'笔头四线_焊线焊盘候选.json').read_text())
        self.assertEqual(sum(s.startswith('PAD~') for s in d['shape']),4)
        self.assertFalse(any(s.startswith(('HOLE~','VIA~')) for s in d['shape']))
        for s in d['shape']:
            if s.startswith('PAD~'):self.assertEqual(float(s.split('~')[9]),0)

    def test_pen_paste_suppression_setting(self):
        d=json.loads((OUT/'笔头四线_焊线焊盘候选.json').read_text())
        for s in d['shape']:
            if not s.startswith('PAD~'):continue
            v=s.split('~');w,h=float(v[4]),float(v[5]);exp=float(v[17])
            self.assertLess(exp,-(w*w+h*h)**.5)
            self.assertGreater(float(v[18]),0)  # 焊线铜面仍开阻焊窗。

    def test_no_false_native_binding(self):
        d=json.loads((OUT/'封装清单.json').read_text())
        for k,v in d.items():
            if isinstance(v,dict):
                self.assertFalse(v['原生绑定']);self.assertFalse(v['制造放行'])


if __name__=='__main__':unittest.main(verbosity=2)
