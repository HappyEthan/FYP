"""Read-only comparison and copper screening of Q1 local trial. Not native DRC."""
from pathlib import Path
import collections, itertools, json, hashlib, sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),'/tmp/round-pcb-audit-libs']
from check_pcb_a5 import parse,xy,U
from shapely.geometry import Polygon,LineString,Point

O=ROOT/'easyeda_std/Q1直接修复_20261006'
src=O/'PCB_Q1修改前_原生回读_20261006.json'
candidate=Path(sys.argv[1]) if len(sys.argv)>1 else O/'PCB_Q1直接修复_孔距收尾_保存重开_20261006.json'
d,parts,c,holes=parse(candidate);old,op,oc,oh=parse(src)
def ident(s):
    f=s.split('~')
    if f[0]=='LIB':return f[6]
    if f[0]=='TRACK':return f[5]
    if f[0]=='VIA':return f[6]
    return s
orig={ident(s):s for s in old['shape']}
new={ident(s):s for s in d['shape']}
changed={k for k,s in new.items() if k not in orig or s!=orig[k]}
changed_refs={r for r in parts if parts[r]!=op[r]}
objs=[]
for a in c:objs.append({'id':a['ref']+'.'+a['pin'],'net':a['net'],'layer':a['layer'],'g':Polygon(a['poly']), 'changed':a['ref'] in changed_refs})
for s in d['shape']:
 f=s.split('~')
 if f[0]=='TRACK':
  a=list(map(float,f[4].split()));ps=[xy(*a[i:i+2]) for i in range(0,len(a),2)]
  objs.append({'id':f[5],'net':f[3],'layer':f[2],'g':LineString(ps).buffer(float(f[1])*U/2,resolution=48),'changed':f[5] in changed})
 if f[0]=='VIA':objs.append({'id':f[6],'net':f[4],'layer':'11','g':Point(xy(f[1],f[2])).buffer(float(f[3])*U/2,resolution=96),'changed':f[6] in changed})
issues=[];closest=[]
def rule(net):
 for k,r in d['DRCRULE'].items():
  if isinstance(r,dict) and net in r.get('nets',[]):return float(r['clearance'])*U
 return float(d['DRCRULE']['Default']['clearance'])*U
for a,b in itertools.combinations(objs,2):
 if a['net']==b['net'] or (a['layer']!=b['layer'] and '11' not in (a['layer'],b['layer'])):continue
 if not (a['changed'] or b['changed']):continue
 gap=a['g'].distance(b['g']);req=max(rule(a['net']),rule(b['net']))
 row=[a['id'],b['id'],round(gap,8),round(req,8),a['net'],b['net'],a['layer'],b['layer']]
 if gap<req-1e-5:issues.append(row)
 if gap<.3:closest.append(row)
hole_issues=[]
for a in objs:
 if not a['changed']:continue
 for h in holes:
  gap=a['g'].distance(Polygon(h['poly']))
  if gap<.19999:hole_issues.append([a['id'],h['ref'],gap])
report={'source':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),
 'candidate':str(candidate),'candidate_sha256':hashlib.sha256(candidate.read_bytes()).hexdigest(),
 'status':'local polygon/round-ended track screening; excludes pours/native DRC/CAM/process/physical proof',
 'changed_refs':sorted(changed_refs),'changed_shape_ids':sorted(changed),'removed_shape_ids':sorted(set(orig)-set(new)),
 'nonshape_changes':[k for k in old if k!='shape' and old[k]!=d[k]],
 'pin_net_signature_unchanged':sorted((p['ref'],p['pin'],p['net']) for p in c)==sorted((p['ref'],p['pin'],p['net']) for p in oc),
 'rules_unchanged':d['DRCRULE']==old['DRCRULE'] and d['routerRule']==old['routerRule'],
 'parts':len(parts),'local_clearance_issues':issues,'nearby_clearances':closest,'hole_issues':hole_issues,
 'Q1_pin_centers_mm':{v[8]:{'net':v[7],'center':xy(v[2],v[3])} for v in parts['Q1']['items'] if v[0]=='PAD'},
 'production_released':False}
(O/'Q1候选几何初筛_仅审核.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:report[k] for k in ['changed_refs','parts','rules_unchanged','pin_net_signature_unchanged','local_clearance_issues','hole_issues','Q1_pin_centers_mm']},ensure_ascii=False,indent=2))
