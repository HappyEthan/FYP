"""R导出有限格式Gerber核对：遇未支持语法拒绝，不作为CAM/工厂验收。"""
import hashlib,json,math,re,zipfile
from collections import Counter
from pathlib import Path
from check_pcb_a5 import ROOT,parse,rect,ellipse,oval,distance,inside,xy,U

SOURCE=ROOT/'easyeda_std/PCB_克隆板USB局部重布_原生回读_20260929.json'
ZIP=ROOT/'manufacturing/仅审核禁止生产/Gerber_圆形传感板_R_仅审核禁止生产_20260929.zip'
assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()=='c3c0d4e5630df0b756df07d380213af8edc1a5eab8da054e44c54a5e4e337954'
assert hashlib.sha256(ZIP.read_bytes()).hexdigest()=='3660b1f776e00ce33d671d8ed88066fd348e57455e6e41f433869474edd8d3f1'
d,p,c,h=parse(SOURCE)

def area(poly):return abs(sum(x*v-u*y for (x,y),(u,v) in zip(poly,poly[1:]+poly[:1])))/2

def read_mask(t):
    assert '%FSLAX45Y45*%' in t and '%MOMM*%' in t
    assert '%LPC' not in t and 'G02' not in t and 'G03' not in t
    macros={};aps={};out=[];reg=None;ap=None
    for raw in t.splitlines():
        s=raw.strip()
        if not s or s.startswith('G04'):continue
        if s.startswith('%AM'):
            m=re.fullmatch(r'%AM([^*]+)\*([^*]+)\*%',s);assert m,s
            macros[m[1]]=m[2];continue
        if s.startswith('%ADD'):
            m=re.fullmatch(r'%ADD(\d+)([^,*]+)(?:,([^*]+))?\*%',s);assert m,s
            aps[m[1]]=(m[2],m[3]);continue
        if s.startswith('%'):assert s in ['%FSLAX45Y45*%','%MOMM*%','%LPD*%'],s;continue
        if s=='G36*':assert reg is None;reg=[];continue
        if s=='G37*':assert reg and len(reg)>=3;out.append(reg);reg=None;continue
        if s in ('G01*','G75*','M02*'):continue
        m=re.fullmatch(r'D(\d+)\*',s)
        if m:ap=aps[m[1]];continue
        m=re.fullmatch(r'X(-?\d+)Y(-?\d+)D0([123])\*',s);assert m,s
        x,y=int(m[1])/1e5,-int(m[2])/1e5;mode=m[3]
        if reg is not None:assert mode in ('1','2');reg.append((x,y));continue
        assert mode=='3' and ap is not None,s
        name,param=ap;params=[float(v) for v in param.split('X')] if param else []
        if name=='R':poly=rect(x,y,*params)
        elif name=='C':poly=ellipse(x,y,params[0],params[0])
        elif name=='O':poly=oval(x,y,*params,0)
        else:
            template=macros[name]
            for i,v in enumerate(params,1):template=template.replace('$'+str(i),str(v))
            v=[float(x) for x in template.split(',')]
            assert v[1]==1
            if v[0]==21:
                assert len(v)==7 and v[4:6]==[0,0]
                poly=rect(x,y,v[2],v[3],-v[6])
            elif v[0]==4:
                assert v[-1]==0 and len(v)==3+2*(int(v[2])+1)+1
                poly=[(x+v[i],y-v[i+1]) for i in range(3,len(v)-1,2)]
            else:raise AssertionError(template)
        out.append(poly)
    assert reg is None
    return out

