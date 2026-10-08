from pathlib import Path
import json, csv, io, collections, hashlib, zipfile, copy, sys, re
r=Path('/Users/liuchunyu/Documents/fyp/hardware/round_sensor_v0');s=r/'easyeda_std/C9替料_20261005';o=r/'manufacturing/仅审核禁止生产/C9替料_20261005';old=r/'manufacturing/仅审核禁止生产/板外充电_20261005'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text())
def prop(x):
 f=x.split('#@$')[0].split('~');p=f[3].split('`');return dict(zip(p[::2],p[1::2]))
def ref(x,pcb=True):
 for q in x.split('#@$')[1:]:
  if q.startswith('TEXT~P~') if pcb else q.startswith('T~P~'):return q.split('~')[10 if pcb else 12]
def counter(v):return collections.Counter(v)
a=read(s/'PCB_C9替料前_20261005.json');b=read(s/'PCB_C9替料_重铺保存重开_20261005.json')
assert sha(s/'PCB_C9替料_重铺保存重开_20261005.json')=='9bf591e459d91d93a55d6c76143323030acbc7299e75c267a41acebdb0801e84'
assert {k:v for k,v in a.items() if k!='shape'}=={k:v for k,v in b.items() if k!='shape'}
def pick(d):return {ref(x):x for x in d['shape'] if x.startswith('LIB~')}
ap,bp=pick(a),pick(b);assert len(ap)==len(bp)==41;assert set(ap)==set(bp)
changed=[k for k in ap if ap[k]!=bp[k]];assert changed==['C9']
ac,bc=ap['C9'].split('#@$'),bp['C9'].split('#@$');assert ac[2:]==bc[2:];af,bf=ac[0].split('~'),bc[0].split('~');assert af[:3]+af[4:]==bf[:3]+bf[4:]
assert counter(x for x in a['shape'] if not x.startswith('LIB~'))==counter(x for x in b['shape'] if not x.startswith('LIB~'))
assert prop(bp['C9'])['Manufacturer Part']=='GRM155R61A475MEAAD';assert prop(bp['C9'])['Supplier Part']=='C335105';assert prop(bp['C9'])['Value']=='4.7uF / 10V'
# SCH LIB field 10 is a volatile import-instance token, not electrical or placement data.
def norm(x):
 if not x.startswith('LIB~'):return x
 c=x.split('#@$');f=c[0].split('~');f[10]='<volatile-import-instance>';c[0]='~'.join(f);return '#@$'.join(c)
sa=read(s/'SCH_C9替料前_五页_20261005.json');sb=read(s/'SCH_C9替料_五页保存重开_20261005.json');assert len(sa['schematics'])==len(sb['schematics'])==5
assert {k:v for k,v in sa.items() if k!='schematics'}=={k:v for k,v in sb.items() if k!='schematics'}
sch_delta=[];refs=[]
for i,(aa,bb) in enumerate(zip(sa['schematics'],sb['schematics']),1):
 assert {k:v for k,v in aa.items() if k!='dataStr'}=={k:v for k,v in bb.items() if k!='dataStr'}
 da,db=aa['dataStr'],bb['dataStr'];assert {k:v for k,v in da.items() if k!='shape'}=={k:v for k,v in db.items() if k!='shape'}
 ca,cb=counter(norm(x) for x in da['shape']),counter(norm(x) for x in db['shape']);diffA=list((ca-cb).elements());diffB=list((cb-ca).elements())
 if i!=4:assert not diffA and not diffB
 else:
  assert len(diffA)==len(diffB)==1;assert ref(diffA[0],False)==ref(diffB[0],False)=='C9';assert diffA[0].split('#@$')[2:]==diffB[0].split('#@$')[2:]
 sch_delta.append({'page':i,'title':bb['title'],'changed_LIB_count':len(diffB),'volatile_LIB_field_10_normalized':True})
 refs.extend(ref(x,False) for x in db['shape'] if x.startswith('LIB~'))
