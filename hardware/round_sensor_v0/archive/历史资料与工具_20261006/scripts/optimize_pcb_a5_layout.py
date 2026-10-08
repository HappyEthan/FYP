"""A5 原生实时快照的布局优化与刚体几何预检；不更改封装/网络。"""
import copy
import hashlib
import itertools
import json
import math
from check_pcb_a5 import ROOT, U, parse, distance, rect
from check_pcb_a5_mechanical import inspect

SOURCE=ROOT/'easyeda_std/PCB_A5_layout_before_20260916.json'
# x、y 为板心相对毫米；角度为相对本轮快照的逆时针转角。
POSES={
    'J1':(0,-4.218,0),'U1':(-1.143,2.74,0),
    'ANT1':(5.7,1.7,0),'R30':(4.4,5.35,0),'C30':(3.17,5.77,270),'C31':(5.8,4.45,0),
    'C20':(0,7.5,0),'C21':(2.2,7.18,270),
    'U2':(4.0,4.2,0),'C2':(6.0,5.22,90),'C3':(1.5,4.25,0),
    'U3':(-4.45,2.3,0),'C4':(-3.55,4.06,180),'C5':(-6.85,3.05,0),
    'U4':(0,-4.2,0),'C6':(-1.5,-4.55,0),'C7':(1.5,-4.55,180),
    'R10':(0,-3.1,0),'Q1':(3.3,-4.8,0),'D4':(2.85,-5.75,0),'R9':(3.1,-3.85,0),
    'U5':(5.95,-.5,0),'C9':(3.8,-.875,0),'C10':(7.65,-.73,90),'R11':(3.8,-.05,0),
    'U6':(-.6,-1.95,90),'R3':(-2.95,-1.0,90),'R4':(-2.0,-1.0,90),
    'R1':(1.45,-1.85,0),'R2':(-2.4,-3.75,0),'D1':(2.9,-1.75,0),
    'D2':(1.5,-2.75,0),'D3':(-1.8,-2.8,0),
    'R5':(2.8,1.7,0),'R6':(2.8,.85,0),'R7':(1.3,5.1,0),'R8':(1.3,2.55,0),'C1':(1.3,3.4,0),
    'J3':(1.7,6.85,0),'SW1':(-3.15,5.5,0),
}


def transform(points,old,new,angle):
    a=math.radians(-angle);co,si=math.cos(a),math.sin(a)
    return [(new[0]+co*(x-old[0])-si*(y-old[1]),new[1]+si*(x-old[0])+co*(y-old[1])) for x,y in points]


def geometry(source=SOURCE,poses=None):
    d,parts,copper,holes=parse(source)
    mech,_,_,_=inspect(source)
    bodies=mech['器件本体']
    if poses:
        for ref,pose in poses.items():
            old=parts[ref]['center'];new=pose[:2];angle=pose[2]
            for item in copper+holes:
                if item['ref']==ref:item['poly']=transform(item['poly'],old,new,angle)
            if ref in bodies:
                b=bodies[ref]; b['polygon']=transform(b['polygon'],old,new,angle)
                b['center']=transform([b['center']],old,new,angle)[0]
                if angle%180:b['nominal_mm'][:2]=reversed(b['nominal_mm'][:2]);b['maximum_mm'][:2]=reversed(b['maximum_mm'][:2])
            parts[ref]['center']=new
    return d,parts,copper,holes,bodies


