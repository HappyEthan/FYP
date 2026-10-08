from pathlib import Path
import json,re,os
R=Path(__file__).resolve().parents[2]
OP=R/'archive/目录整理_20261006'
H='archive/历史资料与工具_20261006'
O=R/'manufacturing/仅审核禁止生产/Q1直接修复_20261006'
MOVES=json.loads((OP/'移动清单.json').read_text())['files']
current_name='06 当前PCB_圆形传感板_A5'
def remap_paths(text):
    # Current documents only; historical records remain byte-identical.
    for old,v in sorted(MOVES.items(),key=lambda kv:len(kv[0]),reverse=True):
        text=text.replace(old,v['to'])
    return text

p=R/'AGENTS.md'; text=p.read_text()
old='- 当前工作入口：`圆形传感板_SCH_A5` → 用户自动布线克隆 `PCB_圆形传感板_SCH_A5 copy`（文档 ID `cca094630ebf453c98ae64b900f0d7f0`，2026-09-28 已核对）。原版 `PCB_圆形传感板_SCH_A5` 保留不动。历史 `圆形传感板_A5_当前工作版` 不得冒充当前板或被盲目覆盖；其独有未保存内容已单独备份。'
new='- 当前工作入口：`圆形传感板_SCH_A5` → `06 当前PCB_圆形传感板_A5`（文档 ID `cca094630ebf453c98ae64b900f0d7f0`）。2026-10-06仅整理名称/说明，原名 `PCB_圆形传感板_SCH_A5 copy` 仍是历史别名。两张旧PCB分别标为 `90 历史PCB_A5原版_禁止下单`、`91 历史PCB_A5旧工作版_禁止下单`；内容、ID保留，旧工作板独有未保存内容已有备份。'
assert old in text
text=remap_paths(text.replace(old,new))
text += '\n## 本地目录与工具（2026-10-06整理）\n\n当前源码在 `easyeda_std/Q1直接修复_20261006/`；当前制造审阅资料在 `manufacturing/仅审核禁止生产/Q1直接修复_20261006/`。旧源码、候选、制造包、专题报告和一次性生成器在 `archive/历史资料与工具_20261006/`，原目录结构和文件字节保留；路径映射见 `archive/目录整理_20261006/移动清单.json`。历史报告内路径是当时记录，按映射定位。`scripts/`只保留当前只读审核工具及解析依赖；旧名解析模块仅供导入，不独立执行其历史主程序。不得重跑旧生成器恢复当前设计。\n'
p.write_text(text)

p=R/'CAD_HANDOFF.md'; text=p.read_text().split('## 10月1日预审细节')[0].rstrip()
old='工程 `圆形传感板_SCH_A5`，工程ID `3c2f1824ae2d4fd391ecd83abc2b3411`；唯一工作PCB `PCB_圆形传感板_SCH_A5 copy`，文档ID `cca094630ebf453c98ae64b900f0d7f0`。原版及 `圆形传感板_A5_当前工作版` 保留作历史；本轮候选只开独立未保存标签，未新增云端PCB。'
new='工程 `圆形传感板_SCH_A5`，工程ID `3c2f1824ae2d4fd391ecd83abc2b3411`；唯一工作PCB `06 当前PCB_圆形传感板_A5`，文档ID `cca094630ebf453c98ae64b900f0d7f0`。原名 `PCB_圆形传感板_SCH_A5 copy` 保留作历史别名。2026-10-06仅修改目录名称/说明：两张旧板标为 `90 历史PCB_A5原版_禁止下单`、`91 历史PCB_A5旧工作版_禁止下单`，内容和ID不变；未新增云端PCB。'
assert old in text
text=remap_paths(text.replace(old,new))
text+='''

## 工程目录与历史追溯｜2026-10-06

根目录README是导航入口，本交接只显示当前结论。当前源、准确BOM/CPL和Gerber路径保持；历史专题资料已完整归档，未删除恢复资料。目录整理仅涉及名称、路径和说明，不修改电路、封装、模型、位置、布线或规则，也不把既有DRC记录改写为本轮重新检查。

- 当前源码：[源码目录说明](easyeda_std/README.md)。保留最终PCB、五页SCH、网表、个人库、现有核验以及Q1改前恢复点。
- 当前制造资料：[制造目录说明](manufacturing/README.md)，全部仅审核；[审阅说明](manufacturing/仅审核禁止生产/Q1直接修复_20261006/制造审阅说明_仅审核.md)。
- 历史完整交接：[整理前原件](archive/目录整理_20261006/整理前原件/CAD_HANDOFF.md)，含10月1日至本轮前的逐轮记录。
- 旧版路径：[逐文件移动及SHA256清单](archive/目录整理_20261006/移动清单.json)。历史报告保留原字节与原记录时间；按清单找到现址，不用旧数量、旧Q1、旧制造包覆盖当前结论。
- 旧工具：[历史资料目录说明](archive/历史资料与工具_20261006/README.md)。不得批量恢复或运行旧生成器；确有历史比较需要时，单独恢复指定输入到独立目录。
'''
p.write_text(text+'\n')

