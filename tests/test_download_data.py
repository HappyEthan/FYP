import json
import os
import tempfile

from scripts.download_data import download_make_me_a_hanzi


def test_download_creates_files():
    """Download script should create dictionary.txt and graphics.txt"""
    with tempfile.TemporaryDirectory() as tmpdir:
        download_make_me_a_hanzi(output_dir=tmpdir)

        dict_path = os.path.join(tmpdir, "dictionary.txt")
        graph_path = os.path.join(tmpdir, "graphics.txt")

        assert os.path.exists(dict_path), "dictionary.txt should exist"
        assert os.path.exists(graph_path), "graphics.txt should exist"

        # Verify files are non-empty
        assert os.path.getsize(dict_path) > 0, "dictionary.txt should not be empty"
        assert os.path.getsize(graph_path) > 0, "graphics.txt should not be empty"

        # Verify dictionary.txt each line is valid JSON
        with open(dict_path, "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
            data = json.loads(first_line)
            assert "character" in data
            # dictionary.txt has "decomposition" not "strokes"; graphics.txt has "strokes"
            assert "decomposition" in data or "strokes" in data
