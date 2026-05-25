"""Standard character reference image generator.

Renders Chinese characters using OpenCV FreeType with KaiTi font
to produce clean reference images for quality comparison.
"""

import cv2
import numpy as np


class ReferenceRenderer:
    """Renders standard Chinese character images using KaiTi font."""

    def __init__(
        self,
        font_path: str = "C:/Windows/Fonts/simkai.ttf",
        font_size: int = 256,
        image_size: tuple = (300, 300),
    ):
        """Initialize the reference renderer.

        Args:
            font_path: Path to KaiTi .ttf font file
            font_size: Font height in pixels
            image_size: Output image dimensions (width, height)
        """
        self._font_path = font_path
        self._font_size = font_size
        self._image_size = image_size

        self._ft = cv2.freetype.createFreeType2()
        self._ft.loadFontData(font_path, 0)

    def render(self, char: str) -> np.ndarray:
        """Render a single Chinese character as a binary image (white bg, black char).

        Args:
            char: Single Chinese character to render

        Returns:
            Binary uint8 image (300x300), 0=black(char), 255=white(bg)
        """
        w, h = self._image_size
        img = np.ones((h, w, 3), dtype=np.uint8) * 255

        # Measure text size to center it
        size = self._ft.getTextSize(char, self._font_size, -1)
        baseline = size[1]
        text_w = size[0][0]
        text_h = size[0][1]

        x = (w - text_w) // 2
        y = (h + text_h) // 2 - baseline

        self._ft.putText(img, char, (x, y), self._font_size, (0, 0, 0), -1, cv2.LINE_AA, True)

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY)
        return binary
