"""按P原生回读提取电源分支与电容路径。只写审查报告，不改PCB。

中心线图包含焊盘内/线宽内接触。铜阻只计算所选路径的走线，不含
孔壁、器件、连接器、地返回、电流分流、温升及瞬态，因此不是PDN验收。
"""
import hashlib
import heapq
import json
import math
import sys
from pathlib import Path
from check_pcb_a5 import ROOT, parse, point_seg, inside, distance
from audit_a5_routed_snapshot import routes
from repair_clone_batch_20260928 import center

if len(sys.argv)!=3:
    raise SystemExit('用法：python3 audit_clone_power_paths_20260929.py 来源.json 报告.json；必须显式指定，以免覆盖历史检查点。')
SOURCE=Path(sys.argv[1])
d,p,c,h=parse(SOURCE)
ts,vs,_=routes(d)
RHO=.01724  # copper at 20 C, ohm mm^2/m; conditional estimate, not process guarantee
THICKNESS={'1':.035,'2':.035,'21':.0152,'22':.0152}

def graph(net):
    tracks=sorted([t for t in ts if t['net']==net],key=lambda t:t['id'])
    pads=sorted([a for a in c if a['net']==net],key=lambda a:(a['ref'],a['pin']))
    vias=sorted([v for v in vs+c if v['net']==net and (v.get('kind')=='via' or v in vs)],key=lambda v:v.get('id',v.get('ref','')+'.'+v.get('pin','')))
    nodes=[];adj=[];labels={}
    def node(l,q):
        for i,(ll,qq) in enumerate(nodes):
            if ll==l and math.dist(q,qq)<.0003:return i
        nodes.append((l,q));adj.append([]);return len(nodes)-1
    def edge(a,b,length,res,tag):
        if a==b:return
        adj[a].append((b,length,res,tag));adj[b].append((a,length,res,tag))
    for t in tracks:
        for q in t['points']:node(t['layer'],q)
    for a in pads:labels[a['ref']+'.'+a['pin']]=node(a['layer'],center(a))
    for v in vias:
        ids=[node(l,center(v)) for l in THICKNESS]
        for i,j in zip(ids,ids[1:]):edge(i,j,0,0,'过孔_未计铜阻')
    # Add projection nodes for pad/via contacts and branch points within trace width.
    for t in tracks:
        for a,b in zip(t['points'],t['points'][1:]):
            le=math.dist(a,b)
            if le<1e-10:continue
            for i,(l,q) in list(enumerate(nodes)):
                if l!=t['layer']:continue
                f=sum((q[k]-a[k])*(b[k]-a[k]) for k in (0,1))/le**2
                if not 0<=f<=1:continue
                qq=tuple(a[k]+f*(b[k]-a[k]) for k in (0,1))
                if math.dist(qq,q)<=t['width']/2+.0003:
                    edge(i,node(l,qq),0,0,'线宽内接触')
    for a in pads:
        idx=labels[a['ref']+'.'+a['pin']]
        for i,(l,q) in enumerate(nodes):
            if l==a['layer'] and (inside(q,a['poly']) or min(point_seg(q,x,y) for x,y in zip(a['poly'],a['poly'][1:]+a['poly'][:1]))<.0003):
                edge(idx,i,0,0,'焊盘内接触')
    for v in vias:
        q=center(v);rad=max(math.dist(q,x) for x in v['poly'])
        for i,(l,qq) in list(enumerate(nodes)):
            if math.dist(q,qq)<=rad+.0003:edge(node(l,q),i,0,0,'过孔铜环接触')
    for t in tracks:
        for a,b in zip(t['points'],t['points'][1:]):
            le=math.dist(a,b)
            if le<1e-10:continue
            ids=[]
            for i,(l,q) in enumerate(nodes):
                if l==t['layer'] and point_seg(q,a,b)<.0003:
                    f=sum((q[k]-a[k])*(b[k]-a[k]) for k in (0,1))/le**2
                    if -.0003/le<=f<=1+.0003/le:ids.append((max(0,min(1,f)),i))
            ids.sort()
            for (f,i),(g,j) in zip(ids,ids[1:]):
                length=(g-f)*le
                edge(i,j,length,RHO*(length/1000)/(t['width']*THICKNESS[t['layer']]),t['id'])
    return labels,adj

def path(net,start,end):
    labels,adj=graph(net);a,b=labels[start],labels[end]
    costs={a:0};prior={};heap=[(0,a)]
    while heap:
        cost,i=heapq.heappop(heap)
        if cost!=costs[i]:continue
        if i==b:break
        for j,le,res,tag in adj[i]:
            new=cost+le
            if new<costs.get(j,float('inf')):
                costs[j]=new;prior[j]=(i,le,res,tag);heapq.heappush(heap,(new,j))
    if b not in costs:return {'端点':[start,end],'中心线图未解析':True}
    steps=[];i=b
    while i!=a:
        prev,le,res,tag=prior[i];steps.append((le,res,tag));i=prev
    steps.reverse();r=sum(s[1] for s in steps)
    return {'端点':[start,end],'网络':net,'路径走线长_mm':sum(s[0] for s in steps),
            '所选走线铜阻估算_ohm':r,'图元顺序':list(dict.fromkeys(s[2] for s in steps if s[0]>0)),
            '仅走线条件压降_mV':{str(amp)+'A':r*amp*1000 for amp in [.004,.1,.3,.5]}}

cases=[('VSYS','D4.1','U5.6'),('VSYS','Q1.3','U5.6'),('VSYS','D4.1','SW1.3'),
       ('USB_5V','J1.A4','U4.A2'),('USB_5V','J1.A9','U4.A2'),
       ('USB_5V','J1.A9','D4.2'),('BAT_P','J2.1','Q1.1'),
       ('3V3','C2.1','U2.6'),('GND','C2.2','U2.5'),('3V3','C3.1','U2.4'),
       ('3V3','C10.1','U5.1'),('VSYS','C9.1','U5.6')]
rows=[path(*case) for case in cases]
out={'来源':SOURCE.name,'来源SHA256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
     '当前板未修改':True,'方法限制':'焊盘/铜环内长度忽略，过孔阻值未计；选中心线最短路径，不解并联电流。铜厚外35um/内15.2um为层叠候选假设。不是最坏值、载流温升或动态电源验收。',
     '路径':rows,'结论':[
         'T291+T292约26.58mm仅从VSYS节点到SW1.3；SW1.2接REG_EN、SW1.1接GND，不是串联主负载供电线。无需以主控电流乘这条支路铜阻。',
         'USB左右供电脚已经通过板上电源网相连。分别列路径，不假定一条支线承担全部充电与主控电流。',
         'MLX C2至VDD/GND的走线长度见本报告路径；即使局部缩短，低直流压降与几何长度也不能证明高频去耦有效。',
         '仍须核对电池低压时LDO压差、USB供电热耗散、充电与负载电流、实际电容偏压容量和本地去耦。'],
     '原厂引脚依据':{'MLX90393':'https://media.melexis.com/-/media/files/documents/datasheets/mlx90393-datasheet-melexis.pdf','TLV755P':'https://www.ti.com/lit/ds/symlink/tlv755p.pdf'},
     '生产验收':False}
dest=Path(sys.argv[2])
dest.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(out,ensure_ascii=False,indent=2))
