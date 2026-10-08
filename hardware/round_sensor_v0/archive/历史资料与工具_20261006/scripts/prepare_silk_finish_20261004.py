"""Source-hash-guarded local silkscreen candidate; never sends to EDA or rewrites live PCB."""
from pathlib import Path
import sys,json,re,ast,math,zipfile,hashlib
R=Path(__file__).resolve().parents[1];sys.path[:0]=[str(R/'scripts'),'/tmp/round-pcb-audit-libs']
from shapely.geometry import Polygon,Point,LineString,GeometryCollection
from shapely.ops import unary_union
from shapely.validation import make_valid
from check_pcb_a5 import xy,parse
from audit_current_cam import layer
tr=ast.parse((R/'manufacturing/仅审核禁止生产/整板复审_20261004/independent_manufacturing_geometry.py').read_text());exec(compile(ast.Module(body=[n for n in tr.body if isinstance(n,ast.FunctionDef) and n.name in {'geom','merge'}],type_ignores=[]),'<helpers>','exec'))
P=R/'easyeda_std/丝印终检_20261004/PCB_silk_start_20261004.json';assert hashlib.sha256(P.read_bytes()).hexdigest()=='6d7f2ef3b6c2fd0a855bf306228b3910b1ea2db61e71e96b654f64663709052e'
d=json.loads(P.read_text());changes=[]
with zipfile.ZipFile(R/'manufacturing/仅审核禁止生产/同步与制造收尾_20261004/Gerber_制造收尾R2_仅审核_20261004.zip') as z:
 masks={s:merge(layer(z.read(n).decode())) for s,n in [('3','Gerber_TopSolderMaskLayer.GTS'),('4','Gerber_BottomSolderMaskLayer.GBS')]}
def fmt(x):return f'{x:.8f}'.rstrip('0').rstrip('.')
def transpath(path,dx,dy):
 toks=re.findall(r'[A-Za-z]|[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?',path);out=[];j=0;cmd='';k=0
 for tok in toks:
  if tok.isalpha():cmd=tok;k=0;out.append(tok);continue
  offset=(dx if k%2==0 else dy) if cmd in 'MLC' else (dx if k==5 else dy if k==6 else 0)
  out.append(fmt(float(tok)+offset));k+=1
 return ' '.join(out)
def textgeom(v):
 toks=re.findall(r'[A-Za-z]|[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?',v[11]);i=0;pts=[];rings=[]
 while i<len(toks):
  c=toks[i];i+=1
  if c in ['M','L']:
   p=xy(toks[i],toks[i+1]);i+=2
   if c=='M' and pts:rings.append(pts);pts=[]
   pts.append(p)
  elif c=='C':
   a=pts[-1];b=xy(*toks[i:i+2]);cc=xy(*toks[i+2:i+4]);dd=xy(*toks[i+4:i+6]);i+=6
   for n in range(1,33):
    t=n/32;pts.append(tuple((1-t)**3*a[j]+3*(1-t)**2*t*b[j]+3*(1-t)*t*t*cc[j]+t**3*dd[j] for j in range(2)))
  elif c=='Z':
   if pts:rings.append(pts);pts=[]
  else:raise ValueError(c)
 if pts:rings.append(pts)
 if 'Z' in toks:
  g=GeometryCollection()
  for ring in rings:g=g.symmetric_difference(make_valid(Polygon(ring)))
  return g
 return unary_union([LineString(p).buffer(float(v[4])*.254/2) for p in rings])
for ii,s in enumerate(d['shape']):
 if not s.startswith('LIB~'):continue
 items=[q.split('~') for q in s.split('#@$')];ref=next(q[10] for q in items if q[:2]==['TEXT','P']);new=[items[0]]
 for v in items[1:]:
  old=v.copy();k=v[0]
  if ref in {'SW3','U1'} and k=='TEXT' and v[1]=='P':
   dx=(-.8 if ref=='SW3' else -.1)/.254;dy=(.06 if ref=='SW3' else 0)/.254;v[2]=fmt(float(v[2])+dx);v[3]=fmt(float(v[3])+dy);v[11]=transpath(v[11],dx,dy)
  if ref in {'U1','U3','U5'} and k=='CIRCLE' and v[5] in ['3','4']:
   dx,dy={'U1':(-.1,0),'U3':(.175,.475),'U5':(.5,.85)}[ref]
   v[1]=fmt(float(v[1])+dx/.254);v[2]=fmt(float(v[2])+dy/.254)
  if ref=='SW1' and k=='ARC' and v[2]=='4':
   v[2]='12'; new.append(v);new.append(['CIRCLE',fmt(4020+17.15/.254),fmt(3404-84.8/.254),fmt(.0625/.254),fmt(.125/.254),'4','ggeSW1PIN1silk20261004','0','','']);changes.append({'ref':ref,'id':v[6],'action':'original ARC to Document; new 0.25 mm pin-1 dot outside pad at (17.15,-84.8)'});continue
  if k=='TRACK' and v[2] in masks:
   coords=list(map(float,v[4].split()));line=LineString([xy(*coords[n:n+2]) for n in range(0,len(coords),2)])
   cut=line.difference(masks[v[2]].buffer(.16+float(v[1])*.254/2,quad_segs=128))
   if not cut.equals(line):
    original=v.copy();original[2]='12';new.append(original)
    segs=list(cut.geoms) if hasattr(cut,'geoms') else [cut]
    kept=[]
    for j,g in enumerate(segs):
     if g.is_empty or g.length<.15:continue
     vv=v.copy();vv[4]=' '.join(fmt(p[axis]/.254+(4020 if axis==0 else 3404)) for p in g.coords for axis in (0,1));vv[5]=v[5]+'_silk_'+str(j);new.append(vv);kept.append(vv[5])
    changes.append({'ref':ref,'id':v[5],'action':'original to Document; retain clipped silk segments','new_ids':kept});continue
  if old!=v:changes.append({'ref':ref,'id':v[13] if k=='TEXT' else v[6],'action':'translate silk marker only','before':old[:11],'after':v[:11]})
  new.append(v)
 d['shape'][ii]='#@$'.join('~'.join(v) for v in new)
issues=[]
for s in d['shape']:
 if not s.startswith('LIB~'):continue
 vs=[v.split('~') for v in s.split('#@$')];ref=next(v[10] for v in vs if v[:2]==['TEXT','P'])
 for v in vs[1:]:
  k=v[0];li={'TEXT':7,'TRACK':2,'ARC':2,'CIRCLE':5}.get(k)
  if li is None or v[li] not in masks or (k=='TEXT' and v[12]=='none'):continue
  if k=='TEXT':g=textgeom(v)
  elif k=='TRACK':co=list(map(float,v[4].split()));g=LineString([xy(*co[n:n+2]) for n in range(0,len(co),2)]).buffer(float(v[1])*.254/2)
  elif k=='CIRCLE':g=Point(xy(v[1],v[2])).buffer((float(v[3])+float(v[4])/2)*.254)
  else:continue # native CAM will validate moved SW1 arc
  dist=g.distance(masks[v[li]])
  if dist<.15:issues.append({'ref':ref,'id':v[13] if k=='TEXT' else v[5] if k=='TRACK' else v[6],'clearance':dist,'bounds':g.bounds})
P.with_name('PCB_silk_candidate_20261004.json').write_text(json.dumps(d,ensure_ascii=False,separators=(',',':')))
P.with_name('丝印候选差异.json').write_text(json.dumps({'changes':changes,'remaining_source_screening':issues},ensure_ascii=False,indent=2))
print(json.dumps({'changes':len(changes),'issues':issues},ensure_ascii=False,indent=2))
