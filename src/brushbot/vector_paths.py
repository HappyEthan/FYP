"""Absolute SVG outline subset used by the local glyph engineering fixtures."""
import re

from matplotlib.path import Path as VectorPath


def vector_path(svg):
    """Read absolute M/L/Q/C/Z commands without fetching external SVG content."""
    tokens = re.findall(r'[A-Za-z]|[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?', svg)
    vertices, codes = [], []
    index, start = 0, None
    while index < len(tokens):
        command = tokens[index]
        index += 1
        if command == 'Z':
            if start is None:
                raise ValueError('outline closes before its first move')
            vertices.append(start)
            codes.append(VectorPath.CLOSEPOLY)
            continue
        if command not in {'M', 'L', 'Q', 'C'}:
            raise ValueError(f'unsupported outline command: {command}')
        for _ in range({'M': 1, 'L': 1, 'Q': 2, 'C': 3}[command]):
            point = [float(tokens[index]), float(tokens[index+1])]
            index += 2
            vertices.append(point)
            codes.append({'M': VectorPath.MOVETO, 'L': VectorPath.LINETO,
                          'Q': VectorPath.CURVE3, 'C': VectorPath.CURVE4}[command])
            if command == 'M':
                start = point
    return VectorPath(vertices, codes)
