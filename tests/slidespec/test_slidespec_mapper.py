"""Tests for PresentationPlan to SlideSpec Mapper (PR9)."""

from pathlib import Path

from backend.paper import extract_paper
from backend.presentation import generate_presentation_plan
from backend.presentation.schema import SlideType
from backend.slidespec import (
    DeckSpec,
    SlideSpec,
    VisualIntent,
    map_presentation_plan_to_deck_spec,
    map_slide_plan_to_slide_spec,
)

FIXTURE_PDF = Path("tests/fixtures/paper/anomaly_agent.pdf")


def test_mapper_title_slide():
    paper = extract_paper(FIXTURE_PDF)
    plan = generate_presentation_plan(paper, profile="research_15min")
    title_plan = plan.slides[0]

    slide_spec = map_slide_plan_to_slide_spec(title_plan, paper)
    assert slide_spec.slide_type == SlideType.TITLE
    assert slide_spec.visual_intent == VisualIntent.TITLE_HERO
    assert len(slide_spec.get_blocks_by_kind("badge")) >= 1
    # Check that authors is placed in subtitle and not duplicated across bullet blocks
    assert slide_spec.subtitle is not None
    assert "Researcher" in slide_spec.subtitle

    # Ensure metadata lines like "Paper:" or "Presented by:" do not clutter blocks
    for b in slide_spec.get_blocks_by_kind("text"):
        assert not b.content.lower().startswith("paper:")
        assert not b.content.lower().startswith("presented by:")


def test_mapper_method_detail_slide_preserves_figures():
    """Verify that when a METHOD_DETAIL slide has source_figures, FigureBlocks are created."""
    from backend.presentation.schema import SlidePlan

    detail_plan = SlidePlan(
        index=7,
        slide_type=SlideType.METHOD_DETAIL,
        title="Core Mechanism",
        objective="Explain algorithmic formulation",
        key_messages=["Loss function details", "Policy gradient steps"],
        source_sections=["4"],
        source_figures=["figure2"],
        source_tables=[],
    )
    paper = extract_paper(FIXTURE_PDF)
    slide_spec = map_slide_plan_to_slide_spec(detail_plan, paper)

    assert slide_spec.visual_intent == VisualIntent.PIPELINE_ARCHITECTURE
    figs = slide_spec.get_blocks_by_kind("figure")
    assert len(figs) == 1
    assert figs[0].source_figure_id == "figure2"
    assert "Fig. 2" in figs[0].xref_label or "2" in figs[0].xref_label


def test_mapper_two_column_contrast_sets_columns():
    """Verify that TWO_COLUMN_CONTRAST slides partition items into left and right columns."""
    from backend.presentation.schema import SlidePlan

    prob_plan = SlidePlan(
        index=3,
        slide_type=SlideType.PROBLEM,
        title="Problem Definition",
        objective="Contrast challenges against assumptions",
        key_messages=["Bottleneck 1", "Bottleneck 2", "Bottleneck 3", "Bottleneck 4"],
        source_sections=["3"],
    )
    slide_spec = map_slide_plan_to_slide_spec(prob_plan)
    assert slide_spec.visual_intent == VisualIntent.TWO_COLUMN_CONTRAST

    text_blocks = slide_spec.get_blocks_by_kind("text")
    left_blocks = [b for b in text_blocks if getattr(b, "column", None) == "left"]
    right_blocks = [b for b in text_blocks if getattr(b, "column", None) == "right"]

    assert len(left_blocks) >= 1
    assert len(right_blocks) >= 1
    assert len(left_blocks) + len(right_blocks) == 4


def test_mapper_empty_key_messages_falls_back_to_objective():
    """Verify that slides with empty key_messages cleanly fallback to slide.objective."""
    from backend.presentation.schema import SlidePlan

    overview_empty = SlidePlan(
        index=6,
        slide_type=SlideType.METHOD_OVERVIEW,
        title="Empty Messages Method",
        objective="Explain complete framework architecture",
        key_messages=[],
        source_sections=["4"],
        source_figures=["figure1"],
    )
    slide_spec = map_slide_plan_to_slide_spec(overview_empty)
    texts = slide_spec.get_blocks_by_kind("text")
    assert len(texts) == 1
    assert texts[0].content == "Explain complete framework architecture"


def test_mapper_method_overview_slide():
    paper = extract_paper(FIXTURE_PDF)
    plan = generate_presentation_plan(paper, profile="research_15min")
    overview_plan = plan.get_slides_by_type(SlideType.METHOD_OVERVIEW)[0]

    slide_spec = map_slide_plan_to_slide_spec(overview_plan, paper)
    assert slide_spec.slide_type == SlideType.METHOD_OVERVIEW
    assert slide_spec.visual_intent == VisualIntent.PIPELINE_ARCHITECTURE

    figs = slide_spec.get_blocks_by_kind("figure")
    assert len(figs) == 1
    assert figs[0].source_figure_id == "figure1"
    assert "Overview" in figs[0].caption or len(figs[0].caption) > 0


