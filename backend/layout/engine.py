"""Layout Engine and Synthesis Pipeline (PR10).

Orchestrates geometry synthesis from SlideSpec into LayoutSpec:
1. Template selection and visual hierarchy synthesis
2. Constraint evaluation (Canvas bounds, overlap avoidance, figure ratios)
3. Deterministic geometry assignment
4. Post-synthesis quality validation
"""

from __future__ import annotations

from typing import List, Optional

from ..slidespec.schema import DeckSpec, SlideSpec
from .constraints import (
    check_canvas_bounds,
    check_figure_aspect_ratio,
    check_no_overlap,
    check_text_overflow,
)
from .schema import Canvas, DeckLayoutSpec, ElementType, LayoutConstraint, LayoutSpec
from .templates import get_template_for_intent
from .validator import validate_layout


def generate_layout(
    slide_spec: SlideSpec,
    canvas: Optional[Canvas] = None,
    validate: bool = True,
    strict: bool = False,
) -> LayoutSpec:
    """Generate spatial LayoutSpec for a single SlideSpec."""
    active_canvas = canvas or Canvas()

    # 1. Dispatch layout template
    template = get_template_for_intent(slide_spec.visual_intent)
    layout_spec = template.layout(slide_spec, active_canvas)

    # 2. Evaluate and record geometric constraints
    constraints: List[LayoutConstraint] = []

    # Canvas bounds
    for el in layout_spec.elements:
        constraints.append(check_canvas_bounds(el, active_canvas, margin=0.0))

    # Pairwise non-overlap
    fg_elements = [el for el in layout_spec.elements if el.element_type != ElementType.CONTAINER]
    n = len(fg_elements)
    for i in range(n):
        for j in range(i + 1, n):
            constraints.append(check_no_overlap(fg_elements[i], fg_elements[j]))

    # Figure aspect ratio
    for el in layout_spec.elements:
        if el.element_type == ElementType.FIGURE:
            constraints.append(check_figure_aspect_ratio(el))

    # Text overflow checks
    for el in layout_spec.elements:
        if el.element_type in (ElementType.TEXT, ElementType.BADGE):
            constraints.append(check_text_overflow(el))

    layout_spec.constraints = constraints

    # 3. Validation guard
    if validate:
        validate_layout(layout_spec, strict=strict)

    return layout_spec


def generate_deck_layout(
    deck_spec: DeckSpec,
    canvas: Optional[Canvas] = None,
    validate: bool = True,
    strict: bool = False,
) -> DeckLayoutSpec:
    """Generate complete presentation DeckLayoutSpec from DeckSpec."""
    active_canvas = canvas or Canvas()
    slide_layouts: List[LayoutSpec] = []

    for slide in deck_spec.slides:
        layout = generate_layout(
            slide,
            canvas=active_canvas,
            validate=validate,
            strict=strict,
        )
        slide_layouts.append(layout)

    return DeckLayoutSpec(
        title=deck_spec.title,
        canvas=active_canvas,
        slides=slide_layouts,
        metadata={"profile": deck_spec.profile},
    )