p=O/'本轮交接_仅审核.md'; text=p.read_text().replace('`PCB_圆形传感板_SCH_A5 copy`',f'`{current_name}`')
text=text.replace('初次替料Gerber已放历史中间目录，禁止制造。',f'初次替料Gerber已归入`{H}/manufacturing/仅审核禁止生产/Q1直接修复_20261006/历史中间版_孔距未收尾_禁止制造/`，禁止制造。')
p.write_text(text)
p=O/'制造审阅说明_仅审核.md'; text=p.read_text()
text=text.replace('## 先看三项',f'当前共享工程：`圆形传感板_SCH_A5` → `{current_name}`（文档ID不变）。2026-10-06目录整理只改名称与路径，源、制造数据保持。\n\n## 先看三项')
text=text.replace('详尽历史恢复文件保留在原工程','详尽历史恢复文件保留在`archive/`')
text += '\n本说明的路径以工程根目录为基准。旧USB/C9/整板来源报告在`archive/历史资料与工具_20261006/manufacturing/仅审核禁止生产/`；文件名及内容保持，按移动清单追溯。\n'
p.write_text(text)

p=R/'scripts/audit_q1_saved_outputs_20261006.py'; text=p.read_text()
for sub in ['整板复审_20261004/independent_manufacturing_geometry.py','C9替料_20261005/Gerber_C9替料_仅审核_20261005.zip','C9替料_20261005/BOM_36件准确料号_C9替料_仅审核_20261005.csv','C9替料_20261005/CPL_36件SMT_中心校正_C9替料_仅审核_20261005.csv']:
 old='manufacturing/仅审核禁止生产/'+sub; assert old in text; text=text.replace(old,H+'/'+old)
# The report describes the original inspection date/name; do not rewrite historical UI claims.
p.write_text(text)
p=R/'scripts/audit_q1_direct_fix_20261006.py'; text=p.read_text(); old="else O/'PCB_Q1直接修复_局部候选_仅审核_20261006.json'"; assert old in text; p.write_text(text.replace(old,"else O/'PCB_Q1直接修复_孔距收尾_保存重开_20261006.json'"))

