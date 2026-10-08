"""批量补线的独立几何、连通和原生回读核验；不代替制造审核。"""
import collections
import hashlib
import json
import math
import re
import sys
from pathlib import Path
import numpy as np
from matplotlib.path import Path as PlotPath
from check_pcb_a5 import parse,xy,ROOT
from audit_a5_routed_snapshot import routes
from test_a5_usb_soc_fanout import connected_groups
import repair_clone_rf_20260928 as rf
import repair_clone_batch_20260928 as batch

def verify(path,native=False):
    source,_,_,_=parse(batch.SOURCE)
    expected,_,_,_=parse(batch.OUT)
    actual,parts,copper,holes=parse(path)
    rf.SOURCE=batch.SOURCE;rf.PREFIX=batch.PREFIX
    result=rf.check(source,actual,copper,holes)
    assert not result['冲突'],result['冲突']
    for typ in ('LIB~','CIRCLE~','SOLIDREGION~'):
        assert [s for s in source['shape'] if s.startswith(typ)]==[s for s in actual['shape'] if s.startswith(typ)]
    assert source['DRCRULE']==actual['DRCRULE']
    # 编辑器会把坐标序列化为四位小数；比较实际几何，不比较小数尾零。
    for es,aas in zip(routes(expected)[:2],routes(actual)[:2]):
        e={x['id']:x for x in es};a={x['id']:x for x in aas}
        assert e.keys()==a.keys(),'原生图元增减'
        for key,p in e.items():
            q=a[key];field='points' if 'points' in p else 'poly'
            assert (p['net'],p['layer'])==(q['net'],q['layer'])
            assert len(p[field])==len(q[field])
            assert max(math.dist(x,y) for x,y in zip(p[field],q[field]))<.0002,(key,'原生几何变化')
            if 'width' in p:assert abs(p['width']-q['width'])<.000001
    nets=sorted({p['net'] for p in copper if p['net']})
    # 复用几何引擎，不复用上一轮的状态及待办文字。
    geometry={k:result[k] for k in ('冲突','最小间距项','射频长度_mm','新增过孔数','元件及规则保持')}
    result={'来源SHA256':hashlib.sha256(batch.SOURCE.read_bytes()).hexdigest(),'回读SHA256':hashlib.sha256(path.read_bytes()).hexdigest(),'几何检查':geometry,'端点连通组':{n:[len(connected_groups(source,copper,n)),len(connected_groups(actual,copper,n))] for n in nets},'元件数':len(parts),'原生回读':native,'云端保存':False,'制造放行':False}
    if native:
        ca=next(s.split('~') for s in actual['shape'] if s.startswith('COPPERAREA~'))
        assert ca[2:4]==['21','GND'] and ca[10]
        rings=[]
        for group in json.loads(ca[10]):
            for svg in group:
                for sub in re.split('[Mm]',svg):
                    if not sub.strip():continue
                    assert not re.search('[ACHQSTVachqstv]',sub)
                    nums=list(map(float,re.findall(r'-?\d+(?:\.\d+)?',sub)))
                    rings.append(PlotPath([xy(*nums[i:i+2]) for i in range(0,len(nums),2)]))
        def at(points):
            ret=np.zeros(len(points),bool)
            for ring in rings:ret ^= ring.contains_points(points)
            return ret
        ts,vs,_=routes(actual);bad=[]
        sp=PlotPath(next(p['poly'] for p in copper if p['ref']=='ANT1' and p['pin']=='1'))
        for t in ts:
            if t['net'] not in ('RF_SOC','R30_2'):continue
            ps=[];radius=t['width']/2+.2982
            for a,b in zip(t['points'],t['points'][1:]):
                for f in np.linspace(0,1,max(2,math.ceil(math.dist(a,b)/.02))):
                    p=(a[0]+f*(b[0]-a[0]),a[1]+f*(b[1]-a[1]))
                    if sp.contains_point(p):continue
                    ps.append(p);ps.extend((p[0]+radius*math.cos(x),p[1]+radius*math.sin(x)) for x in np.linspace(0,2*math.pi,24,endpoint=False))
            if not np.all(at(ps)):bad.append([t['id'],'射频参考地缺铜'])
        counts={'接地孔':0,'非地孔':0}
        for v in vs+[p for p in copper if p['kind']=='via']:
            p=np.mean(v['poly'],axis=0)
            if v['net']=='GND':
                counts['接地孔']+=1
                if not np.all(at([p.tolist()]+v['poly'])):bad.append([v.get('id',v.get('pin')),'地孔未覆盖'])
            else:
                counts['非地孔']+=1;r=max(math.dist(p,q) for q in v['poly'])+.199
                ps=[p.tolist()]+[(p[0]+r*math.cos(x),p[1]+r*math.sin(x)) for x in np.linspace(0,2*math.pi,96,endpoint=False)]
                if np.any(at(ps)):bad.append([v['id'],'非地孔隔离不足'])
        result['实际地铜检查']={'异常':bad,**counts}
        assert not bad,bad
    name='克隆板批量原生核验_20260928.json' if native else '克隆板批量独立核验_20260928.json'
    (ROOT/'easyeda_std'/name).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='几何检查'},ensure_ascii=False,indent=2))
    return result

if __name__=='__main__':verify(Path(sys.argv[1]),'--native' in sys.argv)
