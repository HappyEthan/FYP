"""Hash-guarded local Q1 trial. Does not write to the live editor or run generators."""
from pathlib import Path
import ast, copy, hashlib, json, re, sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'easyeda_std/Q1直接修复_20261006'
SOURCE = OUT / 'PCB_Q1修改前_原生回读_20261006.json'
assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == '104338789cb0e09d8fe32ea936048fd769a2379924382ee0988ad800f5a0006b'
sys.path.insert(0, str(ROOT / 'scripts'))
from check_pcb_a5 import parse, U

def fmt(x): return f'{x:.8f}'.rstrip('0').rstrip('.')
def pairs(s, dx, dy, comma=False):
    a = list(map(float, re.split('[, ]+', s.strip())))
    return (',' if comma else ' ').join(fmt(v + (dx if i % 2 == 0 else dy)) for i,v in enumerate(a))

# Reuse only the three pure translation functions, not a historical generator's module body.
tree = ast.parse((ROOT/'scripts/build_a5_usb_zone_placement.py').read_text())
exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in
    {'svg_translate','node_translate','shift_lib_safe'}], type_ignores=[]), '<pure_translation>', 'exec'))

def attrs(s):
    a = s.split('`'); return dict(zip(a[::2],a[1::2]))
def attrtext(a): return '`'.join(v for item in a.items() for v in item)
def ref(s): return next(v.split('~')[10] for v in s.split('#@$') if v.startswith('TEXT~P~'))
def save(name, d): (OUT/name).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')

d = json.loads(SOURCE.read_text()); before = copy.deepcopy(d)
stock = json.loads((OUT/'PCBLIB_DMP2165UW_SOT323_原生库_20261006.json').read_text())
fp = copy.deepcopy(stock)
PKG = 'DMP2165UW_SOT323_DGS_A5_MFR_LAND_20261006'
UUID = 'fd84b44fef3a4d2db3ea2c93f75c3265'
fp['head']['uuid'] = UUID
fp['head']['c_para']['package'] = PKG
fp['head']['c_para']['Contributor'] = 'eda_htyqpfoe; land from Diodes DMP2165UW; model from JLCEDA/EasyEDA Official Library'
fp['head']['c_para']['link'] = 'https://www.diodes.com/datasheet/download/DMP2165UW.pdf'
fp['head']['c_para']['说明'] = 'A5专用编号1=D(BAT_P),2=G(USB_5V),3=S(VSYS)；原厂物理编号D=3,G=1,S=2。原厂推荐盘0.60x0.47mm，左右中心距1.90mm，同侧节距1.30mm。'
# Canonical top-view footprint: D left, G lower right, S upper right.
# Keep stock 3D and lead/body outlines; replace the generic larger solder lands.
pin_map = {'3': ('1', -.95, 0), '1': ('2', .95, .65), '2': ('3', .95, -.65)}
for i,s in enumerate(fp['shape']):
    v = s.split('~')
    if v[0] in {'TRACK','ARC'} and v[2]=='3':
        v[2]='12'; fp['shape'][i]='~'.join(v)
    if v[0] != 'PAD': continue
    pin, dx, dy = pin_map[v[8]]
    x,y = 404+dx/U, 300+dy/U
    v[2:6] = [fmt(x),fmt(y),fmt(.60/U),fmt(.47/U)]
    v[8],v[11] = pin,'0'
    v[10] = ' '.join(fmt(q) for p in [(x-.30/U,y-.235/U),(x+.30/U,y-.235/U),
        (x+.30/U,y+.235/U),(x-.30/U,y+.235/U)] for q in p)
    v[17],v[18],v[19] = '0','0',f'{fmt(x)},{fmt(y)}'
    fp['shape'][i] = '~'.join(v)
save('PCBLIB_Q1_DMP2165UW_原厂盘_自定义DGS_候选.json',fp)

oldq = next(s for s in d['shape'] if s.startswith('LIB~') and ref(s)=='Q1')
old_h = oldq.split('#@$')[0].split('~'); h = old_h.copy()
target = (25.9,-74.5); h[1],h[2] = fmt(4020+target[0]/U),fmt(3404+target[1]/U)
a = attrs(h[3]); a.update({'package':PKG,'Value':'DMP2165UW-7','Manufacturer Part':'DMP2165UW-7',
    'Manufacturer':'DIODES','Supplier':'LCSC','Supplier Part':'C388477','JLCPCB Part Class':'Extended Part',
    'Package candidate':'SOT-323 / max body 2.20x1.35 mm / max height 1.10 mm',
    '说明':fp['head']['c_para']['说明'],'link':fp['head']['c_para']['link'],
    '3DModel':fp['head']['c_para']['3DModel'],
    '审查备注':'1=D接BAT_P,2=G接USB_5V,3=S接VSYS；原厂脚3=D,1=G,2=S；体二极管BAT_P至VSYS。当前官网及2025选型册ESD=Y。'})
