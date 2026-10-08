"""R电源条件计算与引脚核对。只生成审查数据，不改PCB/原理图，不作为实测。"""
import hashlib,json
from pathlib import Path
from check_pcb_a5 import ROOT,parse

SRC=ROOT/'easyeda_std/PCB_克隆板USB局部重布_原生回读_20260929.json'
EXPECTED='c3c0d4e5630df0b756df07d380213af8edc1a5eab8da054e44c54a5e4e337954'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(SRC)==EXPECTED,'源已变化，不能复用R审核'
d,parts,copper,holes=parse(SRC)
pads={(x['ref'],x['pin']):x['net'] for x in copper if x['kind']=='pad'}
expected={
 'U4':{'A1':'BAT_P','A2':'USB_5V','B1':'GND','B2':'','C1':'U4_C1','C2':'GND'},
 'U5':{'1':'3V3','2':'','3':'GND','4':'REG_EN','5':'','6':'VSYS','7':'GND'},
 'Q1':{'1':'BAT_P','2':'USB_5V','3':'VSYS'},'D4':{'1':'VSYS','2':'USB_5V'},
 'SW1':{'1':'GND','2':'REG_EN','3':'VSYS'},'R9':{'1':'USB_5V','2':'GND'},
 'R10':{'1':'U4_C1','2':'GND'},'R11':{'1':'REG_EN','2':'GND'},
 'J2':{'1':'BAT_P','2':'GND'},'J4':{'1':'3V3','2':'GND','3':'I2C_SDA','4':'I2C_SCL'},
 'C6':{'1':'USB_5V','2':'GND'},'C7':{'1':'BAT_P','2':'GND'},
 'C9':{'1':'VSYS','2':'GND'},'C10':{'1':'3V3','2':'GND'}}
for ref,pins in expected.items():
 for pin,net in pins.items():assert pads[(ref,pin)]==net,(ref,pin)
values={ref:next(x[10] for x in p['items'] if x[:2]==['TEXT','N']) for ref,p in parts.items()}
assert values['R10']=='220k / 1%' and values['U5']=='TLV75533PDRVR'
assert values['U4']=='SGM40567-4.2XG/TR' and values['Q1']=='LP0404N3T5G'
ichg=24000/220/1000
rows=[]
for i in [.1,.2,.3,.5]:
    # 两个不同手册测试条件的组合/线性外推，仅灵敏度场景，绝非全温最坏保证。
    mos_drop=i*.67;ldo_drop=i*(.215/.5)
    ldo_p=(5-.3-3.3)*i;diode_p=.3*i;chg_p=(5-3)*ichg
    rows.append({'系统负载_A_场景非实测':i,'Q1压降_V_0.67ohm模型':mos_drop,
       'LDO压差_V_215mV每500mA线性模型':ldo_drop,'维持标称3V3电池端电压_V_未计线阻电池内阻':3.3+mos_drop+ldo_drop,
       'USB5V_D4假设0.3V时LDO损耗_W':ldo_p,'D4损耗_W':diode_p,
       '电池3V_标称充电损耗_W':chg_p,'电源器件合计损耗_W_不含主控传感器':ldo_p+diode_p+chg_p,
       'USB输入电流_A_忽略静态电流':i+ichg,
       'LDO标准板热阻100.2K每W对应温升_K_非本板':ldo_p*100.2})
capacitors={}
for ref in ['C6','C7','C9','C10','C20']:
 s=next(s for s in d['shape'] if s.startswith('LIB~') and any(v.startswith('TEXT~P~') and v.split('~')[10]==ref for v in s.split('#@$')))
 fields=s.split('~')[3].split('`');attrs=dict(zip(fields[::2],fields[1::2]))
 capacitors[ref]={'标称':values[ref],'封装':attrs.get('package'),'制造商料号字段':attrs.get('Manufacturer Part'),
     '完整采购料号已确定':False,'旧封装link不得当采购选型':True}
report={'检查点':'R','来源':str(SRC),'来源SHA256':EXPECTED,'PCB与原理图未修改':True,
 '已逐脚核对':expected,'实际值':{k:values[k] for k in expected},
 '标称充电电流_mA':ichg*1000,'仅1%电阻误差范围_mA':[24000/(220*1.01),24000/(220*.99)],
 '充电误差边界':'手册仅给120k和600k测试点误差；不得把220k电阻1%当成完整充电电流误差，也不插值成保证范围。',
 '负载场景':rows,'场景条件':'USB端5.0V，D4压降假设0.3V，电池端3.0V且按109.09mA充电；无板温/平均电流实测。',
 '压差边界':'MOS 0.67ohm为25C/-2.5V栅源/660mA脉冲表值；LDO 215mV为500mA、结温至85C。不同条件组合，低电流外推，仅筛查。输出进入dropout不等于立即关机。',
 'USB500mA预算剩余系统电流_mA_忽略其他耗流':500-ichg*1000,
 'USB边界':'仅电流加总示例，500mA端口不是默认已获授权；本板无USB枚举/暂停联动充电控制，沿用既有取舍，不宣称USB电源规范全合规。',
 '电容':capacitors,'C9_C10有效电容门槛_uF':.47,
 '电容条件':'保持名义1uF及X5R/X7R选型；有效值需结合具体料号、实际偏压、公差、温度和老化验证，不把通用50%降额作为保证。C20远端容量不能直接替代C10本地电容。',
 '电池保护':'无独立电芯过放保护/NTC网络；SGM充电温控不是电芯温控，LDO欠压也不是锂电保护。需规格可追溯的带保护单节4.2V锂电，充放电能力待匹配。',
 '热边界':'100.2K/W为DRV标准板热参数，158K/W为充电器手册参考；不能用于18mm塑料笔杆内温升保证。D4在500mA/0.5V条件耗散0.25W，达到其25C最小焊盘功耗额定。',
 '风险':['电池及电容无确定料号，无法关闭安全与偏压审核','500mA额定不代表低电量/热环境下的整板持续能力','固定109mA充电与系统负载共用USB输入预算','USB拔插/启动瞬态和低电量重启需实测'],
 '下一步':'优先确定C6/C7/C9/C10/C20完整料号并查偏压；电池选型后匹配R10，保留架构；用受控电源和实际固件验证启动、BLE及热工况。',
 '电源已验收':False,'允许生产':False}
dest=ROOT/'easyeda_std/克隆板R电源预算审核_20260929.json'
dest.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
assert sha(SRC)==EXPECTED
print(json.dumps({'报告':str(dest),'充电_mA':ichg*1000,'电阻范围':report['仅1%电阻误差范围_mA'],'场景':rows},ensure_ascii=False,indent=2))
