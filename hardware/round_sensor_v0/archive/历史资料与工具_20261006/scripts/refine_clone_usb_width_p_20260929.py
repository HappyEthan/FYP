"""USB线宽局部试排；不直接覆盖O，须原生验证后才能纳入。"""
import hashlib,json
from pathlib import Path
from refine_clone_usb_20260928 import parse,configure,batch,old_losses
from repair_clone_inner_layer_20260928 import path_text

src=Path('/Users/liuchunyu/Downloads/PCBUSBcloudReopenO20260929.json')
assert hashlib.sha256(src.read_bytes()).hexdigest()=='50cc5d7c2417931c8f61c0baab8dde430b13e5a49fc2826c03c5c9560b2952b4'
d,parts,c,h=parse(src);configure();b=json.loads(json.dumps(d));changed=[]
for i,s in enumerate(b['shape']):
    f=s.split('~')
    if f[0]=='TRACK' and f[3].startswith('USB_D'):
        f[1]=str(.17/.254)
        if f[5]=='ggeUSB0928T306':
            f[4]=path_text([(23.049992,-77.9671796),(23.3199914,-77.6971802),(23.3199914,-77.1884156),(23.0315744,-76.8999986),(22.8000052,-76.8999986),(22.199981,-76.3001268)])
    elif f[0]=='TRACK' and f[5]=='ggeUSB0928T319':f[1]=str(.23/.254)
    else:continue
    b['shape'][i]='~'.join(f);changed.append(b['shape'][i])
assert len(changed)==13 and not batch.check_new(b,c,h,changed)
for net in ['USB_DP','USB_DM','USB_DP_SOC','USB_DM_SOC','GND']:
    assert not old_losses(d,c,b,c,net)
for i,s in enumerate(b['shape']):
    f=s.split('~')
    if f[0]=='COPPERAREA':f[10]='';b['shape'][i]='~'.join(f)
dest=src.with_name('PCBUSBwidthPTrial20260929.json')
dest.write_text(json.dumps(b,ensure_ascii=False,indent=2)+'\n')
print(dest,hashlib.sha256(dest.read_bytes()).hexdigest())
print(next(s for s in changed if 'ggeUSB0928T306' in s))