h[3],h[4],h[8],h[9] = attrtext(a),'180',UUID,fp['head']['utime'].__str__()
def mirror_pairs(s, comma=False):
    a=list(map(float,re.split('[, ]+',s.strip())))
    return (',' if comma else ' ').join(fmt(v if i%2==0 else 600-v) for i,v in enumerate(a))
def mirror_path(s):
    tokens=re.findall(r'[A-Za-z]|[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?',s);out=[];i=0
    counts={'M':2,'L':2,'C':6,'A':7,'Z':0}
    while i<len(tokens):
        cmd=tokens[i];i+=1;n=counts[cmd];v=list(map(float,tokens[i:i+n]));i+=n
        if cmd in {'M','L','C'}:
            for j in range(1,n,2):v[j]=600-v[j]
        elif cmd=='A':v[4]=1-v[4];v[6]=600-v[6]
        out.extend([cmd,*map(fmt,v)])
    return ' '.join(out)
# Native bottom 0 deg = stored 180 deg and mirrored Y projection of the canonical library.
# Preserve the same stock footprint chirality when turning the component to the bottom face.
def mirror_node(n):
    a=n.get('attrs',{})
    if 'c_origin' in a:a['c_origin']=mirror_pairs(a['c_origin'],True)
    if 'points' in a:a['points']=mirror_pairs(a['points'])
    if 'c_rotation' in a:a['c_rotation']='0,0,90'
    for c in n.get('childNodes',[]):mirror_node(c)
items = []
for s in fp['shape']:
    v=s.split('~');k=v[0]
    if k=='PAD':
        v[6]='2';v[7]={'1':'BAT_P','2':'USB_5V','3':'VSYS'}[v[8]]
        v[3]=fmt(600-float(v[3]));v[10]=mirror_pairs(v[10]);v[19]=mirror_pairs(v[19],True)
    elif k=='TRACK':
        v[4]=mirror_pairs(v[4])
        if v[2]=='3':v[2]='4'
    elif k=='ARC':
        v[4]=mirror_path(v[4])
        if v[2]=='3':v[2]='4'
    elif k=='SOLIDREGION':v[3]=mirror_path(v[3])
    elif k=='CIRCLE':v[2]=fmt(600-float(v[2]))
    # IDs must be unique across all board components.
    s='~'.join(v)
    s=re.sub(r'(?<=~)(gge[^~]+)',lambda m:'ggeQ1NEW20261006_'+m.group(1),s)
    if k=='SVGNODE':
        node=json.loads(s.split('~',1)[1])
        def ids(n):
            if 'gId' in n: n['gId']='q1_20261006_'+n['gId']
            if 'id' in n.get('attrs',{}): n['attrs']['id']='q1_20261006_'+n['attrs']['id']
            for c in n.get('childNodes',[]): ids(c)
        ids(node);mirror_node(node);s='SVGNODE~'+json.dumps(node,ensure_ascii=False,separators=(',',':'))
    items.append(s)
temp = '#@$'.join(['LIB~404~300~'+h[3]+'~180~~'+h[6]+'~2~'+UUID+'~'+h[9]+'~0~~yes~~',*items])
newq = shift_lib_safe(temp,(target[0]-(404-4020)*U,target[1]-(300-3404)*U))
# Preserve the existing hidden designator and instance identity; hidden value is textual evidence only.
for s in oldq.split('#@$')[1:]:
    if not s.startswith('TEXT~'): continue
    t=shift_lib_safe('#@$'.join([oldq.split('#@$')[0],s]),(target[0]-26.035,target[1]+74.295)).split('#@$')[1]
    if t.startswith('TEXT~N~'):
        v=t.split('~');v[10]='DMP2165UW-7';v[11]='';v[12]='none';t='~'.join(v)
    newq += '#@$'+t

for i,s in enumerate(d['shape']):
    if not s.startswith('LIB~'): continue
    r=ref(s)
    if r=='Q1':d['shape'][i]=newq
    elif r=='D4': d['shape'][i]=shift_lib_safe(s,(0,.4))
    elif r=='R9': d['shape'][i]=shift_lib_safe(s,(0,-.2))

# Replace only the old Q1/D4/R9 local stubs. Retain the shared supply trunks.
remove = {'ggeBATCH0928T295','ggeBATCH0928T296','ggeBATCH0928T297','ggeBATCH0928V299',
    'ggeUSB0928T293','ggeUSB0928T298','ggeUSB0928T308','ggeUSB0928T328'}
