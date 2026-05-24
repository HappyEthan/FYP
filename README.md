# FYP — 多模态融合 AI 书法教学与评估系统

## 项目概述

本项目构建书法 AI 系统的数据基础层：**笔画类别库** 和 **相机 OCR 识别管线**。为后续触觉数据标注和 Transformer 模型训练提供基础数据能力。

## 环境要求

- [pixi](https://pixi.sh)（Python 环境与依赖管理）
- Windows / Linux / macOS

## 快速开始

```bash
# 1. 安装依赖（自动创建隔离环境）
pixi install

# 2. 下载 Make Me a Hanzi 原始数据
pixi run download-data

# 3. 构建笔画类别库
pixi run build-taxonomy

# 4. 运行全部测试
pixi run test
```

## 项目结构

```
FYP/
├── data/stroke_taxonomy/
│   ├── stroke_taxonomy.json    # 笔画类别库（9574 字符, 29 笔画类型）
│   └── raw/                    # Make Me a Hanzi 原始数据（gitignore）
├── src/
│   ├── stroke_taxonomy/
│   │   ├── stroke_names.py     # 29 类笔画定义（基本/钩/折/复合）
│   │   ├── parser.py           # 数据解析 + SVG 几何笔画分类
│   │   └── taxonomy.py         # 笔画类别库查询接口
│   └── ocr/
│       ├── recognizer.py       # PaddleOCR 封装（单字识别）
│       └── pipeline.py         # 端到端标注管线（OCR → 查库 → 笔画序列）
├── tests/                      # 39 个单元测试
├── scripts/
│   ├── download_data.py        # 下载 Make Me a Hanzi 数据
│   └── build_taxonomy.py       # 构建笔画类别库 JSON
├── docs/superpowers/
│   ├── specs/                  # 需求规格说明书
│   └── plans/                  # 实现计划
├── pyproject.toml              # pixi 项目配置
└── pytest.ini
```

## pixi 任务

| 命令 | 作用 |
|------|------|
| `pixi run test` | 运行全部 39 个测试 |
| `pixi run test-parser` | 只跑解析器测试 |
| `pixi run test-taxonomy` | 只跑类别库查询测试 |
| `pixi run test-ocr` | 只跑 OCR 识别器测试 |
| `pixi run test-pipeline` | 只跑端到端管线测试 |
| `pixi run test-download` | 只跑数据下载测试 |
| `pixi run download-data` | 下载 Make Me a Hanzi 原始数据 |
| `pixi run build-taxonomy` | 从原始数据构建笔画类别库 JSON |
| `pixi shell` | 进入隔离环境 shell |

## 核心模块使用示例

### 1. 笔画类别库查询

```python
from src.stroke_taxonomy.taxonomy import StrokeTaxonomy

tax = StrokeTaxonomy("data/stroke_taxonomy/stroke_taxonomy.json")

# 查询某个字的笔画序列
tax.get_char_strokes("永")           # [4, 14, 15, 2, 3]
tax.get_char_strokes_with_names("永") # ["点", "横折钩", "横撇", "撇", "捺"]

# 查询笔画信息
tax.get_stroke(0)                     # {"id": 0, "name": "横", "stroke_type": "basic", ...}
tax.get_stroke_name(14)               # "横折钩"

# 按类型筛选
tax.get_strokes_by_type("basic")      # 6 个基本笔画
tax.get_strokes_by_type("compound")   # 15 个复合笔画

# 统计
tax.num_strokes()                     # 29
tax.get_stroke_count("永")            # 5
```

### 2. OCR 单字识别

```python
from src.ocr.recognizer import CalligraphyOCR

ocr = CalligraphyOCR(confidence_threshold=0.5)

# 从文件识别
char = ocr.recognize_from_file("path/to/calligraphy_photo.png")
print(char)  # "永"

# 从 numpy 数组识别
import cv2
img = cv2.imread("photo.png")
char = ocr.recognize(img)
```

### 3. 端到端标注管线

```python
from src.ocr.pipeline import AnnotationPipeline

pipeline = AnnotationPipeline(
    taxonomy_path="data/stroke_taxonomy/stroke_taxonomy.json",
    ocr_confidence_threshold=0.5,
)

# 标注一张书法字照片
result = pipeline.annotate_from_file("photo.png")
print(result)
# {
#     "char": "永",
#     "stroke_ids": [4, 14, 15, 2, 3],
#     "stroke_names": ["点", "横折钩", "横撇", "撇", "捺"],
#     "stroke_count": 5,
# }
```

## 笔画类别体系（29 类）

| 大类 | 笔画 | 数量 |
|------|------|------|
| 基本笔画 | 横、竖、撇、捺、点、提 | 6 |
| 钩类 | 竖钩、弯钩、斜钩、卧钩、横钩 | 5 |
| 折类 | 横折、竖折、撇折 | 3 |
| 复合笔画 | 横折钩、横撇、横撇弯钩、横折弯钩、竖折折钩、横折折撇、竖提、撇点、横折提、横折弯、竖弯、竖弯钩、横斜钩、横折折折钩、横折折 | 15 |

## 数据来源

- [Make Me a Hanzi](https://github.com/skishore/makemeahanzi) — 汉字笔画拆解与 SVG 路径数据
- 《现代汉语通用字笔顺规范》— 国家语委笔顺标准

## 技术栈

- Python 3.11+（pixi 隔离环境）
- PaddleOCR（中文手写体识别）
- OpenCV（图像处理）
- PyTorch（为后续 Transformer 模型预留）
- pytest（测试框架）

## 已完成

- [x] 笔画类别库（9574 字符，29 笔画类型）
- [x] Make Me a Hanzi 数据下载与解析
- [x] SVG 几何笔画分类器
- [x] PaddleOCR 单字识别封装
- [x] OCR + 笔画类别库端到端标注管线
- [x] pixi 隔离环境管理
- [x] 39 个单元测试全部通过

## 待开发

- [ ] 视觉质量评估（传统图像处理方案）
- [ ] 笔画分割算法
- [ ] 触觉数据采集模块（依赖传感器硬件）
- [ ] Transformer 笔画识别与质量评估模型
- [ ] 笔迹还原可视化
