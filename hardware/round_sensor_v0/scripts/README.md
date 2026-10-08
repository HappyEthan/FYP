# 当前审核工具与解析依赖

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
