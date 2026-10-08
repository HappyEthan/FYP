"""核对 SGM40567 第14页圆铜焊盘；原生形状已正确，不修改PCB。"""
from refine_clone_usb_20260928 import *
from build_a5_rf_clearance_layout import ref
from check_pcb_a5 import U
doc,p,c,h=parse(OUT);changed=[]
for i,s in enumerate(doc['shape']):
    if not s.startswith('LIB~') or ref(s)!='U4':continue
    chunks=s.split('#@$')
    for j,ch in enumerate(chunks):
        a=ch.split('~')
        if a[0]!='PAD':continue
        assert a[8] in {'A1','A2','B1','B2','C1','C2'} and a[1] in {'RECT','ELLIPSE'}
        assert abs(float(a[4])*U-.2)<.001 and abs(float(a[5])*U-.2)<.001
        changed.append([a[8],a[1],'ELLIPSE']);a[1]='ELLIPSE';a[10]='';chunks[j]='~'.join(a)
    doc['shape'][i]='#@$'.join(chunks)
assert len(changed)==6
_,np_,nc,nh=parse(doc)
assert {(a['ref'],a['pin'],a['net']) for a in c}=={(a['ref'],a['pin'],a['net']) for a in nc}
assert all(math.dist(batch.center(a),batch.center(b))<1e-4 for a,b in zip(c,nc))
assert not any(old_losses(parse(OUT)[0],c,doc,nc,n) for n in {a['net'] for a in nc if a['net']})
assert all(a[1]=='ELLIPSE' for a in changed),'出现实际形状不符须重新审查，不自动修改'
r=json.loads(REPORT.read_text());r.pop('U4厂家铜形状修正',None);r['U4厂家铜形状核对']={'依据':'references/sgm40567.pdf 第14页 RECOMMENDED LAND PATTERN','推荐铜直径范围_mm':[.19,.21],'既有铜直径_mm':.2,'原生六焊盘原本均为圆形':True,'PCB未修改':True,'更正':'曾从辅助图误判为方形，原生源码已否定该判断；不是封装修复成果','阻焊钢网贴装工艺仍待审核':True}
REPORT.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print('U4_LAND_VERIFIED_NO_CHANGE')