assert len(refs)==len(set(refs))==41
netnew=o/'SCH_C9替料_原生Protel全图_仅审核_20261005.net';netold=old/'SCH_板外充电_原生Protel全图_仅审核_20261005.net';assert netnew.read_bytes()==netold.read_bytes().replace(b'[\nC9\nC0402\n1uF / 10V',b'[\nC9\nC0402\n4.7uF / 10V')
def native_csv(p):
 raw=p.read_bytes();txt=raw.decode('utf-16') if raw.startswith(b'\xff\xfe') else raw.decode('utf-8-sig');return list(csv.DictReader(io.StringIO(txt),delimiter='\t' if '\t' in txt.splitlines()[0] else ','))
nb=native_csv(o/'BOM_C9替料_原生全属性_仅审核_20261005.csv');assert len(nb)==41;nr={x['Designator']:x for x in nb};assert nr['C9']['Manufacturer Part']=='GRM155R61A475MEAAD';assert nr['C9']['Name']==nr['C9']['Value']=='4.7uF / 10V';assert nr['C9']['Supplier Part']=='C335105'
oldbom=old/'BOM_36件准确料号_仅审核_20261005.csv';rows=list(csv.DictReader(oldbom.open(encoding='utf-8-sig',newline='')));fields=list(rows[0]);assert len(rows)==36
for row in rows:
 if row['位号']=='C9':
  row['完整料号']='GRM155R61A475MEAAD';row['历史立创编号_下单前复核']='C335105';row['说明']='4.7µF/10V X5R ±20%；国内准确条目与SMT扩展库标签已核；实际库存/接贴待工厂；最大高0.65mm；无极性'
