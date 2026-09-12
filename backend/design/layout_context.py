"""Per-slide layout design context.

Only the pages/crops relevant to the current slide are attached (tier 3 of the
context budget), plus the deck art direction and the slide's exact semantic
content. This keeps vision calls bounded regardless of paper length.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..paper.schema import PaperIR
from ..paper_visual.context import select_visual_context_for_slide
from ..paper_visual.schema import PaperVisualIR
from ..presentation.schema import SlidePlan
from ..slidespec.schema import SlideSpec
from .schema import DeckArtDirection


@dataclass
class SlideLayoutContext:
    text: str
    image_paths: List[str] = field(default_factory=list)

    @property
    def use_vision(self) -> bool:
        return bool(self.image_paths)


def _block_description(block: Any) -> Dict[str, Any]:
    data: Dict[str, Any] = {"kind": getattr(block, "kind", "?")}
    for key in ("block_id", "role", "content", "text", "source_figure_id",
                "source_table_id", "caption", "column", "emphasis"):
        value = getattr(block, key, None)
        if value not in (None, "", [], False):
            data[key] = value if not hasattr(value, "value") else value.value
    return data


def _art_direction_summary(art: DeckArtDirection) -> str:
    color = art.color_direction
    lines = [
        f"Design concept: {art.design_concept}",
        f"Visual language: {art.visual_language}",
        f"Typography: {art.typography_strategy}",
        f"Spacing: {art.spacing_strategy}",
        f"Figure strategy: {art.figure_strategy}",
        f"Table strategy: {art.table_strategy}",
        f"Chart strategy: {art.chart_strategy}",
        f"Decoration: {art.decoration_strategy}",
        (
            "Colors: "
            f"text={color.primary_text}, secondary_text={color.secondary_text}, "
            f"accent={color.primary_accent}"
            + (f", accent2={color.secondary_accent}" if color.secondary_accent else "")
        ),
    ]
    if art.consistency_rules:
        lines.append("Consistency rules: " + "; ".join(art.consistency_rules[:8]))
    return "\n".join(lines)


def build_slide_layout_context(
    slide_spec: SlideSpec,
    slide_plan: Optional[SlidePlan],
    art_direction: DeckArtDirection,
    paper_ir: Optional[PaperIR] = None,
    paper_visual_ir: Optional[PaperVisualIR] = None,
    previous_layout: Optional[Any] = None,
    previous_feedback: Optional[str] = None,
    max_images: int = 6,
) -> SlideLayoutContext:
    parts: List[str] = []
    parts.append(_art_direction_summary(art_direction))
    parts.append(
        f"SLIDE {slide_spec.index}: type={slide_spec.slide_type.value}, "
        f"visual_intent={slide_spec.visual_intent.value}\n"
        f"title: {slide_spec.title}\n"
        + (f"subtitle: {slide_spec.subtitle}\n" if slide_spec.subtitle else "")
    )
    if slide_plan is not None:
        if slide_plan.design_goal:
            parts.append(f"Design goal: {slide_plan.design_goal}")
        if slide_plan.visual_priority:
            parts.append(f"Visual priority: {slide_plan.visual_priority}")
        if slide_plan.key_messages:
            parts.append("Key messages:\n" + "\n".join(f"- {m}" for m in slide_plan.key_messages))

    block_lines = [str(_block_description(b)) for b in slide_spec.blocks]
    if block_lines:
        parts.append("CONTENT BLOCKS (use exactly this content):\n" + "\n".join(block_lines))

    image_paths: List[str] = []
    if paper_visual_ir is not None:
        source_pages = slide_plan.source_pages if slide_plan else []
        figure_ids = slide_plan.source_figures if slide_plan else []
        table_ids = slide_plan.source_tables if slide_plan else []
        visual_ctx = select_visual_context_for_slide(
            paper_visual_ir,
            source_pages=source_pages,
            figure_ids=figure_ids,
            table_ids=table_ids,
        )
        if visual_ctx.page_assets:
            parts.append(
                "RELEVANT PAPER PAGES: "
                + ", ".join(str(p) for p in visual_ctx.source_pages)
            )
        for path in visual_ctx.page_image_paths:
            image_paths.append(path)
        for path in visual_ctx.crop_paths:
            image_paths.append(path)

    if previous_layout is not None:
        parts.append(f"PREVIOUS LAYOUT SUMMARY:\n{previous_layout}")
    if previous_feedback:
        parts.append(f"VALIDATION FEEDBACK TO FIX:\n{previous_feedback}")

    # De-duplicate while preserving order, then bound.
    seen = set()
    bounded_images: List[str] = []
    for path in image_paths:
        if path and path not in seen:
            seen.add(path)
            bounded_images.append(path)
    bounded_images = bounded_images[:max_images]

    return SlideLayoutContext(text="\n\n".join(parts), image_paths=bounded_images)


__all__ = ["SlideLayoutContext", "build_slide_layout_context"]
