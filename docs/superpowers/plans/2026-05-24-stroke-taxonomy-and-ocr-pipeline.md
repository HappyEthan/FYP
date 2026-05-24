# 笔画类别库 & 相机 OCR 识别管线 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建笔画类别库数据文件和相机 OCR 识别管线，为后续触觉数据标注和模型训练提供基础数据能力。

**Architecture:** 笔画类别库从 Make Me a Hanzi 项目下载并解析原始数据，生成结构化 JSON 供下游查询。OCR 管线使用 PaddleOCR 对相机拍摄的书法字照片进行识别，输出字标签后查询笔画类别库获取标准笔画序列。两个模块通过笔画类别库耦合，独立可测。

**Tech Stack:** Python 3.10+, PaddleOCR, OpenCV, PyTorch (为后续模型预留), pytest

---

## File Structure

```
FYP/
├── data/
│   └── stroke_taxonomy/
│       ├── stroke_taxonomy.json       # 最终笔画类别库（Task 2 生成）
│       └── raw/                        # Make Me a Hanzi 原始数据（Task 1 下载）
│           ├── dictionary.txt
│           └── graphics.txt
├── src/
│   ├── __init__.py
│   ├── stroke_taxonomy/
│   │   ├── __init__.py
│   │   ├── parser.py                  # 解析 Make Me a Hanzi 原始数据
│   │   ├── taxonomy.py                # 笔画类别库查询接口
│   │   └── stroke_names.py           # 笔画名称映射（笔画拆解代码 → 中文名）
│   └── ocr/
│       ├── __init__.py
│       ├── recognizer.py              # PaddleOCR 封装，识别单字
│       └── pipeline.py                # 完整标注管线：OCR → 查库 → 输出笔画序列
├── tests/
│   ├── __init__.py
│   ├── test_parser.py                 # 解析器测试
│   ├── test_taxonomy.py               # 类别库查询测试
│   ├── test_recognizer.py             # OCR 识别测试
│   └── test_pipeline.py               # 端到端管线测试
├── scripts/
│   ├── download_data.py               # 下载 Make Me a Hanzi 数据
│   └── build_taxonomy.py              # 构建笔画类别库 JSON
├── requirements.txt
└── pytest.ini
```

---

### Task 1: 项目初始化与数据下载脚本

**Files:**
- Create: `requirements.txt`
- Create: `pytest.ini`
- Create: `src/__init__.py`
- Create: `src/stroke_taxonomy/__init__.py`
- Create: `src/ocr/__init__.py`
- Create: `tests/__init__.py`
- Create: `scripts/download_data.py`

- [ ] **Step 1: 创建项目基础文件**

创建 `requirements.txt`：

```
paddleocr>=2.7
paddlepaddle>=2.5
opencv-python>=4.8
numpy>=1.24
pytest>=7.4
requests>=2.31
```

创建 `pytest.ini`：

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_functions = test_*
```

创建空 `__init__.py` 文件：
- `src/__init__.py`
- `src/stroke_taxonomy/__init__.py`
- `src/ocr/__init__.py`
- `tests/__init__.py`

- [ ] **Step 2: 编写 download_data.py 测试**

创建 `tests/test_download_data.py`：

```python
import json
import os
import tempfile

from scripts.download_data import download_make_me_a_hanzi


