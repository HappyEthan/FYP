"""仅在原生Q与云端重开全字段/图元多重集合一致后纳入，允许图元排列顺序变化。"""
import hashlib
import json
from collections import Counter
from pathlib import Path
from refine_clone_usb_20260928 import OUT, REPORT, parse, configure, batch, old_losses, save
from audit_clone_native_ground_20260929 import ground_groups

dl=Path('/Users/liuchunyu/Downloads')
before=dl/'PCBpowerBeforeQ20260929.json'
native=dl/'PCBpowerNativeQ20260929.json'
cloud=dl/'PCBpowerCloudReopenQ20260929.json'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(OUT)=='77e777ab4af512d65fde15a467e3468f13170183ebcb193a8d6ba9216485d54c'
assert sha(before)=='6290d0e973c52c67595c322b69f22d619a93941f7d6f21a56f51854f1904d319'
assert sha(native)=='334b0774b72335aed7885bfd4ab59ea9f3d8cd8f86b2c6c39c0d212d78b081c4'
native_data=json.loads(native.read_text());cloud_data=json.loads(cloud.read_text())
assert set(native_data)==set(cloud_data)
assert Counter(native_data['shape'])==Counter(cloud_data['shape'])
assert all(native_data[k]==cloud_data[k] for k in native_data if k!='shape')
a,pa,ca,ha=parse(before);b,pb,cb,hb=parse(cloud)
assert pa==pb and ca==cb and ha==hb and len(pb)==43 and a['DRCRULE']==b['DRCRULE']
def retained(doc):
    out=[]
    for s in doc['shape']:
        f=s.split('~')
        if f[0]=='TRACK' and f[5]=='ggeLDO0929Qshort':continue
        if f[0]=='COPPERAREA':f[10]=''
        out.append('~'.join(f))
    return Counter(out)
assert retained(a)==retained(b)
added=[s for s in b['shape'] if s.startswith('TRACK~') and s not in a['shape']]
assert len(added)==1 and added[0].split('~')[5]=='ggeLDO0929Qshort'
for layer in ['21','22']:
    assert [s for s in a['shape'] if s.startswith('COPPERAREA~') and s.split('~')[2]==layer]==[s for s in b['shape'] if s.startswith('COPPERAREA~') and s.split('~')[2]==layer]
configure();assert not batch.check_new(b,cb,hb,added)
for n in {v['net'] for v in ca if v['net']}:assert not old_losses(a,ca,b,cb,n)
assert len(ground_groups(b,cb))==1
detail=json.loads((dl/'PCBpowerNativeQ20260929.usb.json').read_text())
assert detail['SHA256']==sha(native)
for layers in detail['网络'].values():
    for x in layers.values():
        assert not any(k.startswith('中心线/') and k!='中心线/USB信号孔避空' for k in x['缺铜分类'])
save(b)
(OUT.parent/'PCB_克隆板USB局部重布_原生回读_20260929.json').write_bytes(cloud.read_bytes())
report={
 '当前检查点':'Q','目标PCB':'PCB_圆形传感板_SCH_A5 copy','文档ID':'cca094630ebf453c98ae64b900f0d7f0',
 '原生SHA256':sha(cloud),'临时原生SHA256':sha(native),'候选SHA256':sha(OUT),'恢复点':str(before),'云端回读':str(cloud),
 '云端已保存重开':True,'云端回读逐字节一致':False,'全部图元多重集合及其他字段一致':True,
 '字节差异说明':'云端回读仅shape列表排列顺序改变，无图元增加删除或字段变化；当前规范源采用云端原始字节。',
 '原生DRC':1,'未连接':0,'剩余DRC':'仅Q1原厂0.14mm焊盘间距，沉金及钢网仍待正式制造审核',
 '新增导线':added[0],'线宽_mm':.1500124,'C10到U5输出的路径走线长度_mm_前后':[5.3023433974,1.6843592686],
 '长度边界':'按同一中心线接触图计算，忽略焊盘/铜环内部长度与过孔长度；新增导线本身1.68436mm，无换层。',
 '旧供电分支保留':True,'元件焊盘过孔规则及USB_RF导线不变':True,'L2_L3铜缓存逐字节不变':True,
 '实际地网组数':1,'RF参考地缺铜采样':0,'USB中心线除自身孔避空外缺铜采样':0,
 '新增云端PCB':False,'原版未修改':True,'允许生产':False,
 '剩余':'MLX去耦局部布局、USB完整阻抗/过孔过渡、电源电流/热/低电量压差、Q1及PICO钢网、整包Gerber制造复审。',
 '原厂布局依据':'https://www.ti.com/lit/ds/symlink/tlv755p.pdf 7.4.1',
}
(OUT.parent/'克隆板C10短接Q云端核验_20260929.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
r=json.loads(REPORT.read_text());r['当前本地检查点']='Q';r['当前候选SHA256']=sha(OUT);r['当前云端保存状态']=report;r['C10输出电容Q复查']=report
REPORT.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report,ensure_ascii=False,indent=2))
