"""Explicit character priors, kept separate from image recognition."""

# Indices refer to the original ordered Make Me a Hanzi median vertices.
# These are candidate structural labels, never human-confirmation flags.
YONG_MEDIANS_SHA256 = '894b5267ca26f959a97e438f81d2275671ff6a5ee41df83186052f354257602a'
YONG_STROKES = [
    ('dian', '点', []),
    ('hengzhegou', '横折钩', [('turn', 4), ('hook', 6)]),
    ('hengpie', '横撇', [('turn', 5)]),
    ('pie', '撇', []),
    ('na', '捺', []),
]
