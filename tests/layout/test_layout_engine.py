"""Unit Tests for Layout Engine and Intent Synthesis (PR10)."""

from backend.layout import generate_layout
from backend.layout.schema import ElementType
from backend.presentation.schema import SlideType
from backend.slidespec.schema import (
    BadgeBlock,
    BlockRole,
    FigureBlock,
    SlideSpec,
    TableBlock,
    TextBlock,
    VisualIntent,
)


def test_title_hero_synthesis():
    slide = SlideSpec(
        index=1,
        slide_type=SlideType.TITLE,
        visual_intent=VisualIntent.TITLE_HERO,
        title="Robust Agent Architecture for Deep Learning",
        subtitle="Julian He, AI Research Lab",
        blocks=[
            BadgeBlock(text="ICLR 2026", variant="primary"),
            BadgeBlock(text="Oral Presentation", variant="accent"),
        ],
    )

    layout = generate_layout(slide, validate=True, strict=True)
    assert layout.slide_id == "slide_1"
    assert layout.visual_intent == VisualIntent.TITLE_HERO

    # Must contain title, subtitle, and 2 badges
    title_el = layout.get_element("slide_1_title_hero")
    assert title_el is not None
    assert title_el.element_type == ElementType.TEXT
    assert title_el.geometry.y >= 40.0

    sub_el = layout.get_element("slide_1_subtitle")
    assert sub_el is not None
    assert sub_el.element_type == ElementType.TEXT
    assert sub_el.geometry.y > title_el.geometry.bottom

    badges = layout.get_elements_by_type(ElementType.BADGE)
    assert len(badges) == 2
    for b in badges:
        assert b.geometry.y > sub_el.geometry.bottom


def test_pipeline_architecture_synthesis():
    slide = SlideSpec(
        index=4,
        slide_type=SlideType.METHOD_OVERVIEW,
        visual_intent=VisualIntent.PIPELINE_ARCHITECTURE,
        title="Framework Architecture & Dataflow",
        subtitle="End-to-end multi-agent orchestration pipeline",
        blocks=[
            TextBlock(content="Stage 1: Ingestion and parsing of unstructured PDF tokens"),
            TextBlock(content="Stage 2: Deterministic semantic contract synthesis"),
            TextBlock(content="Stage 3: Spatial constraint solving and geometry engine"),
            FigureBlock(
                source_figure_id="figure1",
                caption="System architecture of the end-to-end presentation compiler",
                xref_label="Figure 1",
            ),
        ],
    )

    layout = generate_layout(slide, validate=True, strict=True)
    assert layout.slide_id == "slide_4"

    fig_elements = layout.get_elements_by_type(ElementType.FIGURE)
    assert len(fig_elements) == 1
    fig = fig_elements[0]
    assert fig.content["source_figure_id"] == "figure1"

    # Verify left text elements do not overlap with right figure
    text_elements = [
        el for el in layout.elements
        if el.element_type == ElementType.TEXT and el.source_block_id.startswith("text_")
    ]
    assert len(text_elements) == 3
    for t in text_elements:
        assert t.geometry.right <= fig.geometry.x


def test_benchmark_comparison_synthesis():
    slide = SlideSpec(
        index=7,
        slide_type=SlideType.RESULT,
        visual_intent=VisualIntent.BENCHMARK_COMPARISON,
        title="Benchmark Performance Evaluation",
        subtitle="Comparison against SOTA multi-modal LLM baselines",
        blocks=[
            TableBlock(
                source_table_id="table1",
                caption="Accuracy and latency across benchmark datasets",
                xref_label="Table 1",
            ),
            TextBlock(content="Our approach achieves 94.2% accuracy (+8.5% over Baseline).", emphasis=True),
            TextBlock(content="Inference latency is reduced by 3.2x via deterministic constraints."),
        ],
    )

    layout = generate_layout(slide, validate=True, strict=True)
    table_elements = layout.get_elements_by_type(ElementType.TABLE)
    assert len(table_elements) == 1
    tbl = table_elements[0]
    assert tbl.content["source_table_id"] == "table1"

    takeaways = [
        el for el in layout.elements
        if el.element_type == ElementType.TEXT and el.source_block_id.startswith("text_")
    ]
    assert len(takeaways) == 2
    for tw in takeaways:
        assert tw.geometry.x >= tbl.geometry.right


