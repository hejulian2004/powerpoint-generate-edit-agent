"""Compile free-form LLM layout plans into deterministic LayoutSpec.

The LLM chooses geometry; this module only translates and hard-validates it. It
never rewrites the design. Legacy template layout is used solely as a per-slide
fallback when a plan is missing or the LLM path is disabled.
"""

from __future__ import annotations

import logging
from typing import Callable, Dict, List, Optional, Sequence

from ..config import settings
from ..layout.constraints import (
    check_canvas_bounds,
    check_figure_aspect_ratio,
    check_no_overlap,
    check_text_overflow,
)
from ..layout.schema import (
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
from ..layout.validator import ValidationReport, validate_layout
from ..slidespec.schema import SlideSpec
from .layout_schema import LayoutElementPlan, LLMLayoutPlan

logger = logging.getLogger(__name__)

LAYOUT_PLAN_VERSION = "1.0.0"
MIN_READABLE_FONT_SIZE = 10.0
MIN_BODY_FONT_SIZE = 12.0
MAX_CARD_RADIUS = 3.0

_ALIGNMENTS = {"left", "center", "right", "justify"}
_VERTICAL_ALIGNMENTS = {"top", "middle", "bottom"}
_DEFAULT_BLOCK_IDS = {"header_title", "header_subtitle", "title", "subtitle"}


def _coerce_element_type(value: object) -> ElementType:
    text = str(value or "TEXT").strip().upper()
    try:
        return ElementType(text)
    except ValueError:
        return ElementType.TEXT


def _coerce_alignment(value: object) -> str:
    text = str(value or "left").strip().lower()
    return text if text in _ALIGNMENTS else "left"


def _coerce_vertical(value: object) -> str:
    text = str(value or "top").strip().lower()
    return text if text in _VERTICAL_ALIGNMENTS else "top"


def _coerce_weight(value: object) -> str:
    return "bold" if str(value or "normal").strip().lower() == "bold" else "normal"


def _build_style(plan: LayoutElementPlan) -> ElementStyle:
    needs_text_style = any(
        v is not None
        for v in (plan.font_size, plan.font_family, plan.text_color, plan.alignment, plan.font_weight)
    )
    text_style = None
    if needs_text_style:
        text_style = TextStyle(
            font_size=max(6.0, float(plan.font_size or 18.0)),
            font_weight=_coerce_weight(plan.font_weight),
            font_family=plan.font_family or "Segoe UI",
            alignment=_coerce_alignment(plan.alignment),
            vertical_alignment=_coerce_vertical(plan.vertical_alignment),
            line_height=float(plan.line_height) if plan.line_height else 1.2,
            color=plan.text_color,
            italic=bool(plan.italic),
        )
    return ElementStyle(
        text=text_style,
        background_color=plan.fill_color,
        border_color=plan.border_color,
        border_width=max(0.0, float(plan.border_width or 0.0)),
        # Deterministic enforcement of the repo design standard: card radii stay subtle.
        corner_radius=max(0.0, min(MAX_CARD_RADIUS, float(plan.corner_radius or 0.0))),
        padding=max(0.0, float(plan.padding or 0.0)),
        opacity=max(0.0, min(1.0, float(plan.opacity))),
    )


def compile_llm_layout(
    plan: LLMLayoutPlan,
    slide_spec: SlideSpec,
    canvas: Optional[Canvas] = None,
) -> LayoutSpec:
    """Compile an ``LLMLayoutPlan`` into a ``LayoutSpec`` (no design rewriting)."""
    active_canvas = canvas or Canvas()
    elements: List[LayoutElement] = []
    for element_plan in plan.elements:
        elements.append(
            LayoutElement(
                element_id=element_plan.element_id,
                source_block_id=element_plan.source_block_id,
                source_evidence_ids=list(element_plan.source_evidence_ids),
                element_type=_coerce_element_type(element_plan.element_type),
                geometry=Rect(
                    x=float(element_plan.x),
                    y=float(element_plan.y),
                    width=max(0.0, float(element_plan.width)),
                    height=max(0.0, float(element_plan.height)),
                ),
                style=_build_style(element_plan),
                content=element_plan.content,
                z_index=int(element_plan.z_index),
            )
        )

    layout = LayoutSpec(
        slide_id=plan.slide_id or f"slide_{slide_spec.index}",
        slide_index=slide_spec.index,
        visual_intent=slide_spec.visual_intent,
        canvas=active_canvas,
        elements=elements,
        metadata={
            "layout_source": "llm",
            "layout_plan_version": LAYOUT_PLAN_VERSION,
            "validation_rounds": 0,
        },
    )

    constraints: List[LayoutConstraint] = []
    for el in layout.elements:
        constraints.append(check_canvas_bounds(el, active_canvas, margin=0.0))
    foreground = [el for el in layout.elements if el.element_type != ElementType.CONTAINER]
    for i in range(len(foreground)):
        for j in range(i + 1, len(foreground)):
            constraints.append(check_no_overlap(foreground[i], foreground[j]))
    for el in layout.elements:
        if el.element_type == ElementType.FIGURE:
            constraints.append(check_figure_aspect_ratio(el))
        if el.element_type in (ElementType.TEXT, ElementType.BADGE):
            constraints.append(check_text_overflow(el))
    layout.constraints = constraints
    return layout


def hard_validate_layout(
    layout: LayoutSpec,
    slide_spec: Optional[SlideSpec] = None,
) -> ValidationReport:
    """Hard-validate a compiled layout; returns precise, repairable diagnostics."""
    report = validate_layout(layout)

    valid_block_ids = set()
    if slide_spec is not None:
        valid_block_ids = {b.block_id for b in slide_spec.blocks if b.block_id}

    for el in layout.elements:
        if el.element_type in (ElementType.TEXT, ElementType.BADGE):
            font_size = el.style.text.font_size if el.style.text else None
            if font_size is not None and font_size < MIN_READABLE_FONT_SIZE:
                report.add_error(
                    f"Element '{el.element_id}' font size {font_size:.1f} is below the "
                    f"minimum readable size {MIN_READABLE_FONT_SIZE:.0f}"
                )
            elif font_size is not None and font_size < MIN_BODY_FONT_SIZE:
                report.add_warning(
                    f"Element '{el.element_id}' font size {font_size:.1f} is small for body text"
                )

        if (
            slide_spec is not None
            and el.source_block_id
            and valid_block_ids
            and el.source_block_id not in valid_block_ids
            and el.source_block_id not in _DEFAULT_BLOCK_IDS
        ):
            report.add_error(
                f"Element '{el.element_id}' references unknown source block "
                f"'{el.source_block_id}'"
            )

        if el.element_type == ElementType.FIGURE:
            ratio = el.geometry.aspect_ratio
            if ratio and (ratio < 0.1 or ratio > 10.0):
                report.add_error(
                    f"Figure '{el.element_id}' aspect ratio {ratio:.2f} is corrupted"
                )

    return report


def compile_llm_deck_layout(
    plans: Sequence[LLMLayoutPlan],
    deck_spec,
    canvas: Optional[Canvas] = None,
    on_fallback: Optional[Callable[[int, str], None]] = None,
) -> DeckLayoutSpec:
    """Compile a whole deck; per-slide legacy fallback when a plan is missing."""
    active_canvas = canvas or Canvas()
    plans_by_index: Dict[int, LLMLayoutPlan] = {}
    for plan in plans:
        index = _slide_index_from_id(plan.slide_id)
        if index is not None:
            plans_by_index[index] = plan

    slide_layouts: List[LayoutSpec] = []
    fallback_indices: List[int] = []

    for slide in deck_spec.slides:
        plan = plans_by_index.get(slide.index)
        if plan is not None and settings.llm_native_layout_enabled:
            slide_layouts.append(compile_llm_layout(plan, slide, active_canvas))
        else:
            from ..layout.engine import generate_layout

            layout = generate_layout(slide, canvas=active_canvas, validate=True)
            layout.metadata["layout_source"] = "fallback_template"
            fallback_indices.append(slide.index)
            if on_fallback is not None:
                on_fallback(slide.index, "missing_llm_layout_plan")
            slide_layouts.append(layout)

    source = "llm" if not fallback_indices else ("mixed" if len(fallback_indices) < len(slide_layouts) else "fallback_template")
    return DeckLayoutSpec(
        title=deck_spec.title,
        canvas=active_canvas,
        slides=slide_layouts,
        metadata={
            "layout_source": source,
            "layout_plan_version": LAYOUT_PLAN_VERSION,
            "fallback_slide_indices": fallback_indices,
        },
    )


def _slide_index_from_id(slide_id: str) -> Optional[int]:
    if not slide_id:
        return None
    digits = "".join(ch for ch in slide_id if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


__all__ = [
    "LAYOUT_PLAN_VERSION",
    "compile_llm_layout",
    "compile_llm_deck_layout",
    "hard_validate_layout",
]
