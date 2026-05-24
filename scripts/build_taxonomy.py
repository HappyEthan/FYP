"""Build stroke taxonomy JSON from Make Me a Hanzi raw data."""

import os
import sys

# Add project root to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.stroke_taxonomy.parser import build_taxonomy

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "stroke_taxonomy", "raw")
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "stroke_taxonomy", "stroke_taxonomy.json")


def main():
    dict_path = os.path.join(RAW_DIR, "dictionary.txt")
    graph_path = os.path.join(RAW_DIR, "graphics.txt")

    if not os.path.exists(dict_path):
        print(f"dictionary.txt not found at {dict_path}")
        print("Run scripts/download_data.py first.")
        sys.exit(1)

    if not os.path.exists(graph_path):
        print(f"graphics.txt not found at {graph_path}")
        print("Run scripts/download_data.py first.")
        sys.exit(1)

    print(f"Building taxonomy from {dict_path} and {graph_path} ...")
    taxonomy = build_taxonomy(dict_path, graph_path, OUTPUT_PATH)

    num_chars = len(taxonomy["char_to_strokes"])
    num_strokes = len(taxonomy["strokes"])
    print(f"Done. {num_chars} characters, {num_strokes} stroke types.")
    print(f"Output: {os.path.abspath(OUTPUT_PATH)}")


if __name__ == "__main__":
    main()