def test_two_column_contrast_synthesis():
    slide = SlideSpec(
        index=3,
        slide_type=SlideType.PROBLEM,
        visual_intent=VisualIntent.TWO_COLUMN_CONTRAST,
        title="Limitations of Current Paradigms",
        subtitle="Traditional end-to-end generation vs structured intermediate representations",
        blocks=[
            TextBlock(content="Existing LLM slide tools generate unconstrained raster coordinates.", column="left"),
            TextBlock(content="High frequency of element overlapping and typography clipping.", column="left"),
            TextBlock(content="Our pipeline enforces formal geometry and constraint solving.", column="right", emphasis=True),
            TextBlock(content="Guarantees 100% boundary safety and zero collision artifacts.", column="right", emphasis=True),
        ],
    )

    layout = generate_layout(slide, validate=True, strict=True)
    left_els = [el for el in layout.elements if "left_col" in el.element_id]
    right_els = [el for el in layout.elements if "right_col" in el.element_id]

    assert len(left_els) == 2
    assert len(right_els) == 2

    # Left items stay on left half, right items stay on right half
    for l in left_els:
        assert l.geometry.right <= 656.0
    for r in right_els:
        assert r.geometry.x >= 656.0


def test_key_takeaway_list_synthesis():
    slide = SlideSpec(
        index=10,
        slide_type=SlideType.CONCLUSION,
        visual_intent=VisualIntent.KEY_TAKEAWAY_LIST,
        title="Conclusion & Key Takeaways",
        subtitle="Summary of core findings and research impact",
        blocks=[
            TextBlock(content="First formal semantic-to-geometry decoupled pipeline for academic decks.", emphasis=True),
            TextBlock(content="Deterministic constraint validation eliminates visual layout artifacts."),
            TextBlock(content="Extensible architecture ready for multi-modal rendering backends."),
        ],
    )

    layout = generate_layout(slide, validate=True, strict=True)
    cards = [el for el in layout.elements if "takeaway_card" in el.element_id]
    assert len(cards) == 3

    # Verify vertical ordering and clearance
    assert cards[1].geometry.y >= cards[0].geometry.bottom
    assert cards[2].geometry.y >= cards[1].geometry.bottom


def test_metric_card_grid_synthesis_3_items():
    slide = SlideSpec(
        index=9,
        slide_type=SlideType.RESULT,
        visual_intent=VisualIntent.METRIC_CARD_GRID,
        title="Key Performance Metrics",
        subtitle="Across diverse evaluation benchmarks",
        blocks=[
            TextBlock(content="+12.4% Accuracy Improvement", emphasis=True),
            TextBlock(content="3.2x Throughput Acceleration", emphasis=True),
            TextBlock(content="-45% GPU Memory Footprint", emphasis=False),
        ],
    )

    layout = generate_layout(slide, validate=True, strict=True)
    cards = [el for el in layout.elements if "metric_card" in el.element_id]
    assert len(cards) == 3
    # 3 horizontal columns side by side
    assert cards[0].geometry.right <= cards[1].geometry.x
    assert cards[1].geometry.right <= cards[2].geometry.x


def test_metric_card_grid_synthesis_4_items_grid():
    slide = SlideSpec(
        index=9,
        slide_type=SlideType.RESULT,
        visual_intent=VisualIntent.METRIC_CARD_GRID,
        title="Comprehensive System Metrics",
        blocks=[
            TextBlock(content="Latency: 42ms"),
            TextBlock(content="Precision: 98.1%"),
            TextBlock(content="Recall: 96.4%"),
            TextBlock(content="F1 Score: 97.2%"),
        ],
    )

    layout = generate_layout(slide, validate=True, strict=True)
    grid_cards = [el for el in layout.elements if "grid_card" in el.element_id]
    assert len(grid_cards) == 4

    # Top row
    assert grid_cards[0].geometry.y == grid_cards[1].geometry.y
    assert grid_cards[0].geometry.right <= grid_cards[1].geometry.x
    # Bottom row below top row
    assert grid_cards[2].geometry.y >= grid_cards[0].geometry.bottom
    assert grid_cards[3].geometry.y >= grid_cards[1].geometry.bottom


