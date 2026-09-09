"""Unit tests for SlideSpec Compiler (PR13 Step 3)."""

from backend.layout.engine import generate_deck_layout
from backend.pptspec.compiler import compile_pptspec_to_deckspec
from backend.pptspec.schema import (
    CanonicalPPTSpec,
    ClaimEvidence,
    FigureReferenceEvidence,
    MetricEvidence,
    PresentationConfig,
    SlideRequest,
    SourceDocument,
    TableEvidence,
)
from backend.presentation.schema import SlideType
from backend.slidespec.schema import FigureBlock, TableBlock, TextBlock, VisualIntent


def test_compile_pptspec_to_deckspec_deterministic_ids():
    spec = CanonicalPPTSpec(
        spec_version="1.0",
        presentation=PresentationConfig(title="Deterministic Compilation"),
        source_document=SourceDocument(title="Study", venue="NeurIPS 2024", authors=["Alice", "Bob"]),
        evidence=[
            ClaimEvidence(id="ev_c1", content="Key finding 1"),
            ClaimEvidence(id="ev_c2", content="Key finding 2"),
            MetricEvidence(id="ev_m1", name="Accuracy", value="92.4%"),
            FigureReferenceEvidence(id="ev_fig1", label="Figure 3", caption="Framework Architecture", source_page=5),
            TableEvidence(id="ev_tbl1", columns=["Model", "Score"], rows=[["Ours", "95.0"]], caption="Main Table", complete_table=True),
            TableEvidence(id="ev_tbl2", columns=[], rows=[], caption="Ablation Table", complete_table=False),
        ],
        slides=[
            SlideRequest(
                id="slide_01",
                type=SlideType.TITLE,
                title="Title Slide",
                evidence_refs=["ev_c1"],
            ),
            SlideRequest(
                id="slide_02",
                type=SlideType.METHOD_OVERVIEW,
                title="Method Overview",
                evidence_refs=["ev_fig1", "ev_c2"],
            ),
            SlideRequest(
                id="slide_03",
                type=SlideType.RESULT,
                title="Results",
                evidence_refs=["ev_m1", "ev_tbl1", "ev_tbl2"],
            ),
        ],
    )

    deck_spec = compile_pptspec_to_deckspec(spec)
    assert deck_spec.title == "Deterministic Compilation"
    assert len(deck_spec.slides) == 3

    # Slide 1 (Title)
    s1 = deck_spec.slides[0]
    assert s1.visual_intent == VisualIntent.TITLE_HERO
    assert s1.subtitle == "Alice, Bob"
    block_ids_s1 = [b.block_id for b in s1.blocks]
    assert "slide_01_venue_badge" in block_ids_s1
    assert "slide_01_claim_01" in block_ids_s1

    # Slide 2 (Figure)
    s2 = deck_spec.slides[1]
    fig_blocks = [b for b in s2.blocks if isinstance(b, FigureBlock)]
    assert len(fig_blocks) == 1
    assert fig_blocks[0].block_id == "slide_02_figure_01"
    assert fig_blocks[0].placeholder is True
    assert fig_blocks[0].xref_label == "Figure 3"
    assert fig_blocks[0].source_page == 5

    # Slide 3 (Tables & Metrics)
    s3 = deck_spec.slides[2]
    tbl_blocks = [b for b in s3.blocks if isinstance(b, TableBlock)]
    assert len(tbl_blocks) == 2
    # Complete table
    assert tbl_blocks[0].block_id == "slide_03_table_01"
    assert tbl_blocks[0].placeholder is False
    assert len(tbl_blocks[0].rows) == 1
    # Incomplete table placeholder
    assert tbl_blocks[1].block_id == "slide_03_table_02"
    assert tbl_blocks[1].placeholder is True

    # Check that the compiled DeckSpec passes through layout engine without error!
    deck_layout = generate_deck_layout(deck_spec)
    assert deck_layout.slide_count == 3
    assert len(deck_layout.slides[0].elements) > 0
    assert len(deck_layout.slides[1].elements) > 0
    assert len(deck_layout.slides[2].elements) > 0
