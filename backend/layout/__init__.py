"""Academic Presentation Layout Engine and Geometry Synthesis (PR10).

Public API exposing layout models, engine dispatchers, constraints, and validators.
"""

from .constraints import (
    check_canvas_bounds,
    check_figure_aspect_ratio,
    check_minimum_margin,
    check_no_overlap,
    check_text_overflow,
)
from .engine import generate_deck_layout, generate_layout
from .schema import (
    Canvas,
    DeckLayoutSpec,
    ElementStyle,
    ElementType,
    LayoutConstraint,
    LayoutElement,
    LayoutSpec,
    Rect,
    TextStyle,
)
from .validator import LayoutValidationError, ValidationReport, validate_layout

__all__ = [
    # Data Models
    "Canvas",
    "Rect",
    "ElementType",
    "TextStyle",
    "ElementStyle",
    "LayoutElement",
    "LayoutConstraint",
    "LayoutSpec",
    "DeckLayoutSpec",
    # Engine Operations
    "generate_layout",
    "generate_deck_layout",
    # Constraints
    "check_canvas_bounds",
    "check_no_overlap",
    "check_figure_aspect_ratio",
    "check_minimum_margin",
    "check_text_overflow",
    # Validation
    "validate_layout",
    "ValidationReport",
    "LayoutValidationError",
]
