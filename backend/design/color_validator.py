"""Semantic color direction + WCAG contrast validation (S3 / Phase 7).

Read-only validation of the LLM's ``DeckArtDirection.color_direction`` and of each
compiled slide's text/background contrast. Reuses the canonical WCAG implementation
in ``backend.eval.layout_diff`` (no duplicate color math).

Boundary: this module only *reports* problems; it never mutates a layout.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from ..layout.schema import Canvas, ElementType, LayoutSpec
from .schema import DeckArtDirection

_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_COLOR_TOKENS = {"none", "transparent"}

# WCAG 2.1 thresholds.
CONTRAST_BODY_MIN = 4.5
CONTRAST_LARGE_MIN = 3.0
LARGE_TEXT_PT = 24.0
LARGE_BOLD_TEXT_PT = 18.66


@dataclass
class ColorIssue:
    slide_id: Optional[str]
    element_id: Optional[str]
    kind: str  # "invalid_color" | "low_contrast" | "semantic_drift"
    severity: str  # "error" | "warning"
    description: str
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slide_id": self.slide_id,
            "element_id": self.element_id,
            "kind": self.kind,
            "severity": self.severity,
            "description": self.description,
            "evidence": self.evidence,
        }


@dataclass
class ColorValidationReport:
    issues: List[ColorIssue] = field(default_factory=list)
    checked_elements: int = 0
    min_contrast: Optional[float] = None

    @property
    def is_valid(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    @property
    def errors(self) -> List[ColorIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> List[ColorIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "checked_elements": self.checked_elements,
            "min_contrast": self.min_contrast,
            "issues": [i.to_dict() for i in self.issues],
        }


def _is_valid_color(value: Optional[str]) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    return bool(_HEX_RE.match(text)) or text.lower() in _COLOR_TOKENS


def _direction_colors(art_direction: DeckArtDirection) -> Dict[str, Optional[str]]:
    cd = art_direction.color_direction
    colors: Dict[str, Optional[str]] = {
        "primary_text": cd.primary_text,
        "secondary_text": cd.secondary_text,
        "primary_accent": cd.primary_accent,
        "secondary_accent": cd.secondary_accent,
        "semantic_positive": cd.semantic_positive,
        "semantic_negative": cd.semantic_negative,
        "semantic_warning": cd.semantic_warning,
    }
    for binding in cd.bindings:
        colors[f"binding:{binding.semantic_key}"] = binding.color
    return colors


def validate_color_direction(art_direction: DeckArtDirection) -> List[ColorIssue]:
    """Validate hex well-formedness and semantic-binding uniqueness."""
    issues: List[ColorIssue] = []
    for name, color in _direction_colors(art_direction).items():
        if not _is_valid_color(color):
            issues.append(
                ColorIssue(
                    slide_id=None,
                    element_id=None,
                    kind="invalid_color",
                    severity="error",
                    description=f"Color '{name}' is not a valid hex value: {color!r}",
                    evidence={"role": name, "value": color},
                )
            )

    seen: Dict[str, str] = {}
    for binding in art_direction.color_direction.bindings:
        key = binding.semantic_key.strip().lower()
        if key in seen:
            issues.append(
                ColorIssue(
                    slide_id=None,
                    element_id=None,
                    kind="semantic_drift",
                    severity="warning",
                    description=(
                        f"Semantic key '{binding.semantic_key}' is bound more than once"
                    ),
                    evidence={"semantic_key": binding.semantic_key},
                )
            )
        else:
            seen[key] = binding.color
    return issues


def _effective_background(layout: LayoutSpec, canvas: Canvas) -> Optional[str]:
    """A full-bleed container fill if present, else None (caller uses default)."""
    canvas_area = max(1.0, canvas.width * canvas.height)
    best_color: Optional[str] = None
    best_area = 0.0
    for el in layout.elements:
        if el.element_type != ElementType.CONTAINER:
            continue
        color = el.style.background_color
        if not _is_valid_color(color) or color in (None, "none", "transparent"):
            continue
        area = el.geometry.width * el.geometry.height
        if area / canvas_area >= 0.5 and area > best_area:
            best_area = area
            best_color = color
    return best_color


def _contrast_threshold(font_size: Optional[float], font_weight: Optional[str]) -> float:
    size = float(font_size or 18.0)
    bold = str(font_weight or "normal").lower() == "bold"
    if size >= LARGE_TEXT_PT:
        return CONTRAST_LARGE_MIN
    if size >= LARGE_BOLD_TEXT_PT and bold:
        return CONTRAST_LARGE_MIN
    return CONTRAST_BODY_MIN


def validate_deck_colors(
    art_direction: DeckArtDirection,
    layouts: Sequence[LayoutSpec],
    default_background: str = "#FFFFFF",
) -> ColorValidationReport:
    """Validate color direction + per-slide text contrast on compiled layouts."""
    from ..eval.layout_diff import calculate_contrast_ratio

    report = ColorValidationReport(issues=validate_color_direction(art_direction))
    primary_text = art_direction.color_direction.primary_text

    for layout in layouts:
        canvas = layout.canvas or Canvas()
        slide_bg = _effective_background(layout, canvas) or default_background

        for el in layout.elements:
            if el.element_type not in (ElementType.TEXT, ElementType.BADGE):
                continue
            style = el.style
            if style is None:
                continue
            text_color = None
            font_size = None
            font_weight = None
            if style.text is not None:
                text_color = style.text.color
                font_size = style.text.font_size
                font_weight = style.text.font_weight
            text_color = text_color or primary_text
            background = style.background_color or slide_bg
            if background in ("none", "transparent"):
                background = slide_bg
            if not _is_valid_color(text_color) or not _is_valid_color(background):
                report.issues.append(
                    ColorIssue(
                        slide_id=layout.slide_id,
                        element_id=el.element_id,
                        kind="invalid_color",
                        severity="error",
                        description=(
                            f"Element '{el.element_id}' has a non-hex text/background color"
                        ),
                        evidence={"text_color": text_color, "background": background},
                    )
                )
                continue

            ratio = float(calculate_contrast_ratio(text_color, background))
            report.checked_elements += 1
            if report.min_contrast is None or ratio < report.min_contrast:
                report.min_contrast = ratio

            threshold = _contrast_threshold(font_size, font_weight)
            if ratio < threshold:
                severity = "error" if ratio < CONTRAST_LARGE_MIN else "warning"
                report.issues.append(
                    ColorIssue(
                        slide_id=layout.slide_id,
                        element_id=el.element_id,
                        kind="low_contrast",
                        severity=severity,
                        description=(
                            f"Element '{el.element_id}' contrast {ratio:.2f}:1 is below "
                            f"the {threshold:.1f}:1 WCAG threshold"
                        ),
                        evidence={
                            "contrast_ratio": ratio,
                            "threshold": threshold,
                            "text_color": text_color,
                            "background": background,
                        },
                    )
                )
    return report


__all__ = [
    "ColorIssue",
    "ColorValidationReport",
    "CONTRAST_BODY_MIN",
    "CONTRAST_LARGE_MIN",
    "validate_color_direction",
    "validate_deck_colors",
]
