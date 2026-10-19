#!/usr/bin/env python3
"""Render the Chinese daily report from its single Markdown source, offline."""
import base64
import csv
import hashlib
import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote
from zoneinfo import ZoneInfo

os.environ.setdefault("MPLCONFIGDIR", "/tmp/fyp-matplotlib")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from markdown_it import MarkdownIt

OUT = Path(__file__).resolve().parent
BASE = OUT.parent.parent
ROOT = BASE.parents[3]
DOCUMENT = ROOT / "docs/08-system-evaluation/four-direction-experiment-report-2026-10-05.md"
BENCHMARK = OUT.parent / "directional_calibration_benchmark"
NAMES = dict(right="+X", up="+Y", left="−X", down="−Y")
COLORS = dict(right="#2474b5", up="#d47c2c", left="#7855a3", down="#238774")
CUTOFF = "20261005T074054.304822Z-1014ac"


def csv_rows(path):
    return list(csv.DictReader(path.open(encoding="utf-8-sig")))


def local_time(value):
    return datetime.fromisoformat(value).astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")


def main():
    summary = json.loads((BENCHMARK/"metrics.json").read_text())
    candidates = json.loads((BENCHMARK/"directional_calibration.json").read_text())
    for filename, digest in summary["input_sha256"].items():
        assert hashlib.sha256((BASE/filename).read_bytes()).hexdigest() == digest, filename
    assert hashlib.sha256((BENCHMARK/"analyze.py").read_bytes()).hexdigest() == summary["generator_sha256"]
    quality = csv_rows(OUT.parent/"stage3_review/run_quality.csv")
    heights = csv_rows(OUT.parent/"stage3_review/height_repeatability.csv")
    speed_pairs = csv_rows(OUT.parent/"stage2_review/hold_repeatability.csv")
    stats = {r["run_id"]:r for r in quality}
    index, raw_ids, matched_keys, source_hashes = [], [], set(), {}
    for path in sorted((BASE/"raw").glob("*/manifest.json")):
        manifest = json.loads(path.read_text())
        if manifest["run_id"] > CUTOFF:
            continue
        assert manifest["status"] == "completed" and manifest["execution_environment"] == "hardware"
        profile = json.loads((path.parent/"identification.json").read_text())
        resolved = json.loads((path.parent/"resolved.json").read_text())
        matched_keys.add((resolved["batch_id"], resolved["trial_index"]))
        run_id = manifest["run_id"]
        raw_ids.append(run_id)
        hold = profile["mode"] == "four-direction-hold"
        use = ("核心建模与互换测试" if run_id in candidates["train_run_ids"] else
               "加载路径迁移检查" if not hold else
               "速度迁移检查" if profile["speed_mm_s"] != 10 else "旧 X 参照检查")
        index.append({"开始时间（北京时间）":local_time(manifest["started_at"]),
                      "结束时间（北京时间）":local_time(manifest["finished_at"]),
                      "方向":NAMES[profile["direction"]], "实验类型":"定高" if hold else "半程下压",
                      "速度（mm/s）":profile["speed_mm_s"],
                      "命令起始Z（mm）":profile["start_z_mm"], "命令结束Z（mm）":profile["end_z_mm"],
                      "30至120mm中位数（µT）":stats[run_id]["primary_median_uT"],
                      "分析用途":use, "运行状态":"完成", "run_id":run_id,
                      "原始记录目录":path.parent.name})
    assert len(index) == 48 and set(raw_ids) == set(stats)
    index.sort(key=lambda r:r["run_id"])
    with (OUT/"run_index.csv").open("w",newline="",encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream,fieldnames=list(index[0]))
        writer.writeheader();writer.writerows(index)
    positioning = []
    for path in sorted((BASE/"positioning").glob("*.json")):
        row = json.loads(path.read_text())
        key = (row["context"]["batch_id"],row["context"]["trial_index"])
        positioning.append(dict(file=path.name,status=row["status"],started_at=row["started_at"],
                                matched_measurement=key in matched_keys,error=row.get("error")))
        source_hashes[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    assert Counter(r["status"] for r in positioning) == {"completed":49,"failed":3}
    assert sum(r["matched_measurement"] for r in positioning) == 48
    plt.rcParams.update({"font.family":"Noto Sans CJK SC","font.size":10,
                         "axes.spines.top":False,"axes.spines.right":False})
    fig, axes = plt.subplots(2,2,figsize=(12,8),layout="constrained")
    for ax, direction in zip(axes.flat,NAMES):
        selected = sorted([r for r in speed_pairs if r["direction"] == direction],key=lambda r:float(r["speed_mm_s"]))
        assert len(selected) == 3
        x = [float(r["speed_mm_s"]) for r in selected]
        for field,label,color in (("round1_median_uT","第一轮中段中位数","#2474b5"),
                                 ("round2_median_uT","第二轮中段中位数","#d47c2c")):
            ax.plot(x,[float(r[field]) for r in selected],"o-",color=color,label=label)
        ax.set(title=f"{NAMES[direction]} 方向，命令 Z30",xlabel="行笔速度（mm/s）",ylabel="中段磁响应（µT）")
        ax.set_xticks([7,10,15]);ax.grid(alpha=.2);ax.legend(fontsize=9)
    fig.suptitle("Z30 速度实验：两轮独立笔次，主窗口 30–120 mm",fontsize=14)
    fig.savefig(OUT/"01_speed_comparison.png",dpi=155);plt.close(fig)
    fig, ax = plt.subplots(figsize=(11,6.5),layout="constrained")
    for direction in NAMES:
        selected = sorted([r for r in heights if r["direction"] == direction],key=lambda r:-float(r["command_z_mm"]))
        assert len(selected) == 3
        x = np.array([40-float(r["command_z_mm"]) for r in selected])
        a = np.array([float(r["run1_median_uT"]) for r in selected])
        b = np.array([float(r["run2_median_uT"]) for r in selected])
        ax.plot(x,(a+b)/2,"o-",color=COLORS[direction],label=f"{NAMES[direction]}：两笔等权均值")
        ax.fill_between(x,np.minimum(a,b),np.maximum(a,b),color=COLORS[direction],alpha=.12)
    old_x = [r for r in index if r["分析用途"] == "旧 X 参照检查"]
    assert len(old_x) == 2
    ax.scatter([10]*2,[float(r["30至120mm中位数（µT）"]) for r in old_x],marker="x",s=90,
               color="#666666",linewidths=2,label="旧批次 +X/Z30：不并入新 X 曲线")
    ax.set(title="四方向高度响应：色带为两笔范围，非置信区间",xlabel="名义压深 d＝40−命令 Z（mm）",ylabel="中段磁响应（µT）")
    ax.set_xticks([5,10,13],["5（Z35）","10（Z30）","13（Z27）"])
    ax.grid(alpha=.2);ax.legend(fontsize=9,loc="upper left")
    fig.savefig(OUT/"02_height_response.png",dpi=155);plt.close(fig)
    source = DOCUMENT.read_text()
    assert source.startswith("---\n")
    body = source.split("---",2)[2].strip()
    renderer = MarkdownIt("commonmark",{"html":True}).enable("table")
    tokens = renderer.parse(body)
    image_count = 0
    for token in tokens:
        for child in token.children or []:
            if child.type == "image":
                target = (DOCUMENT.parent/unquote(child.attrGet("src"))).resolve()
                assert target.is_file(),target
                child.attrSet("src","data:image/png;base64,"+base64.b64encode(target.read_bytes()).decode())
                source_hashes[str(target.relative_to(ROOT))] = hashlib.sha256(target.read_bytes()).hexdigest()
                image_count += 1
            elif child.type == "link_open":
                href = child.attrGet("href")
                if not href.startswith(("http:","https:","#")):
                    target = (DOCUMENT.parent/unquote(href)).resolve()
                    assert target.exists(),target
                    child.attrSet("href",os.path.relpath(target,OUT))
    assert image_count == 4
    contents = renderer.renderer.render(tokens,renderer.options,{})
    css = 'body{max-width:1100px;margin:auto;padding:28px;font:16px/1.75 "Noto Sans CJK SC","Microsoft YaHei",sans-serif;color:#233548}h1{font-size:28px}h2{margin-top:34px;border-bottom:1px solid #dfe5eb;padding-bottom:8px}h3{font-size:19px}table{border-collapse:collapse;width:100%;font-size:14px;margin:18px 0}td,th{padding:8px;border-bottom:1px solid #dfe5eb;text-align:left;vertical-align:top}th{background:#f2f5f8}img{max-width:100%;height:auto}a{color:#226fa4}pre{background:#f2f5f8;padding:14px;white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}code{font-size:.9em}@media print{body{padding:0;font-size:11pt}h2,h3{break-after:avoid}img,tr{break-inside:avoid}a{color:inherit;text-decoration:none}}'
    page = '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>2026-10-05 四方向、速度与下压高度实验报告</title><style>'+css+'</style></head><body>'+contents+'</body></html>'
    (OUT/"index.html").write_text(page,encoding="utf-8")
    for path in [DOCUMENT,BENCHMARK/"metrics.json",BENCHMARK/"directional_calibration.json",
                 OUT.parent/"stage3_review/run_quality.csv",OUT.parent/"stage3_review/height_repeatability.csv",
                 OUT.parent/"stage2_review/hold_repeatability.csv",OUT.parent/"stage2_review/speed_contrasts.csv",
                 Path(__file__)]:
        source_hashes[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    (OUT/"report_source.json").write_text(json.dumps(dict(date="2026-10-05",timezone="Asia/Shanghai",
         canonical_document=str(DOCUMENT.relative_to(ROOT)),run_count=48,first_start=index[0]["开始时间（北京时间）"],
         last_finish=index[-1]["结束时间（北京时间）"],run_ids=raw_ids,positioning=positioning,
         raw_hashes_verified=len(summary["input_sha256"]),source_sha256=source_hashes,
         figures_embedded=image_count,scope="hardware records + retrospective offline calibration; no new hardware execution"),
         ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(dict(document=str(DOCUMENT),html=str(OUT/"index.html"),runs=len(index),
                          embedded_figures=image_count,raw_hashes_verified=len(summary["input_sha256"])),ensure_ascii=False))


if __name__ == "__main__":
    main()
