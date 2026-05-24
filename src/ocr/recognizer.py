"""PaddleOCR wrapper for single character recognition.

Recognizes calligraphy character photos and returns the character label.
Accepts numpy arrays or file paths.
"""

from typing import Optional

import numpy as np

try:
    from paddleocr import PaddleOCR
except ImportError:
    PaddleOCR = None  # Allow import in environments without PaddleOCR


class CalligraphyOCR:
    """OCR recognizer for calligraphy characters."""

    def __init__(self, confidence_threshold: float = 0.5):
        """Initialize PaddleOCR engine.

        Args:
            confidence_threshold: Minimum confidence for recognition results.
        """
        if PaddleOCR is None:
            raise ImportError(
                "PaddleOCR is not installed. "
                "Install with: pip install paddleocr paddlepaddle"
            )
        self._ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
        self._confidence_threshold = confidence_threshold

    def recognize(self, image: np.ndarray) -> Optional[str]:
        """Recognize a single character from a numpy array.

        Args:
            image: BGR or grayscale image (numpy array)

        Returns:
            Recognized character label, or None if recognition fails
            or confidence is below threshold.
            When multiple characters are detected, returns the one with highest confidence.
        """
        results = self._ocr.ocr(image, cls=True)

        if not results or not results[0]:
            return None

        # Extract all results, filter by confidence
        candidates = []
        for line in results[0]:
            text = line[1][0]
            confidence = line[1][1]
            if confidence >= self._confidence_threshold:
                candidates.append((text, confidence))

        if not candidates:
            return None

        # Return highest confidence result
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0][0]

    def recognize_from_file(self, image_path: str) -> Optional[str]:
        """Recognize a single character from a file path.

        Args:
            image_path: Path to image file

        Returns:
            Recognized character label, or None if recognition fails.
        """
        import cv2
        image = cv2.imread(image_path)
        if image is None:
            return None
        return self.recognize(image)
