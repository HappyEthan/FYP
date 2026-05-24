"""Download Make Me a Hanzi project data files."""

import os
import json
import urllib.request

DICTIONARY_URL = "https://raw.githubusercontent.com/skishore/makemeahanzi/master/dictionary.txt"
GRAPHICS_URL = "https://raw.githubusercontent.com/skishore/makemeahanzi/master/graphics.txt"


def download_make_me_a_hanzi(output_dir: str) -> None:
    """Download dictionary.txt and graphics.txt to the specified directory.

    Args:
        output_dir: Target directory path, created if it doesn't exist.
    """
    os.makedirs(output_dir, exist_ok=True)

    dict_path = os.path.join(output_dir, "dictionary.txt")
    graph_path = os.path.join(output_dir, "graphics.txt")

    for url, path in [(DICTIONARY_URL, dict_path), (GRAPHICS_URL, graph_path)]:
        if not os.path.exists(path):
            print(f"Downloading {url} ...")
            urllib.request.urlretrieve(url, path)
            print(f"Saved to {path}")
        else:
            print(f"Already exists: {path}")

    # Verify downloaded file is valid JSON Lines format
    for path in [dict_path]:
        with open(path, "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
            json.loads(first_line)  # Will raise if format is wrong


if __name__ == "__main__":
    import sys
    output_dir = sys.argv[1] if len(sys.argv) > 1 else "data/stroke_taxonomy/raw"
    download_make_me_a_hanzi(output_dir)
