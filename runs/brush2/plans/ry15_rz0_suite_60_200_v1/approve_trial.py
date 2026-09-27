#!/usr/bin/env python3
"""Confirm this trial's settings locally; never import or connect to hardware."""
import json
from datetime import datetime, timezone
from pathlib import Path


def main():
    folder = Path(__file__).resolve().parent
    table_path = folder / "feedforward.json"
    settings_path = folder / "settings.json"
    table = json.loads(table_path.read_text(encoding="utf-8"))
    settings = json.loads(settings_path.read_text(encoding="utf-8"))

    print("本次：brush2，Ry15/Rz0，60–200 uT，前三条计划。")
    print("请现场核验 TCP_brush/Base、接触零点 Z=40 mm、路径净空。")
    print("等待位姿：XYZ=(-200,500,130) mm，RPY=(0,15,0) 度。")
    print("确认表示接受候选前馈及动态过渡试验，不表示性能已验证。")
    try:
        answer = input("核验完成后输入 CONFIRM；其他输入取消：").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n已取消，配置未修改。")
        return
    if answer != "CONFIRM":
        print("已取消，配置未修改。")
        return

    stamp = datetime.now(timezone.utc).isoformat()
    table.update(approved=True, transient_approved=True, approved_at=stamp)
    table["approval_note"] = (
        "Operator-approved experimental trial: profiles 01-03, 60-200 uT; "
        "not performance validation.")
    settings.update(verified=True, verified_at=stamp)
    settings["provenance"] = (
        "Operator confirmed current installation, contact reference and clearance.")
    for path, data in ((table_path, table), (settings_path, settings)):
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8")
        temporary.replace(path)
    print("三个试验标志已启用。未连接机械臂；现在可以运行单条执行命令。")


if __name__ == "__main__":
    main()
