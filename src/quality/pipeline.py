"""End-to-end calligraphy quality assessment pipeline.

Flow: image -> OCR recognition -> reference rendering -> quality assessment.
"""

from typing import Optional

import cv2
import numpy as np

from src.ocr.pipeline import AnnotationPipeline
from src.quality.assessor import QualityAssessor
from src.quality.reference import ReferenceRenderer


class QualityPipeline:
    """End-to-end pipeline for calligraphy visual quality assessment."""

    def __init__(
        self,
        taxonomy_path: str,
        ocr_confidence_threshold: float = 0.5,
        font_path: str = "C:/Windows/Fonts/simkai.ttf",
        font_size: int = 256,
        image_size: tuple = (300, 300),
    ):
        """Initialize the quality assessment pipeline.

        Args:
            taxonomy_path: Path to stroke_taxonomy.json
            ocr_confidence_threshold: OCR confidence threshold
            font_path: Path to KaiTi .ttf font file
            font_size: Font height in pixels for reference rendering
            image_size: Output image dimensions for reference (width, height)
        """
        self._annotation = AnnotationPipeline(
            taxonomy_path=taxonomy_path,
            ocr_confidence_threshold=ocr_confidence_threshold,
        )
        self._renderer = ReferenceRenderer(
            font_path=font_path,
            font_size=font_size,
            image_size=image_size,
        )
        self._assessor = QualityAssessor(self._renderer)

    def assess_from_camera(self, camera_id: int = 0) -> Optional[dict]:
        """Capture from camera, recognize, and assess quality.

        Args:
            camera_id: Camera device ID (default 0)

        Returns:
            Quality assessment result dict, or None if OCR fails
        """
        cap = cv2.VideoCapture(camera_id)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open camera {camera_id}")

        try:
            ret, frame = cap.read()
            if not ret:
                raise RuntimeError("Failed to capture frame from camera")
        finally:
            cap.release()

        return self.assess(frame)

    def assess_from_file(self, image_path: str) -> Optional[dict]:
        """Assess quality from an image file.

        Args:
            image_path: Path to image file

        Returns:
            Quality assessment result dict, or None if OCR fails
        """
        image = cv2.imread(image_path)
        if image is None:
            raise FileNotFoundError(f"Cannot read image: {image_path}")
        return self.assess(image)

    def assess(self, image: np.ndarray) -> Optional[dict]:
        """Assess quality from a numpy image array.

        Args:
            image: BGR format numpy array

        Returns:
            Quality assessment result dict with annotation + quality scores,
            or None if OCR recognition fails
        """
        annotation = self._annotation.annotate(image)
        if annotation is None:
            return None

        char = annotation["char"]
        quality = self._assessor.assess(image, char)

        return {
            **annotation,
            **quality,
        }