def test_mapper_result_slide():
    paper = extract_paper(FIXTURE_PDF)
    plan = generate_presentation_plan(paper, profile="research_15min")
    result_plan = plan.get_slides_by_type(SlideType.RESULT)[0]

    slide_spec = map_slide_plan_to_slide_spec(result_plan, paper)
    assert slide_spec.slide_type == SlideType.RESULT
    assert slide_spec.visual_intent == VisualIntent.BENCHMARK_COMPARISON

    # Has table or figure block
    tabs = slide_spec.get_blocks_by_kind("table")
    figs = slide_spec.get_blocks_by_kind("figure")
    assert len(tabs) > 0 or len(figs) > 0
    badges = slide_spec.get_blocks_by_kind("badge")
    assert len(badges) >= 1


def test_mapper_experiment_setup_preserves_tables_and_figures():
    """Verify that EXPERIMENT_SETUP slides preserve table and figure assets."""
    from backend.presentation.schema import SlidePlan

    setup_plan = SlidePlan(
        index=9,
        slide_type=SlideType.EXPERIMENT_SETUP,
        title="Benchmark Setup",
        objective="Explain datasets and evaluation protocol",
        key_messages=["MVTec-AD dataset benchmark", "Standard evaluation metrics"],
        source_sections=["5"],
        source_figures=["figure3"],
        source_tables=["table1"],
    )
    paper = extract_paper(FIXTURE_PDF)
    slide_spec = map_slide_plan_to_slide_spec(setup_plan, paper)

    assert slide_spec.visual_intent == VisualIntent.BENCHMARK_COMPARISON
    tabs = slide_spec.get_blocks_by_kind("table")
    figs = slide_spec.get_blocks_by_kind("figure")
    assert len(tabs) == 1
    assert len(figs) == 1
    assert tabs[0].source_table_id == "table1"
    assert figs[0].source_figure_id == "figure3"


def test_mapper_method_detail_preserves_both_figures_and_tables():
    """Verify METHOD_DETAIL simultaneously generates both FigureBlock and TableBlock."""
    from backend.presentation.schema import SlidePlan

    detail_plan = SlidePlan(
        index=8,
        slide_type=SlideType.METHOD_DETAIL,
        title="Algorithmic Formulation",
        objective="Explain training details and algorithm steps",
        key_messages=["Policy loss formulation", "Hyperparameter table"],
        source_sections=["4"],
        source_figures=["figure2"],
        source_tables=["table2"],
    )
    paper = extract_paper(FIXTURE_PDF)
    slide_spec = map_slide_plan_to_slide_spec(detail_plan, paper)

    figs = slide_spec.get_blocks_by_kind("figure")
    tabs = slide_spec.get_blocks_by_kind("table")
    assert len(figs) == 1
    assert len(tabs) == 1
    assert figs[0].source_figure_id == "figure2"
    assert tabs[0].source_table_id == "table2"


def test_mapper_contrast_single_message_falls_back_to_takeaway_list():
    """Verify that contrast slides with < 2 key_messages do not produce empty right columns."""
    from backend.presentation.schema import SlidePlan

    contrast_single = SlidePlan(
        index=4,
        slide_type=SlideType.PROBLEM,
        title="Single Problem",
        objective="Core bottleneck",
        key_messages=["Only one bottleneck"],
        source_sections=["3"],
    )
    slide_spec = map_slide_plan_to_slide_spec(contrast_single)
    assert slide_spec.visual_intent == VisualIntent.KEY_TAKEAWAY_LIST
    text_blocks = slide_spec.get_blocks_by_kind("text")
    for b in text_blocks:
        assert getattr(b, "column", None) is None


def test_mapper_title_filters_academic_presentation_fallback():
    """Verify fallback string 'Academic Presentation' is cleanly filtered on title slides."""
    from backend.presentation.schema import SlidePlan

    title_plan = SlidePlan(
        index=1,
        slide_type=SlideType.TITLE,
        title="Sample Paper",
        objective="Title slide",
        key_messages=[
            "Paper: Sample Paper",
            "Presented by: Alice, Bob",
            "Academic Presentation",
            "Novel self-supervised paradigm for computer vision",
        ],
    )
    slide_spec = map_slide_plan_to_slide_spec(title_plan)
    for b in slide_spec.get_blocks_by_kind("text"):
        assert "academic presentation" not in b.content.lower()
        assert not b.content.lower().startswith("paper:")


def test_mapper_full_deck():
    paper = extract_paper(FIXTURE_PDF)
    plan = generate_presentation_plan(paper, profile="research_15min")
    deck_spec = map_presentation_plan_to_deck_spec(plan, paper)

    assert isinstance(deck_spec, DeckSpec)
    assert deck_spec.slide_count == 12
    assert deck_spec.title == plan.title

    for i, slide in enumerate(deck_spec.slides, start=1):
        assert slide.index == i
        assert len(slide.blocks) > 0
        assert slide.provenance is not None
