#!/usr/bin/env python3
"""Offline daily direction/speed report; reads raw runs without changing them."""
import csv
import hashlib
import html
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
import numpy as np

BASE = Path(__file__).resolve().parent.parent
DIRS = ['right', 'up', 'left', 'down']
SPEEDS = [7., 10., 15.]
NAMES = dict(right='右 +X', up='上 +Y', left='左 −X', down='下 −Y')
UNITS = dict(right=[1, 0], up=[0, 1], left=[-1, 0], down=[0, -1])
COLORS = dict(right='#2474b5', up='#159570', left='#dd8433', down='#9951a6')
SCOLORS = {7.: '#238b69', 10.: '#2876b5', 15.: '#d76c37'}
FONT = FontProperties(fname='/usr/local/share/fonts/msyh.ttf').get_name()
plt.rcParams.update({'font.family': FONT, 'axes.unicode_minus': False, 'font.size': 11,
                     'axes.spines.top': False, 'axes.spines.right': False,
                     'figure.facecolor': '#fafbfc', 'axes.facecolor': 'white',
                     'savefig.facecolor': '#fafbfc'})


def read_json(p):
    return json.loads(p.read_text())