def shape_id(s):
    v=s.split('~');return v[5] if v[0]=='TRACK' else v[6] if v[0]=='VIA' else None
d['shape']=[s for s in d['shape'] if shape_id(s) not in remove]
def track(id,net,layer,width,pts):
    return f'TRACK~{fmt(width/U)}~{layer}~{net}~'+ ' '.join(fmt(4020+x/U) if a==0 else fmt(3404+y/U)
        for x,y in pts for a in (0,1))+f'~{id}~0'
replace = {
    'ggeUSB0928T339':('GND','2',.10000000066,[(23.837011,-73.66),(24.25,-74.072989),(24.25,-74.817184),(24.6898414,-75.2570254)]),
    'ggeUSB0928T332':('GND','2',.10000000066,[(24.6898414,-75.2570254),(24.6898414,-75.65),(24.5898414,-75.75),(24.1698272,-75.75),(24.1698272,-76.377038),(24.5968012,-76.8039866),(24.6379746,-76.8039866)]),
    'gge5173048':('USB_5V','2',.2500122,[(23.8241078,-75.2570254),(23.8241078,-74.6102394)]),
    'ggeBATCH0928T305':('USB_5V','2',.2500122,[(23.824184,-75.2570254),(23.824184,-74.5370366)]),
    'ggeBATCH0928T300':('VSYS','2',.2500122,[(25.6849626,-72.8790254),(25.404973,-73.1590358),(25.2449584,-73.1590358)]),
    'ggeUSB0928T399':('USB_5V','2',.2500122,[(26.3849866,-72.8790254),(26.385,-72.1)]),
    'ggeUSB0928T400':('USB_5V','1',.2500122,[(26.385,-72.1),(26.144982,-72.6390216),(25.0249944,-72.6390216),(23.824184,-73.839832),(23.824184,-73.9492044)]),
}
for i,s in enumerate(d['shape']):
    k=shape_id(s)
    if k in replace: d['shape'][i]=track(k,*replace[k])
    elif k in {'ggeBATCH0928V298','ggeUSB0928V392','ggeUSB0928V329'}:
        v=s.split('~');pos,net = {'ggeBATCH0928V298':((26.35,-75.35),'USB_5V'),
            'ggeUSB0928V392':((26.385,-72.1),'USB_5V'),'ggeUSB0928V329':((23.25,-74.15),'GND')}[k]
        v[1],v[2],v[4]=fmt(4020+pos[0]/U),fmt(3404+pos[1]/U),net
        d['shape'][i]='~'.join(v)

new_tracks = [
    ('C7_GROUND','GND','2',.10000000066,[(23.837011,-73.66),(23.347011,-74.15),(23.25,-74.15)]),
    ('BAT','BAT_P','2',.2500122,[(24.95,-74.5),(24.6770398,-74.2270398),(24.6770398,-73.6600254)]),
    ('SOURCE','VSYS','2',.2500122,[(26.85,-73.85),(26.4,-74.3),(25.64511,-74.7649)]),
    ('SOURCE_VIA','VSYS','1',.2500122,[(25.64511,-74.7649),(25.64511,-74.6790226)]),
    ('GATE','USB_5V','2',.10000000066,[(26.85,-75.15),(26.55,-75.35),(26.35,-75.35)]),
    ('GATE_VIA','USB_5V','1',.10000000066,[(26.35,-75.35),(25.9,-75.35),(25.6,-75.65),(25.1841762,-75.65),(25.1841762,-75.8970288)]),
]
for suffix,*spec in new_tracks: d['shape'].append(track('ggeQ1LOCAL20261006_'+suffix,*spec))
assert d['DRCRULE']==before['DRCRULE'] and d['routerRule']==before['routerRule']
_,parts,cs,hs=parse(d);_,op,oc,oh=parse(before)
assert sorted((c['ref'],c['pin'],c['net'],c['kind']) for c in cs)==sorted((c['ref'],c['pin'],c['net'],c['kind']) for c in oc)
assert set(parts)==set(op) and len(parts)==41
assert all(parts[r]==op[r] for r in parts if r not in {'Q1','D4','R9'})
save('PCB_Q1直接修复_局部候选_仅审核_20261006.json',d)
save('Q1候选变更范围_仅审核.json',{'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
    'status':'local trial only; not applied or native checked','parts_changed':['Q1','D4','R9'],
    'old_new_pin_net_mapping_identical':True,'unchanged_rules':True,'removed_local_ids':sorted(remove),
    'new_local_tracks':new_tracks,'custom_to_manufacturer_pin_numbers':{'1 D':'3','2 G':'1','3 S':'2'},
    'footprint_uuid':UUID,'native_repour_required':True,'production_released':False})
print('Local candidate written; 41 components; pin/net signatures and all rules preserved.')
