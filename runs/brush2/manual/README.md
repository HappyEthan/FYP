# brush2 手采实验

按 `日期/时间__批次名/` 保存手持毛笔的录制，与日期目录下的机器人执行实验分开。
新建批次：`PYTHONPATH=src .venv/bin/python scripts/record_manual_brush.py --label dunbi`。
每批保留 raw、media、analysis、session.json、records.csv 和操作说明。未录制的空批次不算实测数据。
