"""在现有 18mm 板内搜索 R10 的可布位置；不改封装尺寸、网络或制造规则。"""
import re,tempfile
from pathlib import Path
from refine_clone_usb_20260928 import *
from build_a5_rf_clearance_layout import ref
from check_pcb_a5 import U,ORIGIN

def pose(s,target,angle):
    chunks=[v.split('~') for v in s.split('#@$')];h=chunks[0]
    cx,cy=map(float,h[1:3]);tx,ty=target[0]/U+ORIGIN[0],target[1]/U+ORIGIN[1]
    th=-angle*math.pi/180;co,si=math.cos(th),math.sin(th)
    def point(x,y):
        dx,dy=float(x)-cx,float(y)-cy
        return f'{tx+co*dx-si*dy:.8f}',f'{ty+si*dx+co*dy:.8f}'
    def pairs(v,comma=False):
        a=re.findall(r'-?\d+(?:\.\d+)?',v);out=[]
        for j in range(0,len(a),2):out+=point(a[j],a[j+1])
        return (',' if comma else ' ').join(out)
    def svg(v):
        assert not re.search('[ACHQSTVachqstv]',v)
        return re.sub(r'(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)',lambda m:' '.join(point(m[1],m[2])),v)
    h[1],h[2]=f'{tx:.8f}',f'{ty:.8f}';h[4]=str((float(h[4] or 0)+angle)%360)
    for v in chunks[1:]:
        k=v[0]
        if k in ('TEXT','PAD'):
            v[2],v[3]=point(v[2],v[3])
            if k=='TEXT':v[5]=str((float(v[5] or 0)+angle)%360);v[11]=svg(v[11])
            else:
                v[10]=pairs(v[10]);v[11]=str((float(v[11] or 0)+angle)%360)
                if len(v)>19 and v[19].strip():v[19]=pairs(v[19],True)
        elif k=='TRACK':v[4]=pairs(v[4])
        elif k=='SOLIDREGION':v[3]=svg(v[3])
        elif k=='CIRCLE':v[1],v[2]=point(v[1],v[2])
        elif k=='SVGNODE':
            n=json.loads(v[1]);a=n['attrs'];a['c_origin']=pairs(a['c_origin'],True)
            rs=a['c_rotation'].split(',');rs[-1]=str((float(rs[-1])+angle)%360);a['c_rotation']=','.join(rs)
            stack=list(n.get('childNodes',[]))
            while stack:
                q=stack.pop();attrs=q.get('attrs',{})
                if 'points' in attrs:attrs['points']=pairs(attrs['points'])
                stack+=q.get('childNodes',[])
            v[1]=json.dumps(n,ensure_ascii=False,separators=(',',':'))
        else:raise AssertionError(k)
    return '#@$'.join('~'.join(v) for v in chunks)

def run():
    configure();batch.STEP=.02
    gold=Path('/var/folders/6b/_qmhvjlj1dj0tqz5lb5pfzf40000gn/T/edausb-signal-ml3za3yg/before.json')
    base=Path('/var/folders/6b/_qmhvjlj1dj0tqz5lb5pfzf40000gn/T/edausb-signal-waumibfv/before.json')
    doc,parts,c,h=parse(gold);original,_,_,_=parse(base)
    r10=next(s for s in original['shape'] if s.startswith('LIB~') and ref(s)=='R10')
    oldground={s for s in original['shape'] if s.startswith(('TRACK~','VIA~')) and s.split('~')[3 if s.startswith('TRACK~') else 4]=='GND'}
    doc['shape']=[s for s in doc['shape'] if not(s.startswith(('TRACK~','VIA~')) and s.split('~')[3 if s.startswith('TRACK~') else 4]=='GND' and PREFIX in s and s not in oldground)]
    candidates=[(24.85,-78.0,90),(24.9,-78.0,90),(25.0,-78.0,90)]
    candidates +=[(float(x),float(y),a) for a in (90,270,0,180) for y in np.arange(-79.3,-72.9,.2) for x in np.arange(22,26,.2)]
    ts,vs,_=routes(doc);others=[p for p in c if p['ref']!='R10']
    def lower(a,b):
        return max(min(x for x,y in a)-max(x for x,y in b),min(x for x,y in b)-max(x for x,y in a),
                   min(y for x,y in a)-max(y for x,y in b),min(y for x,y in b)-max(y for x,y in a),0)
    valid=0
    for x,y,a in candidates:
        candidate=copy.deepcopy(doc);candidate['shape']=[pose(r10,(x,y),a) if s.startswith('LIB~') and ref(s)=='R10' else s for s in doc['shape']]
        _,pa,cc,hh=parse(candidate);pads=[p for p in cc if p['ref']=='R10'];bad=[]
        for p in pads:
            for q in others+vs:
                if not shared_layer(p,q):continue
                gap=max(.1 if q.get('kind')=='pad' else 0,batch.clearance(doc,p['net'],q['net']) if p['net']!=q['net'] else 0)
                if lower(p['poly'],q['poly'])<gap and distance(p['poly'],q['poly'])<gap-1e-5:bad.append('焊盘');break
            if bad:break
            for t in ts:
                if t['layer']!=p['layer'] or t['net']==p['net']:continue
                gap=batch.clearance(doc,p['net'],t['net'])
                if lower(p['poly'],t['points'])<gap+t['width']/2 and track_gap(t,p['poly'])<gap-1e-5:bad.append('导线');break
            if bad:break
            if any(distance(p['poly'],q['poly'])<.2 for q in hh):bad.append('孔');break
            if max(math.dist(v,(22.999954,-78.999842)) for v in p['poly'])>8.69998:bad.append('板边');break
        if bad:continue
        valid+=1;groups=batch.island_contacts(candidate,cc,'U4_C1')
        ga=next(g for g in groups if any(p['id'].startswith('U4.C1:') for p in g));gb=next(g for g in groups if any(p['id'].startswith('R10.1:') for p in g))
        ok,info=batch.route(candidate,cc,hh,'U4_C1',ga,gb,*dimensions(candidate,'U4_C1'))
        print('POSE',x,y,a,ok,info,flush=True)
        if not ok:continue
        issues=local_check(candidate,cc,hh)
        if issues:print('REJECT',issues,flush=True);continue
        assert len(connected_groups(candidate,cc,'U4_C1'))==1
        report=json.loads(REPORT.read_text());report['R10可布位置搜索']={'恢复来源':str(gold),'新中心':[x,y],'相对旋转':a,'路径':info,'通过几何位置数':valid}
        report['移动元件']['R10']=[x,y]
        save(candidate);REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');return
    raise RuntimeError(f'搜索范围内 {valid} 个几何合格位置均未找到路径；未覆盖当前候选')

if __name__=='__main__':run()
