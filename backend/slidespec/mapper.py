"""PresentationPlan to SlideSpec Semantic Mapper (PR9).

Maps each high-level SlidePlan into a strongly-typed SlideSpec with structured
content blocks and visual intents.

Decoupling Principle:
- Does NOT assign pixel coordinates (left, top, width, height).
- Determines visual layout archetype (VisualIntent) and semantic roles (BlockRole).
- Encapsulates figure and table references with paper metadata.
"""

from __future__ import annotations

import re
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


def _format_default_xref(asset_id: str, kind: str = "figure") -> str:
    """Format fallback printed label from asset id (e.g. 'figure3' -> 'Fig. 3')."""
    match = re.search(r"\d+", asset_id)
    num = match.group(0) if match else "1"
    return f"Fig. {num}" if kind == "figure" else f"Table {num}"


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

        # Filter out repetitive metadata lines from key_messages (e.g. "Paper: ...", "Presented by: ...")
        lead_messages = [
            msg for msg in slide.key_messages
            if not msg.lower().startswith("paper:")
            and not msg.lower().startswith("presented by:")
            and not msg.lower().startswith("published:")
        ]
        if lead_messages:
            for msg in lead_messages:
                blocks.append(TextBlock(role=BlockRole.LEAD_SUMMARY, content=msg))
        else:
            blocks.append(TextBlock(role=BlockRole.LEAD_SUMMARY, content=slide.objective))

    # 2. SlideType: METHOD_OVERVIEW
    elif slide_type == SlideType.METHOD_OVERVIEW:
        if slide.source_figures:
            visual_intent = VisualIntent.PIPELINE_ARCHITECTURE
            for fig_id in slide.source_figures:
                fig = _find_figure(paper, fig_id)
                cap = (fig.caption.strip() if fig and fig.caption else "") or "Overall Framework Pipeline"
                xref = (fig.xref_label.strip() if fig and fig.xref_label else "") or _format_default_xref(fig_id, "figure")
                blocks.append(
                    FigureBlock(
                        source_figure_id=fig_id,
                        caption=cap,
                        xref_label=xref,
                    )
                )
        else:
            visual_intent = VisualIntent.KEY_TAKEAWAY_LIST

        if slide.key_messages:
            for idx, msg in enumerate(slide.key_messages):
                blocks.append(
                    TextBlock(
                        role=BlockRole.BULLET_ITEM,
                        content=msg,
                        emphasis=(idx == 0),
                    )
                )
        else:
            blocks.append(TextBlock(role=BlockRole.LEAD_SUMMARY, content=slide.objective))

    # 3. SlideType: METHOD_DETAIL
    elif slide_type == SlideType.METHOD_DETAIL:
        if slide.source_figures:
            visual_intent = VisualIntent.PIPELINE_ARCHITECTURE
            for fig_id in slide.source_figures:
                fig = _find_figure(paper, fig_id)
                cap = (fig.caption.strip() if fig and fig.caption else "") or "Technical Component Details"
                xref = (fig.xref_label.strip() if fig and fig.xref_label else "") or _format_default_xref(fig_id, "figure")
                blocks.append(
                    FigureBlock(
                        source_figure_id=fig_id,
                        caption=cap,
                        xref_label=xref,
                    )
                )
        elif slide.source_tables:
            visual_intent = VisualIntent.BENCHMARK_COMPARISON
            for tab_id in slide.source_tables:
                tab = _find_table(paper, tab_id)
                cap = (tab.caption.strip() if tab and tab.caption else "") or "Algorithmic Specifications"
                xref = (tab.xref_label.strip() if tab and tab.xref_label else "") or _format_default_xref(tab_id, "table")
                blocks.append(
                    TableBlock(
                        source_table_id=tab_id,
                        caption=cap,
                        xref_label=xref,
                    )
                )
        else:
            visual_intent = VisualIntent.KEY_TAKEAWAY_LIST

        if slide.key_messages:
            for idx, msg in enumerate(slide.key_messages):
                blocks.append(
                    TextBlock(
                        role=BlockRole.BULLET_ITEM,
                        content=msg,
                        emphasis=(idx == 0),
                    )
                )
        else:
            blocks.append(TextBlock(role=BlockRole.LEAD_SUMMARY, content=slide.objective))

    # 4. SlideType: RESULT
    elif slide_type == SlideType.RESULT:
        if slide.source_tables or slide.source_figures:
            visual_intent = VisualIntent.BENCHMARK_COMPARISON
            blocks.append(BadgeBlock(text="Empirical Benchmark", variant="success"))

            for tab_id in slide.source_tables:
                tab = _find_table(paper, tab_id)
                cap = (tab.caption.strip() if tab and tab.caption else "") or "Comparative Results"
                xref = (tab.xref_label.strip() if tab and tab.xref_label else "") or _format_default_xref(tab_id, "table")
                blocks.append(
                    TableBlock(
                        source_table_id=tab_id,
                        caption=cap,
                        xref_label=xref,
                    )
                )

            for fig_id in slide.source_figures:
                fig = _find_figure(paper, fig_id)
                cap = (fig.caption.strip() if fig and fig.caption else "") or "Evaluation Results"
                xref = (fig.xref_label.strip() if fig and fig.xref_label else "") or _format_default_xref(fig_id, "figure")
                blocks.append(
                    FigureBlock(
                        source_figure_id=fig_id,
                        caption=cap,
                        xref_label=xref,
                    )
                )
        else:
            visual_intent = VisualIntent.KEY_TAKEAWAY_LIST

        if slide.key_messages:
            for idx, msg in enumerate(slide.key_messages):
                blocks.append(
                    TextBlock(
                        role=BlockRole.BULLET_ITEM,
                        content=msg,
                        emphasis=(idx == 0),
                    )
                )
        else:
            blocks.append(TextBlock(role=BlockRole.LEAD_SUMMARY, content=slide.objective))

    # 5. SlideType: ABLATION
    elif slide_type == SlideType.ABLATION:
        if slide.source_tables or slide.source_figures:
            visual_intent = VisualIntent.BENCHMARK_COMPARISON
            for tab_id in slide.source_tables:
                tab = _find_table(paper, tab_id)
                cap = (tab.caption.strip() if tab and tab.caption else "") or "Ablation Study"
                xref = (tab.xref_label.strip() if tab and tab.xref_label else "") or _format_default_xref(tab_id, "table")
                blocks.append(
                    TableBlock(
                        source_table_id=tab_id,
                        caption=cap,
                        xref_label=xref,
                    )
                )

            for fig_id in slide.source_figures:
                fig = _find_figure(paper, fig_id)
                cap = (fig.caption.strip() if fig and fig.caption else "") or "Ablation Analysis"
                xref = (fig.xref_label.strip() if fig and fig.xref_label else "") or _format_default_xref(fig_id, "figure")
                blocks.append(
                    FigureBlock(
                        source_figure_id=fig_id,
                        caption=cap,
                        xref_label=xref,
                    )
                )
        else:
            visual_intent = VisualIntent.TWO_COLUMN_CONTRAST

        if slide.key_messages:
            for msg in slide.key_messages:
                blocks.append(TextBlock(role=BlockRole.BULLET_ITEM, content=msg))
        else:
            blocks.append(TextBlock(role=BlockRole.LEAD_SUMMARY, content=slide.objective))

    # 6. SlideType: PROBLEM / MOTIVATION / RELATED_WORK (Two-Column Contrast)
    elif slide_type in (SlideType.PROBLEM, SlideType.MOTIVATION, SlideType.RELATED_WORK):
        visual_intent = VisualIntent.TWO_COLUMN_CONTRAST
        if slide.key_messages:
            # First item as left-column lead/challenge, remainder partitioned cleanly
            half = max(1, len(slide.key_messages) // 2)
            left_msgs = slide.key_messages[:half]
            right_msgs = slide.key_messages[half:]

            for msg in left_msgs:
                blocks.append(TextBlock(role=BlockRole.BULLET_ITEM, content=msg, column="left"))
            for msg in right_msgs:
                blocks.append(TextBlock(role=BlockRole.BULLET_ITEM, content=msg, column="right"))
        else:
            blocks.append(TextBlock(role=BlockRole.LEAD_SUMMARY, content=slide.objective, column="left"))

    # 7. Default: BACKGROUND, EXPERIMENT_SETUP, LIMITATION, CONCLUSION
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