def metrics(parts,copper,holes,bodies):
    cross=[];via=[];edge=[];body=[];body_edge=[];hole=[];pad_under_body=[]
    for a,b in itertools.combinations(copper,2):
        if a['ref']==b['ref'] or not(a['layer']==b['layer'] or '11' in(a['layer'],b['layer'])):continue
        gap=distance(a['poly'],b['poly'])
        if gap < .15-1e-4:cross.append([a['ref']+'.'+a['pin'],b['ref']+'.'+b['pin'],round(gap,4)])
        if 'via' in(a['kind'],b['kind']) and gap < .25-1e-4:via.append([a['ref']+'.'+a['pin'],b['ref']+'.'+b['pin'],round(gap,4)])
    for p in copper:
        gap=9-max(math.hypot(x,y) for x,y in p['poly'])
        if gap<.2-1e-4:edge.append([p['ref']+'.'+p['pin'],round(gap,4)])
    for h in holes:
        for p in copper:
            if h['ref']!=p['ref'] and distance(h['poly'],p['poly'])<.2-1e-4:
                hole.append([h['ref'],p['ref']+'.'+p['pin'],round(distance(h['poly'],p['poly']),4)])
    for (r,a),(s,b) in itertools.combinations(bodies.items(),2):
        if a['layer']!=b['layer']:continue
        # 即使 DNP，也保留将来装配位置，禁止相互压住。
        aw,ah=a['maximum_mm'][:2];bw,bh=b['maximum_mm'][:2]
        pa=rect(*a['center'],aw or a['nominal_mm'][0],ah or a['nominal_mm'][1])
        pb=rect(*b['center'],bw or b['nominal_mm'][0],bh or b['nominal_mm'][1])
        gap=distance(pa,pb)
        if gap<.2-1e-4:body.append([r,s,round(gap,4)])
    for r,b in bodies.items():
        if r=='J1':continue # 用户允许 USB 本体局部伸出，铜不允许。
        mw,mh=b['maximum_mm'][:2]
        poly=rect(*b['center'],mw or b['nominal_mm'][0],mh or b['nominal_mm'][1])
        gap=9-max(math.hypot(x,y) for x,y in poly)
        if gap<.2-1e-4:body_edge.append([r,round(gap,4)])
        for p in copper:
            if p['ref']==r or not(p['layer']==b['layer'] or p['layer']=='11'):continue
            gap=distance(poly,p['poly'])
            if gap<.1-1e-4:pad_under_body.append([r,p['ref']+'.'+p['pin'],round(gap,4)])
    # U.FL 中心禁布区为当前阶段保守预留，不等于厂商形状最终确认。
    ax,ay=parts['ANT1']['center'];keep=rect(ax,ay,.0+1.8,2.6)
    rf_keep=[]
    for p in copper:
        if p['ref']=='ANT1':continue
        if distance(keep,p['poly'])<.1-1e-4:rf_keep.append([p['ref']+'.'+p['pin'],round(distance(keep,p['poly']),4)])
    centers={(p['ref'],p['pin']):(sum(x for x,y in p['poly'])/len(p['poly']),sum(y for x,y in p['poly'])/len(p['poly'])) for p in copper if p['kind']=='pad'}
    pairs=[('U1','1','R30','1'),('R30','2','ANT1','1'),('C1','1','U1','4'),('R7','2','U1','4'),
           ('R8','2','U1','5'),('C21','1','U1','56'),('C20','1','U1','46'),('C2','1','U2','4'),
           ('C3','1','U2','6'),('C4','1','U3','5'),('C5','1','U3','8'),('C9','1','U5','6'),('C10','1','U5','1'),
           ('D2','1','J1','A5'),('D3','1','J1','B5')]
    lengths={f'{a}.{b} → {c}.{e}':round(math.dist(centers[a,b],centers[c,e]),3) for a,b,c,e in pairs}
    return {'跨元件铜间距小于0.15mm':cross,'贯穿过孔至其他元件铜小于0.25mm':via,
            '铜至板边小于0.2mm':edge,'本体间距小于0.2mm':body,'非USB本体至板边小于0.2mm':body_edge,
            '定位孔至其他铜小于0.2mm':hole,'本体覆盖其他元件铜或间距小于0.1mm':pad_under_body,
            'UFL中心预留区与其他铜冲突':rf_keep,'关键焊盘直线距离_mm_不是走线长度':lengths}


