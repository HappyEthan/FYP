"""只读审核用户最新布线副本，包含板级走线/过孔；不编辑PCB。"""
import hashlib
import json
import math
from collections import Counter
from check_pcb_a5 import ROOT, U, parse, xy, distance, rect, ellipse
from audit_a5_ufl_keepout import audit

SOURCE = ROOT/'easyeda_std/PCB_A5_用户布线副本_调整前备份_20260917.json'
BASE = ROOT/'easyeda_std/PCB_A5_production_silk_verified_20260916.json'
CANDIDATE = ROOT/'easyeda_std/PCB_A5_天线净空布局候选_未原生验证_20260917.json'
OUT = ROOT/'easyeda_std/pcb_a5_routed_snapshot_audit.json'


def routes(data):
    tracks, vias, unsupported = [], [], []
    for s in data['shape']:
        v=s.split('~')
        if v[0]=='TRACK':
            points=list(map(float,v[4].split()))
            tracks.append({'id':v[5], 'net':v[3], 'layer':v[2], 'width':float(v[1])*U,
                           'points':[xy(*points[i:i+2]) for i in range(0,len(points),2)]})
        elif v[0]=='VIA':
            vias.append({'id':v[6], 'net':v[4], 'layer':'11',
                         'poly':ellipse(*xy(v[1],v[2]),float(v[3])*U,float(v[3])*U)})
        elif v[0] not in {'LIB','TEXT','CIRCLE'}:
            unsupported.append(v[0])
        elif v[0]=='CIRCLE' and v[5]!='10':
            unsupported.append('非板框圆')
    return tracks,vias,unsupported


def track_gap(track, polygon):
    # 把实际线宽计入，路径段按圆头线处理；比只查中心线更严格。
    return min(distance([a,b],polygon) for a,b in zip(track['points'],track['points'][1:]))-track['width']/2


def analyze():
    d,p,c,h=parse(SOURCE); base,bp,bc,_=parse(BASE); _,_,moved,_=parse(CANDIDATE)
    tracks,vias,unsupported=routes(d)
    report,_,_=audit(SOURCE)
    zones={}
    for name,area in report['区域'].items():
        polys=area['板心坐标多边形_mm']
        hits=[{'图元':t['id'],'网络':t['net'],'层':t['layer'],'线宽_mm':round(t['width'],4)}
              for t in tracks if min(track_gap(t,q) for q in polys)<-1e-6]
        vh=[{'图元':v['id'],'网络':v['net']} for v in vias
            if min(distance(v['poly'],q) for q in polys)<1e-6]
        zones[name]={'现有焊盘侵入':area['现有焊盘过孔相交'],
                     ('走线侵入' if name=='中心禁走线区' else '走线与包络相交_未扣除顶层必要焊盘例外'):hits,
                     '板级过孔侵入':vh}
    involved=[]
    for old,new in zip(c,moved):
        if old['ref'] not in {'U5','C10','R11'}:continue
        touched=[]
        for t in tracks:
            if t['net']!=old['net'] or t['layer']!=old['layer']:continue
            if track_gap(t,old['poly']) <= 1e-4:
                touched.append({'图元':t['id'], '网络':t['net'],
                                '仅移动后仍接触该焊盘':track_gap(t,new['poly'])<=1e-4})
        if touched:involved.append({'焊盘':old['ref']+'.'+old['pin'],'原有接触走线':touched})
    original_shapes=Counter(base['shape']); current_shapes=Counter(d['shape'])
    result={'日期':'2026-09-17','原生文档':'PCB_圆形传感板_SCH_A5_XIAO精简版 copy',
            '来源':SOURCE.name,'源SHA256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
            '采集方式':'在桌面嘉立创标准版从当前未保存标签导出；未点击云端保存',
            '状态':'最新布线已备份；未修改、未覆盖或删除用户布线',
            '相对旧基线元件中心不变':all(p[r]['center']==bp[r]['center'] for r in bp),
            '相对旧基线铜焊盘嵌入过孔完全相同':c==bc,
            '旧基线图元全部仍存在':not(original_shapes-current_shapes),
            '图元计数':dict(Counter(s.split('~')[0] for s in d['shape'])),
            '板级走线按层计数':dict(Counter(t['layer'] for t in tracks)),
            '层说明':{'1':'顶层','2':'底层','21':'内层1','22':'内层2','11':'贯穿'},
            '未覆盖图形类型':unsupported,'净空检查':zones,'移动三实例会影响的接触':involved,
            '原生DRC实际观察':{'总计':46,'未完成连接':43,'间距叶子条目':3,
                                '导线间距':[{'图元':['gge1020990','gge1020963'],'实际_mm':.146,'规则_mm':.152},
                                           {'图元':['gge1020879','gge1020825'],'实际_mm':.146,'规则_mm':.152}],
                                '焊盘间距':[{'图元':['gge2136','gge2151'],'实际_mm':.14,'规则_mm':.152}],
                                '说明':'界面间距父节点显示2，但展开有2条导线和1条焊盘错误；按3个叶子条目记录'},
            '限制':'本脚本只检测净空及拟移动焊盘接触；不代替原生DRC、完整连通图、USB/RF阻抗或制造审查。'
                  '较大本体包络相交项未扣除顶层必要焊盘及馈线例外，不能把它的14项相交全部认作错误；'
                  '中心禁区已排除信号焊盘，可单独作为此次7条走线和1个过孔的净空发现。'
                  '净空为工程候选范围；当前原生没有对应规则。需要确定保留最新布线或另起未布线副本。'}
    return result


if __name__=='__main__':
    result=analyze()
    assert not result['未覆盖图形类型']
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'计数':result['图元计数'],'净空':result['净空检查'],
                      '移动影响':result['移动三实例会影响的接触']},ensure_ascii=False,indent=2))
