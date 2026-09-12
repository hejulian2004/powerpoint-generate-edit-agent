"""Geometry helpers for the paper visual subsystem.

All normalized region boxes use the convention ``[x0, y0, x1, y1]`` in ``[0, 1]``,
page-relative, top-left origin, matching the pypdfium2 raster orientation.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Tuple

BBox = List[float]


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def normalize_bbox(
    bbox_points: Sequence[float],
    page_width_pt: float,
    page_height_pt: float,
) -> BBox:
    """Convert an absolute PDF-point bbox to a normalized ``[0, 1]`` bbox.

    ``bbox_points`` follows the ``PaperIR.BBox`` convention: ``[x0, top, x1, bottom]``
    in PDF points with a top-left origin. ``page_width_pt`` / ``page_height_pt``
    must come from the *rotation-aware* canonical page size (pypdfium2
    ``get_size()``) so the normalization matches the rendered raster.
    """
    if page_width_pt <= 0 or page_height_pt <= 0:
        return [0.0, 0.0, 0.0, 0.0]
    x0, top, x1, bottom = (float(v) for v in bbox_points)
    return [
        clamp01(x0 / page_width_pt),
        clamp01(top / page_height_pt),
        clamp01(x1 / page_width_pt),
        clamp01(bottom / page_height_pt),
    ]


def bbox_area(bbox: Sequence[float]) -> float:
    x0, y0, x1, y1 = bbox
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def bbox_iou(a: Sequence[float], b: Sequence[float]) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    if inter <= 0.0:
        return 0.0
    union = bbox_area(a) + bbox_area(b) - inter
    return inter / union if union > 0 else 0.0


def bbox_center(bbox: Sequence[float]) -> Tuple[float, float]:
    x0, y0, x1, y1 = bbox
    return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)


def normalized_to_pixels(
    bbox: Sequence[float],
    image_width: int,
    image_height: int,
) -> Tuple[int, int, int, int]:
    """Convert a normalized bbox to integer pixel bounds (left, top, right, bottom)."""
    x0, y0, x1, y1 = bbox
    left = int(round(x0 * image_width))
    top = int(round(y0 * image_height))
    right = int(round(x1 * image_width))
    bottom = int(round(y1 * image_height))
    left = max(0, min(image_width, left))
    right = max(0, min(image_width, right))
    top = max(0, min(image_height, top))
    bottom = max(0, min(image_height, bottom))
    if right <= left:
        right = min(image_width, left + 1)
    if bottom <= top:
        bottom = min(image_height, top + 1)
    return left, top, right, bottom


def best_match_index(
    target: Sequence[float],
    candidates: Iterable[Sequence[float]],
    threshold: float = 0.05,
) -> Optional[int]:
    """Return the index of the candidate with the highest IoU >= ``threshold``."""
    best_idx: Optional[int] = None
    best_iou = threshold
    for idx, candidate in enumerate(candidates):
        iou = bbox_iou(target, candidate)
        if iou >= best_iou:
            best_iou = iou
            best_idx = idx
    return best_idx


__all__ = [
    "BBox",
    "clamp01",
    "normalize_bbox",
    "bbox_area",
    "bbox_iou",
    "bbox_center",
    "normalized_to_pixels",
    "best_match_index",
]
