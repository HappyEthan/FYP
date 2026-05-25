"""One-click calligraphy quality assessment from camera.

Usage: pixi run python scripts/assess_quality.py
"""

import os
import sys

import cv2

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.quality.pipeline import QualityPipeline


def main():
    taxonomy_path = os.path.join(
        os.path.dirname(__file__), "..", "data", "stroke_taxonomy", "stroke_taxonomy.json"
    )

    if not os.path.exists(taxonomy_path):
        print(f"Taxonomy file not found: {taxonomy_path}")
        print("Run: pixi run download-data && pixi run build-taxonomy")
        sys.exit(1)

    print("Initializing quality assessment pipeline...")
    pipeline = QualityPipeline(taxonomy_path=taxonomy_path)

    print("Press Enter to capture photo from camera, or type a file path to assess from file.")
    choice = input("> ").strip()

    if choice:
        print(f"Assessing from file: {choice}")
        result = pipeline.assess_from_file(choice)
    else:
        print("Capturing from camera... (press any key in the preview window to capture)")
        result = pipeline.assess_from_camera()

    if result is None:
        print("ERROR: OCR recognition failed. Could not identify character.")
        sys.exit(1)

    print()
    print("=" * 50)
    print(f"  Character: {result['char']}")
    print(f"  Stroke count: {result['stroke_count']}")
    print(f"  Stroke names: {' → '.join(result['stroke_names'] or [])}")
    print("-" * 50)
    print(f"  Shape Score:     {result['shape_score']:.4f}")
    print(f"  Position Score:  {result['position_score']:.4f}")
    print(f"  Structure Score: {result['structure_score']:.4f}")
    print("-" * 50)
    print(f"  OVERALL SCORE:   {result['overall_score']:.4f}")
    print("=" * 50)

    # Save result visualization
    out_path = "quality_result.png"
    ref_renderer = pipeline._renderer
    ref_img = ref_renderer.render(result["char"])
    cv2.imwrite(out_path, ref_img)
    print(f"\nReference image saved to: {out_path}")


if __name__ == "__main__":
    main()
