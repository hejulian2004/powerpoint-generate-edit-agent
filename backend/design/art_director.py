"""Multimodal Deck Art Director.

Produces a ``DeckArtDirection`` and a ``PresentationPlan`` from the paper text +
visual structure (+ optional contact sheet). Any image-bearing request uses
``role="vision"``; pure-text reasoning uses ``role="reasoning"``.

The LLM decides the number of slides, which content deserves its own slide, and
the entire visual language. On failure this returns ``(None, None)`` so the caller
can fall back to the legacy deterministic planner.
"""

from __future__ import annotations

import inspect
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..config import settings
from ..paper.schema import PaperIR
from ..paper_visual.schema import PaperVisualIR
from ..presentation.schema import PresentationPlan, SlidePlan, SlideType
from .context_builder import build_art_direction_text, build_contact_sheet
from .json_utils import extract_json
from .prompts import ART_DIRECTOR_SYSTEM_PROMPT
from .schema import ColorDirection, DeckArtDirection, SemanticColorBinding

logger = logging.getLogger(__name__)

_VALID_SLIDE_TYPES = {t.value for t in SlideType}


def default_color_direction() -> ColorDirection:
    """Deterministic neutral fallback direction (used when the LLM is unavailable)."""
    return ColorDirection(
        background_strategy="light neutral background",
        surface_strategy="subtle sharp-cornered surfaces",
        primary_text="#16181D",
        secondary_text="#5A6472",
        background_color="#FFFFFF",
        surface_color="#F8FAFC",
        primary_accent="#C2410C",
        secondary_accent=None,
        semantic_positive="#15803D",
        semantic_negative="#B91C1C",
        semantic_warning="#B45309",
        rationale="Neutral fallback palette",
        bindings=[
            SemanticColorBinding(semantic_key="ours", color="#C2410C"),
            SemanticColorBinding(semantic_key="baseline", color="#5A6472"),
        ],
    )


def default_art_direction() -> DeckArtDirection:
    return DeckArtDirection(
        design_concept="Legacy fallback design (LLM art direction unavailable)",
        visual_language="editorial technical",
        typography_strategy="clear hierarchy, restrained accents",
        color_direction=default_color_direction(),
        spacing_strategy="generous margins",
        figure_strategy="one hero figure per slide where available",
        table_strategy="compact tables with highlighted key row",
        chart_strategy="emphasize the primary series",
        decoration_strategy="minimal hairline rules",
        consistency_rules=["keep card radius <= 3px", "one accent per slide"],
        layout_source="fallback_template",
    )


def _to_slide_type(value: Any) -> SlideType:
    text = str(value or "").strip().upper()
    if text in _VALID_SLIDE_TYPES:
        return SlideType(text)
    return SlideType.METHOD_DETAIL


def _string_list(value: Any, limit: int = 12) -> List[str]:
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            out.append(text[:300])
        if len(out) >= limit:
            break
    return out


def _int_list(value: Any, limit: int = 12) -> List[int]:
    if not isinstance(value, list):
        return []
    out: List[int] = []
    for item in value:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if number > 0 and number not in out:
            out.append(number)
        if len(out) >= limit:
            break
    return out


def _parse_art_direction(payload: Any) -> DeckArtDirection:
    if not isinstance(payload, dict):
        raise ValueError("art_direction must be an object")
    data = dict(payload)
    data.setdefault("color_direction", {})
    return DeckArtDirection.model_validate({**data, "layout_source": "llm"})


def _parse_slides(payload: Any, fallback_title: str) -> List[SlidePlan]:
    if not isinstance(payload, list) or not payload:
        raise ValueError("slides must be a non-empty list")
    slides: List[SlidePlan] = []
    for idx, entry in enumerate(payload, start=1):
        if not isinstance(entry, dict):
            continue
        slides.append(
            SlidePlan(
                index=idx,
                slide_type=_to_slide_type(entry.get("slide_type")),
                title=str(entry.get("title") or fallback_title or f"Slide {idx}")[:200],
                objective=str(entry.get("objective") or "")[:400],
                key_messages=_string_list(entry.get("key_messages")),
                source_sections=_string_list(entry.get("source_sections"), limit=8),
                source_figures=_string_list(entry.get("source_figures"), limit=8),
                source_tables=_string_list(entry.get("source_tables"), limit=8),
                notes=(str(entry.get("notes")) if entry.get("notes") else None),
                source_pages=_int_list(entry.get("source_pages")),
                visual_evidence_ids=_string_list(entry.get("visual_evidence_ids")),
                design_goal=str(entry.get("design_goal") or "")[:400],
                visual_priority=str(entry.get("visual_priority") or "")[:60],
                factual_evidence_ids=_string_list(entry.get("factual_evidence_ids")),
            )
        )
    if not slides:
        raise ValueError("no valid slides parsed")
    return slides


