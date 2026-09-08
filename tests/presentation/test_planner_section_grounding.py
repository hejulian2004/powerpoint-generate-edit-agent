"""Tests for Planner Section Grounding and Consumption (PR7.2.1).

Validates that:
- TITLE slide does not bind body sections (source_sections is empty).
- METHOD_OVERVIEW and METHOD_DETAIL slides are strictly grounded in Method sections, not Introduction.
- RESULT and EXPERIMENT slides are grounded in Experiments sections.
- Sections are consumed in order without clustering indiscriminately on section 1.
"""

from pathlib import Path

from backend.paper.parser import extract_paper
from backend.presentation import SlideType, generate_presentation_plan

FIXTURE_PDF = Path("tests/fixtures/paper/anomaly_agent.pdf")


def test_title_slide_has_no_source_sections():
    paper = extract_paper(FIXTURE_PDF)
    plan = generate_presentation_plan(paper, profile="research_15min")
    title_slide = plan.slides[0]
    assert title_slide.slide_type == SlideType.TITLE
    assert title_slide.source_sections == []


def test_method_slides_grounded_in_method_not_intro():
    paper = extract_paper(FIXTURE_PDF)
    plan = generate_presentation_plan(paper, profile="research_15min")

    method_overview_slides = plan.get_slides_by_type(SlideType.METHOD_OVERVIEW)
    method_detail_slides = plan.get_slides_by_type(SlideType.METHOD_DETAIL)

    assert len(method_overview_slides) >= 1
    assert len(method_detail_slides) >= 1

    # In anomaly_agent.pdf: Section 1 is Introduction, Section 4 is Method
    for s in method_overview_slides + method_detail_slides:
        assert "1" not in s.source_sections, f"Method slide {s.index} erroneously grounded in Section 1 (Intro)"
        # Should be grounded in Method section '4'
        assert "4" in s.source_sections or any("method" in sec.lower() for sec in s.source_sections)


def test_result_slides_grounded_in_experiments():
    paper = extract_paper(FIXTURE_PDF)
    plan = generate_presentation_plan(paper, profile="research_15min")

    result_slides = plan.get_slides_by_type(SlideType.RESULT)
    assert len(result_slides) >= 1

    # In anomaly_agent.pdf: Section 5 is Experiments
    for s in result_slides:
        assert "1" not in s.source_sections
        assert "5" in s.source_sections or any("experiment" in sec.lower() for sec in s.source_sections)


def test_section_consumption_diversity():
    """Verify that multiple slides do not all collapse into section 1."""
    paper = extract_paper(FIXTURE_PDF)
    plan = generate_presentation_plan(paper, profile="research_15min")

    all_source_secs = [
        s.source_sections[0]
        for s in plan.slides
        if s.source_sections
    ]
    # Check that diverse sections are used (at least 4 distinct sections across the deck)
    distinct_secs = set(all_source_secs)
    assert len(distinct_secs) >= 4
    # Introduction should only appear for background / context slides
    intro_count = all_source_secs.count("1")
    assert intro_count <= 2


def test_planner_fallbacks_have_no_domain_hallucinations():
    """Verify that an empty or generic non-RL paper produces no RL/anomaly/simulation domain keywords."""
    from backend.paper.schema import PaperIR, PaperMetadata
    from backend.presentation import generate_presentation_plan

    generic_paper = PaperIR(
        source_filename="transformer_attention.pdf",
        metadata=PaperMetadata(
            title="Attention Is All You Need",
            authors=["A. Vaswani", "N. Shazeer"],
            venue="NeurIPS 2017",
            page_count=10,
        ),
        abstract="",
        sections=[],
        figures=[],
        tables=[],
    )

    plan = generate_presentation_plan(generic_paper, profile="research_15min")
    assert plan.slide_count == 12

    # Check that domain-specific keywords never appear anywhere in key_messages
    forbidden_terms = [
        "reinforcement learning",
        "anomaly",
        "simulation",
        "simulator",
        "industrial inspection",
        "reward shaping",
    ]

    for slide in plan.slides:
        for msg in slide.key_messages:
            msg_lower = msg.lower()
            for term in forbidden_terms:
                assert term not in msg_lower, (
                    f"Domain hallucination '{term}' detected on slide {slide.index} ({slide.slide_type}): '{msg}'"
                )

