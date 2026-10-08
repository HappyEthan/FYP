"""纳入已保存重开验证的P线宽候选，不授予USB或制造验收。"""
import hashlib,json
from collections import Counter
from pathlib import Path
from refine_clone_usb_20260928 import OUT,REPORT,parse,configure,batch,old_losses,save,routes
from audit_clone_native_ground_20260929 import ground_groups

downloads=Path('/Users/liuchunyu/Downloads')
source=downloads/'PCBUSBcloudReopenO20260929.json'
native=downloads/'PCBUSBnativeP20260929.json'
cloud=downloads/'PCBUSBcloudReopenP20260929.json'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(OUT)=='c736f670bb61cde7112daceaf40a6f7cc6047f0854b17bc2056adac1787a88a8'
assert sha(native)=='6290d0e973c52c67595c322b69f22d619a93941f7d6f21a56f51854f1904d319'
assert native.read_bytes()==cloud.read_bytes()
a,pa,ca,ha=parse(source);b,pb,cb,hb=parse(native)
assert pa==pb and ca==cb and ha==hb and len(pb)==43 and a['DRCRULE']==b['DRCRULE']
allowed={s.split('~')[5] for s in a['shape'] if s.startswith('TRACK~') and s.split('~')[3].startswith('USB_D')}|{'ggeUSB0928T319'}
assert len(allowed)==13
def retained(d):
    result=[]
    for s in d['shape']:
        f=s.split('~')
        if f[0]=='TRACK' and f[5] in allowed:continue
        if f[0]=='COPPERAREA':f[10]=''
        result.append('~'.join(f))
    return Counter(result)
assert retained(a)==retained(b)
for layer in ['21','22']:
    cache=lambda d:[s.split('~')[10] for s in d['shape'] if s.startswith('COPPERAREA~') and s.split('~')[2]==layer]
    assert cache(a)==cache(b), '内部参考地铜面发生变化'
assert len(ground_groups(b,cb))==1
configure()
changed=[s for s in b['shape'] if s not in a['shape'] and not s.startswith('COPPERAREA~')]
assert len(changed)==13 and not batch.check_new(b,cb,hb,changed)
for net in ['USB_DP','USB_DM','USB_DP_SOC','USB_DM_SOC','GND']:assert not old_losses(a,ca,b,cb,net)
detail=json.loads(native.with_suffix('.reference.json').read_text())
assert detail['SHA256']==sha(native)
for layers in detail['网络'].values():
    for x in layers.values():
        assert not any(k.startswith('中心线/') and k!='中心线/USB信号孔避空' for k in x['缺铜分类'])
ts,vs,_=routes(b)
assert all(abs(t['width']-.17)<.00001 for t in ts if t['net'].startswith('USB_D'))
save(b)
(OUT.parent/'PCB_克隆板USB局部重布_原生回读_20260929.json').write_bytes(cloud.read_bytes())
(OUT.parent/'克隆板USB换层回流细查_20260929.json').write_bytes(native.with_suffix('.reference.json').read_bytes())
r={
    '当前检查点':'P','目标PCB':'PCB_圆形传感板_SCH_A5 copy','文档ID':'cca094630ebf453c98ae64b900f0d7f0',
    '原生SHA256':sha(native),'候选SHA256':sha(OUT),'云端回读':str(cloud),'云端回读逐字节一致':True,
    '云端已保存重开':True,'原版未修改':True,'新增云端PCB':False,'恢复点':str(source),
    '修改图元':sorted(allowed),'USB线宽_mm_前后':[.155,.17],
    'T306局部横向偏移_mm':-.03,'T319短地线宽_mm_前后':[.254,.23],
    '元件过孔位置及规则不变':True,'L2_L3原生铜面缓存逐字节不变':True,
    '原生DRC':1,'未连接':0,'实际地网组数':1,'RF参考地缺铜采样':0,
    '中心线除USB孔避空外缺铜采样':0,
    '邻域采样说明':'线宽变动改变采样位置，分类计数不可直接与O作单调比较；两层内部实际铜面完全相同。剩余孔周过渡仍未验收。',
    '厂家计算器只读核对':{
        '网址':'https://jlcpcb.com/pcb-impedance-calculator','层叠':'JLC04081H-3313',
        '板厚_mm':.8,'外铜_oz':1,'内铜_oz':.5,'介质厚_mm':.0994,
        '模型':'L1参考L2，带阻焊非共面差分，未勾选线宽线距补偿',
        '间距0_645mm_90欧姆推荐线宽_mm':.1826,
        '间距0_645mm_99欧姆推荐线宽_mm':.1501,
        '间距0_345mm_90欧姆推荐线宽_mm':.1717,
        '边界':'以上为原走线两段间距的模型基准，不是当前整条走线计算/仿真，也非国内订单工厂保证；加宽后局部净间距改变，包地/换层/变间距仍须核验',
    },
    'USB完整阻抗验收':False,'制造验收':False,'允许生产':False,
    'Gerber说明':'O包只保留板框诊断用途，不再是当前铜图；P完成后须重新导出整包',
}
(OUT.parent/'克隆板USB线宽P云端核验_20260929.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
d=json.loads(REPORT.read_text());d['当前本地检查点']='P';d['当前候选SHA256']=sha(OUT)
d['当前云端保存状态']=r;d['USB线宽原生P复查']=r
REPORT.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(r,ensure_ascii=False,indent=2))
