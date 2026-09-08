"""Layout Validation and Quality Assurance (PR10).

Validates generated LayoutSpec instances against academic layout rules:
- Canvas bounding limits (no negative coordinates or overflows)
- Foreground collision detection (no overlap between content elements)
- Content sanity (no empty text, presence of valid asset IDs)
- Aspect ratio integrity for figures
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .constraints import check_canvas_bounds, check_figure_aspect_ratio, check_no_overlap
from .schema import ElementType, LayoutConstraint, LayoutElement, LayoutSpec


class LayoutValidationError(ValueError):
    """Raised when a slide layout violates critical spatial or content constraints."""

    def __init__(self, message: str, errors: Optional[List[str]] = None):
        super().__init__(message)
        self.errors = errors or [message]


@dataclass
class ValidationReport:
    """Detailed summary of layout validation results."""

    is_valid: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    evaluated_constraints: List[LayoutConstraint] = field(default_factory=list)

    def add_error(self, message: str) -> None:
        self.is_valid = False
        self.errors.append(message)

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)


def validate_layout(
    layout: LayoutSpec,
    strict: bool = False,
    allow_empty_slides: bool = False,
) -> ValidationReport:
    """Validate a single LayoutSpec against geometric, structural, and content rules."""
    report = ValidationReport()

    # 1. Slide element count check
    if not layout.elements and not allow_empty_slides:
        report.add_error(f"Slide '{layout.slide_id}' has no layout elements")

    # 2. Geometric bounds check
    for el in layout.elements:
        # Check coordinates validity
        if el.geometry.width <= 0 or el.geometry.height <= 0:
            report.add_error(
                f"Element '{el.element_id}' has non-positive dimension: "
                f"{el.geometry.width}x{el.geometry.height}"
            )
        if el.geometry.x < 0 or el.geometry.y < 0:
            report.add_error(
                f"Element '{el.element_id}' has negative coordinates: x={el.geometry.x}, y={el.geometry.y}"
            )

        c_bounds = check_canvas_bounds(el, layout.canvas, margin=0.0)
        report.evaluated_constraints.append(c_bounds)
        if not c_bounds.satisfied and c_bounds.message:
            report.add_error(c_bounds.message)

    # 3. Collision / Overlap check among foreground elements
    fg_elements = [el for el in layout.elements if el.element_type != ElementType.CONTAINER]
    n = len(fg_elements)
    for i in range(n):
        for j in range(i + 1, n):
            c_overlap = check_no_overlap(fg_elements[i], fg_elements[j])
            report.evaluated_constraints.append(c_overlap)
            if not c_overlap.satisfied and c_overlap.message:
                report.add_error(c_overlap.message)

    # 4. Content sanity check
    for el in layout.elements:
        if el.element_type in (ElementType.TEXT, ElementType.BADGE):
            text_str = str(el.content or "")
            if not text_str.strip():
                report.add_error(f"Text/Badge element '{el.element_id}' has empty content")
        elif el.element_type == ElementType.FIGURE:
            fig_id = None
            if isinstance(el.content, dict):
                fig_id = el.content.get("source_figure_id")
            elif isinstance(el.content, str):
                fig_id = el.content
            if not fig_id:
                report.add_error(f"Figure element '{el.element_id}' missing source_figure_id")

            # Check aspect ratio
            c_ratio = check_figure_aspect_ratio(el)
            report.evaluated_constraints.append(c_ratio)
            if not c_ratio.satisfied and c_ratio.message:
                report.add_warning(c_ratio.message)

        elif el.element_type == ElementType.TABLE:
            tbl_id = None
            if isinstance(el.content, dict):
                tbl_id = el.content.get("source_table_id")
            elif isinstance(el.content, str):
                tbl_id = el.content
            if not tbl_id:
                report.add_error(f"Table element '{el.element_id}' missing source_table_id")

    if strict and not report.is_valid:
        raise LayoutValidationError(
            f"Layout validation failed for slide '{layout.slide_id}': {'; '.join(report.errors)}",
            errors=report.errors,
        )

    return report
