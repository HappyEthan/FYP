"""Parse Make Me a Hanzi data files to build the stroke taxonomy.

Make Me a Hanzi data format:
- dictionary.txt: Each line is a JSON object with "character", "decomposition" (IDS), etc.
  Does NOT contain stroke names — only structural decomposition.
- graphics.txt: Each line is a JSON object with "character", "strokes" (SVG path list),
  and "medians" (median line list for each stroke).

Strategy: Parse graphics.txt for SVG paths, classify strokes geometrically,
and build a character-to-stroke-ID mapping.
"""

import json
import math
import os
import re
from typing import Optional

from src.stroke_taxonomy.stroke_names import NAME_TO_ID, STROKES


def parse_dictionary(file_path: str) -> dict[str, dict]:
    """Parse dictionary.txt, return {character: {decomposition, ...}}."""
    result: dict[str, dict] = {}
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                char = data["character"]
                result[char] = {
                    "decomposition": data.get("decomposition", ""),
                    "definition": data.get("definition", ""),
                }
            except (json.JSONDecodeError, KeyError):
                continue
    return result


def parse_graphics(file_path: str) -> dict[str, list[str]]:
    """Parse graphics.txt, return {character: [SVG path strings]}."""
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
    """Extract commands and coordinates from an SVG path string.

    Returns:
        [(command, [x1, y1, x2, y2, ...]), ...]
    """
    commands = []
    pattern = r"([MLHVCSQTAZmlhvcsqtaz])([^MLHVCSQTAZmlhvcsqtaz]*)"
    for match in re.finditer(pattern, svg):
        cmd = match.group(1)
        nums_str = match.group(2).strip()
        nums = [float(x) for x in re.findall(r"[-+]?[\d]*\.?[\d]+", nums_str)] if nums_str else []
        commands.append((cmd, nums))
    return commands


def _extract_points(svg: str) -> list[tuple[float, float]]:
    """Extract all points from an SVG path."""
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
        elif cmd == "C":
            # Cubic bezier: use control points and end point
            points.append((nums[0], nums[1]))
            points.append((nums[2], nums[3]))
            cx, cy = nums[4], nums[5]
            points.append((cx, cy))
        elif cmd == "Q":
            # Quadratic bezier: use control point and end point
            points.append((nums[0], nums[1]))
            cx, cy = nums[2], nums[3]
            points.append((cx, cy))
        elif cmd == "m":
            cx += nums[0]
            cy += nums[1]
            points.append((cx, cy))
        elif cmd == "l":
            cx += nums[0]
            cy += nums[1]
            points.append((cx, cy))
        elif cmd == "c":
            points.append((cx + nums[0], cy + nums[1]))
            points.append((cx + nums[2], cy + nums[3]))
            cx += nums[4]
            cy += nums[5]
            points.append((cx, cy))
        elif cmd == "q":
            points.append((cx + nums[0], cy + nums[1]))
            cx += nums[2]
            cy += nums[3]
            points.append((cx, cy))
        elif cmd == "Z" or cmd == "z":
            if points:
                points.append(points[0])

    return points


def _count_direction_changes(points: list[tuple[float, float]]) -> int:
    """Count significant direction changes in a stroke path."""
    if len(points) < 3:
        return 0

    changes = 0
    for i in range(1, len(points) - 1):
        seg1_dx = points[i][0] - points[i - 1][0]
        seg1_dy = points[i][1] - points[i - 1][1]
        seg2_dx = points[i + 1][0] - points[i][0]
        seg2_dy = points[i + 1][1] - points[i][1]

        len1 = math.sqrt(seg1_dx * seg1_dx + seg1_dy * seg1_dy) + 1e-6
        len2 = math.sqrt(seg2_dx * seg2_dx + seg2_dy * seg2_dy) + 1e-6

        # Dot product for angle
        dot = (seg1_dx * seg2_dx + seg1_dy * seg2_dy) / (len1 * len2)
        dot = max(-1.0, min(1.0, dot))
        angle = math.acos(dot)

        if angle > math.pi / 6:  # > 30 degrees
            changes += 1

    return changes