with zipfile.ZipFile(ZIP) as z:
    layers={key:read_mask(z.read(name).decode()) for key,name in {
        '顶锡膏':'Gerber_TopPasteMaskLayer.GTP','底锡膏':'Gerber_BottomPasteMaskLayer.GBP',
        '顶阻焊':'Gerber_TopSolderMaskLayer.GTS','底阻焊':'Gerber_BottomSolderMaskLayer.GBS'}.items()}
    outline=z.read('Gerber_BoardOutlineLayer.GKO').decode()
    moves=re.findall(r'X(-?\d+)Y(-?\d+)D02\*',outline)
    arcs=re.findall(r'X(-?\d+)Y(-?\d+)I(-?\d+)J(-?\d+)D01\*',outline)
    assert len(moves)==len(arcs)==4 and outline.count('G02*')==4
    starts=[tuple(int(v)/1e5 for v in q) for q in moves]
    ends=[tuple(int(v)/1e5 for v in q[:2]) for q in arcs]
    assert all(ends[i]==starts[(i+1)%4] for i in range(4))
    dims=[max(q[k] for q in starts)-min(q[k] for q in starts) for k in (0,1)]
    assert all(abs(v-18)<.0001 for v in dims)
    drill=z.read('Drill_PTH_Through_Via.DRL').decode();tools={};holes=[];active=None
    assert 'METRIC,LZ,000.000' in drill
    for s in drill.splitlines():
        m=re.fullmatch(r'T(\d+)C([\d.]+)',s)
        if m:tools[m[1]]=float(m[2]);continue
        m=re.fullmatch(r'T(\d+)',s)
        if m:active=tools[m[1]];continue
        m=re.fullmatch(r'X(-?\d+)Y(-?\d+)',s)
        if m:assert active;holes.append(((int(m[1])/1000,-int(m[2])/1000),active))

ep=next(x for x in c if x['ref']=='U1' and x['pin']=='57')['poly']
source_vias=[]
for shape in d['shape']:
    for item in shape.split('#@$'):
        f=item.split('~')
        if f[0]=='VIA':source_vias.append((xy(f[1],f[2]),float(f[5])*2*U,f[6]))
assert len(source_vias)==len(holes)
matched=set();max_pos_error=0;max_dia_error=0
for q,dia,ident in source_vias:
    i=min(range(len(holes)),key=lambda i:math.dist(q,holes[i][0]))
    assert i not in matched;matched.add(i)
    pos_error=math.dist(q,holes[i][0]);dia_error=abs(dia-holes[i][1])
    assert pos_error<.0008 and dia_error<.00101,(ident,pos_error,dia_error)
    max_pos_error=max(max_pos_error,pos_error);max_dia_error=max(max_dia_error,dia_error)
ep_paste=[x for x in layers['顶锡膏'] if distance(x,ep)<1e-7]
ep_holes=[(q,dia) for q,dia in holes if inside(q,ep)]
j4=[x for x in c if x['ref']=='J4']
j4_paste={x['pin']:sum(distance(poly,x['poly'])<1e-7 for poly in layers['底锡膏']) for x in j4}
q1={x['pin']:x for x in c if x['ref']=='Q1'}
q1_masks={pin:[poly for poly in layers['底阻焊'] if inside(tuple(sum(q[k] for q in x['poly'])/len(x['poly']) for k in (0,1)),poly)] for pin,x in q1.items()}
assert all(len(v)==1 for v in q1_masks.values())
mask_gap=distance(q1_masks['2'][0],q1_masks['3'][0]);copper_gap=distance(q1['2']['poly'],q1['3']['poly'])
capacitor_paste=[]
for ref in ['C6','C7','C9','C10','C20']:
    for pad in sorted([x for x in c if x['ref']==ref and x['kind']=='pad'],key=lambda x:x['pin']):
        layer={'1':'顶锡膏','2':'底锡膏'}[pad['layer']]
        # 按当前矩形焊盘中心定位开口，不将相邻开口的接近误认为本焊盘开口。
        center=tuple(sum(q[k] for q in pad['poly'])/len(pad['poly']) for k in (0,1))
        openings=[poly for poly in layers[layer] if inside(center,poly)]
        capacitor_paste.append({'位号':ref,'引脚':pad['pin'],'层':layer,
            '铜面积_mm2':area(pad['poly']),'开口数':len(openings),
            '锡膏面积_mm2':sum(area(poly) for poly in openings),
            '锡膏面积与铜面积比':sum(area(poly) for poly in openings)/area(pad['poly'])})

