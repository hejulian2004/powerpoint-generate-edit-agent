"""Visual Fidelity Evaluation Package for PPT slides and presentations."""

from .pixel_diff import PixelDiffEngine, PixelDiffResult
from .typography_diff import TypographyDiffEngine, TypographyDiffReport, TypographyMismatch
from .style_diff import StyleDiffEngine, StyleDiffReport, StyleMismatch
from .fidelity_score import FidelityScore, FidelityEvaluator
from .repair_policy import RepairAcceptancePolicy

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
    "RepairAcceptancePolicy",
]
