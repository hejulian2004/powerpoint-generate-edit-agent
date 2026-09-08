"""End-to-End Pipeline Integration Test (PDF -> PaperIR -> PresentationPlan -> DeckSpec -> JSON)."""

from pathlib import Path

from backend.paper import extract_paper
from backend.presentation import generate_presentation_plan
from backend.slidespec import DeckSpec, VisualIntent, map_presentation_plan_to_deck_spec

FIXTURE_PDF = Path("tests/fixtures/paper/anomaly_agent.pdf")


def test_full_pipeline_to_deck_spec(tmp_path: Path):
    # Step 1: PDF -> PaperIR
    paper = extract_paper(FIXTURE_PDF)
    assert paper.title != ""

    # Step 2: PaperIR -> PresentationPlan
    plan = generate_presentation_plan(paper, profile="research_15min")
    assert plan.slide_count == 12

    # Step 3: PresentationPlan -> DeckSpec
    deck = map_presentation_plan_to_deck_spec(plan, paper)
    assert deck.slide_count == 12
    assert deck.title == plan.title

    # Verify visual intents diversity
    intents = {s.visual_intent for s in deck.slides}
    assert VisualIntent.TITLE_HERO in intents
    assert VisualIntent.PIPELINE_ARCHITECTURE in intents
    assert VisualIntent.BENCHMARK_COMPARISON in intents
    assert VisualIntent.TWO_COLUMN_CONTRAST in intents
    assert VisualIntent.KEY_TAKEAWAY_LIST in intents

    # Step 4: JSON Roundtrip
    out_file = tmp_path / "deck_spec.json"
    deck.to_json_file(out_file)
    assert out_file.exists()

    reloaded = DeckSpec.from_json_file(out_file)
    assert reloaded.slide_count == 12
    assert reloaded.title == deck.title
    assert reloaded.model_dump() == deck.model_dump()