(R/'README.md').write_text('''# 圆形传感板工程

更新：2026-10-06。先看当前入口；历史文件不用于下单。

## EDA 当前工程

`圆形传感板_SCH_A5` → **`06 当前PCB_圆形传感板_A5`**。

工程ID `3c2f1824ae2d4fd391ecd83abc2b3411`；PCB文档ID `cca094630ebf453c98ae64b900f0d7f0`。原名 `PCB_圆形传感板_SCH_A5 copy`，本轮仅改名/说明，原理图五页01–05保留。两张旧PCB已标为90/91历史板；更早的A1–A3工程集中到`90 历史工程_仅比较恢复`。共享当前工程的位置和权限未改。

## 本地当前入口

- [当前交接与剩余事项](CAD_HANDOFF.md)
- [最终保存重开PCB](easyeda_std/Q1直接修复_20261006/PCB_Q1直接修复_孔距收尾_保存重开_20261006.json)
- [完整五页SCH](easyeda_std/Q1直接修复_20261006/SCH_Q1替料_最终五页回读_20261006.json)
- [准确36件BOM](manufacturing/仅审核禁止生产/Q1直接修复_20261006/BOM_36件准确料号_Q1修复_仅审核_20261006.csv) · [校正CPL](manufacturing/仅审核禁止生产/Q1直接修复_20261006/CPL_36件SMT_中心校正_Q1修复_仅审核_20261006.csv)
- [最终Gerber，仅审核](manufacturing/仅审核禁止生产/Q1直接修复_20261006/Gerber_Q1直接修复_孔距收尾_仅审核_20261006.zip)
- [博后审阅包，仅审核](manufacturing/仅审核禁止生产/圆形传感板_Q1修复最终审阅_20261006.zip)
- [冻结需求](DESIGN_BASELINE_XIAO_PICO.md)

当前41位置、20网络、36件SMT；Q1修复版原生保存重开DRC0/未连接0为已有审核证据。工厂工艺、机器基准、首板使用范围和真实笔杆装配仍见交接；目录整理不代替这些确认，未下单。

## 目录分工

| 目录 | 用途 |
|---|---|
| `easyeda_std/` | 当前原生源码、核验和本轮改前恢复点；见[说明](easyeda_std/README.md) |
| `manufacturing/` | 唯一当前审阅包、准确BOM/CPL、Gerber、装配/CAM图；见[说明](manufacturing/README.md) |
| `references/` | 器件原厂图纸及工艺依据，路径和内容保留 |
| `scripts/` | 当前只读审核/渲染工具及解析依赖；见[说明](scripts/README.md) |
| `archive/` | 旧工程快照、候选、制造包、报告、一次性生成器和整理恢复资料 |

## 查找旧文件

本轮归档[目录说明](archive/历史资料与工具_20261006/README.md)，按原来的目录结构保存。[移动清单](archive/目录整理_20261006/移动清单.json)记录641个移动文件的原址、现址、大小、SHA256；所有移动均已核对字节。原有更早archive保持。

历史报告中的路径和“当前”仅描述当时版本。需要旧文件时按清单单独取出，避免整体覆盖现工程；不得重跑旧生成器。整理前完整[交接原件](archive/目录整理_20261006/整理前原件/CAD_HANDOFF.md)及[文件总清单](archive/目录整理_20261006/整理前文件清单.json)保留。
''')
(R/'easyeda_std/README.md').write_text('''# 当前 EDA 原生资料

唯一工作PCB：`圆形传感板_SCH_A5` → `06 当前PCB_圆形传感板_A5`，文档ID `cca094630ebf453c98ae64b900f0d7f0`。本地当前资料全部在`Q1直接修复_20261006/`。

| 类型 | 文件 |
|---|---|
| 当前PCB | `PCB_Q1直接修复_孔距收尾_保存重开_20261006.json` |
| 保存后恢复点 | `PCB_Q1直接修复_孔距收尾_原生保存后_20261006.json` |
| 当前五页SCH | `SCH_Q1替料_最终五页回读_20261006.json` |
| 五页保存重开证据 | `SCH_Q1替料_五页保存重开_20261006.json` |
| 当前个人封装 | `PCBLIB_Q1_个人库保存重开_20261006.json` |
| 原生整图网表 | `SCH_Q1替料_原生整图网表_20261006.net` |
| 审核证据 | `Q1直接修复_整图逐脚核验_保存重开.json`、`Q1候选几何初筛_仅审核.json` |
| Q1改前恢复/比较输入 | `PCB_Q1修改前_原生回读_20261006.json`、`SCH_Q1修改前_五页原生回读_20261006.json`，不是当前源 |

内容和哈希沿用根目录[CAD_HANDOFF.md](../CAD_HANDOFF.md)，本轮文件移动不改变工程。旧候选/中间状态/库种子与9月、10月1–5日资料归入[历史资料](../archive/历史资料与工具_20261006/easyeda_std/)，文件字节保留。目录整理前后回读及逐文件清单位于`../archive/目录整理_20261006/`。

不得把历史JSON整批导入，不执行旧生成器覆盖当前板；原生库UUID/专用Q1脚号以交接为准。
''')
(R/'manufacturing/README.md').write_text('''# 制造资料｜仅审核

唯一当前资料：`仅审核禁止生产/Q1直接修复_20261006/`；唯一当前审阅ZIP：[圆形传感板_Q1修复最终审阅_20261006.zip](仅审核禁止生产/圆形传感板_Q1修复最终审阅_20261006.zip)。

- 先读[本轮交接](仅审核禁止生产/Q1直接修复_20261006/本轮交接_仅审核.md)和[审阅说明](仅审核禁止生产/Q1直接修复_20261006/制造审阅说明_仅审核.md)。
- 使用36件准确BOM及中心校正CPL，原生41行导出仅作为证据。ANT1原生中心与机器角度尚待厂确认。
- 唯一当前Gerber文件名含`Q1直接修复_孔距收尾`，内容未改。
- Q1脚号映射PNG及CAM全层PDF用于审阅，SHA256文件清单与ZIP核验结果在同目录。

其他历史制造包/报告、首版未收尾Q1 Gerber已归到[历史制造资料](../archive/历史资料与工具_20261006/manufacturing/仅审核禁止生产/)，禁止用于当前生产。旧报告路径通过[移动清单](../archive/目录整理_20261006/移动清单.json)查找。

博后已有共享工程权限；本地准确BOM/CPL与工艺说明用于其审核和安排打样。工厂接单/装配条件未批准，实物未验收；本任务不提交订单。
''')
(R/'scripts/README.md').write_text('''# 当前审核工具与解析依赖

只保留对当前文件做只读分析/渲染的工具；输出审核资料，不写CAD或云端。当前输入与哈希见根目录CAD_HANDOFF.md。不要为目录整理重复运行电气审核；既有报告已保留。

| 工具 | 用途 |
|---|---|
| `audit_final_review_snapshot.py` | 显式指定两个PCB快照做差异比较 |
| `audit_current_netlist.py` | 显式输入五页SCH/PCB/原生网表，逐脚比对 |
| `audit_current_cam.py` | 显式输入PCB/新旧Gerber，有限CAM对照 |
| `audit_q1_direct_fix_20261006.py` | Q1局部几何；默认已改为最终源，输出同名审核JSON，重跑前保留旧报告 |
| `audit_q1_saved_outputs_20261006.py` | 最终Q1源/输出增量审核；历史输入路径已指向archive，只提取历史脚本的两项纯几何函数。会重写准确CSV/核验报告，确有设计变化时才运行 |
| `render_review_cam.py` / `render_review_assembly.py` | 显式输入Gerber或PCB，生成本地审阅图 |

`check_pcb_a5.py`、`audit_clone_connector_s_20260929.py`、`audit_a5_routed_snapshot.py`、`audit_a5_ufl_keepout.py`是保留的原格式解析/几何依赖，名称仍旧，字节不变。**仅导入所需解析函数，不独立运行其历史主程序、probe_local或历史审核默认输入**；那些入口引用旧输入/生成器。

其余一次性生成器、旧审核/测试脚本、缓存完整归到`../archive/历史资料与工具_20261006/scripts/`，按移动清单恢复到独立目录后才能用于指定历史对照，禁止覆盖当前板。目录整理未执行旧生成器。
''')
(R/H/'README.md').write_text('''# 历史资料与工具｜2026-10-06归档

仅供追溯、比较、恢复；不是当前制造入口。

按整理前的相对目录结构保存根目录专题报告、easyeda_std旧源码/候选/封装、manufacturing旧审阅包/审核、scripts旧工具和tmp渲染。每个文件移动前后SHA256及大小均已核对，没有永久删除。

当前入口见工程根目录README.md；逐文件原址→现址→SHA256见`../目录整理_20261006/移动清单.json`。旧报告内路径和“当前”保持当时记录，不重写历史；本轮归档路径在原址前加`archive/历史资料与工具_20261006/`（以清单为准）。

原有archive下的更早恢复树、下载ZIP保持。目录整理前原件及完整交接、文件总清单在`../目录整理_20261006/`。

只取所需历史文件到独立目录比较，禁止整批还原覆盖当前源；不重跑旧生成器。首版Q1未收尾Gerber在本归档对应`manufacturing/仅审核禁止生产/Q1直接修复_20261006/历史中间版_孔距未收尾_禁止制造/`，禁止制造。
''')
print('Current entry documents and two audit input paths updated. Historical source/report bytes retained.')
