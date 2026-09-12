"""Layout Engine and Synthesis Pipeline (PR10).

Orchestrates geometry synthesis from SlideSpec into LayoutSpec:
1. Template selection and visual hierarchy synthesis
2. Constraint evaluation (Canvas bounds, overlap avoidance, figure ratios)
3. Deterministic geometry assignment
4. Post-synthesis quality validation
"""

from __future__ import annotations

from typing import List, Optional

from ..slidespec.schema import DeckSpec, FigureBlock, SlideSpec, TableBlock
from .constraints import (
    check_canvas_bounds,
    check_figure_aspect_ratio,
    check_no_overlap,
    check_text_overflow,
)
from .schema import Canvas, DeckLayoutSpec, ElementType, LayoutConstraint, LayoutSpec
from .templates import (
    BenchmarkComparisonTemplate,
    PipelineArchitectureTemplate,
    get_template_for_intent,
)
from .templates.base import BaseLayoutTemplate
from .validator import validate_layout


_VISUAL_TEMPLATES = (PipelineArchitectureTemplate, BenchmarkComparisonTemplate)


def _select_template(slide_spec: SlideSpec, template: BaseLayoutTemplate) -> BaseLayoutTemplate:
    """Never route a slide carrying visual source assets to a text-only template.

    The Title / Takeaway / TwoColumn templates do not render FigureBlock/TableBlock,
    so dispatching a visual slide to them would silently drop its assets. Promote such
    a slide to a visual-capable template so every figure/table is emitted (as a
    resolved asset or an explicit placeholder).
    """
    if isinstance(template, _VISUAL_TEMPLATES):
        return template
    if any(isinstance(b, FigureBlock) for b in slide_spec.blocks):
        return PipelineArchitectureTemplate()
    if any(isinstance(b, TableBlock) for b in slide_spec.blocks):
        return BenchmarkComparisonTemplate()
    return template


def generate_layout(
    slide_spec: SlideSpec,
    canvas: Optional[Canvas] = None,
    validate: bool = True,
    strict: bool = False,
) -> LayoutSpec:
    """Generate spatial LayoutSpec for a single SlideSpec."""
    active_canvas = canvas or Canvas()

    # 1. Dispatch layout template
    template = _select_template(slide_spec, get_template_for_intent(slide_spec.visual_intent))
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
        report = validate_layout(layout_spec, strict=strict)
        layout_spec.metadata["validation"] = {
            "is_valid": report.is_valid,
            "errors": report.errors,
            "warnings": report.warnings,
        }

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


def compile_llm_layout(
    plan: "object",
    slide_spec: SlideSpec,
    canvas: Optional[Canvas] = None,
) -> LayoutSpec:
    """Compile a free-form LLM layout plan into a LayoutSpec.

    Thin, lazily-imported entry point so callers can depend on ``backend.layout``
    without importing ``backend.design`` at module load time (avoids a cycle).
    """
    from ..design.layout_compiler import compile_llm_layout as _impl

    return _impl(plan, slide_spec, canvas)


def compile_llm_deck_layout(
    plans: "object",
    deck_spec: DeckSpec,
    canvas: Optional[Canvas] = None,
    on_fallback=None,
) -> DeckLayoutSpec:
    """Compile a deck of LLM layout plans; per-slide template fallback if missing."""
    from ..design.layout_compiler import compile_llm_deck_layout as _impl

    return _impl(plans, deck_spec, canvas, on_fallback)
