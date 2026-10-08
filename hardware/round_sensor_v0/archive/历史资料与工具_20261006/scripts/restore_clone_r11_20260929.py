"""用户确认 R11 为误拖后，恢复原位置及联动变化的 REG_EN 导线。"""
from pathlib import Path
from refine_clone_usb_20260928 import *
from build_a5_rf_clearance_layout import ref

configure();doc,_,_,_=parse(OUT)
base=Path('/var/folders/6b/_qmhvjlj1dj0tqz5lb5pfzf40000gn/T/edausb-cc-zlqmp4uz/staging.json')
old,_,_,_=parse(base)
lib=next(s for s in old['shape'] if s.startswith('LIB~') and ref(s)=='R11')
def isreg(s):return s.startswith(('TRACK~','VIA~')) and s.split('~')[3 if s.startswith('TRACK~') else 4]=='REG_EN'
doc['shape']=[lib if s.startswith('LIB~') and ref(s)=='R11' else s for s in doc['shape'] if not isreg(s)]
doc['shape'] += [s for s in old['shape'] if isreg(s)]
_,parts,c,h=parse(doc);issues=local_check(doc,c,h)
assert not issues,issues
ids=[s.split('~')[5 if s.startswith('TRACK~') else 6] for s in doc['shape'] if s.startswith(('TRACK~','VIA~'))]
assert len(ids)==len(set(ids))
save(doc);report=json.loads(REPORT.read_text());report['R11误拖恢复']={'用户已明确确认':True,'原位置_mm':parts['R11']['center'],'恢复REG_EN几何':True,'几何冲突':issues};report['候选几何冲突']=issues
REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print('R11_RESTORED',parts['R11']['center'],'GEOMETRY',issues)
