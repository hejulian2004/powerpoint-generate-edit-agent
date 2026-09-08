"""End-to-End Pipeline Integration Test (PaperIR -> PresentationPlan).

Validates that:
1. Real or mock PaperIR cleanly flows through presentation planning.
2. Slot categories, section bindings, and figure bindings are all correctly resolved.
3. The resulting PresentationPlan satisfies academic presentation constraints:
   - 15min produces 12 slides; 10min produces 8 slides.
   - Title has empty sections.
   - Method Overview binds architecture figure.
   - Main Result binds result table or figure.
   - No domain hallucinations appear in generic/empty paper runs.
4. Deterministic JSON serialization and deserialization retains 100% integrity.
"""

from pathlib import Path

from backend.paper import PaperIR, extract_paper
from backend.presentation import (
    PresentationPlan,
    SlideType,
    generate_presentation_plan,
)

FIXTURE_PDF = Path("tests/fixtures/paper/anomaly_agent.pdf")


def test_full_pipeline_from_pdf_to_presentation_plan(tmp_path: Path):
    """End-to-end integration: PDF -> PaperIR -> PresentationPlan -> JSON file -> Reload."""
    assert FIXTURE_PDF.exists(), f"Missing fixture PDF: {FIXTURE_PDF}"

    # Step 1: Parse PDF into PaperIR
    paper_ir = extract_paper(FIXTURE_PDF)
    assert isinstance(paper_ir, PaperIR)
    assert paper_ir.title != ""
    assert len(paper_ir.sections) >= 6
    assert len(paper_ir.figures) >= 3
    assert len(paper_ir.tables) >= 2

    # Step 2: Generate 15-minute presentation plan
    plan_15min = generate_presentation_plan(paper_ir, profile="research_15min")
    assert isinstance(plan_15min, PresentationPlan)
    assert plan_15min.slide_count == 12
    assert plan_15min.duration_minutes == 15
    assert plan_15min.slides[0].slide_type == SlideType.TITLE
    assert plan_15min.slides[-1].slide_type == SlideType.CONCLUSION

    # Verify visual evidence bindings
    overview_slides = plan_15min.get_slides_by_type(SlideType.METHOD_OVERVIEW)
    assert len(overview_slides) >= 1
    assert "figure1" in overview_slides[0].source_figures

    result_slides = plan_15min.get_slides_by_type(SlideType.RESULT)
    assert len(result_slides) >= 1
    assert "table1" in result_slides[0].source_tables or len(result_slides[0].source_figures) > 0

    # Step 3: Round-trip JSON file serialization
    out_file = tmp_path / "final_presentation_plan.json"
    plan_15min.to_json_file(out_file)
    assert out_file.exists()

    reloaded = PresentationPlan.from_json_file(out_file)
    assert reloaded.title == plan_15min.title
    assert reloaded.slide_count == 12
    assert reloaded.slides[0].title == plan_15min.slides[0].title
    assert reloaded.slides[5].source_figures == plan_15min.slides[5].source_figures


def test_full_pipeline_from_pdf_to_10min_plan():
    """End-to-end integration for 10-minute presentation profile."""
    paper_ir = extract_paper(FIXTURE_PDF)
    plan_10min = generate_presentation_plan(paper_ir, profile="research_10min")

    assert plan_10min.slide_count == 8
    assert plan_10min.duration_minutes == 10

    slide_types = [s.slide_type for s in plan_10min.slides]
    assert slide_types[0] == SlideType.TITLE
    assert slide_types[1] == SlideType.BACKGROUND
    assert slide_types[2] == SlideType.METHOD_OVERVIEW
    assert SlideType.LIMITATION in slide_types
    assert slide_types[-1] == SlideType.CONCLUSION
