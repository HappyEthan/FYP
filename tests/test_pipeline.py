"""OCR + stroke taxonomy end-to-end pipeline tests."""

import json
import os
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.ocr.pipeline import AnnotationPipeline


@pytest.fixture
def taxonomy_file(tmp_path):
    """Create a sample stroke taxonomy JSON file."""
    data = {
        "strokes": [
            {"id": 0, "name": "横", "name_pinyin": "heng", "stroke_type": "basic", "description": "Horizontal stroke"},
            {"id": 1, "name": "竖", "name_pinyin": "shu", "stroke_type": "basic", "description": "Vertical stroke"},
            {"id": 2, "name": "撇", "name_pinyin": "pie", "stroke_type": "basic", "description": "Diagonal stroke"},
            {"id": 3, "name": "捺", "name_pinyin": "na", "stroke_type": "basic", "description": "Diagonal stroke"},
            {"id": 4, "name": "点", "name_pinyin": "dian", "stroke_type": "basic", "description": "Dot stroke"},
            {"id": 14, "name": "横折钩", "name_pinyin": "hengzhegou", "stroke_type": "compound", "description": "Horizontal fold with hook"},
            {"id": 15, "name": "横撇", "name_pinyin": "hengpie", "stroke_type": "compound", "description": "Horizontal then diagonal"},
        ],
        "char_to_strokes": {
            "永": [4, 14, 15, 2, 3],
            "一": [0],
        },
    }
    path = os.path.join(str(tmp_path), "stroke_taxonomy.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return path


class TestAnnotationPipeline:
    @patch("src.ocr.pipeline.CalligraphyOCR")
    def test_annotate_single_char(self, mock_ocr_cls, taxonomy_file):
        """End-to-end: OCR -> taxonomy lookup -> stroke sequence."""
        mock_ocr_instance = MagicMock()
        mock_ocr_cls.return_value = mock_ocr_instance
        mock_ocr_instance.recognize.return_value = "永"

        pipeline = AnnotationPipeline(
            taxonomy_path=taxonomy_file,
            ocr_confidence_threshold=0.5,
        )

        dummy_img = np.ones((100, 100, 3), dtype=np.uint8) * 255
        result = pipeline.annotate(dummy_img)

        assert result is not None
        assert result["char"] == "永"
        assert result["stroke_ids"] == [4, 14, 15, 2, 3]
        assert result["stroke_names"] == ["点", "横折钩", "横撇", "撇", "捺"]
        assert result["stroke_count"] == 5

    @patch("src.ocr.pipeline.CalligraphyOCR")
    def test_annotate_char_not_in_taxonomy(self, mock_ocr_cls, taxonomy_file):
        """When char not in taxonomy, return char but stroke_ids/names as None."""
        mock_ocr_instance = MagicMock()
        mock_ocr_cls.return_value = mock_ocr_instance
        mock_ocr_instance.recognize.return_value = "龘"

        pipeline = AnnotationPipeline(
            taxonomy_path=taxonomy_file,
            ocr_confidence_threshold=0.5,
        )

        dummy_img = np.ones((100, 100, 3), dtype=np.uint8) * 255
        result = pipeline.annotate(dummy_img)

        assert result is not None
        assert result["char"] == "龘"
        assert result["stroke_ids"] is None
        assert result["stroke_names"] is None
        assert result["stroke_count"] is None

    @patch("src.ocr.pipeline.CalligraphyOCR")
    def test_annotate_ocr_failure(self, mock_ocr_cls, taxonomy_file):
        """When OCR fails, return None."""
        mock_ocr_instance = MagicMock()
        mock_ocr_cls.return_value = mock_ocr_instance
        mock_ocr_instance.recognize.return_value = None

        pipeline = AnnotationPipeline(
            taxonomy_path=taxonomy_file,
            ocr_confidence_threshold=0.5,
        )

        dummy_img = np.ones((100, 100, 3), dtype=np.uint8) * 255
        result = pipeline.annotate(dummy_img)

        assert result is None

    @patch("src.ocr.pipeline.CalligraphyOCR")
    def test_annotate_from_file(self, mock_ocr_cls, taxonomy_file):
        """Annotation from file path should work."""
        mock_ocr_instance = MagicMock()
        mock_ocr_cls.return_value = mock_ocr_instance
        mock_ocr_instance.recognize_from_file.return_value = "一"

        pipeline = AnnotationPipeline(
            taxonomy_path=taxonomy_file,
            ocr_confidence_threshold=0.5,
        )

        result = pipeline.annotate_from_file("/fake/path/to/image.png")

        assert result is not None
        assert result["char"] == "一"
        assert result["stroke_ids"] == [0]
        assert result["stroke_names"] == ["横"]
        assert result["stroke_count"] == 1
