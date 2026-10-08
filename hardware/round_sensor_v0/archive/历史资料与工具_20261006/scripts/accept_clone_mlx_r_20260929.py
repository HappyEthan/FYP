"""纳入R需原生与云端重开一致；严格限制为C2局部调整，不作生产放行。"""
import hashlib,json,math
from collections import Counter
from pathlib import Path
from refine_clone_usb_20260928 import OUT,REPORT,parse,configure,batch,old_losses,save
from audit_clone_native_ground_20260929 import ground_groups
from audit_clone_native_reference_20260929 import audit
from audit_a5_routed_snapshot import routes,track_gap
from check_pcb_a5 import distance,shared_layer,U,xy
from build_a5_rf_clearance_layout import ref

dl=Path(__file__).resolve().parents[1]/'archive/R核验与Q恢复_20260929';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
before=dl/'PCBMLXBeforeR20260929.json';native=dl/'PCBMLXNativeR20260929.json';cloud=OUT.parent/'PCB_克隆板USB局部重布_原生回读_20260929.json'
assert sha(OUT)=='fd437d7144d0d62c58f417e2eb83ab73b594b5009ac53e610eec162274ad2c43'
assert sha(before)=='26cdf1c80dbe3e5bc43660953d9f6fdb41da61ddeb4cee2725395cdcbd236eb8'
assert sha(native)=='aa0227ce2340d43c39341f66b20747049edb6b9e990939ee8f0d5c8269fe8d25'
n=json.loads(native.read_text());b,pb,cb,hb=parse(cloud);a,pa,ca,ha=parse(before)
assert set(n)==set(b) and Counter(n['shape'])==Counter(b['shape'])
assert all(n[k]==b[k] for k in n if k!='shape')
assert len(pb)==43 and set(pa)==set(pb) and a['DRCRULE']==b['DRCRULE']
assert all(pa[k]==pb[k] for k in pa if k!='C2')
assert Counter((x['ref'],x['pin'],x['net']) for x in ca)==Counter((x['ref'],x['pin'],x['net']) for x in cb)
allowed={'ggeUSB0928T'+x for x in ['242','264','343','344','345','346','355']}
def retained(doc):
    out=[]
    for s in doc['shape']:
        f=s.split('~')
        if f[0]=='LIB' and ref(s)=='C2':continue
        if f[0]=='TRACK' and f[5] in allowed:continue
        if f[0]=='VIA' and f[6]=='ggeUSB0928V265':continue
        if f[0]=='COPPERAREA':f[10]=''
        out.append('~'.join(f))
    return Counter(out)
assert retained(a)==retained(b)
at,av,_=routes(a);bt,bv,_=routes(b)
assert len(at)==len(bt) and len(av)==len(bv)
assert {t['id'] for t in bt}=={t['id'] for t in at}
assert {v['id'] for v in bv}=={v['id'] for v in av}
changed=[s for s in b['shape'] if s not in a['shape']]
configure();assert not batch.check_new(b,cb,hb,changed)
for pad in cb:
    if pad['ref']!='C2':continue
    for other in cb+bv:
        if other.get('ref')=='C2' or not shared_layer(pad,other):continue
        assert distance(pad['poly'],other['poly'])>=.15-1e-5
    for t in bt:
        if t['layer']==pad['layer'] and t['net']!=pad['net']:
            assert track_gap(t,pad['poly'])>=batch.clearance(b,t['net'],pad['net'])-1e-5
for net in {x['net'] for x in ca if x['net']}:assert not old_losses(a,ca,b,cb,net)
assert len(ground_groups(b,cb))==1
via=next(s.split('~') for s in b['shape'] if s.startswith('VIA~') and s.split('~')[6]=='ggeUSB0928V265')
drill_gap=min(distance([xy(via[1],via[2])],x['poly'])-float(via[5])*U for x in cb if x['kind']=='pad' and x['layer'] in ('1','2'))
assert drill_gap>.20
rf=audit(cloud)
assert all(v['缺铜数']==0 for net in ['RF_SOC','R30_2'] for v in rf[net]['参考面'].values())
old_usb=json.loads((OUT.parent/'克隆板USB换层回流细查_20260929.json').read_text())
new_usb=json.loads((dl/'PCBMLXNativeR20260929.usb.json').read_text())
assert new_usb['SHA256']==sha(native)
for net,layers in new_usb['网络'].items():
    for layer,entry in layers.items():assert entry['缺铜分类']==old_usb['网络'][net][layer]['缺铜分类']
power=json.loads((dl/'PCBMLXNativeR20260929.power.json').read_text())
assert power['来源SHA256']==sha(native)
paths={tuple(x['端点']):x['路径走线长_mm'] for x in power['路径']}
assert paths[('C2.1','U2.6')]<1.89 and paths[('C2.2','U2.5')]<1.68
save(b);(OUT.parent/'PCB_克隆板USB局部重布_原生回读_20260929.json').write_bytes(cloud.read_bytes())
report={'当前检查点':'R','目标PCB':'PCB_圆形传感板_SCH_A5 copy','文档ID':'cca094630ebf453c98ae64b900f0d7f0',
 '原生SHA256':sha(cloud),'临时原生SHA256':sha(native),'候选SHA256':sha(OUT),'恢复点':str(before),'云端回读':str(cloud),
 '云端已保存重开':True,'云端回读逐字节一致':cloud.read_bytes()==native.read_bytes(),'全部图元多重集合及其他字段一致':True,
 '原生DRC':1,'未连接':0,'剩余DRC':'Q1原厂0.14mm焊盘间距，保留沉金/阻焊/钢网制造待审，不放宽规则',
 'C2中心_mm':pb['C2']['center'],'C2相对旋转_deg':180,'移动已有REG_EN孔_mm':[19.3,-83.55],
 '变更导线':sorted(allowed),'新增器件或过孔':False,'其他元件及规则不变':True,
 'C2供电路径_mm_前后':[3.6782189671,paths[('C2.1','U2.6')]],
 'C2地线路径_mm_前后':[1.1862740329,paths[('C2.2','U2.5')]],
 '长度边界':'相同中心线接触图口径，忽略焊盘/铜环内长及过孔长，未解铺铜并联；地线路径单独变长，总和缩短，非高频去耦性能验收。',
 '移动孔钻边至SMT最小_mm':drill_gap,'实际地网组数':1,'RF参考地缺铜采样':0,'USB细采样分类与Q相同':True,
 '新增云端PCB':False,'原版未修改':True,'允许生产':False,
 '剩余':'USB完整阻抗与过孔过渡、电源热/电流/低电量压差、器件电容偏压、Q1/PICO钢网、最新Gerber制造复审及实物验证。'}
(OUT.parent/'克隆板MLX去耦R云端核验_20260929.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
r=json.loads(REPORT.read_text());r['当前本地检查点']='R';r['当前候选SHA256']=sha(OUT);r['当前云端保存状态']=report;r['MLX去耦R复查']=report
REPORT.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report,ensure_ascii=False,indent=2))
