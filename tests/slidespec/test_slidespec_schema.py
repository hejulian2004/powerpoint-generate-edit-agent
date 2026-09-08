"""Tests for SlideSpec and DeckSpec Data Models (PR9)."""

from pathlib import Path

from backend.presentation.schema import SlideType
from backend.slidespec import (
    BadgeBlock,
    BlockRole,
    DeckSpec,
    FigureBlock,
    SlideSpec,
    TableBlock,
    TextBlock,
    VisualIntent,
)


def test_content_blocks_polymorphism():
    text_block = TextBlock(role=BlockRole.HEADING, content="Main Heading", emphasis=True)
    fig_block = FigureBlock(source_figure_id="figure1", caption="Overview diagram", xref_label="Fig. 1")
    tab_block = TableBlock(source_table_id="table1", caption="Results", highlight_cells=["r1c2"])
    badge_block = BadgeBlock(text="SOTA", variant="success")

    assert text_block.kind == "text"
    assert fig_block.kind == "figure"
    assert tab_block.kind == "table"
    assert badge_block.kind == "badge"


def test_slide_spec_instantiation_and_helpers():
    blocks = [
        TextBlock(role=BlockRole.LEAD_SUMMARY, content="Summary point"),
        FigureBlock(source_figure_id="figure1", caption="Architecture"),
        TextBlock(role=BlockRole.BULLET_ITEM, content="Detailed step"),
    ]

    slide = SlideSpec(
        index=1,
        slide_type=SlideType.METHOD_OVERVIEW,
        visual_intent=VisualIntent.PIPELINE_ARCHITECTURE,
        title="Method Overview",
        subtitle="Framework Architecture",
        blocks=blocks,
        speaker_notes="Explain the agent interaction loop.",
        provenance={"source_figures": ["figure1"]},
    )

    assert slide.index == 1
    assert slide.visual_intent == VisualIntent.PIPELINE_ARCHITECTURE
    assert len(slide.blocks) == 3

    figs = slide.get_blocks_by_kind("figure")
    assert len(figs) == 1
    assert figs[0].source_figure_id == "figure1"

    texts = slide.get_blocks_by_kind("text")
    assert len(texts) == 2


def test_deck_spec_roundtrip(tmp_path: Path):
    slide = SlideSpec(
        index=1,
        slide_type=SlideType.TITLE,
        visual_intent=VisualIntent.TITLE_HERO,
        title="Sample Presentation",
        blocks=[
            BadgeBlock(text="NeurIPS 2026", variant="primary"),
            TextBlock(role=BlockRole.HEADING, content="Sample Presentation"),
        ],
    )

    deck = DeckSpec(
        title="Sample Presentation",
        profile="research_15min",
        slides=[slide],
    )

    assert deck.slide_count == 1
    json_path = tmp_path / "deck_spec.json"
    deck.to_json_file(json_path)
    assert json_path.exists()

    reloaded = DeckSpec.from_json_file(json_path)
    assert reloaded.title == deck.title
    assert reloaded.slide_count == 1
    assert reloaded.slides[0].visual_intent == VisualIntent.TITLE_HERO
    assert reloaded.slides[0].blocks[0].kind == "badge"