def clip_box(poly, box):
    """Sutherland-Hodgman裁剪，box为xmin/xmax/ymin/ymax；仅用于轴对齐C20。"""
    out=list(poly)
    for axis,limit,keep_greater in [(0,box[0],True),(0,box[1],False),(1,box[2],True),(1,box[3],False)]:
        src=out;out=[]
        if not src:break
        for a,b in zip(src,src[1:]+src[:1]):
            ia=(a[axis]>=limit) if keep_greater else (a[axis]<=limit)
            ib=(b[axis]>=limit) if keep_greater else (b[axis]<=limit)
            if ia!=ib:
                t=(limit-a[axis])/(b[axis]-a[axis])
                out.append(tuple(a[k]+t*(b[k]-a[k]) for k in (0,1)))
            if ib:out.append(b)
    return out

def bounds(poly):
    return [min(q[0] for q in poly),max(q[0] for q in poly),min(q[1] for q in poly),max(q[1] for q in poly)]

assert abs(area(clip_box(rect(0,0,2,2),[0,2,0,2]))-1)<1e-9
assert clip_box(rect(0,0,2,2),[2,3,2,3])==[]
from audit_a5_routed_snapshot import routes,track_gap
tracks,vias,_=routes(d)
c20_pads=sorted([x for x in c if x['ref']=='C20' and x['kind']=='pad'],key=lambda x:x['pin'])
c20_openings=[];c20_rows=[];c20_trial=[]
for pad in c20_pads:
    box=bounds(pad['poly']);center=((box[0]+box[1])/2,(box[2]+box[3])/2)
    assert abs(area(pad['poly'])-(box[1]-box[0])*(box[3]-box[2]))<1e-8
    opening=next(poly for poly in layers['顶锡膏'] if inside(center,poly))
    c20_openings.append(opening)
    ob=bounds(opening);perimeter=sum(math.dist(a,b) for a,b in zip(opening,opening[1:]+opening[:1]))
    # 一项局部铜候选：推荐范围内，中心、网络、元件放置、线路均不动。
    trial=rect(*center,.8,1.3);c20_trial.append(trial)
    same=[t for t in tracks if t['net']==pad['net'] and t['layer']==pad['layer'] and track_gap(t,pad['poly'])<=1e-5]
    old_vias=[v for v in vias if v['net']==pad['net'] and distance(v['poly'],pad['poly'])<=1e-5]
    gaps=[(distance(trial,x['poly']),x.get('id',x.get('ref','')+'.'+x.get('pin','')))
          for x in c+vias if x['net']!=pad['net'] and x['layer'] in [pad['layer'],'11']]
    gaps += [(track_gap(t,trial),t['id']) for t in tracks if t['net']!=pad['net'] and t['layer']==pad['layer']]
    outside=area(opening)-area(clip_box(opening,bounds(trial)))
    c20_rows.append({'引脚':pad['pin'],'铜长宽_mm':[box[1]-box[0],box[3]-box[2]],
        '开口包围框长宽_mm':[ob[1]-ob[0],ob[3]-ob[2]],'开口多边形_mm':opening,
        '开口面积_mm2':area(opening),'开口周长_mm':perimeter,
        '钢网厚度场景_未选定':[{'厚度_mm':t,'开口体积_mm3_非实际沉积':area(opening)*t,
             '脱模面积比_A除以周长厚度':area(opening)/(perimeter*t)} for t in [.08,.10,.12,.15]],
        '候选铜长宽_mm':[.8,1.3],'候选保持原导线接触':[{'导线':t['id'],'仍接触':track_gap(t,trial)<=1e-5} for t in same],
        '候选保持原直接过孔接触':[{'过孔':v['id'],'仍接触':distance(v['poly'],trial)<=1e-5} for v in old_vias],
        '候选最小异网铜距_mm':min(gaps)[0],'候选最近异网图元':min(gaps)[1],
        '候选板边铜距_mm':8.999982-max(math.dist((22.999954,-78.999842),q) for q in trial),
        '旧锡膏超出候选铜面积_mm2':outside,'旧锡膏超出候选铜比例':outside/area(opening),
        '边界':'只核原导线/过孔接触与局部铜距；未重铺铜/原生DRC，未修改铜/阻焊/锡膏。'})
