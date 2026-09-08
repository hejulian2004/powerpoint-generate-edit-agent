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
    assert len(slide_spec.get_blocks_by_kind("text")) >= 1


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