def test_download_creates_files():
    """下载脚本应创建 dictionary.txt 和 graphics.txt"""
    with tempfile.TemporaryDirectory() as tmpdir:
        download_make_me_a_hanzi(output_dir=tmpdir)

        dict_path = os.path.join(tmpdir, "dictionary.txt")
        graph_path = os.path.join(tmpdir, "graphics.txt")

        assert os.path.exists(dict_path), "dictionary.txt should exist"
        assert os.path.exists(graph_path), "graphics.txt should exist"

        # 验证文件非空
        assert os.path.getsize(dict_path) > 0, "dictionary.txt should not be empty"
        assert os.path.getsize(graph_path) > 0, "graphics.txt should not be empty"

        # 验证 dictionary.txt 每行是合法 JSON
        with open(dict_path, "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
            data = json.loads(first_line)
            assert "character" in data
            assert "strokes" in data
```

- [ ] **Step 3: 运行测试确认失败**

Run: `pytest tests/test_download_data.py -v`
Expected: FAIL — `download_make_me_a_hanzi` 尚未实现

- [ ] **Step 4: 实现 download_data.py**

创建 `scripts/download_data.py`：

```python
"""下载 Make Me a Hanzi 项目数据文件。"""

import os
import json
import urllib.request

DICTIONARY_URL = "https://raw.githubusercontent.com/skishore/makemeahanzi/master/dictionary.txt"
GRAPHICS_URL = "https://raw.githubusercontent.com/skishore/makemeahanzi/master/graphics.txt"


def download_make_me_a_hanzi(output_dir: str) -> None:
    """下载 dictionary.txt 和 graphics.txt 到指定目录。

    Args:
        output_dir: 目标目录路径，不存在则创建。
    """
    os.makedirs(output_dir, exist_ok=True)

    dict_path = os.path.join(output_dir, "dictionary.txt")
    graph_path = os.path.join(output_dir, "graphics.txt")

    for url, path in [(DICTIONARY_URL, dict_path), (GRAPHICS_URL, graph_path)]:
        if not os.path.exists(path):
            print(f"Downloading {url} ...")
            urllib.request.urlretrieve(url, path)
            print(f"Saved to {path}")
        else:
            print(f"Already exists: {path}")

    # 验证下载的文件是合法的 JSON Lines 格式
    for path in [dict_path]:
        with open(path, "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
            json.loads(first_line)  # 如果格式错误会抛异常


if __name__ == "__main__":
    import sys
    output_dir = sys.argv[1] if len(sys.argv) > 1 else "data/stroke_taxonomy/raw"
    download_make_me_a_hanzi(output_dir)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/test_download_data.py -v`
Expected: PASS（注意：此测试需要网络访问，CI 环境可能需要 mock）

- [ ] **Step 6: 运行脚本下载数据**

Run: `python scripts/download_data.py data/stroke_taxonomy/raw`
Expected: `data/stroke_taxonomy/raw/dictionary.txt` 和 `graphics.txt` 被创建

- [ ] **Step 7: Commit**

```bash
git add requirements.txt pytest.ini src/ tests/ scripts/download_data.py data/stroke_taxonomy/raw/
git commit -m "feat: project init with data download script and base structure"
```

---

### Task 2: 笔画类别库解析器

**Files:**
- Create: `src/stroke_taxonomy/parser.py`
- Create: `src/stroke_taxonomy/stroke_names.py`
- Create: `tests/test_parser.py`

Make Me a Hanzi 的数据格式说明：
- `dictionary.txt`：每行一个 JSON 对象，含 `character`（汉字）、`strokes`（笔画拆解代码列表，如 `["横","竖"]` 实际是编码）
- `graphics.txt`：每行一个 JSON 对象，含 `character`（汉字）、`strokes`（SVG 路径字符串列表）

笔画拆解代码遵循一套约定（如 `1` = 横，`2` = 竖 等），但 Make Me a Hanzi 的 `strokes` 字段实际存储的是 SVG 路径字符串而非编码数字。本任务需要解析这些 SVG 路径，分类到笔画类别体系中。

- [ ] **Step 1: 编写笔画名称映射模块**

创建 `src/stroke_taxonomy/stroke_names.py`：

```python
"""笔画名称映射：将中文笔画名称映射到类别 ID 和类型。

笔画类别体系基于《现代汉语通用字笔顺规范》和书法教材。
"""

from dataclasses import dataclass


@dataclass
class StrokeInfo:
    """单个笔画类别的信息。"""
    id: int
    name: str
    name_pinyin: str
    stroke_type: str  # "basic", "hook", "fold", "compound"
    description: str


# 笔画类别定义（~29 类）
STROKES: list[StrokeInfo] = [
    # 基本笔画 (6)
    StrokeInfo(id=0, name="横", name_pinyin="heng", stroke_type="basic", description="从左向右的水平笔画"),
    StrokeInfo(id=1, name="竖", name_pinyin="shu", stroke_type="basic", description="从上向下的竖直笔画"),
    StrokeInfo(id=2, name="撇", name_pinyin="pie", stroke_type="basic", description="从右上向左下的斜笔画"),
    StrokeInfo(id=3, name="捺", name_pinyin="na", stroke_type="basic", description="从左上向右下的斜笔画"),
    StrokeInfo(id=4, name="点", name_pinyin="dian", stroke_type="basic", description="短促的小笔画"),
    StrokeInfo(id=5, name="提", name_pinyin="ti", stroke_type="basic", description="从左下向右上的短笔画"),
    # 钩类 (5)
    StrokeInfo(id=6, name="竖钩", name_pinyin="shugou", stroke_type="hook", description="竖画末端带钩"),
    StrokeInfo(id=7, name="弯钩", name_pinyin="wangou", stroke_type="hook", description="弯折后带钩"),
    StrokeInfo(id=8, name="斜钩", name_pinyin="xiegou", stroke_type="hook", description="斜画末端带钩"),
    StrokeInfo(id=9, name="卧钩", name_pinyin="wogou", stroke_type="hook", description="底部平卧带钩"),
    StrokeInfo(id=10, name="横钩", name_pinyin="henggou", stroke_type="hook", description="横画末端带钩"),
    # 折类 (3)
    StrokeInfo(id=11, name="横折", name_pinyin="hengzhe", stroke_type="fold", description="横画后折向下方"),
    StrokeInfo(id=12, name="竖折", name_pinyin="shuzhe", stroke_type="fold", description="竖画后折向右方"),
    StrokeInfo(id=13, name="撇折", name_pinyin="piezhe", stroke_type="fold", description="撇画后折向右方"),
    # 复合笔画 (15)
    StrokeInfo(id=14, name="横折钩", name_pinyin="hengzhegou", stroke_type="compound", description="横折后带钩"),
    StrokeInfo(id=15, name="横撇", name_pinyin="hengpie", stroke_type="compound", description="横画后接撇画"),
    StrokeInfo(id=16, name="横撇弯钩", name_pinyin="hengpiewangou", stroke_type="compound", description="横撇弯后带钩"),
    StrokeInfo(id=17, name="横折弯钩", name_pinyin="hengzhewangou", stroke_type="compound", description="横折弯后带钩"),
    StrokeInfo(id=18, name="竖折折钩", name_pinyin="shuzhezhegou", stroke_type="compound", description="竖折折后带钩"),
    StrokeInfo(id=19, name="横折折撇", name_pinyin="hengzhezhelipe", stroke_type="compound", description="横折折后接撇"),
    StrokeInfo(id=20, name="竖提", name_pinyin="shuti", stroke_type="compound", description="竖画后上提"),
    StrokeInfo(id=21, name="撇点", name_pinyin="piedian", stroke_type="compound", description="撇画后接点"),
    StrokeInfo(id=22, name="横折提", name_pinyin="hengzeti", stroke_type="compound", description="横折后上提"),
    StrokeInfo(id=23, name="横折弯", name_pinyin="hengzhewan", stroke_type="compound", description="横折后弯折"),
    StrokeInfo(id=24, name="竖弯", name_pinyin="shuwan", stroke_type="compound", description="竖画后弯曲"),
    StrokeInfo(id=25, name="竖弯钩", name_pinyin="shuwangou", stroke_type="compound", description="竖弯后带钩"),
    StrokeInfo(id=26, name="横斜钩", name_pinyin="hengxiegou", stroke_type="compound", description="横画后斜带钩"),
    StrokeInfo(id=27, name="横折折折钩", name_pinyin="hengzhezhezhegou", stroke_type="compound", description="横折折折后带钩"),
    StrokeInfo(id=28, name="横折折", name_pinyin="hengzhezhe", stroke_type="compound", description="横折后再折"),
]

# 名称到 ID 的映射，方便查询
NAME_TO_ID: dict[str, int] = {s.name: s.id for s in STROKES}
ID_TO_STROKE: dict[int, StrokeInfo] = {s.id: s for s in STROKES}

# 笔画类型列表
STROKE_TYPES = ["basic", "hook", "fold", "compound"]
```

- [ ] **Step 2: 编写解析器测试**

创建 `tests/test_parser.py`：

```python
import json
import os
import tempfile

import pytest

from src.stroke_taxonomy.parser import (
    classify_stroke_by_svg,
    parse_dictionary,
    parse_graphics,
    build_taxonomy,
)


@pytest.fixture
def sample_dictionary_content():
    """模拟 dictionary.txt 内容。"""
    return (
        '{"character": "一", "strokes": ["横"], "random": true}\n'
        '{"character": "永", "strokes": ["点", "横折钩", "横撇", "撇", "捺"]}\n'
    )


@pytest.fixture
def sample_graphics_content():
    """模拟 graphics.txt 内容。"""
    return (
        '{"character": "一", "strokes": ["M 0 0 L 100 0"]}\n'
        '{"character": "永", "strokes": ["M 50 0 L 50 50", "M 0 0 L 80 0 L 80 60 L 75 55", "M 80 0 L 0 100", "M 50 50 L 0 100", "M 50 50 L 100 100"]}\n'
    )


@pytest.fixture
def dict_file(sample_dictionary_content, tmp_path):
    p = tmp_path / "dictionary.txt"
    p.write_text(sample_dictionary_content, encoding="utf-8")
    return str(p)


@pytest.fixture
def graph_file(sample_graphics_content, tmp_path):
    p = tmp_path / "graphics.txt"
    p.write_text(sample_graphics_content, encoding="utf-8")
    return str(p)


class TestParseDictionary:
    def test_parse_returns_char_to_strokes(self, dict_file):
        result = parse_dictionary(dict_file)
        assert "一" in result
        assert "永" in result

    def test_strokes_are_chinese_names(self, dict_file):
        result = parse_dictionary(dict_file)
        assert result["一"] == ["横"]
        assert result["永"] == ["点", "横折钩", "横撇", "撇", "捺"]

    def test_empty_file_returns_empty(self, tmp_path):
        p = tmp_path / "empty.txt"
        p.write_text("", encoding="utf-8")
        result = parse_dictionary(str(p))
        assert result == {}


class TestParseGraphics:
    def test_parse_returns_svg_paths(self, graph_file):
        result = parse_graphics(graph_file)
        assert "一" in result
        assert "永" in result

    def test_svg_paths_are_lists(self, graph_file):
        result = parse_graphics(graph_file)
        assert isinstance(result["一"], list)
        assert len(result["一"]) == 1  # "一" 只有 1 个笔画

    def test_yong_has_five_strokes(self, graph_file):
        result = parse_graphics(graph_file)
        assert len(result["永"]) == 5


class TestClassifyStroke:
    def test_heng_classified_as_basic(self):
        # 横画: 大致从左到右的水平线
        svg = "M 0 0 L 100 0"
        result = classify_stroke_by_svg(svg)
        assert result in [0]  # 横 = id 0

    def test_shu_classified_as_basic(self):
        # 竖画: 大致从上到下的竖直线
        svg = "M 50 0 L 50 100"
        result = classify_stroke_by_svg(svg)
        assert result in [1]  # 竖 = id 1


class TestBuildTaxonomy:
    def test_build_taxonomy_json(self, dict_file, graph_file):
        output_path = os.path.join(tmp_path_dir := tempfile.mkdtemp(), "stroke_taxonomy.json")
        result = build_taxonomy(dict_file, graph_file, output_path)

        assert os.path.exists(output_path)
        with open(output_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert "strokes" in data
        assert "char_to_strokes" in data
        assert len(data["strokes"]) == 29  # 笔画类别数

        # "一" 的笔画序列应该是 [0]（横的 id）
        assert data["char_to_strokes"]["一"] == [0]
```

- [ ] **Step 3: 运行测试确认失败**

Run: `pytest tests/test_parser.py -v`
Expected: FAIL — 模块尚未实现

- [ ] **Step 4: 实现解析器 parser.py**

创建 `src/stroke_taxonomy/parser.py`：

```python
"""解析 Make Me a Hanzi 数据文件，构建笔画类别库。

Make Me a Hanzi 数据格式：
- dictionary.txt: 每行一个 JSON 对象 {"character": "永", "strokes": ["点","横折钩","横撇","撇","捺"]}
- graphics.txt: 每行一个 JSON 对象 {"character": "永", "strokes": ["M 50 0 L 50 50", ...]}
"""

import json
import math
import re
from typing import Optional

from src.stroke_taxonomy.stroke_names import NAME_TO_ID, STROKES


def parse_dictionary(file_path: str) -> dict[str, list[str]]:
    """解析 dictionary.txt，返回 {汉字: [笔画名称列表]}。"""
    result: dict[str, list[str]] = {}
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                char = data["character"]
                strokes = data["strokes"]
                result[char] = strokes
            except (json.JSONDecodeError, KeyError):
                continue
    return result


def parse_graphics(file_path: str) -> dict[str, list[str]]:
    """解析 graphics.txt，返回 {汉字: [SVG 路径字符串列表]}。"""
    result: dict[str, list[str]] = {}
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                char = data["character"]
                strokes = data["strokes"]
                result[char] = strokes
            except (json.JSONDecodeError, KeyError):
                continue
    return result


def _parse_svg_commands(svg: str) -> list[tuple[str, list[float]]]:
    """从 SVG path 字符串中提取命令和坐标。

    Returns:
        [(command, [x1, y1, x2, y2, ...]), ...]
    """
    commands = []
    # 匹配 SVG path 命令及其后续数字
    pattern = r"([MLHVCSQTAZmlhvcsqtaz])([^MLHVCSQTAZmlhvcsqtaz]*)"
    for match in re.finditer(pattern, svg):
        cmd = match.group(1)
        nums_str = match.group(2).strip()
        nums = [float(x) for x in re.findall(r"[-+]?[\d]*\.?[\d]+", nums_str)] if nums_str else []
        commands.append((cmd, nums))
    return commands


def _svg_bounding_box(svg: str) -> tuple[float, float, float, float]:
    """计算 SVG 路径的边界框 (min_x, min_y, max_x, max_y)。"""
    commands = _parse_svg_commands(svg)
    points: list[tuple[float, float]] = []
    cx, cy = 0.0, 0.0

    for cmd, nums in commands:
        if cmd == "M":
            cx, cy = nums[0], nums[1]
            points.append((cx, cy))
        elif cmd == "L":
            cx, cy = nums[0], nums[1]
            points.append((cx, cy))
        elif cmd == "m":
            cx += nums[0]
            cy += nums[1]
            points.append((cx, cy))
        elif cmd == "l":
            cx += nums[0]
            cy += nums[1]
            points.append((cx, cy))

    if not points:
        return (0, 0, 0, 0)

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def classify_stroke_by_svg(svg: str) -> int:
    """根据 SVG 路径的几何特征分类笔画。

    使用启发式规则分析 SVG 路径的形状特征（方向、转折）来判断笔画类型。
    这是简化的分类方法 — 对于复合笔画，主要依赖 dictionary.txt 中的
    笔画名称来分类，SVG 分类作为后备方案。

    Args:
        svg: SVG path 字符串，如 "M 0 0 L 100 0"

    Returns:
        笔画类别 ID (0-28)
    """
    commands = _parse_svg_commands(svg)
    if not commands:
        return 0  # 默认返回横

    # 提取所有点
    points: list[tuple[float, float]] = []
    cx, cy = 0.0, 0.0

    for cmd, nums in commands:
        if cmd == "M":
            cx, cy = nums[0], nums[1]
            points.append((cx, cy))
        elif cmd == "L":
            cx, cy = nums[0], nums[1]
            points.append((cx, cy))
        elif cmd == "m":
            cx += nums[0]
            cy += nums[1]
            points.append((cx, cy))
        elif cmd == "l":
            cx += nums[0]
            cy += nums[1]
            points.append((cx, cy))

    if len(points) < 2:
        return 4  # 点

    # 计算起点到终点的总体方向
    dx = points[-1][0] - points[0][0]
    dy = points[-1][1] - points[0][1]
    total_len = math.sqrt(dx * dx + dy * dy) + 1e-6

    # 计算路径总长度
    path_len = 0.0
    for i in range(1, len(points)):
        seg_dx = points[i][0] - points[i - 1][0]
        seg_dy = points[i][1] - points[i - 1][1]
        path_len += math.sqrt(seg_dx * seg_dx + seg_dy * seg_dy)

    # 计算直进度（起点到终点距离 / 路径总长度）
    straightness = total_len / path_len if path_len > 0 else 1.0

    # 计算方向角度
    angle = math.atan2(dy, dx)

    # 检测是否有转折方向变化（用于区分复合笔画）
    has_fold = False
    for i in range(1, len(points) - 1):
        seg1_dx = points[i][0] - points[i - 1][0]
        seg1_dy = points[i][1] - points[i - 1][1]
        seg2_dx = points[i + 1][0] - points[i][0]
        seg2_dy = points[i + 1][1] - points[i][1]

        # 叉积判断转向
        cross = seg1_dx * seg2_dy - seg1_dy * seg2_dx
        if abs(cross) > 1e-3:
            has_fold = True
            break

    # 分类逻辑
    if len(points) == 2 and straightness > 0.8:
        # 简单直线笔画
        if abs(angle) < math.pi / 6 or abs(angle) > 5 * math.pi / 6:
            return 0  # 横
        elif abs(abs(angle) - math.pi / 2) < math.pi / 6:
            return 1  # 竖
        elif angle > 0:
            return 3  # 捺
        else:
            return 2  # 撇

    if not has_fold and path_len < 50:
        return 4  # 点

    # 有转折的笔画 — 简化分类
    # 实际依赖 dictionary.txt 的笔画名称更准确
    if has_fold:
        return 11  # 横折（复合笔画的默认回退）

    return 0  # 默认横


def build_taxonomy(dict_path: str, graph_path: str, output_path: str) -> dict:
    """构建完整的笔画类别库 JSON 文件。

    Args:
        dict_path: dictionary.txt 文件路径
        graph_path: graphics.txt 文件路径
        output_path: 输出 JSON 文件路径

    Returns:
        构建好的笔画类别库字典
    """
    char_strokes = parse_dictionary(dict_path)
    char_graphics = parse_graphics(graph_path)

    # 优先使用 dictionary.txt 中的笔画名称来分类
    char_to_stroke_ids: dict[str, list[int]] = {}

    for char, stroke_names in char_strokes.items():
        stroke_ids = []
        for name in stroke_names:
            if name in NAME_TO_ID:
                stroke_ids.append(NAME_TO_ID[name])
            else:
                # 未在映射表中的笔画名称，用 SVG 几何特征分类作为后备
                svg = char_graphics.get(char, [""])[len(stroke_ids)] if char in char_graphics else ""
                stroke_ids.append(classify_stroke_by_svg(svg))
        char_to_stroke_ids[char] = stroke_ids

    # 构建最终 JSON
    taxonomy = {
        "strokes": [
            {
                "id": s.id,
                "name": s.name,
                "name_pinyin": s.name_pinyin,
                "stroke_type": s.stroke_type,
                "description": s.description,
            }
            for s in STROKES
        ],
        "char_to_strokes": char_to_stroke_ids,
    }

    # 写入文件
    import os
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(taxonomy, f, ensure_ascii=False, indent=2)

    return taxonomy
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/test_parser.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/stroke_taxonomy/ tests/test_parser.py
git commit -m "feat: add stroke taxonomy parser with stroke name mapping and SVG classification"
```

---

### Task 3: 笔画类别库构建脚本与查询接口

**Files:**
- Create: `scripts/build_taxonomy.py`
- Create: `src/stroke_taxonomy/taxonomy.py`
- Create: `tests/test_taxonomy.py`

- [ ] **Step 1: 编写 taxonomy.py 测试**

创建 `tests/test_taxonomy.py`：

```python
import json
import os
import tempfile

import pytest

from src.stroke_taxonomy.taxonomy import StrokeTaxonomy


@pytest.fixture
def sample_taxonomy_file(tmp_path):
    """创建一个模拟的笔画类别库 JSON 文件。"""
    data = {
        "strokes": [
            {"id": 0, "name": "横", "name_pinyin": "heng", "stroke_type": "basic", "description": "水平笔画"},
            {"id": 1, "name": "竖", "name_pinyin": "shu", "stroke_type": "basic", "description": "竖直笔画"},
            {"id": 14, "name": "横折钩", "name_pinyin": "hengzhegou", "stroke_type": "compound", "description": "横折后带钩"},
        ],
        "char_to_strokes": {
            "一": [0],
            "二": [0, 0],
        },
    }
    path = os.path.join(str(tmp_path), "stroke_taxonomy.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return path


class TestStrokeTaxonomy:
    def test_load_taxonomy(self, sample_taxonomy_file):
        tax = StrokeTaxonomy(sample_taxonomy_file)
        assert tax.num_strokes() == 3

    def test_get_stroke_info(self, sample_taxonomy_file):
        tax = StrokeTaxonomy(sample_taxonomy_file)
        info = tax.get_stroke(0)
        assert info["name"] == "横"
        assert info["stroke_type"] == "basic"

    def test_get_strokes_by_type(self, sample_taxonomy_file):
        tax = StrokeTaxonomy(sample_taxonomy_file)
        basic = tax.get_strokes_by_type("basic")
        assert len(basic) == 2
        compound = tax.get_strokes_by_type("compound")
        assert len(compound) == 1

    def test_get_char_strokes(self, sample_taxonomy_file):
        tax = StrokeTaxonomy(sample_taxonomy_file)
        strokes = tax.get_char_strokes("一")
        assert strokes == [0]

    def test_get_char_strokes_with_names(self, sample_taxonomy_file):
        tax = StrokeTaxonomy(sample_taxonomy_file)
        names = tax.get_char_strokes_with_names("一")
        assert names == ["横"]

    def test_char_not_found_returns_none(self, sample_taxonomy_file):
        tax = StrokeTaxonomy(sample_taxonomy_file)
        assert tax.get_char_strokes("不存在的字") is None

    def test_get_stroke_name(self, sample_taxonomy_file):
        tax = StrokeTaxonomy(sample_taxonomy_file)
        assert tax.get_stroke_name(0) == "横"
        assert tax.get_stroke_name(14) == "横折钩"

    def test_get_stroke_name_invalid_id(self, sample_taxonomy_file):
        tax = StrokeTaxonomy(sample_taxonomy_file)
        assert tax.get_stroke_name(999) is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_taxonomy.py -v`
Expected: FAIL — `StrokeTaxonomy` 尚未实现

- [ ] **Step 3: 实现 taxonomy.py**

创建 `src/stroke_taxonomy/taxonomy.py`：

```python
"""笔画类别库查询接口。

提供从笔画类别库 JSON 中查询笔画信息、字-笔画映射等能力。
"""

import json
from typing import Optional


class StrokeTaxonomy:
    """笔画类别库查询接口。"""

    def __init__(self, taxonomy_path: str):
        """加载笔画类别库 JSON 文件。

        Args:
            taxonomy_path: stroke_taxonomy.json 文件路径
        """
        with open(taxonomy_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self._strokes = data["strokes"]
        self._char_to_strokes = data["char_to_strokes"]

        # 构建索引
        self._id_to_stroke: dict[int, dict] = {s["id"]: s for s in self._strokes}
        self._name_to_id: dict[str, int] = {s["name"]: s["id"] for s in self._strokes}
        self._type_to_ids: dict[str, list[int]] = {}
        for s in self._strokes:
            self._type_to_ids.setdefault(s["stroke_type"], []).append(s["id"])

    def num_strokes(self) -> int:
        """返回笔画类别总数。"""
        return len(self._strokes)

    def get_stroke(self, stroke_id: int) -> dict:
        """根据 ID 获取笔画信息。"""
        return self._id_to_stroke[stroke_id]

    def get_stroke_name(self, stroke_id: int) -> Optional[str]:
        """根据 ID 获取笔画名称。"""
        info = self._id_to_stroke.get(stroke_id)
        return info["name"] if info else None

    def get_strokes_by_type(self, stroke_type: str) -> list[dict]:
        """获取指定类型的所有笔画。"""
        ids = self._type_to_ids.get(stroke_type, [])
        return [self._id_to_stroke[i] for i in ids]

    def get_char_strokes(self, char: str) -> Optional[list[int]]:
        """获取指定汉字的笔画 ID 序列。不存在则返回 None。"""
        return self._char_to_strokes.get(char)

    def get_char_strokes_with_names(self, char: str) -> Optional[list[str]]:
        """获取指定汉字的笔画名称序列。不存在则返回 None。"""
        ids = self.get_char_strokes(char)
        if ids is None:
            return None
        return [self.get_stroke_name(sid) for sid in ids]

    def get_all_chars(self) -> list[str]:
        """返回类别库中所有汉字。"""
        return list(self._char_to_strokes.keys())

    def get_stroke_count(self, char: str) -> Optional[int]:
        """获取指定汉字的笔画数。不存在则返回 None。"""
        strokes = self.get_char_strokes(char)
        return len(strokes) if strokes is not None else None
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_taxonomy.py -v`
Expected: PASS

- [ ] **Step 5: 编写构建脚本**

创建 `scripts/build_taxonomy.py`：

```python
"""从 Make Me a Hanzi 原始数据构建笔画类别库 JSON。"""

import os
import sys

# 将项目根目录加入 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.stroke_taxonomy.parser import build_taxonomy

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "stroke_taxonomy", "raw")
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "stroke_taxonomy", "stroke_taxonomy.json")


def main():
    dict_path = os.path.join(RAW_DIR, "dictionary.txt")
    graph_path = os.path.join(RAW_DIR, "graphics.txt")

    if not os.path.exists(dict_path):
        print(f"dictionary.txt not found at {dict_path}")
        print("Run scripts/download_data.py first.")
        sys.exit(1)

    if not os.path.exists(graph_path):
        print(f"graphics.txt not found at {graph_path}")
        print("Run scripts/download_data.py first.")
        sys.exit(1)

    print(f"Building taxonomy from {dict_path} and {graph_path} ...")
    taxonomy = build_taxonomy(dict_path, graph_path, OUTPUT_PATH)

    num_chars = len(taxonomy["char_to_strokes"])
    num_strokes = len(taxonomy["strokes"])
    print(f"Done. {num_chars} characters, {num_strokes} stroke types.")
    print(f"Output: {os.path.abspath(OUTPUT_PATH)}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: 运行构建脚本生成笔画类别库**

先确保原始数据已下载：`python scripts/download_data.py`

然后运行：`python scripts/build_taxonomy.py`
Expected: 生成 `data/stroke_taxonomy/stroke_taxonomy.json`，输出约 9000 字符和 29 笔画类型

- [ ] **Step 7: Commit**

```bash
git add src/stroke_taxonomy/taxonomy.py tests/test_taxonomy.py scripts/build_taxonomy.py
git commit -m "feat: add stroke taxonomy query interface and build script"
```

---

### Task 4: PaddleOCR 单字识别封装

**Files:**
- Create: `src/ocr/recognizer.py`
- Create: `tests/test_recognizer.py`
- Create: `tests/fixtures/` (测试用书法字图片)

- [ ] **Step 1: 安装 PaddleOCR 依赖**

Run: `pip install paddleocr paddlepaddle opencv-python`

- [ ] **Step 2: 编写 OCR 识别器测试**

创建 `tests/test_recognizer.py`：

```python
"""OCR 识别器测试。

注意：此测试需要 PaddleOCR 安装和测试图片。
对于 CI 环境，使用 mock 替代真实 OCR 调用。
"""

import os
import tempfile
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from src.ocr.recognizer import CalligraphyOCR


class TestCalligraphyOCRWithMock:
    """使用 mock 测试 OCR 逻辑，不依赖真实 PaddleOCR。"""

    @patch("src.ocr.recognizer.PaddleOCR")
    def test_init_creates_ocr_engine(self, mock_paddle_ocr):
        """OCR 初始化应创建 PaddleOCR 实例。"""
        ocr = CalligraphyOCR()
        mock_paddle_ocr.assert_called_once()

    @patch("src.ocr.recognizer.PaddleOCR")
    def test_recognize_single_char(self, mock_paddle_ocr):
        """识别单字应返回字标签。"""
        # Mock PaddleOCR 返回值
        mock_instance = MagicMock()
        mock_paddle_ocr.return_value = mock_instance
        mock_instance.ocr.return_value = [
            [
                [[[10, 10], [100, 10], [100, 100], [10, 100]], ("永", 0.99)]
            ]
        ]

        ocr = CalligraphyOCR()
        # 创建一个空白测试图片
        dummy_img = np.ones((100, 100, 3), dtype=np.uint8) * 255
        result = ocr.recognize(dummy_img)

        assert result == "永"

    @patch("src.ocr.recognizer.PaddleOCR")
    def test_recognize_no_text_found(self, mock_paddle_ocr):
        """识别失败时应返回 None。"""
        mock_instance = MagicMock()
        mock_paddle_ocr.return_value = mock_instance
        mock_instance.ocr.return_value = [[]]

        ocr = CalligraphyOCR()
        dummy_img = np.ones((100, 100, 3), dtype=np.uint8) * 255
        result = ocr.recognize(dummy_img)

        assert result is None

    @patch("src.ocr.recognizer.PaddleOCR")
    def test_recognize_from_file(self, mock_paddle_ocr):
        """从文件路径识别应正常工作。"""
        mock_instance = MagicMock()
        mock_paddle_ocr.return_value = mock_instance
        mock_instance.ocr.return_value = [
            [[[[0, 0], [100, 0], [100, 100], [0, 100]], ("字", 0.95)]]
        ]

        ocr = CalligraphyOCR()
        # 使用临时文件模拟图片路径
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            temp_path = f.name

        try:
            result = ocr.recognize_from_file(temp_path)
            assert result == "字"
        finally:
            os.unlink(temp_path)

    @patch("src.ocr.recognizer.PaddleOCR")
    def test_recognize_multiple_returns_first(self, mock_paddle_ocr):
        """当识别到多个文字时，返回置信度最高的第一个。"""
        mock_instance = MagicMock()
        mock_paddle_ocr.return_value = mock_instance
        mock_instance.ocr.return_value = [
            [
                [[[10, 10], [50, 10], [50, 50], [10, 50]], ("永", 0.99)],
                [[[60, 10], [100, 10], [100, 50], [60, 50]], ("字", 0.85)],
            ]
        ]

        ocr = CalligraphyOCR()
        dummy_img = np.ones((100, 200, 3), dtype=np.uint8) * 255
        result = ocr.recognize(dummy_img)

        # 当识别到多个字时，取置信度最高的
        assert result == "永"

    @patch("src.ocr.recognizer.PaddleOCR")
    def test_confidence_threshold(self, mock_paddle_ocr):
        """置信度低于阈值时应返回 None。"""
        mock_instance = MagicMock()
        mock_paddle_ocr.return_value = mock_instance
        mock_instance.ocr.return_value = [
            [[[[10, 10], [100, 10], [100, 100], [10, 100]], ("永", 0.30)]]
        ]

        ocr = CalligraphyOCR(confidence_threshold=0.5)
        dummy_img = np.ones((100, 100, 3), dtype=np.uint8) * 255
        result = ocr.recognize(dummy_img)

        assert result is None
```

- [ ] **Step 3: 运行测试确认失败**

Run: `pytest tests/test_recognizer.py -v`
Expected: FAIL — `CalligraphyOCR` 尚未实现

- [ ] **Step 4: 实现 recognizer.py**

创建 `src/ocr/recognizer.py`：

```python
"""PaddleOCR 单字识别封装。

对书法字照片进行 OCR 识别，返回字标签。
可传入 numpy 数组或文件路径。
"""

from typing import Optional

import numpy as np

try:
    from paddleocr import PaddleOCR
except ImportError:
    PaddleOCR = None  # 允许在未安装 PaddleOCR 的环境中导入


class CalligraphyOCR:
    """书法字 OCR 识别器。"""

    def __init__(self, confidence_threshold: float = 0.5):
        """初始化 PaddleOCR 引擎。

        Args:
            confidence_threshold: 识别置信度阈值，低于此值的结果将被丢弃。
        """
        if PaddleOCR is None:
            raise ImportError(
                "PaddleOCR is not installed. "
                "Install with: pip install paddleocr paddlepaddle"
            )
        self._ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
        self._confidence_threshold = confidence_threshold

    def recognize(self, image: np.ndarray) -> Optional[str]:
        """从 numpy 数组识别单字。

        Args:
            image: BGR 或灰度图像 (numpy 数组)

        Returns:
            识别到的字标签，如果识别失败或置信度不足则返回 None。
            当识别到多个字时，返回置信度最高的。
        """
        results = self._ocr.ocr(image, cls=True)

        if not results or not results[0]:
            return None

        # 提取所有识别结果，按置信度排序
        candidates = []
        for line in results[0]:
            text = line[1][0]
            confidence = line[1][1]
            if confidence >= self._confidence_threshold:
                candidates.append((text, confidence))

        if not candidates:
            return None

        # 按置信度降序排序，返回最高置信度的结果
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0][0]

    def recognize_from_file(self, image_path: str) -> Optional[str]:
        """从文件路径识别单字。

        Args:
            image_path: 图片文件路径

        Returns:
            识别到的字标签，如果识别失败则返回 None。
        """
        import cv2
        image = cv2.imread(image_path)
        if image is None:
            return None
        return self.recognize(image)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/test_recognizer.py -v`
Expected: PASS（使用 mock，不依赖真实 PaddleOCR）

- [ ] **Step 6: Commit**

```bash
git add src/ocr/recognizer.py tests/test_recognizer.py
git commit -m "feat: add PaddleOCR wrapper for single character recognition"
```

---

### Task 5: OCR + 笔画类别库端到端管线

**Files:**
- Create: `src/ocr/pipeline.py`
- Create: `tests/test_pipeline.py`

- [ ] **Step 1: 编写端到端管线测试**

创建 `tests/test_pipeline.py`：

```python
"""OCR + 笔画类别库端到端管线测试。"""

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.ocr.pipeline import AnnotationPipeline


@pytest.fixture
def taxonomy_file(tmp_path):
    """创建模拟笔画类别库文件。"""
    data = {
        "strokes": [
            {"id": 0, "name": "横", "name_pinyin": "heng", "stroke_type": "basic", "description": "水平笔画"},
            {"id": 1, "name": "竖", "name_pinyin": "shu", "stroke_type": "basic", "description": "竖直笔画"},
            {"id": 3, "name": "捺", "name_pinyin": "na", "stroke_type": "basic", "description": "右上到左下"},
            {"id": 4, "name": "点", "name_pinyin": "dian", "stroke_type": "basic", "description": "短笔画"},
            {"id": 14, "name": "横折钩", "name_pinyin": "hengzhegou", "stroke_type": "compound", "description": "横折带钩"},
            {"id": 15, "name": "横撇", "name_pinyin": "hengpie", "stroke_type": "compound", "description": "横画接撇"},
            {"id": 2, "name": "撇", "name_pinyin": "pie", "stroke_type": "basic", "description": "右上到左下"},
        ],
        "char_to_strokes": {
            "永": [4, 14, 15, 2, 3],
            "一": [0],
        },
    }
    path = os.path.join(str(tmp_path), "stroke_taxonomy.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return path


class TestAnnotationPipeline:
    @patch("src.ocr.pipeline.CalligraphyOCR")
    def test_annotate_single_char(self, mock_ocr_cls, taxonomy_file):
        """端到端：OCR 识别字 → 查询笔画类别库 → 返回笔画序列。"""
        # Mock OCR 返回 "永"
        mock_ocr_instance = MagicMock()
        mock_ocr_cls.return_value = mock_ocr_instance
        mock_ocr_instance.recognize.return_value = "永"

        pipeline = AnnotationPipeline(
            taxonomy_path=taxonomy_file,
            ocr_confidence_threshold=0.5,
        )

        dummy_img = np.ones((100, 100, 3), dtype=np.uint8) * 255
        result = pipeline.annotate(dummy_img)

        assert result is not None
        assert result["char"] == "永"
        assert result["stroke_ids"] == [4, 14, 15, 2, 3]
        assert result["stroke_names"] == ["点", "横折钩", "横撇", "撇", "捺"]
        assert result["stroke_count"] == 5

    @patch("src.ocr.pipeline.CalligraphyOCR")
    def test_annotate_char_not_in_taxonomy(self, mock_ocr_cls, taxonomy_file):
        """OCR 识别到的字不在类别库中时，返回包含 char 但 stroke_ids 为 None。"""
        mock_ocr_instance = MagicMock()
        mock_ocr_cls.return_value = mock_ocr_instance
        mock_ocr_instance.recognize.return_value = "龘"

        pipeline = AnnotationPipeline(
            taxonomy_path=taxonomy_file,
            ocr_confidence_threshold=0.5,
        )

        dummy_img = np.ones((100, 100, 3), dtype=np.uint8) * 255
        result = pipeline.annotate(dummy_img)

        assert result is not None
        assert result["char"] == "龘"
        assert result["stroke_ids"] is None
        assert result["stroke_names"] is None

    @patch("src.ocr.pipeline.CalligraphyOCR")
    def test_annotate_ocr_failure(self, mock_ocr_cls, taxonomy_file):
        """OCR 识别失败时返回 None。"""
        mock_ocr_instance = MagicMock()
        mock_ocr_cls.return_value = mock_ocr_instance
        mock_ocr_instance.recognize.return_value = None

        pipeline = AnnotationPipeline(
            taxonomy_path=taxonomy_file,
            ocr_confidence_threshold=0.5,
        )

        dummy_img = np.ones((100, 100, 3), dtype=np.uint8) * 255
        result = pipeline.annotate(dummy_img)

        assert result is None

    @patch("src.ocr.pipeline.CalligraphyOCR")
    def test_annotate_from_file(self, mock_ocr_cls, taxonomy_file):
        """从文件路径进行标注。"""
        mock_ocr_instance = MagicMock()
        mock_ocr_cls.return_value = mock_ocr_instance
        mock_ocr_instance.recognize_from_file.return_value = "一"

        pipeline = AnnotationPipeline(
            taxonomy_path=taxonomy_file,
            ocr_confidence_threshold=0.5,
        )

        result = pipeline.annotate_from_file("/fake/path/to/image.png")

        assert result is not None
        assert result["char"] == "一"
        assert result["stroke_ids"] == [0]
        assert result["stroke_names"] == ["横"]
        assert result["stroke_count"] == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_pipeline.py -v`
Expected: FAIL — `AnnotationPipeline` 尚未实现

- [ ] **Step 3: 实现 pipeline.py**

创建 `src/ocr/pipeline.py`：

```python
"""OCR + 笔画类别库 端到端标注管线。

流程：图片 → OCR 识别字标签 → 查询笔画类别库 → 返回标注结果。
"""

from typing import Optional

import numpy as np

from src.ocr.recognizer import CalligraphyOCR
from src.stroke_taxonomy.taxonomy import StrokeTaxonomy


class AnnotationPipeline:
    """书法字自动标注管线。"""

    def __init__(
        self,
        taxonomy_path: str,
        ocr_confidence_threshold: float = 0.5,
    ):
        """初始化标注管线。

        Args:
            taxonomy_path: 笔画类别库 JSON 文件路径
            ocr_confidence_threshold: OCR 识别置信度阈值
        """
        self._taxonomy = StrokeTaxonomy(taxonomy_path)
        self._ocr = CalligraphyOCR(confidence_threshold=ocr_confidence_threshold)

    def annotate(self, image: np.ndarray) -> Optional[dict]:
        """对图片进行完整标注。

        Args:
            image: BGR 格式的 numpy 数组

        Returns:
            标注结果字典，包含：
            - char: 识别到的字标签
            - stroke_ids: 笔画类别 ID 列表（不在类别库中时为 None）
            - stroke_names: 笔画名称列表（不在类别库中时为 None）
            - stroke_count: 笔画数（不在类别库中时为 None）
            如果 OCR 识别失败则返回 None。
        """
        char = self._ocr.recognize(image)
        if char is None:
            return None

        return self._build_result(char)

    def annotate_from_file(self, image_path: str) -> Optional[dict]:
        """从文件路径进行完整标注。

        Args:
            image_path: 图片文件路径

        Returns:
            同 annotate() 的返回格式。
        """
        char = self._ocr.recognize_from_file(image_path)
        if char is None:
            return None

        return self._build_result(char)

    def _build_result(self, char: str) -> dict:
        """根据字标签构建标注结果。"""
        stroke_ids = self._taxonomy.get_char_strokes(char)

        if stroke_ids is not None:
            stroke_names = self._taxonomy.get_char_strokes_with_names(char)
            stroke_count = len(stroke_ids)
        else:
            stroke_names = None
            stroke_count = None

        return {
            "char": char,
            "stroke_ids": stroke_ids,
            "stroke_names": stroke_names,
            "stroke_count": stroke_count,
        }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: 运行全部测试确认无回归**

Run: `pytest tests/ -v`
Expected: 所有测试 PASS

- [ ] **Step 6: Commit**

```bash
git add src/ocr/pipeline.py tests/test_pipeline.py
git commit -m "feat: add OCR + stroke taxonomy annotation pipeline"
```

---

### Task 6: 运行全部测试与最终验证

**Files:**
- 无新文件

- [ ] **Step 1: 运行完整测试套件**

Run: `pytest tests/ -v --tb=short`
Expected: 所有测试 PASS

- [ ] **Step 2: 运行构建脚本构建实际笔画类别库**

确保原始数据已下载：`python scripts/download_data.py`

构建：`python scripts/build_taxonomy.py`

验证生成的 `data/stroke_taxonomy/stroke_taxonomy.json`：
- `strokes` 数组长度应为 29
- `char_to_strokes` 应包含数千个汉字
- 测试几个常用字的笔画序列是否正确（如"永"应有 5 个笔画、"一"应有 1 个笔画）

- [ ] **Step 3: 验证管线可用（如已安装 PaddleOCR）**

如果有真实的书法字照片，可运行：

```python
from src.ocr.pipeline import AnnotationPipeline

pipeline = AnnotationPipeline(
    taxonomy_path="data/stroke_taxonomy/stroke_taxonomy.json"
)
result = pipeline.annotate_from_file("path/to/calligraphy_image.png")
print(result)
```

Expected: 输出包含字标签、笔画 ID 序列、笔画名称列表

- [ ] **Step 4: 最终 Commit**

```bash
git add data/stroke_taxonomy/stroke_taxonomy.json
git commit -m "feat: add built stroke taxonomy data file"
```

---

## Self-Review Checklist

- [x] **Spec coverage**: Task 1-3 覆盖笔画类别库的下载、解析、构建、查询；Task 4-5 覆盖 OCR 识别和端到端管线；Task 6 是集成验证
- [x] **Placeholder scan**: 无 TBD/TODO/placeholder，所有代码完整
- [x] **Type consistency**: `StrokeTaxonomy` 接口在 Task 3 定义，Task 5 使用；`CalligraphyOCR` 接口在 Task 4 定义，Task 5 使用；笔画 ID 使用 0-28 整数一致
- [x] **No scope creep**: 仅包含笔画类别库 + OCR 管线，不涉及传感器、Transformer 模型等后续任务