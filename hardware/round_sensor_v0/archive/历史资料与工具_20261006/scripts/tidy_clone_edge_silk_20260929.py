"""仅整理越界丝印：无极性 RC 外框移至文档层，保留接口位号与所有铜。"""
from refine_clone_usb_20260928 import *
from build_a5_rf_clearance_layout import ref
from check_pcb_a5 import U,ORIGIN,xy
from tidy_pcb_a5_silkscreen import NUM
from tidy_pcb_a5_labels import bounds,overlap

doc,parts,c,h=parse(OUT);before=copy.deepcopy(doc);log=[]
rc={'C21','C31','C20','R30','C4','C9','R11'}
for i,s in enumerate(doc['shape']):
    if not s.startswith('LIB~') or ref(s) not in rc|{'SW1'}:continue
    chunks=s.split('#@$')
    for j,q in enumerate(chunks[1:],1):
        a=q.split('~')
        if a[0] in ('TRACK','ARC') and a[2] in ('3','4'):
            if ref(s)=='SW1' and (a[0]!='TRACK' or a[5]!='gge2979'):continue
            log.append([ref(s),a[0],a[5] if a[0]=='TRACK' else a[6],'转文档层保留装配外框']);a[2]='12';chunks[j]='~'.join(a)
    doc['shape'][i]='#@$'.join(chunks)

placed=[]
for name in ['J2','J4']:
    index=next(i for i,s in enumerate(doc['shape']) if s.startswith('LIB~') and ref(s)==name)
    chunks=doc['shape'][index].split('#@$');j=next(j for j,q in enumerate(chunks) if q.startswith('TEXT~P~'))
    t=chunks[j].split('~');assert float(t[5] or 0)==0
    nums=list(map(float,NUM.findall(t[11])));pts=[xy(x,y) for x,y in zip(nums[::2],nums[1::2])]
    box=bounds(pts);oldcenter=((box[0]+box[2])/2,(box[1]+box[3])/2)
    factor=.65/(float(t[9])*U);rel=[((x-oldcenter[0])*factor,(y-oldcenter[1])*factor) for x,y in pts]
    b=bounds(rel);layer='1' if t[7]=='3' else '2'
    obstacles=[]
    for r,p in parts.items():
        copper=[q for a in c if a['ref']==r and a['layer'] in (layer,'11') for q in a['poly']]
        if copper:obstacles.append(bounds(copper))
        for other in p['items']:
            if other[:2]!=['TEXT','P'] or r in rc|{'J2','J4'} or other[7]!=t[7]:continue
            ns=list(map(float,NUM.findall(other[11])))
            if ns:obstacles.append(bounds([xy(x,y) for x,y in zip(ns[::2],ns[1::2])]))
    obstacles += [bounds(v['poly']) for v in routes(doc)[1]+h]+placed
    opts=[]
    for ix in range(-35,36):
        for iy in range(-35,36):
            x,y=oldcenter[0]+ix*.1,oldcenter[1]+iy*.1
            bb=(x+b[0]-.06,y+b[1]-.06,x+b[2]+.06,y+b[3]+.06)
            if max(math.dist((22.999954,-78.999842),(xx,yy)) for xx in (bb[0],bb[2]) for yy in (bb[1],bb[3]))>8.65:continue
            if any(overlap(bb,o,.12) for o in obstacles):continue
            opts.append((math.hypot(ix,iy),x,y,bb))
    if not opts:print('SILK_LABEL_NO_FIT',name,flush=True);continue
    _,x,y,bb=min(opts);placed.append(bb)
    coords=iter(z/U+ORIGIN[k] for q in rel for k,z in enumerate((q[0]+x,q[1]+y)))
    t[11]=NUM.sub(lambda m:f'{next(coords):.8f}',t[11])
    anchor=xy(t[2],t[3]);t[2]=str(((anchor[0]-oldcenter[0])*factor+x)/U+ORIGIN[0]);t[3]=str(((anchor[1]-oldcenter[1])*factor+y)/U+ORIGIN[1])
    t[4]=str(.12/U);t[9]=str(.65/U)
    chunks[j]='~'.join(t);doc['shape'][index]='#@$'.join(chunks)
    log.append([name,'位号中心',[x,y],'字高0.65mm','线宽0.12mm']);print('SILK_LABEL',log[-1],flush=True)
_,np_,nc,nh=parse(doc)
assert c==nc and h==nh and routes(doc)==routes(before),'丝印修改不得改变铜及孔'
save(doc);report=json.loads(REPORT.read_text());report['板边丝印整理']={'日志':log,'仅标记和文档层':True,'原生复查':False};REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print('SILK_ACCEPTED',len(log),flush=True)
