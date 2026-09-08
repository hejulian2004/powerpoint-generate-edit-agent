"""PresentationPlan to SlideSpec Semantic Mapper (PR9).

Maps each high-level SlidePlan into a strongly-typed SlideSpec with structured
content blocks and visual intents.

Decoupling Principle:
- Does NOT assign pixel coordinates (left, top, width, height).
- Determines visual layout archetype (VisualIntent) and semantic roles (BlockRole).
- Encapsulates figure and table references with paper metadata.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..paper.schema import PaperFigure, PaperIR, PaperTable
from ..presentation.schema import PresentationPlan, SlidePlan, SlideType
from .schema import (
    BadgeBlock,
    BlockRole,
    ContentBlock,
    DeckSpec,
    FigureBlock,
    SlideSpec,
    TableBlock,
    TextBlock,
    VisualIntent,
)


def _find_figure(paper: Optional[PaperIR], fig_id: str) -> Optional[PaperFigure]:
    if not paper or not fig_id:
        return None
    for f in paper.figures:
        if f.id == fig_id:
            return f
    return None


def _find_table(paper: Optional[PaperIR], tab_id: str) -> Optional[PaperTable]:
    if not paper or not tab_id:
        return None
    for t in paper.tables:
        if t.id == tab_id:
            return t
    return None


def map_slide_plan_to_slide_spec(
    slide: SlidePlan,
    paper: Optional[PaperIR] = None,
) -> SlideSpec:
    """Map a single SlidePlan to its semantic SlideSpec."""
    slide_type = slide.slide_type
    blocks: List[ContentBlock] = []
    subtitle: Optional[str] = None
    visual_intent: VisualIntent = VisualIntent.KEY_TAKEAWAY_LIST

    # 1. SlideType: TITLE
    if slide_type == SlideType.TITLE:
        visual_intent = VisualIntent.TITLE_HERO
        venue = paper.metadata.venue if paper and paper.metadata.venue else "Academic Seminar"
        authors = ", ".join(paper.metadata.authors) if paper and paper.metadata.authors else ""
        if authors:
            subtitle = authors

        blocks.append(BadgeBlock(text=venue, variant="primary"))
        if authors:
            blocks.append(TextBlock(role=BlockRole.SUBHEADING, content=authors))

        # Add key takeaways / subtitle
        for msg in slide.key_messages:
            blocks.append(TextBlock(role=BlockRole.LEAD_SUMMARY, content=msg))

    # 2. SlideType: METHOD_OVERVIEW
    elif slide_type == SlideType.METHOD_OVERVIEW:
        if slide.source_figures:
            visual_intent = VisualIntent.PIPELINE_ARCHITECTURE
            fig_id = slide.source_figures[0]
            fig = _find_figure(paper, fig_id)
            blocks.append(
                FigureBlock(
                    source_figure_id=fig_id,
                    caption=fig.caption if fig else "Overall Framework Pipeline",
                    xref_label=fig.xref_label if fig else "Fig. 1",
                )
            )
        else:
            visual_intent = VisualIntent.KEY_TAKEAWAY_LIST

        # Accompanying architectural bullets
        for idx, msg in enumerate(slide.key_messages):
            blocks.append(
                TextBlock(
                    role=BlockRole.BULLET_ITEM,
                    content=msg,
                    emphasis=(idx == 0),
                )
            )

    # 3. SlideType: RESULT
    elif slide_type == SlideType.RESULT:
        if slide.source_tables or slide.source_figures:
            visual_intent = VisualIntent.BENCHMARK_COMPARISON
            blocks.append(BadgeBlock(text="Empirical Benchmark", variant="success"))

            if slide.source_tables:
                tab_id = slide.source_tables[0]
                tab = _find_table(paper, tab_id)
                blocks.append(
                    TableBlock(
                        source_table_id=tab_id,
                        caption=tab.caption if tab else "Comparative Results",
                        xref_label=tab.xref_label if tab else "Table 1",
                    )
                )
            elif slide.source_figures:
                fig_id = slide.source_figures[0]
                fig = _find_figure(paper, fig_id)
                blocks.append(
                    FigureBlock(
                        source_figure_id=fig_id,
                        caption=fig.caption if fig else "Evaluation Results",
                        xref_label=fig.xref_label if fig else "",
                    )
                )
        else:
            visual_intent = VisualIntent.KEY_TAKEAWAY_LIST

        for idx, msg in enumerate(slide.key_messages):
            blocks.append(
                TextBlock(
                    role=BlockRole.BULLET_ITEM,
                    content=msg,
                    emphasis=(idx == 0),
                )
            )

    # 4. SlideType: ABLATION
    elif slide_type == SlideType.ABLATION:
        if slide.source_tables:
            visual_intent = VisualIntent.BENCHMARK_COMPARISON
            tab_id = slide.source_tables[0]
            tab = _find_table(paper, tab_id)
            blocks.append(
                TableBlock(
                    source_table_id=tab_id,
                    caption=tab.caption if tab else "Ablation Study",
                    xref_label=tab.xref_label if tab else "Table 2",
                )
            )
        elif slide.source_figures:
            visual_intent = VisualIntent.BENCHMARK_COMPARISON
            fig_id = slide.source_figures[0]
            fig = _find_figure(paper, fig_id)
            blocks.append(
                FigureBlock(
                    source_figure_id=fig_id,
                    caption=fig.caption if fig else "Ablation Analysis",
                    xref_label=fig.xref_label if fig else "",
                )
            )
        else:
            visual_intent = VisualIntent.TWO_COLUMN_CONTRAST

        for msg in slide.key_messages:
            blocks.append(TextBlock(role=BlockRole.BULLET_ITEM, content=msg))

    # 5. SlideType: PROBLEM / MOTIVATION / RELATED_WORK
    elif slide_type in (SlideType.PROBLEM, SlideType.MOTIVATION, SlideType.RELATED_WORK):
        visual_intent = VisualIntent.TWO_COLUMN_CONTRAST
        if slide.key_messages:
            blocks.append(TextBlock(role=BlockRole.LEAD_SUMMARY, content=slide.key_messages[0]))
            for msg in slide.key_messages[1:]:
                blocks.append(TextBlock(role=BlockRole.BULLET_ITEM, content=msg))
        else:
            blocks.append(TextBlock(role=BlockRole.LEAD_SUMMARY, content=slide.objective))

    # 6. Default: BACKGROUND, METHOD_DETAIL, EXPERIMENT_SETUP, LIMITATION, CONCLUSION
    else:
        visual_intent = VisualIntent.KEY_TAKEAWAY_LIST
        if slide.key_messages:
            blocks.append(TextBlock(role=BlockRole.LEAD_SUMMARY, content=slide.key_messages[0]))
            for msg in slide.key_messages[1:]:
                blocks.append(TextBlock(role=BlockRole.BULLET_ITEM, content=msg))
        else:
            blocks.append(TextBlock(role=BlockRole.LEAD_SUMMARY, content=slide.objective))

    provenance = {
        "source_sections": slide.source_sections,
        "source_figures": slide.source_figures,
        "source_tables": slide.source_tables,
    }

    return SlideSpec(
        index=slide.index,
        slide_type=slide_type,
        visual_intent=visual_intent,
        title=slide.title,
        subtitle=subtitle,
        blocks=blocks,
        speaker_notes=slide.notes,
        provenance=provenance,
    )


def map_presentation_plan_to_deck_spec(
    plan: PresentationPlan,
    paper: Optional[PaperIR] = None,
) -> DeckSpec:
    """Transform a full PresentationPlan into a DeckSpec."""
    slides = [map_slide_plan_to_slide_spec(s, paper) for s in plan.slides]
    return DeckSpec(
        title=plan.title,
        profile=plan.profile,
        slides=slides,
    )
