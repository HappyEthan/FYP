# 手采批次

- `raw/`：按开始/停止录制生成的 CSV 和同名 JSON；保留原样。CSV 是未经显示平滑的三轴 ΔB，JSON 保存基线和采样质量。原始 B 可由 ΔB + B0 重建，但这里没有保存完整原始串口报文。
- `media/`：照片和视频。建议与对应磁记录同名前缀，例如 `<recording_id>_ink.jpeg`、`<recording_id>_top.mp4`。
- `analysis/`：裁剪、滤波、拟合、图表等派生结果，不覆盖 raw。
- `records.csv`：每条录制一行，可填写动作类型、照片、视频及备注。照片和视频路径相对本批目录。自动更新时保留已填写的 action/photo/video/note。
- `session.json`：补填纸张、墨/水、蘸水方式和姿态。未知条件保持 null，不以计划值代替实测。

每条记录单独按一次开始/停止，按实际动作填写 `dot`（顿笔）、`dot_retract`（顿笔短收）、`heng`（横）或自定义标签。
开始前悬空静止取基线；一条动作结束再停止，保留少量前后空载数据。视频默认未同步，不能直接当作机器人 XY 或同步 TCP 示教。

重新打开本批：

```bash
cd /home/serein/FYP
QT_QPA_PLATFORM=wayland PYTHONPATH=src .venv/bin/python scripts/record_manual_brush.py --session "/home/serein/FYP/runs/brush2/manual/2026-10-23/15-04-13_103314__dunbi"
```
