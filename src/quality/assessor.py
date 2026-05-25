"""Calligraphy visual quality assessor.

Compares user-written character images against standard reference images
across three dimensions: shape (SSIM), position (centroid/bbox), and
structure (Hu Moments + aspect ratio).
"""

import cv2
import numpy as np

from src.quality.reference import ReferenceRenderer


class QualityAssessor:
    """Assesses calligraphy character quality against reference images."""

    def __init__(self, reference_renderer: ReferenceRenderer):
        """Initialize with a reference renderer.

        Args:
            reference_renderer: ReferenceRenderer instance for generating standard images
        """
        self._renderer = reference_renderer

    def assess(self, user_image: np.ndarray, char: str) -> dict:
        """Assess user image quality against standard reference.

        Args:
            user_image: BGR or grayscale user image (numpy array)
            char: The character label for generating reference

        Returns:
            Dict with shape_score, position_score, structure_score, overall_score
        """
        ref_bin = self._renderer.render(char)
        user_bin = self._preprocess(user_image)

        shape_score = self._compute_shape_score(user_bin, ref_bin)
        position_score = self._compute_position_score(user_bin, ref_bin)
        structure_score = self._compute_structure_score(user_bin, ref_bin)

        overall = 0.4 * shape_score + 0.3 * position_score + 0.3 * structure_score

        return {
            "char": char,
            "shape_score": round(shape_score, 4),
            "position_score": round(position_score, 4),
            "structure_score": round(structure_score, 4),
            "overall_score": round(overall, 4),
        }

    def _preprocess(self, img: np.ndarray) -> np.ndarray:
        """Convert input image to normalized binary (300x300, white bg, black char).

        Args:
            img: Input BGR or grayscale image

        Returns:
            300x300 binary uint8 image
        """
        if img.ndim == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img

        # Resize to match reference size
        gray = cv2.resize(gray, self._renderer._image_size, interpolation=cv2.INTER_AREA)

        # Otsu binarization
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # Determine if white-on-black or black-on-white by checking border pixels
        border_mean = np.mean(np.concatenate([
            binary[0, :], binary[-1, :], binary[:, 0], binary[:, -1]
        ]))
        if border_mean < 127:
            # Dark background, white text — invert to white bg, black text
            binary = cv2.bitwise_not(binary)

        # Denoise
        binary = cv2.medianBlur(binary, 3)

        return binary

    def _compute_shape_score(self, user_bin: np.ndarray, ref_bin: np.ndarray) -> float:
        """Compute shape similarity using SSIM via OpenCV quality module.

        Args:
            user_bin: Preprocessed user binary image
            ref_bin: Reference binary image

        Returns:
            SSIM score in [0, 1]
        """
        # OpenCV quality.SSIM expects 8-bit single-channel
        ssim_obj = cv2.quality.QualitySSIM_create(ref_bin)
        score = ssim_obj.compute(user_bin)[0]
        # SSIM is in [-1, 1], map to [0, 1]
        return float((score + 1.0) / 2.0)

    def _compute_position_score(self, user_bin: np.ndarray, ref_bin: np.ndarray) -> float:
        """Compute position score based on centroid and bounding box offset.

        Args:
            user_bin: Preprocessed user binary image
            ref_bin: Reference binary image

        Returns:
            Position score in [0, 1]
        """
        # Centroid offset
        user_m = cv2.moments(user_bin)
        ref_m = cv2.moments(ref_bin)

        if user_m["m00"] == 0 or ref_m["m00"] == 0:
            return 0.0

        user_cx = user_m["m10"] / user_m["m00"]
        user_cy = user_m["m01"] / user_m["m00"]
        ref_cx = ref_m["m10"] / ref_m["m00"]
        ref_cy = ref_m["m01"] / ref_m["m00"]

        centroid_dist = np.sqrt((user_cx - ref_cx) ** 2 + (user_cy - ref_cy) ** 2)
        # Normalize by image diagonal
        diag = np.sqrt(user_bin.shape[0] ** 2 + user_bin.shape[1] ** 2)
        centroid_score = self._map_to_score(centroid_dist, diag * 0.5, 0)

        # Bounding box overlap (IoU)
        user_bbox = self._get_bbox(user_bin)
        ref_bbox = self._get_bbox(ref_bin)
        iou = self._bbox_iou(user_bbox, ref_bbox)

        return 0.5 * centroid_score + 0.5 * iou

    def _compute_structure_score(self, user_bin: np.ndarray, ref_bin: np.ndarray) -> float:
        """Compute structure score using Hu Moments and aspect ratio.

        Args:
            user_bin: Preprocessed user binary image
            ref_bin: Reference binary image

        Returns:
            Structure score in [0, 1]
        """
        # Hu Moments comparison
        user_hu = cv2.HuMoments(cv2.moments(user_bin)).flatten()
        ref_hu = cv2.HuMoments(cv2.moments(ref_bin)).flatten()

        # Log-scale for numerical stability
        user_hu_log = -np.sign(user_hu) * np.log10(np.abs(user_hu) + 1e-10)
        ref_hu_log = -np.sign(ref_hu) * np.log10(np.abs(ref_hu) + 1e-10)

        hu_dist = np.linalg.norm(user_hu_log - ref_hu_log)
        hu_score = self._map_to_score(hu_dist, 10.0, 0)

        # Aspect ratio comparison
        user_bbox = self._get_bbox(user_bin)
        ref_bbox = self._get_bbox(ref_bin)

        user_ar = (user_bbox[2] - user_bbox[0]) / max(user_bbox[3] - user_bbox[1], 1)
        ref_ar = (ref_bbox[2] - ref_bbox[0]) / max(ref_bbox[3] - ref_bbox[1], 1)

        ar_diff = abs(user_ar - ref_ar)
        ar_score = self._map_to_score(ar_diff, 1.0, 0)

        return 0.6 * hu_score + 0.4 * ar_score

    @staticmethod
    def _map_to_score(value: float, worst: float, best: float) -> float:
        """Map a distance value to [0, 1] score range.

        Args:
            value: Raw distance/metric value
            worst: Value that maps to score 0
            best: Value that maps to score 1

        Returns:
            Score in [0, 1], clamped
        """
        if worst == best:
            return 1.0
        score = 1.0 - (value - best) / (worst - best)
        return float(np.clip(score, 0.0, 1.0))

    @staticmethod
    def _get_bbox(binary: np.ndarray) -> tuple:
        """Get bounding box of non-zero pixels.

        Returns:
            (x1, y1, x2, y2) or (0, 0, 0, 0) if empty
        """
        coords = cv2.findNonZero(binary)
        if coords is None:
            return (0, 0, 0, 0)
        x, y, w, h = cv2.boundingRect(coords)
        return (x, y, x + w, y + h)

    @staticmethod
    def _bbox_iou(bbox1: tuple, bbox2: tuple) -> float:
        """Compute IoU of two bounding boxes."""
        x1 = max(bbox1[0], bbox2[0])
        y1 = max(bbox1[1], bbox2[1])
        x2 = min(bbox1[2], bbox2[2])
        y2 = min(bbox1[3], bbox2[3])

        inter_w = max(0, x2 - x1)
        inter_h = max(0, y2 - y1)
        inter_area = inter_w * inter_h

        area1 = (bbox1[2] - bbox1[0]) * (bbox1[3] - bbox1[1])
        area2 = (bbox2[2] - bbox2[0]) * (bbox2[3] - bbox2[1])
        union_area = area1 + area2 - inter_area

        if union_area == 0:
            return 0.0
        return inter_area / union_area
