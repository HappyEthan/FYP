"""OCR + stroke taxonomy end-to-end annotation pipeline.

Flow: image -> OCR character recognition -> stroke taxonomy lookup -> annotation result.
"""

from typing import Optional

import numpy as np

from src.ocr.recognizer import CalligraphyOCR
from src.stroke_taxonomy.taxonomy import StrokeTaxonomy


class AnnotationPipeline:
    """Calligraphy character auto-annotation pipeline."""

    def __init__(
        self,
        taxonomy_path: str,
        ocr_confidence_threshold: float = 0.5,
    ):
        """Initialize the annotation pipeline.

        Args:
            taxonomy_path: Path to stroke_taxonomy.json
            ocr_confidence_threshold: OCR confidence threshold
        """
        self._taxonomy = StrokeTaxonomy(taxonomy_path)
        self._ocr = CalligraphyOCR(confidence_threshold=ocr_confidence_threshold)

    def annotate(self, image: np.ndarray) -> Optional[dict]:
        """Annotate an image with full stroke information.

        Args:
            image: BGR format numpy array

        Returns:
            Annotation result dict with:
            - char: Recognized character label
            - stroke_ids: Stroke category ID list (None if char not in taxonomy)
            - stroke_names: Stroke name list (None if char not in taxonomy)
            - stroke_count: Number of strokes (None if char not in taxonomy)
            Returns None if OCR recognition fails.
        """
        char = self._ocr.recognize(image)
        if char is None:
            return None

        return self._build_result(char)

    def annotate_from_file(self, image_path: str) -> Optional[dict]:
        """Annotate from a file path.

        Args:
            image_path: Path to image file

        Returns:
            Same format as annotate().
        """
        char = self._ocr.recognize_from_file(image_path)
        if char is None:
            return None

        return self._build_result(char)

    def _build_result(self, char: str) -> dict:
        """Build annotation result from character label."""
        stroke_ids = self._taxonomy.get_char_strokes(char)

        if stroke_ids is not None:
            stroke_names = self._taxonomy.get_char_strokes_with_names(char)
            stroke_count = len(stroke_ids)
        else:
            stroke_names = None
            stroke_count = None

        return {
            "char": char,
            "stroke_ids": stroke_ids,
            "stroke_names": stroke_names,
            "stroke_count": stroke_count,
        }
