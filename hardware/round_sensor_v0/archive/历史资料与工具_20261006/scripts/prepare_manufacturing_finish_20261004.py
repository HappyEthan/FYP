"""Local partial candidate only; hash-gated; does not modify live EDA or run native checks."""
from pathlib import Path
import json,hashlib,copy,sys,ast,zipfile
from collections import Counter
r=Path('hardware/round_sensor_v0');sys.path.insert(0,str(r/'scripts'));sys.path.insert(0,'/tmp/round-pcb-audit-libs')
from check_pcb_a5 import parse
from audit_current_cam import layer
from shapely.geometry import Polygon,Point,LineString,GeometryCollection
from shapely.ops import unary_union
from shapely.validation import make_valid
import math
# Load pure geometry functions only; never execute prior audit's top-level work.
t=ast.parse((r/'manufacturing/仅审核禁止生产/整板复审_20261004/independent_manufacturing_geometry.py').read_text());functions=[n for n in t.body if isinstance(n,ast.FunctionDef) and n.name in {'geom','merge'}];exec(compile(ast.Module(body=functions,type_ignores=[]),'<read-only geometry helpers>','exec'))
p=r/'easyeda_std/云端同步_20261004/PCB_independent_cloud_read_20261004.json';assert hashlib.sha256(p.read_bytes()).hexdigest()=='968381becf6f02d16998d06b140e89a698ae9267d8f2ddba1e11730a8d5ffe89'
a,parts,pads,_=parse(p);b=copy.deepcopy(a);log=[]
# Use actual current Gerber mask geometry, including openings from the opposite-side connector.
g=r/'manufacturing/仅审核禁止生产/按键收拢_20261004/Gerber_按键收拢_仅审核_20261004.zip'
with zipfile.ZipFile(g) as z:masks={side:merge(layer(z.read(n).decode())) for side,n in [('3','Gerber_TopSolderMaskLayer.GTS'),('4','Gerber_BottomSolderMaskLayer.GBS')]}
for i,s in enumerate(a['shape']):
 if not s.startswith('LIB~'):continue
 chunks=s.split('#@$'); ref=next(q.split('~')[10] for q in chunks if q.startswith('TEXT~P~'))
 for j,q in enumerate(chunks[1:],1):
  v=q.split('~')
  if v[0]=='PAD' and ref in {'C30','C31'}:
   log.append({'ref':ref,'pin':v[8],'change':'paste_expansion_only','before':v[17],'after':'-11.811024'});v[17]='-11.811024';chunks[j]='~'.join(v)
  elif ref.startswith(('R','C')) and v[0]=='TRACK' and v[2] in masks:
   nums=list(map(float,v[4].split()));pts=[((x-4020)*.254,(y-3404)*.254) for x,y in zip(nums[::2],nums[1::2])];geomline=LineString(pts).buffer(float(v[1])*.254/2)
   if geomline.distance(masks[v[2]])<.15:
    log.append({'ref':ref,'shape_id':v[5],'change':'RC_silk_to_document','original_layer':v[2],'mask_distance_mm':geomline.distance(masks[v[2]])});v[2]='12';chunks[j]='~'.join(v)
 b['shape'][i]='#@$'.join(chunks)
# Strict delta scope: metadata, models, copper, geometry, all board-level shapes remain identical.
assert {k:v for k,v in a.items() if k!='shape'}=={k:v for k,v in b.items() if k!='shape'}
_,pb,pp,_=parse(b)
assert pads==pp
assert Counter(s for s in a['shape'] if not s.startswith('LIB~'))==Counter(s for s in b['shape'] if not s.startswith('LIB~'))
assert len([x for x in log if x['change']=='paste_expansion_only'])==4
out=r/'easyeda_std/制造收尾_20261004';out.mkdir(exist_ok=True)
path=out/'PCB_阻容外框与DNP钢网_局部候选_未原生验证.json';path.write_text(json.dumps(b,ensure_ascii=False,separators=(',',':')))
e={'status':'仅本地部分收尾候选；未写回EDA、未原生DRC、未导出候选Gerber。不是当前工作板。','input':str(p),'input_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'candidate_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'changes':log,'all_copper_geometry_equal':True,'board_shapes_and_rules_equal':True,'remaining':'芯片/二极管/接口丝印和0.15mm间距仍须继续处理；候选已基于独立云端最新源，保留SW3新备注；原生验证后方可纳入。'}
(out/'局部候选差异_仅审核.json').write_text(json.dumps(e,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'candidate':str(path),'DNP_pad_count':4,'RC_shapes_to_document':len(log)-4,'refs':sorted({x['ref'] for x in log})},ensure_ascii=False))