async def _safe_emit(on_event: Optional[Callable], data: Dict[str, Any]) -> None:
    if not on_event:
        return
    try:
        result = on_event(data)
        if inspect.isawaitable(result):
            await result
    except Exception as exc:  # pragma: no cover
        logger.debug("Art director event ignored: %s", exc)


def _vision_available(llm_client: Any) -> bool:
    return bool(llm_client and getattr(llm_client, "api_key", None))


async def design_deck(
    llm_client: Any,
    paper_ir: Optional[PaperIR] = None,
    paper_visual_ir: Optional[PaperVisualIR] = None,
    user_prompt: str = "",
    duration_minutes: int = 15,
    contact_sheet_path: Optional[str] = None,
    on_event: Optional[Callable] = None,
) -> Tuple[Optional[DeckArtDirection], Optional[PresentationPlan]]:
    """Design deck-level art direction + presentation plan via the LLM.

    Returns ``(None, None)`` when the LLM is unavailable or its output cannot be
    validated, so the caller can fall back to the legacy planner.
    """
    if not _vision_available(llm_client):
        return None, None

    await _safe_emit(
        on_event,
        {"type": "generation_stage", "phase": "deck_art_direction", "current": 1, "total": 1},
    )

    text = build_art_direction_text(
        paper_ir, paper_visual_ir, user_prompt=user_prompt, duration_minutes=duration_minutes
    )
    content: List[Dict[str, Any]] = [{"type": "text", "text": text}]

    use_vision = False
    if contact_sheet_path and Path(contact_sheet_path).exists():
        import base64

        encoded = base64.b64encode(Path(contact_sheet_path).read_bytes()).decode("ascii")
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/webp;base64,{encoded}", "detail": "low"},
            }
        )
        use_vision = True

    role = "vision" if use_vision else "reasoning"
    messages = [
        {"role": "system", "content": ART_DIRECTOR_SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]

    try:
        response = await llm_client.chat_completion(messages, role=role, max_tokens=4000)
        raw = response["choices"][0]["message"].get("content", "")
        payload = extract_json(raw)
        if not isinstance(payload, dict):
            raise ValueError("expected a JSON object")
        art_direction = _parse_art_direction(payload.get("art_direction"))
        slides = _parse_slides(payload.get("slides"), fallback_title=(paper_ir.title if paper_ir else ""))
    except Exception as exc:
        logger.warning("Deck art direction LLM failed: %s", exc)
        return None, None

    plan = PresentationPlan(
        title=(paper_ir.title if paper_ir and paper_ir.title else "Research Presentation"),
        audience="Research Lab / Academic Seminar",
        duration_minutes=duration_minutes,
        profile="llm_research",
        source_filename=(paper_ir.source_filename if paper_ir else ""),
        slides=slides,
    )
    return art_direction, plan


async def build_plan_and_direction(
    llm_client: Any,
    paper_ir: Optional[PaperIR],
    paper_visual_ir: Optional[PaperVisualIR],
    user_prompt: str = "",
    duration_minutes: int = 15,
    contact_sheet_dir: Optional[str] = None,
    on_event: Optional[Callable] = None,
) -> Tuple[DeckArtDirection, PresentationPlan, bool]:
    """High-level entry: try LLM-native; fall back to deterministic planning.

    Returns ``(art_direction, plan, used_llm)``.
    """
    contact_sheet_path = None
    if contact_sheet_dir and paper_visual_ir is not None:
        contact_sheet_path = build_contact_sheet(
            [p.page_asset for p in paper_visual_ir.pages],
            Path(contact_sheet_dir) / "contact_sheet.webp",
        )

    if settings.llm_native_layout_enabled:
        art_direction, plan = await design_deck(
            llm_client,
            paper_ir=paper_ir,
            paper_visual_ir=paper_visual_ir,
            user_prompt=user_prompt,
            duration_minutes=duration_minutes,
            contact_sheet_path=contact_sheet_path,
            on_event=on_event,
        )
        if art_direction is not None and plan is not None:
            return art_direction, plan, True

    # Legacy deterministic fallback (templates remain fallback-only, never primary).
    from ..presentation.planner import generate_presentation_plan

    if paper_ir is not None:
        plan = generate_presentation_plan(paper_ir, profile="research_15min")
    else:
        plan = PresentationPlan(title="Research Presentation", slides=[])
    return default_art_direction(), plan, False


__all__ = [
    "design_deck",
    "build_plan_and_direction",
    "default_art_direction",
    "default_color_direction",
]
