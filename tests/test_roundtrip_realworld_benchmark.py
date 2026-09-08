"""Real-World PPTX Round-Trip Fidelity Benchmark (PR6.1).

Runs the same quantitative fidelity benchmark as `test_roundtrip_benchmark.py` but over
genuine, third-party PPTX decks in `tests/assets/real_world/`. These decks are NOT authored
by this repository's generators, so a passing score is not self-referential.

Fetched via `scripts/fetch_real_world_decks.py` (Apache-2.0, see REAL_WORLD_ORIGIN.md).
Skipped when the corpus has not been fetched, so CI stays green before acquisition.

Guards:
- Slide-count parity
- Element-count parity per slide (guards against silently dropped elements)
- Non-vacuous pass: a slide that imports to zero elements must NOT count as a pass
- Composite FidelityScore >= 90.0 (FidelityEvaluator `passed`)

Decks that cannot yet reach >= 90 (or that import to zero elements because the feature is
not covered by the OOXML layer) are documented as KNOWN_BOUNDARY and marked xfail, so the
coverage gap is explicit and does not silently inflate the benchmark.
"""

import glob
import os
from pathlib import Path
import pytest

from backend.ir import import_pptx, export_pptx
from backend.eval.fidelity import FidelityEvaluator

REAL_WORLD_DIR = Path(__file__).resolve().parent / "assets" / "real_world"

# Decks that genuinely round-trip at >= 90% today.
PASSING = {
    "backgrounds.pptx",
}

# Decks that currently fail fidelity because the OOXML layer does not yet cover the
# feature that drives the loss. Reasons document the known coverage boundary.
KNOWN_BOUNDARY = {
    "SmartArt.pptx": "SmartArt graphic dropped on import (0 elements) - SmartArt coverage deferred (PR7/PR8)",
    "chart-slide-bg.pptx": "Chart dropped on import (0 elements) - chart coverage deferred (PR7/PR8)",
    "table-with-theme.pptx": "Table dropped on import (0 elements) - table round-trip coverage pending",
    "aascu.org_hbcu_leadershipsummit_cooper_.pptx": "Real 16-slide deck loses placeholder/shape elements on round-trip - master/placeholder coverage deferred",
    "placeholder-layout-color.pptx": "Placeholder element not reconstructed - master/layout coverage deferred",
    "sample_pptx_grouping_issues.pptx": "Nested group children not preserved on round-trip - group coverage pending",
    "themes.pptx": "Theme-inherited shapes dropped on round-trip - theme/master coverage deferred",
}


def _discover_real_decks():
    if not REAL_WORLD_DIR.exists():
        return []
    decks = sorted(glob.glob(str(REAL_WORLD_DIR / "*.pptx")))
    return [d for d in decks if not os.path.basename(d).startswith("~$")]


_REAL_DECKS = _discover_real_decks()


@pytest.mark.real_world
@pytest.mark.skipif(
    not _REAL_DECKS,
    reason="Real-world deck corpus not fetched. Run: python scripts/fetch_real_world_decks.py"
)
@pytest.mark.parametrize("deck_path", _REAL_DECKS, ids=lambda p: os.path.basename(p))
def test_real_world_deck_fidelity(deck_path: str, tmp_path: Path):
    """Round-trip each real deck through import/export and verify composite fidelity."""
    deck_name = os.path.basename(deck_path)

    # 1. Import original to IR
    orig_pres = import_pptx(deck_path)
    assert len(orig_pres.slides) > 0, f"Deck {deck_path} has no slides"

    # 2. Export IR to temporary round-trip PPTX
    out_path = tmp_path / f"roundtrip_{deck_name}"
    export_pptx(orig_pres, str(out_path))
    assert out_path.exists()

    # 3. Re-import round-trip PPTX to IR
    recon_pres = import_pptx(str(out_path))
    assert len(recon_pres.slides) == len(orig_pres.slides), (
        f"Slide count mismatch on {deck_path}: "
        f"{len(recon_pres.slides)} != {len(orig_pres.slides)}"
    )

    failures = []
    for orig_slide, recon_slide in zip(orig_pres.slides, recon_pres.slides):
        # Non-vacuous guard: a slide that imported to zero elements has no content to
        # compare, so a perfect score would be meaningless (e.g. dropped SmartArt/table).
        if len(orig_slide.elements) == 0:
            failures.append(
                f"slide '{orig_slide.id}' imported to 0 elements (feature not covered)"
            )
            continue

        # Element-count parity (guards against silently dropped elements)
        if len(recon_slide.elements) != len(orig_slide.elements):
            failures.append(
                f"slide '{orig_slide.id}' element count mismatch "
                f"({len(recon_slide.elements)} != {len(orig_slide.elements)})"
            )
            continue

        # Composite fidelity score
        score = FidelityEvaluator.evaluate_slides(orig_slide, recon_slide)
        if not score.passed or score.total < 90.0:
            failures.append(
                f"slide '{orig_slide.id}' fidelity {score.total}% < 90%: "
                f"geo={score.geometry:.1f} text={score.text:.1f} "
                f"style={score.style:.1f} visual={score.visual:.1f}"
            )

    if failures:
        if deck_name in KNOWN_BOUNDARY:
            pytest.xfail(f"{KNOWN_BOUNDARY[deck_name]}: {'; '.join(failures[:3])}")
        pytest.fail(f"Deck {deck_name} regressed: {'; '.join(failures[:5])}")

    assert deck_name in PASSING, (
        f"Deck {deck_name} now passes fidelity but is not in PASSING manifest; "
        "move it from KNOWN_BOUNDARY to PASSING in this module."
    )


def test_real_world_manifest_coverage():
    """Ensures every discovered deck is accounted for in PASSING or KNOWN_BOUNDARY."""
    if not _REAL_DECKS:
        pytest.skip("Real-world deck corpus not fetched")
    names = {os.path.basename(d) for d in _REAL_DECKS}
    unaccounted = names - PASSING - set(KNOWN_BOUNDARY.keys())
    assert not unaccounted, (
        f"Decks missing from manifest: {sorted(unaccounted)}. "
        "Add each to PASSING or KNOWN_BOUNDARY with a reason."
    )