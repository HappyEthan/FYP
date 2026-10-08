"""读取原生铺铜缓存并定位尚未并入主地网的离散连接组。仅辅助原生 DRC。"""
import json,re,sys
from pathlib import Path
import numpy as np
from matplotlib.path import Path as PlotPath
from refine_clone_usb_20260928 import *
from check_pcb_a5 import xy

def regions(doc):
    result=[]
    for s in doc['shape']:
        a=s.split('~')
        if a[0]!='COPPERAREA' or a[3]!='GND' or not a[10]:continue
        for group in json.loads(a[10]):
            for svg in group:
                rings=[]
                for sub in re.split('[Mm]',svg):
                    if not sub.strip():continue
                    assert not re.search('[ACHQSTVachqstv]',sub)
                    nums=list(map(float,re.findall(r'-?\d+(?:\.\d+)?',sub)))
                    rings.append(PlotPath([xy(*nums[i:i+2]) for i in range(0,len(nums),2)]))
                result.append((a[2],rings))
    return result

def contains(rings,points):
    flags=np.zeros(len(points),bool)
    if not len(points):return flags
    for r in rings:flags^=r.contains_points(points)
    return flags

def ground_groups(doc,c):
    groups=batch.island_contacts(doc,c,'GND');rs=regions(doc)
    parent=list(range(len(groups)+len(rs)))
    def root(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    def union(i,j):parent[root(i)]=root(j)
    # 组内通过孔跨层；铺铜轮廓逐区作为附加节点。
    for i,g in enumerate(groups):
        via_points=[]
        ids={}
        for p in g:ids.setdefault(p['id'].rsplit(':',1)[0],[]).append(p)
        for ps in ids.values():
            if len({p['layer'] for p in ps})>1:via_points.append(batch.center(ps[0]))
        for j,(layer,rings) in enumerate(rs):
            points=[batch.center(p) for p in g if p['layer']==layer]+via_points
            if points and np.any(contains(rings,points)):union(i,len(groups)+j)
    merged={}
    for i,g in enumerate(groups):merged.setdefault(root(i),[]).extend(g)
    return list(merged.values())

if __name__=='__main__':
    d,p,c,h=parse(Path(sys.argv[1]));gs=ground_groups(d,c)
    print('地网组数',len(gs))
    for g in gs:print(sorted({a['id'].split(':')[0] for a in g if not a['id'].startswith('gge')}))
