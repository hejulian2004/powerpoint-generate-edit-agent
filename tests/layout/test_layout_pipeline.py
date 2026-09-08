"""End-to-End Pipeline Integration Test (PR10).

Validates the full chain:
PDF -> PaperIR -> PresentationPlan -> DeckSpec -> DeckLayoutSpec -> Validator -> JSON Roundtrip
"""

from pathlib import Path

from backend.layout import DeckLayoutSpec, generate_deck_layout, validate_layout
from backend.paper import extract_paper
from backend.presentation import generate_presentation_plan
from backend.slidespec import map_presentation_plan_to_deck_spec

FIXTURE_PDF = Path("tests/fixtures/paper/anomaly_agent.pdf")


def test_full_pipeline_to_deck_layout(tmp_path: Path):
    # Step 1: PDF -> PaperIR
    paper = extract_paper(FIXTURE_PDF)
    assert paper.title != ""

    # Step 2: PaperIR -> PresentationPlan
    plan = generate_presentation_plan(paper, profile="research_15min")
    assert plan.slide_count == 12

    # Step 3: PresentationPlan -> DeckSpec (PR9)
    deck_spec = map_presentation_plan_to_deck_spec(plan, paper)
    assert deck_spec.slide_count == 12

    # Step 4: DeckSpec -> DeckLayoutSpec (PR10)
    deck_layout = generate_deck_layout(deck_spec, validate=True, strict=True)
    assert deck_layout.slide_count == 12
    assert deck_layout.title == deck_spec.title

    # Verify every slide layout is strictly valid and collision-free
    for slide_layout in deck_layout.slides:
        report = validate_layout(slide_layout, strict=True)
        assert report.is_valid is True
        assert len(report.errors) == 0

        # Assert at least 1 element and all within canvas
        assert len(slide_layout.elements) >= 1
        for el in slide_layout.elements:
            assert el.geometry.x >= 0
            assert el.geometry.y >= 0
            assert el.geometry.right <= deck_layout.canvas.width
            assert el.geometry.bottom <= deck_layout.canvas.height

    # Step 5: JSON Serialization and Roundtrip
    out_file = tmp_path / "deck_layout_spec.json"
    deck_layout.to_json_file(out_file)
    assert out_file.exists()

    reloaded = DeckLayoutSpec.from_json_file(out_file)
    assert reloaded.slide_count == 12
    assert reloaded.title == deck_layout.title
    assert reloaded.model_dump() == deck_layout.model_dump()
