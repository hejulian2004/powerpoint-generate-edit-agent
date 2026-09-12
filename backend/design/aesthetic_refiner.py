"""Bounded aesthetic refinement loop for the LLM-native pipeline (S3 / Phase 8).

Consumes the read-only ``visual_critic`` diagnostics and asks the layout designer to
re-emit a slide ONLY when the critic flags it. A candidate is accepted only when it
is still hard-valid AND its critique score does not regress. Text/facts are never
modified by this loop (the layout designer only emits geometry/style).

Bounded by ``max_aesthetic_refinement_rounds``.
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import replace
from typing import Any, Callable, Dict, List, Optional, Sequence

from ..config import settings
from ..layout.schema import Canvas, DeckLayoutSpec, LayoutSpec
from ..paper.schema import PaperIR
from ..paper_visual.schema import PaperVisualIR
from ..presentation.schema import PresentationPlan
from ..slidespec.schema import DeckSpec
from .color_validator import validate_deck_colors
from .layout_compiler import compile_llm_layout, hard_validate_layout
from .layout_designer import DeckDesignResult, design_slide_layout
from .schema import DeckArtDirection
from .visual_critic import SlideCritique, critique_slide, format_critique_feedback

logger = logging.getLogger(__name__)


async def _safe_emit(on_event: Optional[Callable], data: Dict[str, Any]) -> None:
    if not on_event:
        return
    try:
        result = on_event(data)
        if inspect.isawaitable(result):
            await result
    except Exception as exc:  # pragma: no cover
        logger.debug("Aesthetic refiner event ignored: %s", exc)


def _plan_by_slide_id(design_result: DeckDesignResult) -> Dict[str, Any]:
    return {p.slide_id: p for p in design_result.plans}


async def refine_deck_aesthetics(
    llm_client: Any,
    design_result: DeckDesignResult,
    deck_spec: DeckSpec,
    presentation_plan: PresentationPlan,
    art_direction: DeckArtDirection,
    paper_ir: Optional[PaperIR] = None,
    paper_visual_ir: Optional[PaperVisualIR] = None,
    canvas: Optional[Canvas] = None,
    raster_data_uris: Optional[Dict[str, str]] = None,
    max_rounds: Optional[int] = None,
    include_multimodal: bool = True,
    on_event: Optional[Callable] = None,
) -> DeckDesignResult:
    """Refine slides flagged by the visual critic (bounded, per-slide, non-regressing)."""
    active_canvas = canvas or design_result.deck_layout.canvas or Canvas()
    budget = (
        settings.max_aesthetic_refinement_rounds if max_rounds is None else max_rounds
    )
    if not (llm_client and getattr(llm_client, "api_key", None)):
        budget = 0
    rasters = raster_data_uris or {}
    slide_specs = {s.index: s for s in deck_spec.slides}
    plans_by_index = {p.index: p for p in presentation_plan.slides}
    existing_plans = _plan_by_slide_id(design_result)

    color_report = validate_deck_colors(
        art_direction, design_result.deck_layout.slides
    )

    refined_layouts: List[LayoutSpec] = []
    aesthetic_rounds: Dict[int, int] = {}
    critique_scores: Dict[int, float] = {}

    total = len(design_result.deck_layout.slides)
    for position, layout in enumerate(design_result.deck_layout.slides, start=1):
        slide_spec = slide_specs.get(layout.slide_index)
        slide_id = layout.slide_id
        critique = await critique_slide(
            layout,
            llm_client=llm_client,
            include_multimodal=include_multimodal,
            raster_data_uri=rasters.get(slide_id),
            color_report=color_report,
        )
        current_layout = layout
        rounds = 0

        while (
            critique.needs_refinement
            and rounds < budget
            and slide_spec is not None
        ):
            rounds += 1
            await _safe_emit(
                on_event,
                {
                    "type": "generation_stage",
                    "phase": "aesthetic_refinement",
                    "current": position,
                    "total": total,
                    "slide_id": slide_id,
                    "round": rounds,
                },
            )
            feedback = format_critique_feedback(critique)
            candidate_plan = await design_slide_layout(
                llm_client,
                slide_spec,
                plans_by_index.get(slide_spec.index),
                art_direction,
                paper_ir=paper_ir,
                paper_visual_ir=paper_visual_ir,
                previous_plan=existing_plans.get(slide_id),
                previous_feedback=feedback,
                on_event=on_event,
            )
            if candidate_plan is None:
                break

            candidate_layout = compile_llm_layout(candidate_plan, slide_spec, active_canvas)
            if not hard_validate_layout(candidate_layout, slide_spec).is_valid:
                logger.info(
                    "Aesthetic refinement for %s produced a hard-invalid layout; rejected",
                    slide_id,
                )
                break

            candidate_critique = await critique_slide(
                candidate_layout,
                llm_client=llm_client,
                include_multimodal=include_multimodal,
                raster_data_uri=rasters.get(slide_id),
                color_report=color_report,
            )
            if candidate_critique.score < critique.score:
                logger.info(
                    "Aesthetic refinement for %s regressed score %.1f -> %.1f; rejected",
                    slide_id,
                    critique.score,
                    candidate_critique.score,
                )
                break

            current_layout = candidate_layout
            critique = candidate_critique
            existing_plans[slide_id] = candidate_plan

        aesthetic_rounds[layout.slide_index] = rounds
        critique_scores[layout.slide_index] = critique.score
        refined_layouts.append(current_layout)

    metadata = dict(design_result.deck_layout.metadata)
    metadata["aesthetic_rounds"] = aesthetic_rounds
    metadata["critique_scores"] = critique_scores
    metadata["color_valid"] = color_report.is_valid

    refined_deck = DeckLayoutSpec(
        title=design_result.deck_layout.title,
        canvas=active_canvas,
        slides=refined_layouts,
        metadata=metadata,
    )
    return replace(
        design_result,
        deck_layout=refined_deck,
        plans=list(existing_plans.values()),
    )


def summarize_critiques(critiques: Sequence[SlideCritique]) -> Dict[str, Any]:
    """Aggregate critique scores for telemetry/provenance."""
    if not critiques:
        return {"slides": 0, "min_score": None, "mean_score": None, "flagged": 0}
    scores = [c.score for c in critiques]
    return {
        "slides": len(critiques),
        "min_score": round(min(scores), 1),
        "mean_score": round(sum(scores) / len(scores), 1),
        "flagged": sum(1 for c in critiques if c.needs_refinement),
    }


__all__ = ["refine_deck_aesthetics", "summarize_critiques"]