def test_pipeline_architecture_fallback_no_figures():
    slide = SlideSpec(
        index=4,
        slide_type=SlideType.METHOD_OVERVIEW,
        visual_intent=VisualIntent.PIPELINE_ARCHITECTURE,
        title="Method Pipeline Without Figures",
        blocks=[
            TextBlock(content="Stage A: Tokenization"),
            TextBlock(content="Stage B: Semantic Mapping"),
            TextBlock(content="Stage C: Layout Synthesis"),
        ],
    )

    layout = generate_layout(slide, validate=True, strict=True)
    stages = [el for el in layout.elements if "stage_" in el.element_id]
    assert len(stages) == 3
    assert stages[1].geometry.y >= stages[0].geometry.bottom
    assert stages[2].geometry.y >= stages[1].geometry.bottom


def test_benchmark_comparison_fallback_no_assets():
    slide = SlideSpec(
        index=8,
        slide_type=SlideType.RESULT,
        visual_intent=VisualIntent.BENCHMARK_COMPARISON,
        title="Results Summary Without Assets",
        blocks=[
            TextBlock(content="Insight 1: Consistent outperformance"),
            TextBlock(content="Insight 2: Minimal latency degradation"),
        ],
    )

    layout = generate_layout(slide, validate=True, strict=True)
    results = [el for el in layout.elements if "result_" in el.element_id]
    assert len(results) == 2
    assert results[1].geometry.y >= results[0].geometry.bottom


def test_takeaway_list_fallback_empty_blocks_valid_role():
    # When blocks is completely empty, fallback TextBlock must construct with valid BlockRole
    slide = SlideSpec(
        index=11,
        slide_type=SlideType.CONCLUSION,
        visual_intent=VisualIntent.KEY_TAKEAWAY_LIST,
        title="Empty Blocks Slide",
        blocks=[],
    )

    layout = generate_layout(slide, validate=True, strict=True)
    assert len(layout.elements) >= 2  # header title + fallback card
    fallback_card = layout.get_element("slide_11_takeaway_card_1")
    assert fallback_card is not None
    assert fallback_card.role == BlockRole.BULLET_ITEM
    assert fallback_card.content == "Empty Blocks Slide"


def test_card_overflow_protection_many_items():
    # 8 takeaway items must fit within canvas without bottom overflow
    slide = SlideSpec(
        index=10,
        slide_type=SlideType.CONCLUSION,
        visual_intent=VisualIntent.KEY_TAKEAWAY_LIST,
        title="High Density Takeaways",
        blocks=[TextBlock(content=f"Item {i + 1}: Detailed finding description") for i in range(8)],
    )

    layout = generate_layout(slide, validate=True, strict=True)
    cards = [el for el in layout.elements if "takeaway_card" in el.element_id]
    assert len(cards) == 8
    for c in cards:
        assert c.geometry.y >= 0
        assert c.geometry.bottom <= 720.0


def test_two_column_overflow_protection_many_items():
    # 8 items per column
    blocks = []
    for i in range(8):
        blocks.append(TextBlock(content=f"Left {i+1}", column="left"))
        blocks.append(TextBlock(content=f"Right {i+1}", column="right"))

    slide = SlideSpec(
        index=6,
        slide_type=SlideType.PROBLEM,
        visual_intent=VisualIntent.TWO_COLUMN_CONTRAST,
        title="High Density Contrast",
        blocks=blocks,
    )

    layout = generate_layout(slide, validate=True, strict=True)
    for el in layout.elements:
        assert el.geometry.bottom <= 720.0


def test_title_hero_badge_wrapping_many_badges():
    # 6 badges with longer text must wrap cleanly without exceeding canvas width
    slide = SlideSpec(
        index=1,
        slide_type=SlideType.TITLE,
        visual_intent=VisualIntent.TITLE_HERO,
        title="Scalable Multi-Agent Systems in Computer Vision",
        subtitle="Julian He, AI Research Institute",
        blocks=[
            BadgeBlock(text="ICLR 2026 Conference"),
            BadgeBlock(text="Oral Presentation Award"),
            BadgeBlock(text="Outstanding Paper Track"),
            BadgeBlock(text="Workshop on Autonomous Reasoning"),
            BadgeBlock(text="Benchmark Challenge Winner"),
            BadgeBlock(text="Open Source Release"),
        ],
    )

    layout = generate_layout(slide, validate=True, strict=True)
    badges = layout.get_elements_by_type(ElementType.BADGE)
    assert len(badges) == 6
    for b in badges:
        assert b.geometry.x >= 0
        assert b.geometry.right <= 1280.0