c20_review={'日期':'2026-09-29','焊盘':c20_rows,
    '现有开口最小间距_mm':distance(*c20_openings),'候选铜内间隙_mm':distance(*c20_trial),
    '厂家PDF':'references/GRM21BR61A226ME44-01A.pdf',
    '厂家PDF_SHA256':hashlib.sha256((ROOT/'references/GRM21BR61A226ME44-01A.pdf').read_bytes()).hexdigest(),
    '厂家依据':'PDF第16页要求实际评估适当锡量，第27页推荐a=1.0–1.4/b=0.6–0.8/c=1.2–1.4mm；不是通用一刀切的钢网开口。',
    '嘉立创参考':'https://www.jlc.com/portal/q7i276.html',
    '嘉立创参考边界':'2014年官方CHIP开孔文章提出0805开口内距至少0.7mm及防锡珠；作为历史几何参考，不代替当前订单工程确认。',
    '结论':'现有开口带朝内防锡珠凹口，不能把约80%面积比等同于均匀缩放或自动合格。C20不必因此换料；0.8×1.3mm同中心铜候选局部可行，但旧自定义锡膏不能直接沿用。默认保留R，钢网厚度/锡量与本板完整SMT方案仍需确认。',
    '默认改板':False,'工厂装配确认':False,'允许生产':False}
via_pairs=sorted((math.dist(a[0],b[0])-(a[1]+b[1])/2,i,j)
                 for i,a in enumerate(holes) for j,b in enumerate(holes) if i<j)
via_spacing={'依据':'https://www.jlc.com/portal/vtechnology.html',
             '国内官网孔边距下限_mm':0.2,'过孔数量':len(holes),'比较孔对数':len(via_pairs),
             '最小孔边距_mm':via_pairs[0][0],
             '最近两孔':[holes[via_pairs[0][1]],holes[via_pairs[0][2]]],
             '低于0_2mm孔对':[{'孔边距_mm':gap,'孔':[holes[i],holes[j]]} for gap,i,j in via_pairs if gap<.2-1e-9],
             '范围':'仅Drill_PTH_Through_Via.DRL内83个圆过孔的名义孔边距；不含插件孔/槽孔、刀具补偿和工厂成品公差，不代表全板钻孔DFM通过。'}
report={
 '检查点':'R','源码SHA256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'审核包':str(ZIP),'审核包SHA256':hashlib.sha256(ZIP.read_bytes()).hexdigest(),
 '范围':'实际输出板框、过孔钻孔、锡膏与阻焊局部几何；不是全层CAM/制造放行。圆形开口用64边形近似，本文Q1/EP测量为直边多边形。',
 '板框闭合四圆弧':True,'板框尺寸_mm':dims,'过孔钻孔输出统计':dict(Counter(str(dia) for q,dia in holes)),
 '所有过孔与原生源一一匹配':True,'孔中心输出最大舍入_mm':max_pos_error,'孔径输出最大舍入_mm':max_dia_error,
 '国内工艺过孔孔边距筛查':via_spacing,
 'U1中央焊盘':{'铜面积_mm2':area(ep),'锡膏图形数':len(ep_paste),'锡膏面积_mm2':sum(area(x) for x in ep_paste),'覆盖率':sum(area(x) for x in ep_paste)/area(ep),
   '盘中孔数':len(ep_holes),'盘中孔_mm':ep_holes,'孔中心落入锡膏数':sum(any(inside(q,poly) for poly in ep_paste) for q,dia in ep_holes),
   '待审':'实际仍为单窗，历史四窗候选未应用；新增小地孔后须按实际10孔重新确认填孔/盖帽/钢网，不照搬旧九孔说明。'},
 'J4各焊盘与底锡膏相交图形数':j4_paste,
 '电容锡膏输出核查':{'焊盘':capacitor_paste,'边界':'只核对输出开口面积，不证明焊接质量；C20当前铜尺寸偏离原候选推荐，需连同锡膏厚度/开口复核，不意味着必须换电容。'},
 'C20钢网与同中心铜候选':c20_review,
 'Q1_2与3':{'铜间距_mm':copper_gap,'输出阻焊开窗间桥宽_mm':mask_gap,'待审':'这是设计输出，不是工厂补偿后的成品阻焊桥；保持原厂铜焊盘与既有DRC待审项。'},
 '结论':'保留审核用途；Q1阻焊桥、PICO盘中孔/钢网、双面贴装/回流、孔径取整与工厂层叠须正式确认。未上传订单或采购。','允许生产':False}
