"""OCR recognizer tests.

Uses mock to test OCR logic without requiring real PaddleOCR installation.
"""

import os
import tempfile
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from src.ocr.recognizer import CalligraphyOCR


class TestCalligraphyOCRWithMock:
    """Test OCR logic using mocks, no real PaddleOCR needed."""

    @patch("src.ocr.recognizer.PaddleOCR")
    def test_init_creates_ocr_engine(self, mock_paddle_ocr):
        """OCR init should create a PaddleOCR instance."""
        ocr = CalligraphyOCR()
        mock_paddle_ocr.assert_called_once()

    @patch("src.ocr.recognizer.PaddleOCR")
    def test_recognize_single_char(self, mock_paddle_ocr):
        """Single character recognition should return the character label."""
        mock_instance = MagicMock()
        mock_paddle_ocr.return_value = mock_instance
        mock_instance.ocr.return_value = [
            [
                [[[10, 10], [100, 10], [100, 100], [10, 100]], ("永", 0.99)]
            ]
        ]

        ocr = CalligraphyOCR()
        dummy_img = np.ones((100, 100, 3), dtype=np.uint8) * 255
        result = ocr.recognize(dummy_img)

        assert result == "永"

    @patch("src.ocr.recognizer.PaddleOCR")
    def test_recognize_no_text_found(self, mock_paddle_ocr):
        """Should return None when no text is found."""
        mock_instance = MagicMock()
        mock_paddle_ocr.return_value = mock_instance
        mock_instance.ocr.return_value = [[]]

        ocr = CalligraphyOCR()
        dummy_img = np.ones((100, 100, 3), dtype=np.uint8) * 255
        result = ocr.recognize(dummy_img)

        assert result is None

    @patch("src.ocr.recognizer.PaddleOCR")
    def test_recognize_from_file(self, mock_paddle_ocr):
        """Recognition from file path should work."""
        import sys
        from unittest.mock import MagicMock as MM

        mock_instance = MagicMock()
        mock_paddle_ocr.return_value = mock_instance
        mock_instance.ocr.return_value = [
            [[[[0, 0], [100, 0], [100, 100], [0, 100]], ("字", 0.95)]]
        ]

        # Inject a fake cv2 module so the import inside recognize_from_file works
        fake_cv2 = MM()
        fake_cv2.imread.return_value = np.ones((100, 100, 3), dtype=np.uint8) * 255
        sys.modules["cv2"] = fake_cv2

        ocr = CalligraphyOCR()
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            temp_path = f.name

        try:
            result = ocr.recognize_from_file(temp_path)
            assert result == "字"
        finally:
            os.unlink(temp_path)
            del sys.modules["cv2"]

    @patch("src.ocr.recognizer.PaddleOCR")
    def test_recognize_multiple_returns_highest_confidence(self, mock_paddle_ocr):
        """When multiple characters detected, return the one with highest confidence."""
        mock_instance = MagicMock()
        mock_paddle_ocr.return_value = mock_instance
        mock_instance.ocr.return_value = [
            [
                [[[10, 10], [50, 10], [50, 50], [10, 50]], ("永", 0.99)],
                [[[60, 10], [100, 10], [100, 50], [60, 50]], ("字", 0.85)],
            ]
        ]

        ocr = CalligraphyOCR()
        dummy_img = np.ones((100, 200, 3), dtype=np.uint8) * 255
        result = ocr.recognize(dummy_img)

        assert result == "永"

    @patch("src.ocr.recognizer.PaddleOCR")
    def test_confidence_threshold(self, mock_paddle_ocr):
        """Should return None when confidence is below threshold."""
        mock_instance = MagicMock()
        mock_paddle_ocr.return_value = mock_instance
        mock_instance.ocr.return_value = [
            [[[[10, 10], [100, 10], [100, 100], [10, 100]], ("永", 0.30)]]
        ]

        ocr = CalligraphyOCR(confidence_threshold=0.5)
        dummy_img = np.ones((100, 100, 3), dtype=np.uint8) * 255
        result = ocr.recognize(dummy_img)

        assert result is None

    @patch("src.ocr.recognizer.PaddleOCR")
    def test_recognize_none_results(self, mock_paddle_ocr):
        """Should return None when OCR returns None."""
        mock_instance = MagicMock()
        mock_paddle_ocr.return_value = mock_instance
        mock_instance.ocr.return_value = None

        ocr = CalligraphyOCR()
        dummy_img = np.ones((100, 100, 3), dtype=np.uint8) * 255
        result = ocr.recognize(dummy_img)

        assert result is None
