"""Per-slide layout designer with a hard-validated repair loop.

The LLM emits absolute, free-form geometry (no template catalog). Deterministic
code compiles the plan and hard-validates it (bounds / collision / readable type /
aspect ratio / source refs). On failure the precise diagnostics are fed back and
the model retries, up to a bounded number of rounds. Only when repair fails does
that single slide fall back to the legacy template layout.
"""

from __future__ import annotations

import base64
import inspect
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..config import settings
from ..layout.schema import Canvas, DeckLayoutSpec, LayoutSpec
from ..slidespec.schema import DeckSpec, SlideSpec
from ..paper.schema import PaperIR
from ..paper_visual.schema import PaperVisualIR
from ..presentation.schema import PresentationPlan, SlidePlan
from .json_utils import extract_json
from .layout_compiler import compile_llm_layout, hard_validate_layout
from .layout_context import build_slide_layout_context
from .layout_schema import LayoutElementPlan, LLMLayoutPlan
from .prompts import LAYOUT_DESIGNER_SYSTEM_PROMPT
from .schema import DeckArtDirection
from .validator_feedback import format_layout_validation_feedback

logger = logging.getLogger(__name__)


@dataclass
class DeckDesignResult:
    """Outcome of designing a whole deck's per-slide layouts."""

    deck_layout: DeckLayoutSpec
    plans: List[LLMLayoutPlan] = field(default_factory=list)
    validation_rounds: Dict[int, int] = field(default_factory=dict)
    fallback_slide_indices: List[int] = field(default_factory=list)
    hard_validation: Dict[int, bool] = field(default_factory=dict)

    @property
    def all_valid(self) -> bool:
        return not self.fallback_slide_indices


async def _safe_emit(on_event: Optional[Callable], data: Dict[str, Any]) -> None:
    if not on_event:
        return
    try:
        result = on_event(data)
        if inspect.isawaitable(result):
            await result
    except Exception as exc:  # pragma: no cover
        logger.debug("Layout designer event ignored: %s", exc)


def _coerce_plan(payload: Any, slide: SlideSpec) -> LLMLayoutPlan:
    if isinstance(payload, dict) and isinstance(payload.get("layout"), dict):
        payload = payload["layout"]
    if not isinstance(payload, dict):
        raise ValueError("layout plan must be a JSON object")
    data = dict(payload)
    data.setdefault("slide_id", f"slide_{slide.index}")
    elements_raw = data.get("elements")
    if not isinstance(elements_raw, list) or not elements_raw:
        raise ValueError("layout plan must contain a non-empty elements list")

    seen: Dict[str, int] = {}
    cleaned: List[Dict[str, Any]] = []
    for idx, raw in enumerate(elements_raw, start=1):
        if not isinstance(raw, dict):
            continue
        element = dict(raw)
        element_id = str(element.get("element_id") or f"el_{idx}")
        seen[element_id] = seen.get(element_id, 0) + 1
        if seen[element_id] > 1:
            element_id = f"{element_id}_{seen[element_id]}"
        element["element_id"] = element_id
        # Pydantic will validate; surface a clear error if geometry is missing.
        cleaned.append(element)
    if not cleaned:
        raise ValueError("no valid layout elements found")
    data["elements"] = cleaned
    return LLMLayoutPlan.model_validate(data)


def _summarize_plan(plan: Optional[LLMLayoutPlan]) -> Optional[str]:
    if plan is None:
        return None
    lines = [f"focal={plan.visual_focal_point or 'n/a'}"]
    for el in plan.elements:
        lines.append(
            f"{el.element_id}:{el.element_type} "
            f"({el.x:.0f},{el.y:.0f},{el.width:.0f}x{el.height:.0f})"
        )
    return "\n".join(lines)


