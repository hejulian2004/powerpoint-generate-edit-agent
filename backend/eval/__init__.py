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
from .remediation import (
    DefectCategory,
    FixActionType,
    FixAction,
    RemediationPlan
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
    "DefectCategory",
    "FixActionType",
    "FixAction",
    "RemediationPlan",
    "VisualCritic",
    "VisualReviewResult"
]