def render(parts,copper,holes,bodies):
    from tidy_pcb_a5_silkscreen import assembly
    svg=['<svg xmlns="http://www.w3.org/2000/svg" width="1500" height="850" viewBox="0 0 1500 850"><rect width="1500" height="850" fill="#f4f7fa"/><style>text{font-family:Arial,"PingFang SC",sans-serif}</style>',
         '<text x="35" y="40" font-size="26">A5 · 18 mm 布局优化预检｜未布线，不可投板</text>']
    for i,layer in enumerate(('1','2')):
        cx=375+750*i;cy=445;sc=34;sgn=1 if i==0 else -1
        svg.append(f'<text x="{cx}" y="87" text-anchor="middle" font-size="22">'+('顶面' if i==0 else '底面（翻板视图）')+'</text>')
        def poly(points,style):
            svg.append('<polygon points="'+' '.join(f'{cx+sgn*x*sc},{cy+y*sc}' for x,y in points)+f'" {style}/>')
        svg.append(f'<circle cx="{cx}" cy="{cy}" r="{9*sc}" fill="#e2ece7" stroke="#37664d" stroke-width="2"/>')
        for p in copper:
            if p['layer'] in(layer,'11'):poly(p['poly'],'fill="#c8a656" stroke="#fff" stroke-width=".4"')
        for h in holes:poly(h['poly'],'fill="#f4f7fa" stroke="#6c7c8d"')
        for ref,b in bodies.items():
            if b['layer']!=layer:continue
            poly(b['polygon'],'fill="#4f90b8" fill-opacity=".13" stroke="#276c9b" stroke-width="1.2"')
        ax,ay=parts['ANT1']['center'];poly(rect(ax,ay,1.8,2.6),'fill="#b38eca" fill-opacity=".12" stroke="#9158ac" stroke-dasharray="4 4"')
        for ref,p in parts.items():
            if p['layer']!=layer:continue
            x,y=p['center']
            svg.append(f'<text x="{cx+sgn*x*sc}" y="{cy+y*sc-11}" text-anchor="middle" font-size="12" fill="#193957" stroke="#f4f7fa" stroke-width="2" paint-order="stroke">{ref}</text>')
    svg.append('<text x="35" y="820" font-size="16">蓝色为本体示意；紫色为 U.FL 中心预留区。小阻容尺寸、线缆与整机装配仍待终审。</text></svg>')
    (ROOT/'easyeda_std/PCB_A5_布局优化预检.svg').write_text('\n'.join(svg))


def main():
    old=geometry();new=geometry(poses=POSES)
    report={'来源':SOURCE.name,'来源SHA256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
            '修改前':metrics(*old[1:]),'候选布局':metrics(*new[1:]),'位置与相对转角':POSES,
            '限制':'几何预检，非布线、工艺或实物验证；小阻容采用标称本体；铜间距不代表阻焊合格。'}
    (ROOT/'easyeda_std/pcb_a5_layout_plan.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report['候选布局'],ensure_ascii=False,indent=2))
    render(*new[1:])
    if any(v for k,v in report['候选布局'].items() if k!='关键焊盘直线距离_mm_不是走线长度'):
        raise ValueError('候选布局预检未通过，禁止生成执行脚本')
    code="""// 原生刚体移动/旋转；不改变封装焊盘、网络、层或制造规则。
(function(){
var before=api('getSource',{type:'compress'});if(typeof before==='string')before=JSON.parse(before);
var expected=EXPECTED;
function sig(s){return s.replace(/-?\\d+(?:\\.\\d+)?/g,function(v){return String(Math.round(Number(v)*100)/100);});}
if(JSON.stringify(before.shape.map(sig).sort())!==JSON.stringify(expected.map(sig).sort()))throw Error('布局已改变，重新导出后再操作');
var d=api('getSource',{type:'json'}), refs={},poses=POSES;
Object.keys(d.FOOTPRINT).forEach(function(id){var f=d.FOOTPRINT[id];Object.keys(f.TEXT).forEach(function(k){if(f.TEXT[k].type==='P')refs[f.TEXT[k].text]=id;});});
if(Object.keys(refs).length!==41)throw Error('不是41元件PCB');
Object.keys(poses).forEach(function(r){
 // 原生脚本 degree 正值使几何顺时针，和原生存储 rotation 的方向相反。
 var p=poses[r];if(p[2])api('rotate',{ids:[refs[r]],degree:-p[2]});
 var f=api('getShape',{id:refs[r]});
 api('moveObjs',{objs:[refs[r]],addX:4020+p[0]/.254-Number(f.head.x),addY:3404+p[1]/.254-Number(f.head.y)});
});
api('selectNone');
var updated=api('getSource',{type:'json'});api('applySource',{source:updated,createNew:false});
})();
""".replace('EXPECTED',json.dumps(old[0]['shape'],ensure_ascii=False)).replace('POSES',json.dumps(POSES))
    (ROOT/'scripts/apply_pcb_a5_layout.js').write_text(code)


if __name__=='__main__':main()