dest=ROOT/'easyeda_std/克隆板R制造输出局部审核_20260929.json'
dest.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report,ensure_ascii=False,indent=2))

# 仅渲染已经解析的真实输出；不是嘉立创CAM截图。
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon,Circle,Patch
plt.rcParams['font.family']=['Arial Unicode MS','sans-serif']
fig,axes=plt.subplots(1,3,figsize=(15,5))
ax=axes[0];ax.add_patch(Polygon(ep,color='#ccb770',alpha=.75))
for poly in ep_paste:ax.add_patch(Polygon(poly,color='#41b6c4',alpha=.7))
for q,dia in ep_holes:ax.add_patch(Circle(q,dia/2,facecolor='white',edgecolor='#a51824',linewidth=1.2))
cx,cy=p['U1']['center'];ax.set_xlim(cx-2.3,cx+2.3);ax.set_ylim(cy-2.3,cy+2.3)
ax.set_title('PICO 中央焊盘：单窗约64%，10个盘中孔')
ax.legend(handles=[Patch(color='#ccb770',label='铜焊盘'),Patch(color='#41b6c4',label='实际锡膏开口'),Patch(facecolor='white',edgecolor='#a51824',label='实际钻孔')],fontsize=8)
ax=axes[1]
for pin,pad in q1.items():
    ax.add_patch(Polygon(q1_masks[pin][0],facecolor='#41b6c4',alpha=.6))
    ax.add_patch(Polygon(pad['poly'],fill=False,edgecolor='#9c7218',linewidth=2))
    center=tuple(sum(q[k] for q in pad['poly'])/len(pad['poly']) for k in (0,1));ax.text(*center,pin,ha='center',va='center')
cx,cy=p['Q1']['center'];ax.set_xlim(cx-.8,cx+.8);ax.set_ylim(cy-.7,cy+.7)
ax.set_title('Q1 阻焊桥约0.140mm（工厂补偿前）')
ax=axes[2]
for pad,opening,trial in zip(c20_pads,c20_openings,c20_trial):
    ax.add_patch(Polygon(pad['poly'],facecolor='#ccb770',alpha=.65))
    ax.add_patch(Polygon(opening,facecolor='#41b6c4',alpha=.7))
    ax.add_patch(Polygon(trial,fill=False,edgecolor='#ac2762',linestyle='--',linewidth=1.5))
cx,cy=p['C20']['center'];ax.set_xlim(cx-1.9,cx+1.9);ax.set_ylim(cy-1.35,cy+1.35)
ax.add_patch(Polygon(rect(cx,cy,2,1.25),fill=False,edgecolor='#333333',linestyle=':',linewidth=1))
ax.set_title('C20：原开口带凹口，铜缩小仅试算')
ax.legend(handles=[Patch(color='#ccb770',label='现有铜'),Patch(color='#41b6c4',label='实际锡膏'),
    Patch(fill=False,edgecolor='#ac2762',linestyle='--',label='同中心铜候选（未应用）'),
    Patch(fill=False,edgecolor='#333333',linestyle=':',label='标称本体')],fontsize=8,loc='lower center')
for ax in axes:ax.set_aspect('equal');ax.set_xlabel('X / mm');ax.set_ylabel('Y / mm');ax.grid(alpha=.15)
fig.suptitle('R 实际 Gerber 局部解析，仅审核、禁止生产')
fig.tight_layout();fig.savefig(ROOT/'easyeda_std/R制造输出局部审核_20260929.png',dpi=150);plt.close(fig)
