"""Real-World v2 Round-Trip Fidelity Benchmark (PR6.1 Task 4).

Runs the composite fidelity benchmark over business-archetype decks in
`tests/assets/real_world_v2/`. Unlike the v1 corpus, these decks are REQUIRED to pass:

    Composite Fidelity >= 90%  (per slide, FidelityEvaluator)

Every deck committed into this directory must genuinely round-trip at >= 90%; decks that
cannot are NOT committed here (they belong in the v1 corpus with a KNOWN_BOUNDARY xfail).
Provenance (original Apache POI source + sha256) is recorded in REAL_WORLD_V2_ORIGIN.md.

Guards (same as the v1 benchmark):
- Slide-count parity
- Element-count parity per slide (guards against silently dropped elements)
- Non-vacuous pass: a slide importing to zero elements does NOT count as a pass
"""

import glob
import os
from pathlib import Path
import pytest

from backend.ir import import_pptx, export_pptx
from backend.eval.fidelity import FidelityEvaluator

V2_DIR = Path(__file__).resolve().parent / "assets" / "real_world_v2"

# Archetype decks required by the PR6.1 acceptance criteria, with their original source.
EXPECTED_ARCHETYPES = {
    "corporate_template.pptx": "SampleShow.pptx",
    "research_presentation.pptx": "OverlappingRelations.pptx",
    "financial_report.pptx": "present1.pptx",
    "product_launch.pptx": "copy-slide-demo.pptx",
    "analytics_dashboard.pptx": "rain.pptx",
}


def _discover_v2_decks():
    if not V2_DIR.exists():
        return []
    decks = sorted(glob.glob(str(V2_DIR / "*.pptx")))
    return [d for d in decks if not os.path.basename(d).startswith("~$")]


_V2_DECKS = _discover_v2_decks()


@pytest.mark.real_world_v2
@pytest.mark.skipif(
    not _V2_DECKS,
    reason="Real-world v2 deck corpus not fetched. Run: python scripts/fetch_real_world_decks.py"
)
@pytest.mark.parametrize("deck_path", _V2_DECKS, ids=lambda p: os.path.basename(p))
def test_real_world_v2_deck_fidelity(deck_path: str, tmp_path: Path):
    """Each v2 archetype deck must round-trip at >= 90% composite fidelity."""
    deck_name = os.path.basename(deck_path)

    orig_pres = import_pptx(deck_path)
    assert len(orig_pres.slides) > 0, f"Deck {deck_path} has no slides"

    out_path = tmp_path / f"roundtrip_{deck_name}"
    export_pptx(orig_pres, str(out_path))
    assert out_path.exists()

    recon_pres = import_pptx(str(out_path))
    assert len(recon_pres.slides) == len(orig_pres.slides), (
        f"Slide count mismatch on {deck_path}: "
        f"{len(recon_pres.slides)} != {len(orig_pres.slides)}"
    )

    failures = []
    for orig_slide, recon_slide in zip(orig_pres.slides, recon_pres.slides):
        if len(orig_slide.elements) == 0:
            failures.append(f"slide '{orig_slide.id}' imported to 0 elements")
            continue
        if len(recon_slide.elements) != len(orig_slide.elements):
            failures.append(
                f"slide '{orig_slide.id}' element count mismatch "
                f"({len(recon_slide.elements)} != {len(orig_slide.elements)})"
            )
            continue
        score = FidelityEvaluator.evaluate_slides(orig_slide, recon_slide)
        if not score.passed or score.total < 90.0:
            failures.append(
                f"slide '{orig_slide.id}' fidelity {score.total}% < 90%: "
                f"geo={score.geometry:.1f} text={score.text:.1f} "
                f"style={score.style:.1f} visual={score.visual:.1f}"
            )

    assert not failures, f"Deck {deck_name} failed: {'; '.join(failures[:5])}"


@pytest.mark.real_world_v2
def test_real_world_v2_manifest_complete():
    """Every required archetype deck must be present in the corpus."""
    if not _V2_DECKS:
        pytest.skip("Real-world v2 deck corpus not fetched")
    names = {os.path.basename(d) for d in _V2_DECKS}
    missing = set(EXPECTED_ARCHETYPES) - names
    assert not missing, f"Missing v2 archetype decks: {sorted(missing)}"
    unexpected = names - set(EXPECTED_ARCHETYPES)
    assert not unexpected, f"Unexpected decks in real_world_v2: {sorted(unexpected)}"