def test_secondary_visual_assets_are_not_silently_omitted():
    slide = SlideSpec(
        index=5,
        slide_type=SlideType.METHOD_DETAIL,
        visual_intent=VisualIntent.PIPELINE_ARCHITECTURE,
        title="Multi-Asset Pipeline",
        blocks=[
            TextBlock(content="Stage 1"),
            FigureBlock(source_figure_id="fig_primary", caption="Primary fig"),
            FigureBlock(source_figure_id="fig_secondary", caption="Secondary fig"),
            TableBlock(source_table_id="tbl_extra", caption="Extra table"),
        ],
    )

    layout = generate_layout(slide, validate=True, strict=True)
    assert "omitted_blocks" not in layout.metadata
    figure_refs = {
        el.source_block_id for el in layout.get_elements_by_type(ElementType.FIGURE)
    }
    table_refs = {
        el.source_block_id for el in layout.get_elements_by_type(ElementType.TABLE)
    }
    assert figure_refs == {"fig_primary", "fig_secondary"}
    assert table_refs == {"tbl_extra"}


def test_text_intent_slide_with_visual_assets_is_promoted_not_dropped():
    slide = SlideSpec(
        index=7,
        slide_type=SlideType.BACKGROUND,
        visual_intent=VisualIntent.KEY_TAKEAWAY_LIST,
        title="Figure on a text intent",
        blocks=[
            TextBlock(content="Key point"),
            FigureBlock(source_figure_id="fig_orphan", caption="Orphan fig"),
        ],
    )
    layout = generate_layout(slide, validate=True)
    figure_refs = {
        el.source_block_id for el in layout.get_elements_by_type(ElementType.FIGURE)
    }
    assert figure_refs == {"fig_orphan"}


def test_text_intent_slide_with_table_is_promoted_not_dropped():
    slide = SlideSpec(
        index=8,
        slide_type=SlideType.BACKGROUND,
        visual_intent=VisualIntent.TWO_COLUMN_CONTRAST,
        title="Table on a text intent",
        blocks=[
            TextBlock(content="Key point"),
            TableBlock(source_table_id="tbl_orphan", caption="Orphan table"),
        ],
    )
    layout = generate_layout(slide, validate=True)
    table_refs = {
        el.source_block_id for el in layout.get_elements_by_type(ElementType.TABLE)
    }
    assert table_refs == {"tbl_orphan"}


def test_validation_metadata_recorded_on_strict_false():
    slide = SlideSpec(
        index=2,
        slide_type=SlideType.BACKGROUND,
        visual_intent=VisualIntent.KEY_TAKEAWAY_LIST,
        title="Valid Slide",
        blocks=[TextBlock(content="Normal point")],
    )

    layout = generate_layout(slide, validate=True, strict=False)
    assert "validation" in layout.metadata
    assert layout.metadata["validation"]["is_valid"] is True
    assert isinstance(layout.metadata["validation"]["errors"], list)
    assert isinstance(layout.metadata["validation"]["warnings"], list)


def test_custom_canvas_resolution_scaling():
    from backend.layout.schema import Canvas

    canvas_fhd = Canvas(width=1920.0, height=1080.0)
    slide = SlideSpec(
        index=1,
        slide_type=SlideType.TITLE,
        visual_intent=VisualIntent.TITLE_HERO,
        title="1080p Resolution Slide",
        blocks=[BadgeBlock(text="FHD Preview")],
    )

    layout = generate_layout(slide, canvas=canvas_fhd, validate=True, strict=True)
    assert layout.canvas.width == 1920.0
    assert layout.canvas.height == 1080.0
    for el in layout.elements:
        assert el.geometry.right <= 1920.0
        assert el.geometry.bottom <= 1080.0


