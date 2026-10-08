"""两种 USB-C 插入方向的焊盘中心路径长度；不含芯片/连接器内部和封装延时。"""
from audit_clone_native_ground_20260929 import *
from check_pcb_a5 import ROOT
import heapq

src=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'easyeda_std/PCB_克隆板USB局部重布_原生回读_20260929.json'
source_hash=hashlib.sha256(src.read_bytes()).hexdigest()
assert source_hash=='c3c0d4e5630df0b756df07d380213af8edc1a5eab8da054e44c54a5e4e337954', '来源不是已审核R；先复核新源，禁止覆盖当前报告'
d,p,c,h=parse(src);ts,vs,_=routes(d)
nodes=[];adj={};labels={}
def node(net,layer,q):
    for i,(n,l,r) in enumerate(nodes):
        if net==n and layer==l and math.dist(q,r)<.002:return i
    i=len(nodes);nodes.append((net,layer,q));adj[i]=[];return i
def edge(i,j,w):
    adj[i].append((j,w));adj[j].append((i,w))
usb=lambda n:n.startswith('USB_D')
for t in ts:
    if usb(t['net']):
        for q in t['points']:node(t['net'],t['layer'],q)
for a in c:
    if usb(a['net']):labels[a['ref']+'.'+a['pin']]=node(a['net'],a['layer'],batch.center(a))
for v in vs:
    if usb(v['net']):edge(node(v['net'],'1',batch.center(v)),node(v['net'],'2',batch.center(v)),.8)
for t in ts:
    if not usb(t['net']):continue
    for a,b in zip(t['points'],t['points'][1:]):
        length=math.dist(a,b)
        if not length:continue
        pts=[]
        for i,(n,l,q) in enumerate(nodes):
            if n!=t['net'] or l!=t['layer']:continue
            f=sum((q[k]-a[k])*(b[k]-a[k]) for k in (0,1))/length**2
            proj=tuple(a[k]+f*(b[k]-a[k]) for k in (0,1))
            if -.002/length<=f<=1+.002/length and math.dist(q,proj)<.002:pts.append((f,i))
        pts.sort()
        for (f,i),(g,j) in zip(pts,pts[1:]):edge(i,j,(g-f)*length)
for ref in ['R3','R4']:
    ids=[v for k,v in labels.items() if k.startswith(ref+'.')];assert len(ids)==2
    expected={'USB_DP','USB_DP_SOC'} if ref=='R3' else {'USB_DM','USB_DM_SOC'}
    assert {nodes[i][0] for i in ids}==expected, (ref, '串阻网络不匹配')
    edge(*ids,math.dist(nodes[ids[0]][2],nodes[ids[1]][2]))
def shortest(i,j):
    dist={i:0};heap=[(0,i)]
    while heap:
        w,u=heapq.heappop(heap)
        if u==j:return w
        if w!=dist[u]:continue
        for v,l in adj[u]:
            if w+l<dist.get(v,float('inf')):dist[v]=w+l;heapq.heappush(heap,(w+l,v))
    raise AssertionError('路径未连通')
result={'来源SHA256':source_hash,'范围':'按网络隔离建图，只有R3/R4显式桥接对应网络；焊盘中心几何长度，每次顶底层过孔计0.8mm、含串阻两焊盘中心距；不包含元件内部电气延时。不是DRC/短路检查或传输线仿真。','方向':{}}
for side in ['A','B']:
    rows={}
    for net,pin in [('USB_DP_SOC',side+'6'),('USB_DM_SOC',side+'7')]:
        start=next(a for a in c if a['ref']=='U1' and a['net']==net)
        rows[net]=shortest(labels['U1.'+start['pin']],labels['J1.'+pin])
    rows['几何长度差_mm']=abs(rows['USB_DP_SOC']-rows['USB_DM_SOC']);result['方向'][side]=rows
result['走线图元数']=sum(usb(t['net']) for t in ts)
result['实际线宽_mm']=sorted({t['width'] for t in ts if usb(t['net'])})
result['信号过孔数']=sum(usb(v['net']) for v in vs)
result['平行段筛查说明']='同层异极性线段，方向叉积绝对值小于0.002、投影重叠大于0.05mm、中心距小于1.1mm。只列几何邻近，不保证是独立差分对；插座多分支不能直接套双线模型。'
result['平行段']=[]
segments=[]
for t in ts:
    if not usb(t['net']):continue
    for idx,(a,b) in enumerate(zip(t['points'],t['points'][1:])):
        length=math.dist(a,b)
        if length:segments.append((t,idx,a,b,length,tuple((b[k]-a[k])/length for k in (0,1))))
for t,i,a,b,length,u in segments:
    if 'DP' not in t['net']:continue
    for s,j,e,f,other_length,v in segments:
        if 'DM' not in s['net'] or t['layer']!=s['layer']:continue
        if abs(u[0]*v[1]-u[1]*v[0])>=.002:continue
        project=lambda q:sum((q[k]-a[k])*u[k] for k in (0,1))
        lo,hi=sorted((project(e),project(f)))
        overlap=min(length,hi)-max(0,lo)
        center_dist=abs((e[0]-a[0])*u[1]-(e[1]-a[1])*u[0])
        if overlap>.05 and center_dist<1.1:
            result['平行段'].append({'D+':t['id']+':'+str(i),'D-':s['id']+':'+str(j),'层':t['layer'],'投影重叠_mm':overlap,'近似边间距_mm':center_dist-(t['width']+s['width'])/2})
result['已验收']=False
out=Path(sys.argv[2]) if len(sys.argv)>2 else ROOT/'easyeda_std/克隆板USB正反插路径检查_20260929.json'
out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False,indent=2))
