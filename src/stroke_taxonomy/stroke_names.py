"""Stroke name mapping: maps Chinese stroke names to category IDs and types.

Stroke taxonomy based on the Standard Stroke Order Specification for
Modern Chinese General-Purpose Characters and calligraphy textbooks.
"""

from dataclasses import dataclass


@dataclass
class StrokeInfo:
    """Information about a single stroke category."""
    id: int
    name: str
    name_pinyin: str
    stroke_type: str  # "basic", "hook", "fold", "compound"
    description: str


# Stroke category definitions (~29 categories)
STROKES: list[StrokeInfo] = [
    # Basic strokes (6)
    StrokeInfo(id=0, name="横", name_pinyin="heng", stroke_type="basic", description="Horizontal stroke from left to right"),
    StrokeInfo(id=1, name="竖", name_pinyin="shu", stroke_type="basic", description="Vertical stroke from top to bottom"),
    StrokeInfo(id=2, name="撇", name_pinyin="pie", stroke_type="basic", description="Diagonal stroke from top-right to bottom-left"),
    StrokeInfo(id=3, name="捺", name_pinyin="na", stroke_type="basic", description="Diagonal stroke from top-left to bottom-right"),
    StrokeInfo(id=4, name="点", name_pinyin="dian", stroke_type="basic", description="Short dot stroke"),
    StrokeInfo(id=5, name="提", name_pinyin="ti", stroke_type="basic", description="Short rising stroke from bottom-left to top-right"),
    # Hook strokes (5)
    StrokeInfo(id=6, name="竖钩", name_pinyin="shugou", stroke_type="hook", description="Vertical stroke ending with a hook"),
    StrokeInfo(id=7, name="弯钩", name_pinyin="wangou", stroke_type="hook", description="Curved stroke ending with a hook"),
    StrokeInfo(id=8, name="斜钩", name_pinyin="xiegou", stroke_type="hook", description="Diagonal stroke ending with a hook"),
    StrokeInfo(id=9, name="卧钩", name_pinyin="wogou", stroke_type="hook", description="Flat horizontal hook at the bottom"),
    StrokeInfo(id=10, name="横钩", name_pinyin="henggou", stroke_type="hook", description="Horizontal stroke ending with a hook"),
    # Fold strokes (3)
    StrokeInfo(id=11, name="横折", name_pinyin="hengzhe", stroke_type="fold", description="Horizontal stroke folding downward"),
    StrokeInfo(id=12, name="竖折", name_pinyin="shuzhe", stroke_type="fold", description="Vertical stroke folding rightward"),
    StrokeInfo(id=13, name="撇折", name_pinyin="piezhe", stroke_type="fold", description="Diagonal stroke folding rightward"),
    # Compound strokes (15)
    StrokeInfo(id=14, name="横折钩", name_pinyin="hengzhegou", stroke_type="compound", description="Horizontal fold ending with a hook"),
    StrokeInfo(id=15, name="横撇", name_pinyin="hengpie", stroke_type="compound", description="Horizontal stroke followed by diagonal"),
    StrokeInfo(id=16, name="横撇弯钩", name_pinyin="hengpiewangou", stroke_type="compound", description="Horizontal-diagonal-curve-hook"),
    StrokeInfo(id=17, name="横折弯钩", name_pinyin="hengzhewangou", stroke_type="compound", description="Horizontal-fold-curve-hook"),
    StrokeInfo(id=18, name="竖折折钩", name_pinyin="shuzhezhegou", stroke_type="compound", description="Vertical-fold-fold-hook"),
    StrokeInfo(id=19, name="横折折撇", name_pinyin="hengzhezhelipe", stroke_type="compound", description="Horizontal-fold-fold-diagonal"),
    StrokeInfo(id=20, name="竖提", name_pinyin="shuti", stroke_type="compound", description="Vertical stroke rising at the end"),
    StrokeInfo(id=21, name="撇点", name_pinyin="piedian", stroke_type="compound", description="Diagonal stroke followed by a dot"),
    StrokeInfo(id=22, name="横折提", name_pinyin="hengzeti", stroke_type="compound", description="Horizontal fold rising at the end"),
    StrokeInfo(id=23, name="横折弯", name_pinyin="hengzhewan", stroke_type="compound", description="Horizontal fold then curve"),
    StrokeInfo(id=24, name="竖弯", name_pinyin="shuwan", stroke_type="compound", description="Vertical stroke then curve"),
    StrokeInfo(id=25, name="竖弯钩", name_pinyin="shuwangou", stroke_type="compound", description="Vertical curve ending with a hook"),
    StrokeInfo(id=26, name="横斜钩", name_pinyin="hengxiegou", stroke_type="compound", description="Horizontal then diagonal hook"),
    StrokeInfo(id=27, name="横折折折钩", name_pinyin="hengzhezhezhegou", stroke_type="compound", description="Horizontal-fold-fold-fold-hook"),
    StrokeInfo(id=28, name="横折折", name_pinyin="hengzhezhe", stroke_type="compound", description="Horizontal fold then another fold"),
]

# Name to ID mapping for quick lookup
NAME_TO_ID: dict[str, int] = {s.name: s.id for s in STROKES}
ID_TO_STROKE: dict[int, StrokeInfo] = {s.id: s for s in STROKES}

# Stroke type list
STROKE_TYPES = ["basic", "hook", "fold", "compound"]
