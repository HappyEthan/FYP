"""USB 扇出局部可布性审查。只写报告，不生成/覆盖 PCB，不证明全局不可布。"""
import copy
import hashlib
import json
import math
from pathlib import Path
import numpy as np
from check_pcb_a5 import ROOT, parse, xy, U, distance, shared_layer, ellipse
from audit_a5_routed_snapshot import routes, track_gap
from build_a5_usb_soc_fanout import pad_center
from repair_clone_inner_layer_20260928 import line_distance, poly_distance

SOURCE=Path('/Users/liuchunyu/Downloads/PCB_克隆板USB调整前_20260928.json')
SHA='9d75f1244549d9def425d98eda4fd0a8496061458a9061c360e269ae1f0c8068'
REPORT=ROOT/'easyeda_std/克隆板USB扇出障碍核验_20260928.json'
GAP=.1524
WIDTH=.155
OD=.4

def candidates(copper,tracks,vias,holes,net):
    # 只探索主控 USB 管脚北侧的有限局部区域；不是整板寻路。
    xs=np.arange(22.65,24.251,.02);ys=np.arange(-79.65,-78.899,.02)
    X,Y=np.meshgrid(xs,ys);good=np.ones(X.shape,bool)
    for p in copper+vias:
        if p['net']!=net:good &= poly_distance(X,Y,p['poly'])>=OD/2+GAP+.001
        elif p.get('kind')=='pad':good &= poly_distance(X,Y,p['poly'])>=.1+.1+.001
        if p.get('kind')=='via' or p in vias:good &= poly_distance(X,Y,p['poly'])>=OD/2+.054+.001
    for t in tracks:
        if t['net']==net:continue
        for a,b in zip(t['points'],t['points'][1:]):
            good &= line_distance(X,Y,a,b)>=OD/2+t['width']/2+GAP+.001
    for h in holes:good &= poly_distance(X,Y,h['poly'])>=.1+.254+.001
    return [(float(X[j,i]),float(Y[j,i])) for j,i in zip(*np.where(good))]

def top_lead(copper,net,via):
    start=pad_center(copper,'U1','25' if net=='USB_DM_SOC' else '26')
    dx=via[0]-start[0]
    elbow=(start[0],via[1]+abs(dx))
    return {'id':net+'_顶层扇出','net':net,'layer':'1','width':WIDTH,'points':[start,elbow,via]}

def check_lead(t,copper,tracks,vias):
    issues=[]
    for p in copper+vias:
        if shared_layer(t,p) and t['net']!=p['net']:
            gap=track_gap(t,p['poly'])
            if gap<GAP-1e-5:issues.append([p.get('id',p.get('ref','')+'.'+p.get('pin','')),round(gap,6)])
    for other in tracks:
        if t['layer']!=other['layer'] or t['net']==other['net']:continue
        gap=min(distance([a,b],[x,y]) for a,b in zip(t['points'],t['points'][1:]) for x,y in zip(other['points'],other['points'][1:]))-(t['width']+other['width'])/2
        if gap<GAP-1e-5:issues.append([other['id'],round(gap,6)])
    return issues

def point_issues(p,net,copper,tracks,vias):
    poly=ellipse(*p,OD,OD);issues=[]
    for q in copper+vias:
        if q['net']==net:continue
        gap=distance(poly,q['poly'])
        if gap<GAP-1e-5:issues.append([q.get('id',q.get('ref','')+'.'+q.get('pin','')),q['net'],round(gap,6)])
    for t in tracks:
        if t['net']==net:continue
        gap=track_gap(t,poly)
        if gap<GAP-1e-5:issues.append([t['id'],t['net'],round(gap,6)])
    return issues

def main():
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()==SHA,'现场来源变化，停止'
    d,parts,copper,holes=parse(SOURCE);tracks,vias,_=routes(d)
    u=next(p for p in copper if p['ref']=='U1' and p['pin']=='25')
    j=next(p for p in copper if p['ref']=='J1' and p['pin']=='A7')
    corridor=min(p[1] for p in j['poly'])-max(p[1] for p in u['poly'])
    circle=next(s.split('~') for s in d['shape'] if s.startswith('CIRCLE~'))
    bc=xy(circle[1],circle[2]);br=float(circle[3])*U
    shell=[p for p in copper if p['ref']=='J1' and p['pin']=='SH']
    edge_sweep={str(dy):min(br-max(math.dist(bc,(x,y+dy)) for x,y in p['poly']) for p in shell) for dy in (0,.3,.5)}
    fixed={}
    for n in ('USB_DM_SOC','USB_DP_SOC'):
        points=candidates(copper,tracks,vias,holes,n)
        clear=[p for p in points if not check_lead(top_lead(copper,n,p),copper,tracks,vias)]
        fixed[n]={'可放孔点数':len(points),'可直接顶层扇出点数':len(clear),'可直接扇出点_mm':clear}
    # 一个有明确边界的假设：R6右移0.70mm、SCL顶层横段向主控内部退让。
    # 不改变实际文档，不把这些假设称为已完成摆位。
    proposed={'USB_DM_SOC':(23.05,-79.01),'USB_DP_SOC':(23.65,-79.01)}
    c2=copy.deepcopy(copper)
    for p in c2:
        if p['ref']=='R6':p['poly']=[(x+.7,y) for x,y in p['poly']]
    t2=copy.deepcopy(tracks)
    scl=next(t for t in t2 if t['id']=='ggeBATCH0928T284')
    scl['points']=[scl['points'][0],(24.199,-79.45),(19.809,-79.45),*scl['points'][3:]]
    # 逐孔和顶层扇出检查；尚不包含R6重接、底层完整差分或回流地孔。
    probes={n:{'孔中心_mm':p,'原位置阻挡':point_issues(p,n,copper,tracks,vias),
               '假设调整后孔冲突':point_issues(p,n,c2,t2,vias),
               '假设调整后顶层线冲突':check_lead(top_lead(c2,n,p),c2,t2,vias)} for n,p in proposed.items()}
    result={'来源':str(SOURCE),'来源SHA256':SHA,'云端文档未修改':True,
            '保守筛查间距_mm':GAP,'USB线宽_mm':WIDTH,'候选过孔外径_孔径_mm':[OD,.2],
            '主控与USB插座焊盘净通道_mm':corridor,
            '单线横穿所需净通道_mm':WIDTH+2*GAP,
            '双线横穿所需净通道_mm':2*WIDTH+3*GAP,
            'USB插座向外平移后的固定焊脚最小铜到板边_mm':edge_sweep,
            '固定布局北侧有限区域扫描':fixed,
            '假设扇出检验':probes,
            '假设两过孔铜环间距_mm':math.dist(*proposed.values())-OD,
            '假设调整后的SCL路径冲突':check_lead(scl,c2,t2,vias),
            '所需下一步':'先让出USB区的SCL/REG_EN/MCU_EN等占道段，整体规划R3/R4/U6局部摆位与成对路径，再恢复所有受影响网络；不要直接应用本假设',
            '原生DRC验证':False,'完整USB差分验证':False,'制造放行':False,
            '限制':['有限扫描失败不证明全局不可布','扇出假设不是完整候选，没有新增实际PCB图元',
                    '必须核验双线90欧姆、参考地、回流孔、ESD分支与总长度差；不能只看导通',
                    'R6移动后的机械间距、原有电源/I2C重接尚未验证']}
    REPORT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
