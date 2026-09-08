"""Visual Fidelity Evaluation Package for PPT slides and presentations."""

from .pixel_diff import PixelDiffEngine, PixelDiffResult
from .typography_diff import TypographyDiffEngine, TypographyDiffReport, TypographyMismatch
from .style_diff import StyleDiffEngine, StyleDiffReport, StyleMismatch
from .fidelity_score import FidelityScore, FidelityEvaluator
from .regression_guard import (
    FidelityRegressionGuard,
    FidelityDelta,
    DEFAULT_DIMENSION_LIMITS,
    CRITICAL_FLOOR,
)
from .report import (
    FidelityIssue,
    FidelityReport,
    build_fidelity_report,
    build_presentation_report,
)

__all__ = [
    "PixelDiffEngine",
    "PixelDiffResult",
    "TypographyDiffEngine",
    "TypographyDiffReport",
    "TypographyMismatch",
    "StyleDiffEngine",
    "StyleDiffReport",
    "StyleMismatch",
    "FidelityScore",
    "FidelityEvaluator",
    "FidelityRegressionGuard",
    "FidelityDelta",
    "DEFAULT_DIMENSION_LIMITS",
    "CRITICAL_FLOOR",
    "FidelityIssue",
    "FidelityReport",
    "build_fidelity_report",
    "build_presentation_report",
]
