"""PPT Evaluation and Layout Diff Module."""

from .layout_diff import (
    BoundingBox,
    LayoutDefect,
    LayoutHealthReport,
    LayoutDiffEngine,
    compare_slides,
    calculate_contrast_ratio,
    calculate_relative_luminance
)
from .visual_critic import (
    VisualCritic,
    VisualReviewResult
)

__all__ = [
    "BoundingBox",
    "LayoutDefect",
    "LayoutHealthReport",
    "LayoutDiffEngine",
    "compare_slides",
    "calculate_contrast_ratio",
    "calculate_relative_luminance",
    "VisualCritic",
    "VisualReviewResult"
]
