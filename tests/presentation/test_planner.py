"""Tests for Research Presentation Planner (PR7.2)."""

import json
from pathlib import Path

import pytest

from backend.paper.parser import extract_paper
from backend.presentation import (
    PresentationPlan,
    SlideType,
    generate_presentation_plan,
)

FIXTURE_PDF = Path("tests/fixtures/paper/anomaly_agent.pdf")


def test_generate_15min_presentation_plan():
    paper = extract_paper(FIXTURE_PDF)
    plan = generate_presentation_plan(paper, profile="research_15min")

    assert isinstance(plan, PresentationPlan)
    assert plan.slide_count == 12
    assert plan.duration_minutes == 15
    assert plan.profile == "research_15min"
    assert "AnomalyAgent" in plan.title

    # Check slide sequence
    slides = plan.slides
    assert slides[0].slide_type == SlideType.TITLE
    assert slides[0].index == 1
    assert slides[1].slide_type == SlideType.BACKGROUND
    assert slides[-1].slide_type == SlideType.CONCLUSION
    assert slides[-1].index == 12

    # Check Method Overview has figure1
    overview_slides = plan.get_slides_by_type(SlideType.METHOD_OVERVIEW)
    assert len(overview_slides) >= 1
    assert "figure1" in overview_slides[0].source_figures

    # Check Result slide has source tables or figures
    result_slides = plan.get_slides_by_type(SlideType.RESULT)
    assert len(result_slides) >= 1
    assert len(result_slides[0].source_tables) > 0 or len(result_slides[0].source_figures) > 0

    # Verify each slide has valid key messages
    for s in slides:
        assert len(s.key_messages) >= 2
        for km in s.key_messages:
            assert len(km.strip()) > 0


def test_generate_10min_presentation_plan():
    paper = extract_paper(FIXTURE_PDF)
    plan = generate_presentation_plan(paper, profile="research_10min")

    assert isinstance(plan, PresentationPlan)
    assert plan.slide_count == 8
    assert plan.duration_minutes == 10
    assert plan.profile == "research_10min"

    types = [s.slide_type for s in plan.slides]
    assert types[0] == SlideType.TITLE
    assert types[-1] == SlideType.CONCLUSION
    assert SlideType.METHOD_OVERVIEW in types
    assert SlideType.LIMITATION in types


def test_deterministic_plan_generation():
    """Running generate_presentation_plan on the same PaperIR yields identical results."""
    paper = extract_paper(FIXTURE_PDF)
    plan1 = generate_presentation_plan(paper, profile="research_15min")
    plan2 = generate_presentation_plan(paper, profile="research_15min")

    assert plan1.model_dump() == plan2.model_dump()


def test_enrich_flag_without_live_key_degrades_gracefully():
    """enrich=True with mock or missing key leaves plan completely intact without crash."""
    paper = extract_paper(FIXTURE_PDF)
    plan_clean = generate_presentation_plan(paper, profile="research_15min", enrich=False)
    plan_enriched = generate_presentation_plan(paper, profile="research_15min", enrich=True)

    assert plan_clean.slide_count == plan_enriched.slide_count
    assert plan_clean.slides[0].title == plan_enriched.slides[0].title
