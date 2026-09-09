"""SlideSpec Compiler (PR13 Step 3).

Compiles a strictly validated CanonicalPPTSpec into a DeckSpec composed of SlideSpec instances.
Assigns deterministic block IDs to all content blocks (e.g. 'slide_01_claim_01', 'slide_03_figure_01').
Encodes explicit placeholder semantics for figures and incomplete tables.
"""

from __future__ import annotations

from typing import List, Optional

from ..presentation.schema import SlideType
from ..slidespec.schema import (
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
from .schema import (
    CanonicalPPTSpec,
    ClaimEvidence,
    EquationEvidence,
    FigureReferenceEvidence,
    MetricEvidence,
    MetricGroupEvidence,
    QuoteEvidence,
    SlideRequest,
    TableEvidence,
)


def compile_slide_request_to_slide_spec(
    slide_req: SlideRequest,
    slide_index: int,
    spec: CanonicalPPTSpec,
) -> SlideSpec:
    """Compile a single SlideRequest into a structured SlideSpec with deterministic block IDs."""
    blocks: List[ContentBlock] = []
    evidence_map = {ev.id: ev for ev in spec.evidence}

    claim_idx = 1
    metric_idx = 1
    fig_idx = 1
    tbl_idx = 1
    quote_idx = 1
    eq_idx = 1

    slide_type = slide_req.type
    visual_intent = slide_req.visual_intent

    if visual_intent is None:
        if slide_type == SlideType.TITLE:
            visual_intent = VisualIntent.TITLE_HERO
        elif slide_type == SlideType.METHOD_OVERVIEW:
            visual_intent = VisualIntent.PIPELINE_ARCHITECTURE
        elif slide_type in (SlideType.RESULT, SlideType.ABLATION):
            visual_intent = VisualIntent.BENCHMARK_COMPARISON
        else:
            visual_intent = VisualIntent.KEY_TAKEAWAY_LIST

    # 1. Process referenced evidence items
    has_fig = False
    has_tbl = False

    for ref in slide_req.evidence_refs:
        ev = evidence_map.get(ref)
        if ev is None:
            continue

        if isinstance(ev, ClaimEvidence):
            role = BlockRole.LEAD_SUMMARY if (slide_type == SlideType.TITLE and claim_idx == 1) else BlockRole.BULLET_ITEM
            blocks.append(
                TextBlock(
                    kind="text",
                    block_id=f"{slide_req.id}_claim_{claim_idx:02d}",
                    source_evidence_ids=[ev.id],
                    role=role,
                    content=ev.content,
                )
            )
            claim_idx += 1

        elif isinstance(ev, MetricEvidence):
            unit_str = f" {ev.unit}" if ev.unit else ""
            badge_text = f"{ev.name}: {ev.value}{unit_str}"
            blocks.append(
                BadgeBlock(
                    kind="badge",
                    block_id=f"{slide_req.id}_metric_{metric_idx:02d}",
                    source_evidence_ids=[ev.id],
                    text=badge_text,
                    variant="primary",
                )
            )
            metric_idx += 1

        elif isinstance(ev, MetricGroupEvidence):
            for m in ev.metrics:
                u_str = f" {m.unit}" if m.unit else ""
                blocks.append(
                    BadgeBlock(
                        kind="badge",
                        block_id=f"{slide_req.id}_metric_{metric_idx:02d}",
                        source_evidence_ids=[ev.id],
                        text=f"{m.name}: {m.value}{u_str}",
                        variant="accent",
                    )
                )
                metric_idx += 1

        elif isinstance(ev, FigureReferenceEvidence):
            has_fig = True
            blocks.append(
                FigureBlock(
                    kind="figure",
                    block_id=f"{slide_req.id}_figure_{fig_idx:02d}",
                    source_evidence_ids=[ev.id],
                    source_figure_id=ev.id,
                    caption=ev.caption or "",
                    xref_label=ev.label,
                    placeholder=True,
                    source_page=ev.source_page,
                )
            )
            fig_idx += 1

        elif isinstance(ev, TableEvidence):
            has_tbl = True
            blocks.append(
                TableBlock(
                    kind="table",
                    block_id=f"{slide_req.id}_table_{tbl_idx:02d}",
                    source_evidence_ids=[ev.id],
                    source_table_id=ev.id,
                    caption=ev.caption or "",
                    xref_label=ev.source_reference or f"Table ({ev.id})",
                    columns=ev.columns,
                    rows=ev.rows,
                    placeholder=not ev.complete_table,
                    source_page=ev.source_page,
                )
            )
            tbl_idx += 1

        elif isinstance(ev, EquationEvidence):
            blocks.append(
                TextBlock(
                    kind="text",
                    block_id=f"{slide_req.id}_eq_{eq_idx:02d}",
                    source_evidence_ids=[ev.id],
                    role=BlockRole.CALLOUT,
                    content=f"Formula: {ev.latex}",
                )
            )
            eq_idx += 1

        elif isinstance(ev, QuoteEvidence):
            blocks.append(
                TextBlock(
                    kind="text",
                    block_id=f"{slide_req.id}_quote_{quote_idx:02d}",
                    source_evidence_ids=[ev.id],
                    role=BlockRole.LEAD_SUMMARY,
                    content=f'"{ev.content}"',
                )
            )
            quote_idx += 1

    # 2. Ensure title slides have appropriate badges and subtitle
    subtitle: Optional[str] = None
    if slide_type == SlideType.TITLE:
        authors = ", ".join(spec.source_document.authors) if spec.source_document.authors else ""
        if authors:
            subtitle = authors
        elif spec.presentation.audience:
            subtitle = spec.presentation.audience

        if spec.source_document.venue:
            blocks.insert(
                0,
                BadgeBlock(
                    kind="badge",
                    block_id=f"{slide_req.id}_venue_badge",
                    text=spec.source_document.venue,
                    variant="primary",
                ),
            )

    # 4. If slide has a figure and PIPELINE_ARCHITECTURE intent was requested, adjust if needed
    if has_fig and slide_type == SlideType.METHOD_OVERVIEW:
        visual_intent = VisualIntent.PIPELINE_ARCHITECTURE
    elif (has_tbl or metric_idx > 1) and slide_type in (SlideType.RESULT, SlideType.ABLATION):
        visual_intent = VisualIntent.BENCHMARK_COMPARISON

    return SlideSpec(
        index=slide_index,
        slide_type=slide_type,
        visual_intent=visual_intent,
        title=slide_req.title,
        subtitle=subtitle,
        blocks=blocks,
        speaker_notes=slide_req.speaker_notes,
        provenance={
            "evidence_refs": list(slide_req.evidence_refs),
            "source_document": spec.source_document.model_dump(),
        },
    )


def compile_pptspec_to_deckspec(spec: CanonicalPPTSpec) -> DeckSpec:
    """Compile a complete CanonicalPPTSpec into a DeckSpec."""
    slide_specs: List[SlideSpec] = []
    for s_idx, slide_req in enumerate(spec.slides, start=1):
        slide_spec = compile_slide_request_to_slide_spec(
            slide_req=slide_req,
            slide_index=s_idx,
            spec=spec,
        )
        slide_specs.append(slide_spec)

    return DeckSpec(
        title=spec.presentation.title,
        profile=spec.presentation.style,
        slides=slide_specs,
    )