async def design_slide_layout(
    llm_client: Any,
    slide_spec: SlideSpec,
    slide_plan: Optional[SlidePlan],
    art_direction: DeckArtDirection,
    paper_ir: Optional[PaperIR] = None,
    paper_visual_ir: Optional[PaperVisualIR] = None,
    previous_plan: Optional[LLMLayoutPlan] = None,
    previous_feedback: Optional[str] = None,
    on_event: Optional[Callable] = None,
) -> Optional[LLMLayoutPlan]:
    """Ask the LLM to design a single slide's free-form layout."""
    if not llm_client or not getattr(llm_client, "api_key", None):
        return None

    await _safe_emit(
        on_event,
        {
            "type": "generation_stage",
            "phase": "slide_layout",
            "current": slide_spec.index,
            "total": slide_spec.index,
            "slide_id": f"slide_{slide_spec.index}",
        },
    )

    context = build_slide_layout_context(
        slide_spec,
        slide_plan,
        art_direction,
        paper_ir=paper_ir,
        paper_visual_ir=paper_visual_ir,
        previous_layout=_summarize_plan(previous_plan),
        previous_feedback=previous_feedback,
    )

    content: List[Dict[str, Any]] = [{"type": "text", "text": context.text}]
    for path in context.image_paths:
        try:
            encoded = base64.b64encode(Path(path).read_bytes()).decode("ascii")
        except OSError:
            continue
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{encoded}", "detail": "high"},
            }
        )

    role = "vision" if context.use_vision else "reasoning"
    messages = [
        {"role": "system", "content": LAYOUT_DESIGNER_SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]

    try:
        response = await llm_client.chat_completion(messages, role=role, max_tokens=4000)
        raw = response["choices"][0]["message"].get("content", "")
        payload = extract_json(raw)
        return _coerce_plan(payload, slide_spec)
    except Exception as exc:
        logger.warning("Layout design failed for slide %s: %s", slide_spec.index, exc)
        return None


def _legacy_layout(slide_spec: SlideSpec, canvas: Canvas) -> LayoutSpec:
    from ..layout.engine import generate_layout

    layout = generate_layout(slide_spec, canvas=canvas, validate=True)
    layout.metadata["layout_source"] = "fallback_template"
    return layout


async def design_deck_layouts(
    llm_client: Any,
    deck_spec: DeckSpec,
    presentation_plan: PresentationPlan,
    art_direction: DeckArtDirection,
    paper_ir: Optional[PaperIR] = None,
    paper_visual_ir: Optional[PaperVisualIR] = None,
    canvas: Optional[Canvas] = None,
    on_event: Optional[Callable] = None,
    max_repair_rounds: Optional[int] = None,
) -> DeckDesignResult:
    """Design every slide with a bounded repair loop and per-slide fallback."""
    active_canvas = canvas or Canvas()
    repair_budget = (
        settings.max_layout_repair_rounds if max_repair_rounds is None else max_repair_rounds
    )
    plans_by_index = {p.index: p for p in presentation_plan.slides}

    slide_layouts: List[LayoutSpec] = []
    accepted_plans: List[LLMLayoutPlan] = []
    validation_rounds: Dict[int, int] = {}
    fallback_indices: List[int] = []
    hard_validation: Dict[int, bool] = {}

    for slide in deck_spec.slides:
        slide_plan = plans_by_index.get(slide.index)
        plan = await design_slide_layout(
            llm_client,
            slide,
            slide_plan,
            art_direction,
            paper_ir=paper_ir,
            paper_visual_ir=paper_visual_ir,
            on_event=on_event,
        )
        if plan is None:
            slide_layouts.append(_legacy_layout(slide, active_canvas))
            fallback_indices.append(slide.index)
            validation_rounds[slide.index] = 0
            hard_validation[slide.index] = False
            continue

        compiled = compile_llm_layout(plan, slide, active_canvas)
        report = hard_validate_layout(compiled, slide)
        rounds = 0
        while not report.is_valid and rounds < repair_budget:
            rounds += 1
            feedback = format_layout_validation_feedback(report, compiled)
            repaired = await design_slide_layout(
                llm_client,
                slide,
                slide_plan,
                art_direction,
                paper_ir=paper_ir,
                paper_visual_ir=paper_visual_ir,
                previous_plan=plan,
                previous_feedback=feedback,
                on_event=on_event,
            )
            if repaired is None:
                break
            plan = repaired
            compiled = compile_llm_layout(plan, slide, active_canvas)
            report = hard_validate_layout(compiled, slide)

        compiled.metadata["validation_rounds"] = rounds
        validation_rounds[slide.index] = rounds
        hard_validation[slide.index] = report.is_valid

        if report.is_valid:
            slide_layouts.append(compiled)
            accepted_plans.append(plan)
        else:
            logger.info(
                "Slide %s layout still invalid after %d repair rounds; using template fallback",
                slide.index,
                rounds,
            )
            slide_layouts.append(_legacy_layout(slide, active_canvas))
            fallback_indices.append(slide.index)

    source = (
        "llm"
        if not fallback_indices
        else ("mixed" if len(fallback_indices) < len(slide_layouts) else "fallback_template")
    )
    deck_layout = DeckLayoutSpec(
        title=deck_spec.title,
        canvas=active_canvas,
        slides=slide_layouts,
        metadata={
            "layout_source": source,
            "fallback_slide_indices": fallback_indices,
            "validation_rounds": validation_rounds,
        },
    )
    return DeckDesignResult(
        deck_layout=deck_layout,
        plans=accepted_plans,
        validation_rounds=validation_rounds,
        fallback_slide_indices=fallback_indices,
        hard_validation=hard_validation,
    )


__all__ = [
    "DeckDesignResult",
    "design_slide_layout",
    "design_deck_layouts",
]