newbom=o/'BOM_36件准确料号_C9替料_仅审核_20261005.csv'
with newbom.open('w',encoding='utf-8-sig',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
assert len({x['完整料号'] for x in rows})==22
cplold=old/'CPL_36件SMT_中心校正_仅审核_20261005.csv';cplrows=list(csv.DictReader(cplold.open(encoding='utf-8-sig',newline='')));cplfields=list(cplrows[0]);native=native_csv(o/'CPL_C9替料_原生全41位置_仅审核_20261005.csv');assert len(native)==41;nn={x['Designator']:x for x in native}
for row in cplrows:
 if row['Designator']=='C9':row['Comment']='4.7uF / 10V'
 for key in cplfields:
  if key=='Mid Y' and row['Designator']=='ANT1':assert row[key]=='80.67mm' and nn['ANT1'][key]=='81.43mm';continue
  assert row[key]==nn[row['Designator']][key],(row['Designator'],key,row[key],nn[row['Designator']][key])
newcpl=o/'CPL_36件SMT_中心校正_C9替料_仅审核_20261005.csv'
with newcpl.open('w',encoding='utf-8-sig',newline='') as f:w=csv.DictWriter(f,fieldnames=cplfields);w.writeheader();w.writerows(cplrows)
sys.path[:0]=['/tmp/round-pcb-audit-libs',str(r/'scripts')];from audit_current_cam import layer;from audit_clone_connector_s_20260929 import drill
zgold=r/'manufacturing/仅审核禁止生产/BOOT_RESET标注_20261005/Gerber_BOOT_RESET功能丝印_仅审核_20261005.zip';zgnew=o/'Gerber_C9替料_仅审核_20261005.zip';cam={}
with zipfile.ZipFile(zgold) as z1,zipfile.ZipFile(zgnew) as z2:
 assert set(z1.namelist())==set(z2.namelist())
 for n in z1.namelist():
  if n.endswith('.txt'):continue
  if n.endswith('.DRL'):aa=drill(z1.read(n).decode());bb=drill(z2.read(n).decode());eq=aa==bb
  else:aa=layer(z1.read(n).decode());bb=layer(z2.read(n).decode());eq=counter(json.dumps(q,sort_keys=True) for q in aa)==counter(json.dumps(q,sort_keys=True) for q in bb)
  assert eq,n;cam[n]={'finite_parsed_geometry_identical':True,'primitive_count':len(bb),'byte_identical':z1.read(n)==z2.read(n)}
rep={'scope':'仅审核；C9属性和名称替料增量；非生产放行；未提交订单','current_pcb':{'path':str(s/'PCB_C9替料_重铺保存重开_20261005.json'),'sha256':sha(s/'PCB_C9替料_重铺保存重开_20261005.json'),'document_id':'cca094630ebf453c98ae64b900f0d7f0','same_unique_document_saved_closed_reopened':True,'only_changed_LIB':'C9','changed_fields':['LIB properties','hidden TEXT N regenerated to 4.7uF / 10V'],'all_other_321_shapes_identical':True,'C9_all_items_from_index_2_identical_including_pads_3D':True,'nonshape_fields_identical':True,'all_3_COPPERAREA_including_cache_identical_after_native_rebuild':True},'schematic':{'path':str(s/'SCH_C9替料_五页保存重开_20261005.json'),'sha256':sha(s/'SCH_C9替料_五页保存重开_20261005.json'),'native_property_edit_saved_closed_reopened_all_five':True,'unique_ref_count':41,'pages':sch_delta,'C9_Value_Name_MPN_Supplier_synchronized':True,'legacy_spiceSymbolName':'1uF / 10V, native symbol identifier retained; not the active Value/Name or native netlist/BOM value'},'native_netlist':{'sha256':sha(netnew),'only_difference_C9_value_1_to_4_7_uF':True,'previous_137_connected_49_NC_pin_audit_reusable':True,'complete_independent_electrical_type_ERC_not_obtained':True},'native_check':{'components':41,'nets_complete':20,'nets_total':20,'unconnected':0,'drc':1,'Q1':'gge2100 USB_5V pad2 to gge2115 VSYS pad3; 0.1398524mm < 0.1500124mm rule; retained','rules_loosened':False,'ignored':False,'source_apply_clear_pour_cache_detected_then_native_Shift_B_restored':True,'failed_intermediate_recovery':'PCB_C9替料_保存重开_20261005.json has empty caches; not current and must not manufacture'},'bom_cpl':{'SMT':36,'top':6,'bottom':30,'distinct_full_MPN':22,'only_accurate_BOM_C9_row_changed':True,'native_BOM_C9_verified':True,'all_machine_coordinates_rotations_identical_to_previous_corrected_CPL':True,'C9_native_coordinates':nn['C9'],'ANT1_corrected_Mid_Y_kept_mm':80.67,'native_all_41_BOM_contains_nominal_values_handwire_DNP_not_order_BOM':True,'factory_sourcing_and_machine_origin_pending':True},'gerber':{'sha256':sha(zgnew),'comparison_sha256':sha(zgold),'layers':cam,'copper_masks_silk_paste_outline_drills_identical':True,'PTH':85,'NPTH':2,'via_subset_of_PTH':81,'production_acceptance':False},'C9_part':{'MPN':'GRM155R61A475MEAAD','supplier_part':'C335105','capacitance_uF':4.7,'voltage_V':10,'dielectric':'X5R','tolerance_percent':20,'nonpolar':True,'nominal_LWT_mm':[1.0,0.5,0.5],'max_LWT_mm':[1.15,0.65,0.65],'body_max_temperature_C':[-55,85],'nominal_3D_model_retained':True,'PIM_status_observed':'In Production','domestic_SMT_label_observed':'SMT扩展库','domestic_live_stock_and_acceptance_confirmed':False,'sources':['https://pim.murata.com/en-us/pim/details/?productCategoryId=ceramicCapacitorSMD&partNum=GRM155R61A475MEAA%23','https://item.szlcsc.com/313626.html'],'combined_curve_typical_with_negative_tolerance_screen_min_uF':1.036,'typical_not_guaranteed_manufacturer_minimum':True,'C10_unchanged':True},'known_UI_source_application_issue':{'raw_single_page':'existing project Apply rejected format, no save','single_page_native_container':'existing multi-page project replaced first open page, duplicate refs; discarded without saving and original reloaded','successful_method':'native C9 property panel editing; all-five save/reopen and netlist finite check passed'}}
(o/'C9保存重开与制造增量核验_仅审核.json').write_text(json.dumps(rep,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'PCB_sha256':rep['current_pcb']['sha256'],'SCH_sha256':rep['schematic']['sha256'],'Gerber_sha256':rep['gerber']['sha256'],'only_C9_change':True,'SMT':36,'MPN':22,'unconnected':0,'DRC':1,'CAM_all_identical':True},ensure_ascii=False,indent=2))
