"""Pure Make Me a Hanzi preview data adapter."""

from pathlib import Path

from brushbot.calligraphy.hanzi import load_medians, medians_to_strokes, strokes_to_waypoints


DEFAULT_GRAPHICS = Path(__file__).resolve().parents[3] / "data" / "makemeahanzi" / "graphics.txt"


def preview_character(character, graphics_path=None):
    if not isinstance(character, str) or len(character) != 1:
        raise ValueError("请输入一个汉字")
    medians = load_medians(character, str(graphics_path or DEFAULT_GRAPHICS))
    strokes = medians_to_strokes(medians, size=1.0)
    return {
        "character": character,
        "stroke_count": len(strokes),
        "strokes": [[[float(x), float(y)] for x, y in stroke] for stroke in strokes],
    }


def build_hanzi_plan(character, *, graphics_path=None, origin=(0.45, 0.0),
                     size_m=0.032, z_down_m=0.195, z_up_m=0.23,
                     orientation=(3.141592653589793, 0.0, 1.5707963267948966),
                     yaw_deg=-90.0):
    """Build fixed-orientation six-dimensional waypoints for one character.

    All motion values are explicit server-side configuration; the browser only
    supplies the character.
    """
    if not isinstance(character, str) or len(character) != 1:
        raise ValueError("请输入一个汉字")
    medians = load_medians(character, str(graphics_path or DEFAULT_GRAPHICS))
    strokes = medians_to_strokes(medians, size=size_m)
    xyz = strokes_to_waypoints(strokes, origin, z_down_m, z_up_m,
                               char_yaw_deg=yaw_deg)
    ori = tuple(float(v) for v in orientation)
    if len(ori) != 3:
        raise ValueError("orientation must contain three values")
    return [tuple(float(v) for v in (x, y, z, *ori)) for x, y, z in xyz]
