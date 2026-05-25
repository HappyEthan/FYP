import json
import os
import shutil
import tempfile

import pytest

RAW_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "stroke_taxonomy", "raw"
)


@pytest.mark.skipif(
    not (
        os.path.exists(os.path.join(RAW_DIR, "dictionary.txt"))
        and os.path.exists(os.path.join(RAW_DIR, "graphics.txt"))
    ),
    reason="Local raw data not found; run 'pixi run download-data' first",
)
def test_local_raw_data_valid():
    """Local raw data files should exist and be valid JSON Lines."""
    dict_path = os.path.join(RAW_DIR, "dictionary.txt")
    graph_path = os.path.join(RAW_DIR, "graphics.txt")

    assert os.path.getsize(dict_path) > 0, "dictionary.txt should not be empty"
    assert os.path.getsize(graph_path) > 0, "graphics.txt should not be empty"

    with open(dict_path, "r", encoding="utf-8") as f:
        first_line = f.readline().strip()
        data = json.loads(first_line)
        assert "character" in data
        assert "decomposition" in data or "strokes" in data
