"""Visual quality assessment tests."""

import json
import os
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import pytest

from src.quality.assessor import QualityAssessor
from src.quality.pipeline import QualityPipeline
from src.quality.reference import ReferenceRenderer


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


@pytest.fixture
def renderer():
    """Create a ReferenceRenderer with KaiTi font."""
    return ReferenceRenderer(
        font_path="C:/Windows/Fonts/simkai.ttf",
        font_size=256,
        image_size=(300, 300),
    )


@pytest.fixture
def assessor(renderer):
    """Create a QualityAssessor."""
    return QualityAssessor(renderer)


class TestReferenceRenderer:
    """Tests for ReferenceRenderer."""

    def test_render_returns_correct_size(self, renderer):
        """Rendered image should be 300x300."""
        result = renderer.render("永")
        assert result.shape == (300, 300)

    def test_render_is_not_empty(self, renderer):
        """Rendered image should not be all white (has content)."""
        result = renderer.render("永")
        assert np.min(result) < 255

    def test_render_is_binary(self, renderer):
        """Rendered image should contain only 0 and 255 values."""
        result = renderer.render("永")
        unique = np.unique(result)
        assert all(v in (0, 255) for v in unique)

    def test_render_different_chars_different(self, renderer):
        """Different characters should produce different images."""
        yong = renderer.render("永")
        yi = renderer.render("一")
        assert not np.array_equal(yong, yi)


class TestQualityAssessor:
    """Tests for QualityAssessor."""

    def test_assess_returns_all_scores(self, assessor, renderer):
        """Assess should return all score fields."""
        ref_img = renderer.render("永")
        # Convert binary to BGR for assess input
        user_img = cv2.cvtColor(ref_img, cv2.COLOR_GRAY2BGR)
        result = assessor.assess(user_img, "永")

        assert "char" in result
        assert "shape_score" in result
        assert "position_score" in result
        assert "structure_score" in result
        assert "overall_score" in result
        assert result["char"] == "永"

    def test_identical_image_high_score(self, assessor, renderer):
        """Same image as reference should get high scores."""
        ref_img = renderer.render("永")
        user_img = cv2.cvtColor(ref_img, cv2.COLOR_GRAY2BGR)
        result = assessor.assess(user_img, "永")

        assert result["shape_score"] > 0.9
        assert result["position_score"] > 0.9
        assert result["structure_score"] > 0.9
        assert result["overall_score"] > 0.9

    def test_different_char_low_score(self, assessor, renderer):
        """Different character should get lower scores."""
        ref_img = renderer.render("一")
        user_img = cv2.cvtColor(ref_img, cv2.COLOR_GRAY2BGR)
        result = assessor.assess(user_img, "永")

        assert result["overall_score"] < 0.9

    def test_scores_in_range(self, assessor, renderer):
        """All scores should be in [0, 1]."""
        ref_img = renderer.render("永")
        user_img = cv2.cvtColor(ref_img, cv2.COLOR_GRAY2BGR)
        result = assessor.assess(user_img, "永")

        for key in ["shape_score", "position_score", "structure_score", "overall_score"]:
            assert 0.0 <= result[key] <= 1.0, f"{key} out of range: {result[key]}"

    def test_blank_image_gets_low_structure_score(self, assessor):
        """Blank white image should get low structure score (no character structure)."""
        blank = np.ones((300, 300, 3), dtype=np.uint8) * 255
        result = assessor.assess(blank, "永")

        # SSIM is high because both are mostly white background,
        # but structure score (Hu Moments) should be low since blank has no shape
        assert result["structure_score"] < 0.5

    def test_grayscale_input_accepted(self, assessor, renderer):
        """Grayscale input should work."""
        ref_img = renderer.render("永")
        result = assessor.assess(ref_img, "永")

        assert result["char"] == "永"
        assert 0.0 <= result["overall_score"] <= 1.0

    def test_map_to_score_range(self, assessor):
        """_map_to_score should produce values in [0, 1]."""
        assert assessor._map_to_score(0, 10, 0) == 1.0
        assert assessor._map_to_score(10, 10, 0) == 0.0
        assert assessor._map_to_score(5, 10, 0) == 0.5
        assert assessor._map_to_score(15, 10, 0) == 0.0  # clamped
        assert assessor._map_to_score(-1, 10, 0) == 1.0  # clamped


class TestQualityPipeline:
    """Tests for QualityPipeline end-to-end."""

    def test_assess_returns_combined_result(self, taxonomy_file, renderer):
        """Pipeline should combine annotation + quality scores."""
        ref_img = renderer.render("永")
        user_img = cv2.cvtColor(ref_img, cv2.COLOR_GRAY2BGR)

        with patch("src.ocr.pipeline.CalligraphyOCR") as mock_ocr_cls:
            mock_ocr = MagicMock()
            mock_ocr_cls.return_value = mock_ocr
            mock_ocr.recognize.return_value = "永"

            pipeline = QualityPipeline(taxonomy_path=taxonomy_file)
            result = pipeline.assess(user_img)

        assert result is not None
        assert result["char"] == "永"
        assert result["stroke_ids"] == [4, 14, 15, 2, 3]
        assert result["stroke_names"] == ["点", "横折钩", "横撇", "撇", "捺"]
        assert result["stroke_count"] == 5
        assert "shape_score" in result
        assert "position_score" in result
        assert "structure_score" in result
        assert "overall_score" in result

    def test_assess_ocr_failure_returns_none(self, taxonomy_file):
        """When OCR fails, pipeline should return None."""
        dummy_img = np.ones((100, 100, 3), dtype=np.uint8) * 255

        with patch("src.ocr.pipeline.CalligraphyOCR") as mock_ocr_cls:
            mock_ocr = MagicMock()
            mock_ocr_cls.return_value = mock_ocr
            mock_ocr.recognize.return_value = None

            pipeline = QualityPipeline(taxonomy_path=taxonomy_file)
            result = pipeline.assess(dummy_img)

        assert result is None

    def test_assess_from_file(self, taxonomy_file, renderer, tmp_path):
        """assess_from_file should work with a real image file."""
        ref_img = renderer.render("永")
        img_path = os.path.join(str(tmp_path), "test_char.png")
        cv2.imwrite(img_path, ref_img)

        with patch("src.ocr.pipeline.CalligraphyOCR") as mock_ocr_cls:
            mock_ocr = MagicMock()
            mock_ocr_cls.return_value = mock_ocr
            # assess_from_file calls annotate() which uses recognize(), not recognize_from_file
            mock_ocr.recognize.return_value = "永"

            pipeline = QualityPipeline(taxonomy_path=taxonomy_file)
            result = pipeline.assess_from_file(img_path)

        assert result is not None
        assert result["char"] == "永"
        assert "overall_score" in result
