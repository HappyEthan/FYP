"""核对S原生/云端/实际钻孔差异；所有检查通过也不构成生产放行。"""
import hashlib
import json
import math
import re
import zipfile
from collections import Counter

from check_pcb_a5 import ROOT, parse
from repair_clone_ground_spacing_s_20260929 import SOURCE, ARCHIVE, via_gaps
from refine_clone_usb_20260928 import configure, batch, old_losses
from audit_clone_native_ground_20260929 import ground_groups

CLOUD = ROOT/'easyeda_std/PCB_克隆板GND孔距修正_云端回读_20260929.json'
NATIVE = ARCHIVE/'PCB_GND孔距S_原生验证_20260929.json'
SZIP = ROOT/'manufacturing/仅审核禁止生产/Gerber_圆形传感板_S_仅审核禁止生产_20260929.zip'
RZIP = ROOT/'manufacturing/仅审核禁止生产/Gerber_圆形传感板_R_仅审核禁止生产_20260929.zip'
sha = lambda p:hashlib.sha256(p.read_bytes()).hexdigest()


def normalize(raw):
    """去导出注释与未使用光圈，并以光圈参数代替随机光圈编号。"""
    ls=raw.decode().splitlines()
    aps={m[1]:m[2] for l in ls if (m:=re.fullmatch(r'%ADD(\d+)(.*)\*%',l))}
    result=[]
    for line in ls:
        if line.startswith(('G04',';','%ADD')):continue
        m=re.fullmatch(r'D(\d+)\*',line)
        result.append('APERTURE '+aps[m[1]] if m else line)
    return result


def main():
    assert sha(CLOUD)=='44068c11869d448597dd402fda149b6a929255ddf088eb1769f0a28e4298a0c4'
    assert sha(NATIVE)=='6c30a992fd0aa660e53f93350b9232da0d8e2921dc1b11f670c9be05f080c839'
    assert sha(SZIP)=='38efca8874731fa7c59af042fbb8200ef5a4931908754dd07d695cfb3cc2126d'
    a,pa,ca,ha=parse(SOURCE); b,pb,cb,hb=parse(CLOUD); n=json.loads(NATIVE.read_text())
    assert Counter(n['shape'])==Counter(b['shape'])
    assert all(n[k]==b[k] for k in n if k!='shape')
    removed=list((Counter(a['shape'])-Counter(b['shape'])).elements())
    added=list((Counter(b['shape'])-Counter(a['shape'])).elements())
    assert len(removed)==len(added)==2
    assert {s.split('~')[0] for s in added}=={'TRACK','VIA'}
    assert all(('~ggeUSB0928V313~' in s or '~ggeUSB0928T333~' in s) for s in added+removed)
    assert all(a[k]==b[k] for k in a if k!='shape')
    assert pa==pb and ca==cb and ha==hb and len(pb)==43
    configure(); assert not batch.check_new(b,cb,hb,added)
    assert all(not old_losses(a,ca,b,cb,net) for net in {x['net'] for x in ca} if net)
    assert len(ground_groups(b,cb))==1
    gaps=via_gaps(b);assert gaps[0][0]>.2
    # 源中的三层铺铜缓存均字节不变，信号线/孔也不变，保留R既有参考地结论及未验收项。
    assert [s for s in a['shape'] if s.startswith('COPPERAREA~')]==[s for s in b['shape'] if s.startswith('COPPERAREA~')]
    with zipfile.ZipFile(RZIP) as old,zipfile.ZipFile(SZIP) as new:
        assert old.namelist()==new.namelist()
        change={}
        for name in old.namelist():
            x,y=normalize(old.read(name)),normalize(new.read(name))
            if x==y:continue
            # 只允许本次孔坐标及T333端点的预期变动。
            mapping={'X018713Y086163':'X018793Y086163',
                     'X1871319Y8616314D03*':'X1879320Y8616314D03*',
                     'X1871324Y8616325D01*':'X1879320Y8616314D01*'}
            assert [mapping.get(l,l) for l in x]==y,name
            change[name]=sum(u!=v for u,v in zip(x,y))
        text=new.read('Drill_PTH_Through_Via.DRL').decode()
    assert 'METRIC,LZ,000.000' in text
    tools={};holes=[];active=None
    for line in text.splitlines():
        m=re.fullmatch(r'T(\d+)C([\d.]+)',line)
        if m:tools[m[1]]=float(m[2]);continue
        m=re.fullmatch(r'T(\d+)',line)
        if m:active=tools[m[1]];continue
        m=re.fullmatch(r'X(-?\d+)Y(-?\d+)',line)
        if m:assert active;holes.append(((int(m[1])/1000,-int(m[2])/1000),active))
    pairs=sorted((math.dist(a[0],b[0])-(a[1]+b[1])/2,a,b)
                 for i,a in enumerate(holes) for b in holes[:i])
    assert len(holes)==83 and pairs[0][0]>=.2
    report={'当前检查点':'S','目标文档':'PCB_圆形传感板_SCH_A5 copy',
            '文档ID':'cca094630ebf453c98ae64b900f0d7f0','云端已保存关闭重开':True,
            '源SHA256':sha(SOURCE),'原生临时SHA256':sha(NATIVE),'云端重开SHA256':sha(CLOUD),
            'GerberSHA256':sha(SZIP),'仅变化图元':added,'元件数':43,'网络数':21,
            '原生DRC_现场观察':1,'未连接_现场观察':0,'剩余DRC':'Q1原厂焊盘0.14/0.15mm，沉金及装配仍待工厂审核',
            '地网连通组':1,'元件规则_USB_RF_铺铜缓存不变':True,
            '实际Gerber过孔数':len(holes),'实际Gerber孔对数':len(pairs),
            '实际Gerber最小孔边距_mm':pairs[0],'原问题孔修正后孔边距_mm':pairs[1],
            '归一化Gerber差异':change,'阻焊_钢网_丝印_板框有效输出不变':True,
            '新增云端PCB':False,'允许生产':False,
            '检查边界':'仅核对本轮局部变化与83个过孔孔距；连接器槽孔、公差、阻抗、盘中孔、钢网和工厂审核另列。'}
    out=ROOT/'easyeda_std/克隆板GND孔距S云端与制造核验_20260929.json'
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