def classify_stroke_by_svg(svg: str) -> int:
    """Classify a stroke by its SVG path geometry.

    Uses heuristic rules analyzing shape features (direction, turns, curvature)
    to determine stroke type. This is a simplified classifier — for compound
    strokes it provides a best-effort classification.

    Args:
        svg: SVG path string, e.g. "M 0 0 L 100 0"

    Returns:
        Stroke category ID (0-28)
    """
    points = _extract_points(svg)
    if not points:
        return 0  # Default to 横

    if len(points) < 2:
        return 4  # 点

    # Overall direction from start to end
    dx = points[-1][0] - points[0][0]
    dy = points[-1][1] - points[0][1]
    total_len = math.sqrt(dx * dx + dy * dy) + 1e-6

    # Total path length
    path_len = 0.0
    for i in range(1, len(points)):
        seg_dx = points[i][0] - points[i - 1][0]
        seg_dy = points[i][1] - points[i - 1][1]
        path_len += math.sqrt(seg_dx * seg_dx + seg_dy * seg_dy)

    # Straightness ratio
    straightness = total_len / path_len if path_len > 0 else 1.0

    # Direction angle
    angle = math.atan2(dy, dx)

    # Count direction changes
    num_turns = _count_direction_changes(points)

    # Check for hook at end (sharp turn near the end of the stroke)
    has_hook = False
    if len(points) >= 4:
        # Check last 20% of points for a sharp direction change
        n_check = max(3, len(points) // 5)
        end_points = points[-n_check:]
        if len(end_points) >= 3:
            end_turns = _count_direction_changes(end_points)
            has_hook = end_turns >= 1

    # Classification logic
    if num_turns == 0 and straightness > 0.7:
        # Simple straight stroke
        if abs(angle) < math.pi / 6 or abs(angle) > 5 * math.pi / 6:
            return 0  # 横
        elif abs(abs(angle) - math.pi / 2) < math.pi / 6:
            # Vertical: check if it's too short to be a proper 竖
            if path_len < 50:
                return 4  # 点
            return 1  # 竖
        elif dx < 0:
            # Right-to-left diagonal: 撇
            return 2  # 撇
        else:
            # Left-to-right diagonal: 捺
            return 3  # 捺

    if num_turns == 0 and path_len < 50:
        return 4  # 点

    if num_turns == 0 and angle > 0 and straightness > 0.5:
        return 5  # 提

    # Strokes with turns
    if num_turns == 1:
        if has_hook:
            # Single turn with hook
            first_seg_angle = math.atan2(points[1][1] - points[0][1], points[1][0] - points[0][0])
            if abs(first_seg_angle) < math.pi / 6:
                return 14  # 横折钩
            elif abs(abs(first_seg_angle) - math.pi / 2) < math.pi / 6:
                return 6  # 竖钩
            else:
                return 8  # 斜钩
        else:
            # Single turn without hook
            first_seg_angle = math.atan2(points[1][1] - points[0][1], points[1][0] - points[0][0])
            if abs(first_seg_angle) < math.pi / 6:
                return 11  # 横折
            elif abs(abs(first_seg_angle) - math.pi / 2) < math.pi / 6:
                return 12  # 竖折
            else:
                return 13  # 撇折

    if num_turns >= 2:
        if has_hook:
            return 18  # 竖折折钩 (compound with hook)
        else:
            return 19  # 横折折撇 (compound without hook)

    return 0  # Default to 横


def build_taxonomy(dict_path: str, graph_path: str, output_path: str) -> dict:
    """Build the complete stroke taxonomy JSON file.

    Since dictionary.txt does NOT contain stroke names, we classify strokes
    from graphics.txt SVG paths using geometric heuristics.

    Args:
        dict_path: Path to dictionary.txt
        graph_path: Path to graphics.txt
        output_path: Output JSON file path

    Returns:
        Built taxonomy dictionary
    """
    char_graphics = parse_graphics(graph_path)

    # Classify strokes from SVG paths
    char_to_stroke_ids: dict[str, list[int]] = {}

    for char, svg_paths in char_graphics.items():
        stroke_ids = []
        for svg in svg_paths:
            stroke_id = classify_stroke_by_svg(svg)
            stroke_ids.append(stroke_id)
        char_to_stroke_ids[char] = stroke_ids

    # Build final JSON
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

    # Write file
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(taxonomy, f, ensure_ascii=False, indent=2)

    return taxonomy
