"""Deck-level multimodal review for the paper pipeline (S4 / Phase 9).

Strictly read-only. Reuses the canonical per-slide multimodal critic
(``visual_critic.critique_deck``) — no duplicated geometry rules — and aggregates a
deck review with the slides that need another design pass (``slides_to_revisit``).

Typical caller: the generation graph's ``deck_visual_review_node`` after the
deterministic geometry self-heal loop has converged, so only visual/source
alignment issues remain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from ..layout.schema import LayoutSpec
from .visual_critic import SlideCritique, critique_deck

DEFAULT_REVISIT_SCORE = 80.0


@dataclass
class DeckCritique:
    """Aggregated read-only review of a whole deck."""

    slides: List[SlideCritique] = field(default_factory=list)
    slides_to_revisit: List[int] = field(default_factory=list)
    average_score: float = 100.0
    min_score: float = 100.0
    reviewed: int = 0

    @property
    def needs_revisit(self) -> bool:
        return bool(self.slides_to_revisit)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slides": [c.to_dict() for c in self.slides],
            "slides_to_revisit": list(self.slides_to_revisit),
            "average_score": round(self.average_score, 1),
            "min_score": round(self.min_score, 1),
            "reviewed": self.reviewed,
        }


async def review_deck(
    layouts: Sequence[LayoutSpec],
    llm_client: Any = None,
    *,
    raster_data_uris: Optional[Dict[str, str]] = None,
    source_images_by_slide: Optional[Dict[str, Sequence[str]]] = None,
    color_report: Any = None,
    include_multimodal: bool = True,
    revisit_score: float = DEFAULT_REVISIT_SCORE,
    on_event: Optional[Callable] = None,
) -> DeckCritique:
    """Critique every slide and flag the ones that should be revisited.

    Read-only: returns diagnostics only, never mutates a layout.
    """
    critiques = await critique_deck(
        layouts,
        llm_client=llm_client,
        include_multimodal=include_multimodal,
        raster_data_uris=raster_data_uris,
        source_images_by_slide=source_images_by_slide,
        color_report=color_report,
        on_event=on_event,
    )
    if not critiques:
        return DeckCritique()

    by_id = {layout.slide_id: layout for layout in layouts}
    revisit: List[int] = []
    for critique in critiques:
        layout = by_id.get(critique.slide_id)
        if layout is None:
            continue
        if critique.needs_refinement or critique.score < revisit_score:
            revisit.append(layout.slide_index)

    scores = [c.score for c in critiques]
    return DeckCritique(
        slides=critiques,
        slides_to_revisit=sorted(set(revisit)),
        average_score=sum(scores) / len(scores),
        min_score=min(scores),
        reviewed=len(critiques),
    )


__all__ = ["DeckCritique", "review_deck", "DEFAULT_REVISIT_SCORE"]
