# FYP 项目阶段性成果报告

**日期**: 2026-05-25 | **分支**: master | **最新提交**: `7400e50`

---

## 1. 项目概述

本项目构建**多模态融合 AI 书法教学与评估系统**的数据基础层，已完成三大核心模块：

- **笔画类别库**：覆盖 9,574 个汉字、29 种笔画类别的结构化知识库
- **OCR 识别管线**：基于 PaddleOCR 的端到端书法字标注管线（照片 → 字符识别 → 笔画序列）
- **视觉质量评估**：基于传统图像处理的书法字质量评分（形状/位置/结构三维度）

---

## 2. 已完成模块

### 2.1 笔画类别库（Stroke Taxonomy）

| 指标 | 数值 |
|------|------|
| 覆盖汉字数 | 9,574 |
| 笔画类别数 | 29 |
| 笔画实例总数 | 112,617 |
| 数据来源 | Make Me a Hanzi (graphics.txt medians) |

**29 类笔画体系**：

| 大类 | 包含笔画 | 数量 |
|------|----------|------|
| 基本笔画 | 横、竖、撇、捺、点、提 | 6 |
| 钩类 | 竖钩、弯钩、斜钩、卧钩、横钩 | 5 |
| 折类 | 横折、竖折、撇折 | 3 |
| 复合笔画 | 横折钩、横撇、横撇弯钩、横折弯钩、竖折折钩、横折折撇、竖提、撇点、横折提、横折弯、竖弯、竖弯钩、横斜钩、横折折折钩、横折折 | 15 |

**核心技术突破**：从 SVG 轮廓分类切换到 median 中线分类。SVG 路径描述的是笔画填充轮廓（闭合形状），无法提取书写方向；median 中线是实际运笔轨迹的坐标序列，可准确提取方向、转折角度、钩/折区分等几何特征。详见 `docs/stroke-classification-solution.md`。

### 2.2 OCR 识别管线

| 组件 | 文件 | 功能 |
|------|------|------|
| `CalligraphyOCR` | `src/ocr/recognizer.py` | PaddleOCR 封装，支持 numpy 数组和文件路径输入，置信度过滤 |
| `AnnotationPipeline` | `src/ocr/pipeline.py` | 端到端标注：照片 → OCR 识别 → 笔画库查询 → 结构化结果 |

**管线输出格式**：
```json
{
    "char": "永",
    "stroke_ids": [4, 14, 15, 2, 3],
    "stroke_names": ["点", "横折钩", "横撇", "撇", "捺"],
    "stroke_count": 5
}
```

### 2.3 视觉质量评估（新增）

| 组件 | 文件 | 功能 |
|------|------|------|
| `ReferenceRenderer` | `src/quality/reference.py` | 用 OpenCV FreeType + 楷体字体渲染标准汉字参考图（白底黑字二值图） |
| `QualityAssessor` | `src/quality/assessor.py` | 三维度评分：形状(SSIM)、位置(质心+边界框IoU)、结构(Hu Moments+宽高比) |
| `QualityPipeline` | `src/quality/pipeline.py` | 端到端管线：拍照/文件 → OCR识别 → 生成参考图 → 质量评分 |

**评分输出格式**：
```json
{
    "char": "永",
    "stroke_ids": [4, 14, 15, 2, 3],
    "stroke_names": ["点", "横折钩", "横撇", "撇", "捺"],
    "stroke_count": 5,
    "shape_score": 0.85,
    "position_score": 0.92,
    "structure_score": 0.78,
    "overall_score": 0.85
}
```

**评分维度说明**：
- **shape_score (SSIM)**：结构相似度，衡量笔画形态与标准字的匹配程度
- **position_score (质心+IoU)**：质心偏移 + 边界框重叠率，衡量字在格子中的位置
- **structure_score (Hu Moments)**：Hu 不变矩 + 宽高比，衡量字形结构比例
- **overall_score**：加权平均 (0.4 × shape + 0.3 × position + 0.3 × structure)

### 2.4 笔画分类算法

`classify_stroke_by_median()` 基于 median 中线几何特征的分层决策树：

