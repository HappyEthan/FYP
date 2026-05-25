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


def parse_graphics_with_medians(
    file_path: str,
) -> dict[str, list[list[list[float]]]]:
    """Parse graphics.txt, return {character: [median point arrays]}.

    Each median is a list of [x, y] coordinate pairs representing the
    centerline trajectory of a single stroke.
    """
    result: dict[str, list[list[list[float]]]] = {}
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                char = data["character"]
                medians = data["medians"]
                result[char] = medians
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


def classify_stroke_by_median(median: list[list[float]]) -> int:
    """Classify a stroke by its median (centerline) trajectory.

    Uses heuristic rules on geometric features extracted from the median
    point sequence. The median represents the actual writing path, unlike
    SVG outlines which are filled closed shapes.

    Args:
        median: List of [x, y] coordinate pairs representing the stroke
                centerline. Typically 2-38 points.

    Returns:
        Stroke category ID (0-28)
    """
    pts = median
    if len(pts) < 2:
        return 4  # 点 (single point or empty)

    # ---- Geometric features ----

    # Path length (sum of segment lengths)
    path_len = 0.0
    segments: list[tuple[float, float]] = []
    for i in range(1, len(pts)):
        seg_dx = pts[i][0] - pts[i - 1][0]
        seg_dy = pts[i][1] - pts[i - 1][1]
        seg_len = math.sqrt(seg_dx * seg_dx + seg_dy * seg_dy)
        segments.append((seg_dx, seg_dy))
        path_len += seg_len

    # Overall displacement
    dx = pts[-1][0] - pts[0][0]
    dy = pts[-1][1] - pts[0][1]
    total_len = math.sqrt(dx * dx + dy * dy) + 1e-6
    straightness = total_len / path_len if path_len > 0 else 1.0
    overall_angle = math.atan2(dy, dx)

    # Initial and final segment directions
    init_angle = math.atan2(segments[0][1], segments[0][0])
    final_angle = math.atan2(segments[-1][1], segments[-1][0])

    # ---- Unified turn detection ----
    # Detect all direction changes and classify each as fold (折, > 60°)
    # or hook (钩, <= 60°). This is the key distinction: folds are large
    # direction changes, hooks are small ones at stroke ends.

    TURN_THRESHOLD = math.pi / 12  # 15° — minimum angle to count as a turn
    FOLD_THRESHOLD = math.pi / 3   # 60° — above this, a turn is a fold

    all_turns: list[dict] = []  # {index, angle, direction}
    if len(pts) >= 3:
        for i in range(1, len(pts) - 1):
            s1_dx = pts[i][0] - pts[i - 1][0]
            s1_dy = pts[i][1] - pts[i - 1][1]
            s2_dx = pts[i + 1][0] - pts[i][0]
            s2_dy = pts[i + 1][1] - pts[i][1]
            len1 = math.sqrt(s1_dx * s1_dx + s1_dy * s1_dy) + 1e-6
            len2 = math.sqrt(s2_dx * s2_dx + s2_dy * s2_dy) + 1e-6
            dot = (s1_dx * s2_dx + s1_dy * s2_dy) / (len1 * len2)
            dot = max(-1.0, min(1.0, dot))
            ang = math.acos(dot)
            if ang > TURN_THRESHOLD:
                cross = s1_dx * s2_dy - s1_dy * s2_dx
                all_turns.append({
                    "index": i,
                    "angle": ang,
                    "direction": 1 if cross > 0 else -1,
                    "is_fold": ang > FOLD_THRESHOLD,
                })

    num_turns = len(all_turns)
    num_folds = sum(1 for t in all_turns if t["is_fold"])
    num_hooks = num_turns - num_folds

    # A stroke has a hook if its LAST turn is a hook (small angle)
    has_hook = num_turns > 0 and not all_turns[-1]["is_fold"]
    hook_direction = all_turns[-1]["direction"] if has_hook else 0

    # Check if stroke is a smooth curve (multiple small turns, all hooks)
    is_curve = num_turns >= 2 and all(not t["is_fold"] for t in all_turns)

    # Largest turn angle
    max_turn = max((t["angle"] for t in all_turns), default=0.0)

    # ---- Classification decision tree ----

    # 1. Very short stroke → 点
    if path_len < 20:
        return 4  # 点

    # 2. Rising stroke (提) — short diagonal rising rightward.
    #    Must check BEFORE straight strokes because 提 has the same
    #    num_turns==0, straightness>0.8 profile as 撇/捺.
    if num_turns == 0 and dx > 0 and -math.pi / 3 < overall_angle < -math.pi / 12 and straightness > 0.6:
        return 5  # 提

    # 3. Straight strokes (no turns, high straightness)
    if num_turns == 0 and straightness > 0.8:
        if abs(overall_angle) < math.pi / 12 or abs(overall_angle) > 11 * math.pi / 12:
            return 0  # 横
        elif abs(abs(overall_angle) - math.pi / 2) < math.pi / 12:
            return 1  # 竖
        elif dx < 0:
            return 2  # 撇 (right-to-left)
        else:
            return 3  # 捺 (left-to-right)

    # 4. Single turn = either a fold or a hook
    if num_turns == 1:
        turn = all_turns[0]
        if turn["is_fold"]:
            # Large turn = fold (折)
            if abs(init_angle) < math.pi / 6:
                # Horizontal start: distinguish 横折 (~90°) from 横撇 (>100°)
                if max_turn > 100 * math.pi / 180:  # > 100°
                    return 15  # 横撇
                return 11  # 横折
            elif abs(abs(init_angle) - math.pi / 2) < math.pi / 6:
                # Vertical start: check final direction
                if final_angle < -math.pi / 6:
                    return 20  # 竖提 (ends rising right-up)
                return 12  # 竖折
            elif dx < 0:
                # Diagonal left-down start (pie): 撇点 vs 撇折
                # 撇点: pie then dot (final goes right-down)
                # 撇折: pie then horizontal fold (final goes right)
                if final_angle > 0:
                    return 21  # 撇点
                return 13  # 撇折
            else:
                return 13  # 撇折
        else:
            # Small turn = hook (钩)
            if abs(init_angle) < math.pi / 6:
                return 10  # 横钩
            elif abs(abs(init_angle) - math.pi / 2) < math.pi / 6:
                # hook_direction: +1 = left turn (竖钩), -1 = right turn
                # Right turn from vertical with gentle curve = 竖弯(24), not 竖提(20)
                if hook_direction > 0:
                    return 6  # 竖钩 (hook goes left)
                # Right turn: check if it's a short tick (竖提) or gentle curve (竖弯)
                # 竖弯 curves right gently (< 60°, the fold threshold)
                # 竖提 ticks right-up more sharply
                if max_turn < FOLD_THRESHOLD:
                    return 24  # 竖弯 (gentle curve)
                return 20  # 竖提 (sharper tick)
            else:
                return 8  # 斜钩

    # 5. Two turns
    if num_turns == 2:
        t1, t2 = all_turns[0], all_turns[1]
        if t1["is_fold"] and not t2["is_fold"]:
            # Fold + hook
            if abs(init_angle) < math.pi / 6:
                # 横折钩(14) vs 横折弯(23): both have fold+hook pattern
                # 横折弯: the "hook" is actually a gentle curve continuing right
                # 横折钩: the hook is a clear leftward hook at the end
                if t2["direction"] > 0:
                    return 14  # 横折钩 (hook turns left)
                return 23  # 横折弯 (curve continues right)
            elif abs(abs(init_angle) - math.pi / 2) < math.pi / 6:
                return 18  # 竖折折钩
            else:
                return 16  # 横撇弯钩
        elif t1["is_fold"] and t2["is_fold"]:
            # Two folds
            if abs(init_angle) < math.pi / 6:
                # 横折折撇(19): ends with diagonal left-down (pie), final dx < 0
                # 横折提(22): ends with right-up tick, final dx > 0 and final dy < 0
                # 横折折(28): ends going right or down, final dx > 0 and final dy > 0
                last_seg_dx = segments[-1][0]
                last_seg_dy = segments[-1][1]
                if last_seg_dx < 0:
                    return 19  # 横折折撇 (ends going left = pie)
                if last_seg_dy < 0:
                    return 22  # 横折提 (ends going up = ti)
                return 28  # 横折折 (ends going right-down)
            elif abs(abs(init_angle) - math.pi / 2) < math.pi / 6:
                return 24  # 竖弯
            else:
                return 21  # 撇点
        elif not t1["is_fold"] and t2["is_fold"]:
            # Hook then fold
            if abs(init_angle) < math.pi / 6:
                return 26  # 横斜钩
            elif abs(abs(init_angle) - math.pi / 2) < math.pi / 6:
                return 25  # 竖弯钩 (vertical, curve right, hook left)
            else:
                return 8  # 斜钩
        else:
            # Two hooks = curved stroke
            if abs(init_angle) < math.pi / 6:
                return 10  # 横钩
            elif abs(abs(init_angle) - math.pi / 2) < math.pi / 6:
                return 25  # 竖弯钩
            else:
                return 7  # 弯钩

    # 6. Three or more turns
    if num_turns >= 3:
        if has_hook:
            # 竖折折钩(18): vertical start, 2+ folds, ends with hook
            if abs(abs(init_angle) - math.pi / 2) < math.pi / 6:
                return 18  # 竖折折钩
            return 27  # 横折折折钩
        else:
            # Distinguish 横折折撇/横折提/横折折 by final segment direction
            if abs(init_angle) < math.pi / 6:
                last_seg_dx = segments[-1][0]
                last_seg_dy = segments[-1][1]
                if last_seg_dx < 0:
                    return 19  # 横折折撇 (ends going left = pie)
                if last_seg_dy < 0:
                    return 22  # 横折提 (ends going up = ti)
            return 28  # 横折折

    # 7. Curved strokes (all small turns = hooks)
    if is_curve:
        if abs(overall_angle) < math.pi / 6:
            return 9  # 卧钩 (flat hook)
        elif abs(abs(init_angle) - math.pi / 2) < math.pi / 6:
            return 25  # 竖弯钩
        else:
            return 7  # 弯钩

    # Fallback: classify by initial direction and whether it has a hook
    if has_hook:
        if abs(init_angle) < math.pi / 6:
            return 14  # 横折钩
        elif abs(abs(init_angle) - math.pi / 2) < math.pi / 6:
            return 6  # 竖钩
        else:
            return 8  # 斜钩
    else:
        if num_folds >= 1:
            if abs(init_angle) < math.pi / 6:
                return 11  # 横折
            elif abs(abs(init_angle) - math.pi / 2) < math.pi / 6:
                return 12  # 竖折
            else:
                return 13  # 撇折
        return 19  # 横折折撇

    return 0  # Unreachable, but kept as safety default


def build_taxonomy(dict_path: str, graph_path: str, output_path: str) -> dict:
    """Build the complete stroke taxonomy JSON file.

    Classifies strokes from graphics.txt median (centerline) data using
    geometric heuristics. The medians represent actual writing trajectories,
    unlike SVG outlines which are filled closed shapes.

    Args:
        dict_path: Path to dictionary.txt (reserved for future decomposition
                   tree propagation)
        graph_path: Path to graphics.txt
        output_path: Output JSON file path

    Returns:
        Built taxonomy dictionary
    """
    char_medians = parse_graphics_with_medians(graph_path)

    # Classify strokes from median trajectories
    char_to_stroke_ids: dict[str, list[int]] = {}

    for char, medians in char_medians.items():
        stroke_ids = []
        for median in medians:
            stroke_id = classify_stroke_by_median(median)
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
