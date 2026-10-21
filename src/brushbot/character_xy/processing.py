"""Image preparation with explicit resize/ROI mappings to original pixel centres."""
from __future__ import annotations

import hashlib
import io
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps

from brushbot.image_geometry import connected_components, otsu_threshold, thin_mask


def finite_number(value, name, *, positive=False):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f'{name} must be finite') from exc
    if isinstance(value, bool) or not np.isfinite(number) or (positive and number <= 0):
        raise ValueError(f'{name} must be finite'+(' and positive' if positive else ''))
    return number


def finite_pair(value, name):
    pair = np.asarray(value, float)
    if pair.shape != (2,) or not np.isfinite(pair).all():
        raise ValueError(f'{name} must contain two finite numbers')
    return pair


def processed_to_original(points, preprocessing):
    points = np.asarray(points, float)
    crop = preprocessing['crop_xyxy']
    size = preprocessing['processed_image_size_px']
    ratios = np.array([(crop[2]-crop[0])/size[0], (crop[3]-crop[1])/size[1]])
    return (points+.5)*ratios-.5+crop[:2]


def prepare_image(image_path, *, threshold=None, adaptive=False, adaptive_window=31,
                  adaptive_offset=10, invert=False, min_component_pixels=8,
                  max_side_px=1400, crop=None):
    if threshold is not None and (type(threshold) is not int or not 0 <= threshold <= 254):
        raise ValueError('threshold must be an integer in 0..254')
    if adaptive and threshold is not None:
        raise ValueError('choose either fixed threshold or adaptive threshold')
    if type(adaptive_window) is not int or not 3 <= adaptive_window <= 501 or adaptive_window % 2 == 0:
        raise ValueError('adaptive_window must be odd and between 3 and 501')
    offset = finite_number(adaptive_offset, 'adaptive_offset')
    if not 0 <= offset <= 254:
        raise ValueError('adaptive_offset must be in 0..254')
    if type(min_component_pixels) is not int or min_component_pixels < 1:
        raise ValueError('min_component_pixels must be a positive integer')
    if type(max_side_px) is not int or not 64 <= max_side_px <= 4096:
        raise ValueError('max_side_px must be an integer in 64..4096')
    raw = Path(image_path).read_bytes()
    with Image.open(io.BytesIO(raw)) as source:
        if source.width*source.height > 40_000_000 or min(source.size) < 3:
            raise ValueError('input must be at least 3x3 and at most 40000000 pixels')
        if getattr(source, 'n_frames', 1) != 1:
            raise ValueError('select a single still image')
        rgba = ImageOps.exif_transpose(source).convert('RGBA')
    original_size = list(rgba.size)
    image = Image.alpha_composite(Image.new('RGBA', rgba.size, 'white'), rgba).convert('RGB')
    if crop is None:
        crop = [0, 0, *original_size]
    if (not isinstance(crop, (list, tuple)) or len(crop) != 4 or any(type(v) is not int for v in crop)
            or not 0 <= crop[0] < crop[2] <= original_size[0]
            or not 0 <= crop[1] < crop[3] <= original_size[1]
            or min(crop[2]-crop[0], crop[3]-crop[1]) < 3):
        raise ValueError('crop must be a valid integer left,top,right,bottom rectangle after EXIF correction')
    image = image.crop(tuple(crop))
    ratio = min(1., max_side_px/max(image.size), np.sqrt(2_000_000/(image.width*image.height)))
    size = (int(image.width*ratio), int(image.height*ratio))
    if min(size) < 3:
        raise ValueError('cropped image becomes too narrow when resized; use a single-character crop')
    if size != image.size:
        image = image.resize(size, Image.Resampling.LANCZOS)
    gray = np.asarray(image.convert('L'))
    if gray.min() == gray.max():
        raise ValueError('constant image has no foreground/background contrast')
    work = 255-gray if invert else gray
    if adaptive:
        local = np.asarray(Image.fromarray(work).filter(ImageFilter.GaussianBlur(adaptive_window/6)), float)
        mask = work.astype(float) < local-offset
        used_threshold, mode = None, 'adaptive_gaussian'
    else:
        used_threshold = otsu_threshold(work) if threshold is None else threshold
        mask = work <= used_threshold
        mode = 'otsu' if threshold is None else 'manual'
    components = connected_components(mask)
    removed = [p for p in components if len(p) < min_component_pixels]
    kept = sorted((p for p in components if len(p) >= min_component_pixels),
                  key=lambda p: (int(p[:, 0].min()), int(p[:, 1].min())))
    if not kept:
        raise ValueError('no foreground remains after thresholding and small-component removal')
    mask = np.zeros_like(mask)
    labels = np.full(mask.shape, -1, dtype=np.int32)
    component_info = []
    for i, pixels in enumerate(kept):
        mask[tuple(pixels.T)] = True
        labels[tuple(pixels.T)] = i
        component_info.append(dict(index=i, pixels=len(pixels), bbox_px=[int(pixels[:, 1].min()),
            int(pixels[:, 0].min()), int(pixels[:, 1].max()), int(pixels[:, 0].max())]))
    skeleton = thin_mask(mask)
    point_fallbacks = []
    for i, pixels in enumerate(kept):
        if not skeleton[tuple(pixels.T)].any():
            centre = pixels.mean(axis=0)
            pixel = pixels[int(np.argmin(np.sum((pixels-centre)**2, axis=1)))]
            skeleton[tuple(pixel)] = True
            point_fallbacks.append(i)
    metadata = dict(exif_image_size_px=original_size, crop_xyxy=list(crop),
                    processed_image_size_px=list(image.size), max_side_px=max_side_px,
                    threshold_mode=mode, threshold=used_threshold, invert=bool(invert),
                    adaptive_window=adaptive_window if adaptive else None,
                    adaptive_offset=offset if adaptive else None,
                    min_component_pixels=min_component_pixels,
                    removed_component_count=len(removed), removed_component_pixels=sum(len(p) for p in removed),
                    point_fallback_components=point_fallbacks,
                    foreground_fraction=float(mask.mean()), ink_components=component_info)
    return dict(image=image, mask=mask, skeleton=skeleton, labels=labels,
                source_bytes=raw, source_sha256=hashlib.sha256(raw).hexdigest(), preprocessing=metadata)