1. **特征提取**：路径长度、直线度、整体方向角、初始/末尾段方向
2. **统一转折检测**：遍历相邻线段夹角，>15° 计为转折，>60° 为"折"（fold），≤60° 为"钩"（hook）
3. **7 层决策树**：从简单到复杂依次匹配（直线 → 单转折 → 双转折 → 多转折 → 弧线 → fallback）

### 2.5 工程化

- **pixi 隔离环境**：零污染 Python 环境管理
- **53 个单元测试**全部通过：覆盖解析器、分类器、类别库查询、OCR 识别器、端到端管线、质量评估
- **数据下载脚本**：自动获取 Make Me a Hanzi 原始数据
- **构建脚本**：一键生成 `stroke_taxonomy.json`

---

## 3. 项目结构

```
FYP/
├── data/stroke_taxonomy/
│   ├── stroke_taxonomy.json    # 笔画类别库（9,574 字符, 29 笔画类型）
│   └── raw/                    # Make Me a Hanzi 原始数据
├── src/
│   ├── stroke_taxonomy/
│   │   ├── stroke_names.py     # 29 类笔画定义
│   │   ├── parser.py           # 数据解析 + median 几何笔画分类
│   │   └── taxonomy.py         # 笔画类别库查询接口
│   ├── ocr/
│   │   ├── recognizer.py       # PaddleOCR 封装
│   │   └── pipeline.py         # 端到端标注管线
│   └── quality/                # 新增：视觉质量评估
│       ├── reference.py        # 标准字渲染器
│       ├── assessor.py         # 质量评估器
│       └── pipeline.py         # 端到端质量评估管线
├── tests/                      # 6 个测试文件, 53 个测试用例
│   └── test_quality.py         # 新增：质量评估测试 (14 个)
├── scripts/
│   ├── download_data.py
│   ├── build_taxonomy.py
│   └── assess_quality.py       # 新增：一键质量评估脚本
├── docs/
│   └── stroke-classification-solution.md  # 笔画分类问题解决方案
└── pyproject.toml
```

---

## 4. 测试结果

```
53 passed in 511.95s (全部通过)
```

- 质量评估测试：14 passed
- 已有测试：39 passed（test_download_data 网络超时问题已解决）

---

## 5. 开发历史

| 提交 | 说明 |
|------|------|
| `7400e50` | feat: add visual quality assessment for calligraphy characters |
| `6e18294` | strokes_function |
| `fdb56c9` | docs: add project README with usage guide |
| `a589232` | chore: migrate to pixi for isolated environment management |
| `3690130` | feat: add OCR + stroke taxonomy annotation pipeline |
| `8b91df3` | feat: add PaddleOCR wrapper for single character recognition |
| `bb12a59` | feat: add stroke taxonomy query interface and build script |
| `99807a1` | feat: add stroke taxonomy parser with SVG-based stroke classification |
| `eded820` | feat: project init with data download script and base structure |

---

## 6. 关于 .claude/worktrees 目录

`.claude/worktrees/quality-assessment/` 是本次开发使用的**隔离工作区残留空目录**。

**为什么会有这个目录**：在执行实现计划时，Claude Code 使用 `EnterWorktree` 创建了独立的 git worktree 来隔离开发环境，避免影响 master 分支。开发完成后，代码已合并到 master，分支已删除，git worktree 注册已清理（`git worktree list` 只显示主仓库）。但目录本身因被 shell 进程占用（"Device or resource busy"）未能自动删除。

**这个目录是空的，可以安全删除**：
```bash
rmdir D:\cc_ws\FYP\.claude\worktrees\quality-assessment
```
如果提示 "Device or resource busy"，关闭所有终端窗口后再执行即可。

---

## 7. 待开发

- [ ] 笔画分割算法
- [ ] 触觉数据采集模块（依赖传感器硬件）
- [ ] Transformer 笔画识别与质量评估模型
- [ ] 笔迹还原可视化

---

## 8. 技术栈

- **Python 3.11+**（pixi 隔离环境）
- **PaddleOCR**（中文手写体识别）
- **OpenCV 4.13**（图像处理、FreeType 字体渲染、SSIM）
- **PyTorch**（为后续 Transformer 模型预留）
- **pytest**（测试框架）
