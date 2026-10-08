"""生成两种局部改版封装候选；不伪造原生库 UUID 或制造放行。"""
import copy
import hashlib
import json
from pathlib import Path
from build_sch_a5_footprints import TEMPLATE

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'easyeda_std/usb_keep_min_candidate/footprints'
SPECS={
    '按键_EVPBB_官方铜焊盘':{
        '位号':['SW2','SW3'],'本体':[2.6,1.6],
        '铜焊盘':[('1',-1.325,-.375,.55,.55),('2',-1.325,.375,.55,.55),
                  ('3',1.325,-.375,.55,.55),('4',1.325,.375,.55,.55)],
        '内部连接':[['1','2'],['3','4']],
        '依据':'references/panasonic_evpbb.pdf 第2页，顶视图 A/A′ 左侧，B/B′ 右侧',
        '禁裸铜区域':[-1,-.8,1,.8],
        '钢网目标':{'开口毫米': [.45,.45], '中心同铜焊盘':True,'厚度毫米':.08,'厚度公差毫米':.01},
        '助焊扩展毫米':-.05,
        '待落实':'封装助焊扩展每边-0.05mm；中部阻焊覆盖、钢网厚度及操控空间须在原生 PCB 与装配审核中检查'},
    '笔头四线_焊线焊盘候选':{
        '位号':['J4'],'本体':[3.3,1.0],
        '铜焊盘':[(str(i+1),x,0,.6,1.0) for i,x in enumerate([-1.35,-.45,.45,1.35])],
        '功能':['3V3','GND','SDA','SCL'],
        '助焊扩展毫米':-2.0,
        '禁钢网依据':'https://docs.lceda.cn/cn/PCB/PCB-Tools/ ：负助焊扩展绝对值大于焊盘对角线；2mm大于sqrt(0.6^2+1.0^2)',
        '依据':'用户明确直接飞线，四个表面铜焊盘，不加连接器、排针或穿线孔；不是测试点',
        '尺寸依据':'工程紧凑候选，不是厂家规定的最小飞线焊盘；线径与手焊试验未确认',
        '装配方式':'细飞线手焊，焊盘外由笔杆结构固定导线，焊点不承担拉力；禁止开钢网',
        '待落实':'0.6x1.0mm 铜焊盘、0.9mm节距、0.3mm铜间隙；需匹配线芯/绝缘外径并验证焊接可达性和抗拉固定。3.3x1.0mm仅为铜包围框，不含阻焊开窗、线束与操作净空；未证明最终最小面积'}
}


def main():
    OUT.mkdir(exist_ok=True);base=json.loads(TEMPLATE.read_text());manifest={}
    for name,spec in SPECS.items():
        d=copy.deepcopy(base)
        d['head']={'docType':'4','editorVersion':'6.5.51','newgId':True,'x':400,'y':300,
                   'c_para':{'package':name,'pre':'SW?' if name.startswith('按键') else 'J?',
                             '说明':spec['待落实']}}
        d.pop('BBox',None);d['shape']=[]
        def cv(v,o=0):return f'{o+v/.254:.6f}'
        for n,x,y,w,h in spec['铜焊盘']:
            pad=f'PAD~RECT~{cv(x,400)}~{cv(y,300)}~{cv(w)}~{cv(h)}~1~~{n}~0~~0~ggeUSBFP{n}~0~~Y~0'
            if '助焊扩展毫米' in spec:
                # 标准版 6.5.51 原生源码回读：字段 17=助焊扩展，18=阻焊扩展，单位 10 mil。
                pad+=f'~{cv(spec["助焊扩展毫米"])}~0.2~{cv(x,400)},{cv(y,300)}'
            d['shape'].append(pad)
        w,h=spec['本体'];pts=[(-w/2,-h/2),(w/2,-h/2),(w/2,h/2),(-w/2,h/2),(-w/2,-h/2)]
        xy=' '.join(f'{cv(x,400)} {cv(y,300)}' for x,y in pts)
        d['shape'].append(f'TRACK~{cv(.05)}~12~~{xy}~ggeUSBBody~0')
        path=OUT/(name+'.json');path.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
        svg=['<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="600" viewBox="0 0 1000 600">',
             '<rect width="1000" height="600" fill="white"/>',
             f'<text x="30" y="45" font-family="sans-serif" font-size="24">{name} · 顶视图 · 未原生绑定</text>']
        scale=140;ox=500;oy=320
        svg.append(f'<rect x="{ox-w*scale/2}" y="{oy-h*scale/2}" width="{w*scale}" height="{h*scale}" fill="none" stroke="#777" stroke-dasharray="5 5"/>')
        if '禁裸铜区域' in spec:
            svg.append('<rect x="360" y="208" width="280" height="224" fill="#ddd" opacity="0.4"/>')
        for n,x,y,w,h in spec['铜焊盘']:
            svg.append(f'<rect x="{ox+(x-w/2)*scale}" y="{oy+(y-h/2)*scale}" width="{w*scale}" height="{h*scale}" fill="#b85036"/>')
            svg.append(f'<text x="{ox+x*scale}" y="{oy+y*scale+6}" text-anchor="middle" fill="white" font-family="sans-serif" font-size="20">{n}</text>')
        label='1/2 同组；3/4 同组；中部 2×1.6 mm 不得裸铜/开钢网' if name.startswith('按键') else '1=3V3；2=GND；3=SDA；4=SCL；手焊及固定方式待验证'
        svg.append(f'<text x="35" y="535" font-family="sans-serif" font-size="20">{label}</text></svg>')
        (OUT/(name+'.svg')).write_text(''.join(svg))
        manifest[name]={**spec,'文件':path.name,'SHA256':hashlib.sha256(path.read_bytes()).hexdigest(),
                        '原生绑定':False,'钢网阻焊已验证':False,'制造放行':False}
    manifest['按键原厂PDF_SHA256']=hashlib.sha256((ROOT/'references/panasonic_evpbb.pdf').read_bytes()).hexdigest()
    (OUT/'封装清单.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print('已生成两种封装候选，共三个实例；未绑定、未制造放行。')


if __name__=='__main__':main()
