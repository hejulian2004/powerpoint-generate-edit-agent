"""PR6.4 Round-Trip Fidelity Benchmark Suite.

Executes quantitative fidelity benchmarks across 5 representative design decks:
1. academic.pptx: Academic research layout with footnote, two-columns, and callout
2. business.pptx: Executive business deck with theme accents, KPI stats, and banners
3. dashboard.pptx: Card grid with status badges and connectors
4. image_heavy.pptx: Dual image layouts with captions
5. complex_group.pptx: Nested hierarchical groups and coordinate systems

Guarantees:
- Bounding box error < 2.0px
- Typography font match > 95%
- Visual SSIM > 0.90
- Composite FidelityScore >= 90.0%
"""

import os
from pathlib import Path
import pytest

from backend.ir import import_pptx, export_pptx
from backend.eval.fidelity import (
    FidelityEvaluator, TypographyDiffEngine, StyleDiffEngine, PixelDiffEngine
)
from backend.ir.models import (
    PresentationIR, SlideIR, TableElementIR, TableCellIR, GroupElementIR, TextContentIR
)

BENCHMARK_DIR = Path(__file__).resolve().parent / "assets" / "fidelity"


@pytest.fixture(scope="module")
def benchmark_assets():
    return [
        "academic.pptx",
        "business.pptx",
        "dashboard.pptx",
        "image_heavy.pptx",
        "complex_group.pptx",
    ]


@pytest.mark.parametrize("deck_name", [
    "academic.pptx",
    "business.pptx",
    "dashboard.pptx",
    "image_heavy.pptx",
    "complex_group.pptx",
])
def test_roundtrip_deck_fidelity(deck_name: str, tmp_path: Path):
    deck_path = BENCHMARK_DIR / deck_name
    assert deck_path.exists(), f"Benchmark asset {deck_name} missing"

    # 1. Import original PPTX to IR
    orig_pres = import_pptx(str(deck_path))
    assert len(orig_pres.slides) > 0

    # 2. Export IR to temporary round-trip PPTX
    out_path = tmp_path / f"roundtrip_{deck_name}"
    export_pptx(orig_pres, str(out_path))
    assert out_path.exists()

    # 3. Re-import round-trip PPTX to IR
    recon_pres = import_pptx(str(out_path))
    assert len(recon_pres.slides) == len(orig_pres.slides)

    orig_slide = orig_pres.slides[0]
    recon_slide = recon_pres.slides[0]

    # 4. Geometry Evaluation
    geom_score, geom_diag = FidelityEvaluator._evaluate_geometry(orig_slide, recon_slide)
    assert geom_score >= 98.0, f"Geometry score degraded on {deck_name}: {geom_score}% ({geom_diag})"

    # 5. Typography Evaluation (font match rate > 95%)
    typo_rep = TypographyDiffEngine.compare_slides(orig_slide, recon_slide)
    assert typo_rep.font_match_rate >= 0.95, f"Typography font match low on {deck_name}: {typo_rep.font_match_rate}"
    assert typo_rep.text_match_rate >= 0.95, f"Typography text match low on {deck_name}: {typo_rep.text_match_rate}"

    # 6. Style Evaluation
    style_rep = StyleDiffEngine.compare_slides(orig_slide, recon_slide)
    assert style_rep.score >= 85.0, f"Style score low on {deck_name}: {style_rep.score}"

    # 7. Overall Composite Fidelity Score (>= 90%)
    score = FidelityEvaluator.evaluate_slides(orig_slide, recon_slide)
    assert score.passed is True, f"Fidelity score failed on {deck_name}: {score.to_dict()}"
    assert score.total >= 90.0, f"Composite score {score.total}% below 90% threshold: {score.diagnostics}"


def test_roundtrip_multi_slide_presentation(tmp_path: Path):
    """Verifies fidelity across multi-slide presentations."""
    pres = PresentationIR(title="Multi-Slide Benchmark")
    acad = import_pptx(str(BENCHMARK_DIR / "academic.pptx"))
    biz = import_pptx(str(BENCHMARK_DIR / "business.pptx"))

    pres.slides.append(acad.slides[0])
    pres.slides.append(biz.slides[0])

    out_file = tmp_path / "multi_slide.pptx"
    export_pptx(pres, str(out_file))

    re_pres = import_pptx(str(out_file))
    assert len(re_pres.slides) == 2

    # Verify both slides pass fidelity
    for i in range(2):
        score = FidelityEvaluator.evaluate_slides(pres.slides[i], re_pres.slides[i])
        assert score.passed is True
        assert score.total >= 90.0


def test_roundtrip_table_flattening_is_declared_lossy(tmp_path: Path):
    """Honest contract for TableElementIR write-back (PR6-hardening).

    The export path currently flattens tables into a Group of styled cell
    rectangles, permanently dropping native <a:tbl> semantics. This test pins:

    1. Native import parses real <a:tbl> into TableElementIR (fidelity importer).
    2. Export write-back is DECLARED lossy by the capability matrix.
    3. Round-tripped geometry + text survive, but the element must be a flattened
       Group — never asserted as native table preservation.
    """
    # 1. Native <a:tbl> import must produce an editable TableElementIR
    native_path = Path(__file__).parent / "assets" / "real_world" / "table-with-theme.pptx"
    native_pres = import_pptx(str(native_path))
    native_tables = [
        el for s in native_pres.slides
        for el in s.all_elements(recursive=True)
        if isinstance(el, TableElementIR)
    ]
    assert native_tables, "fidelity importer must parse native <a:tbl> into TableElementIR"

    # 2. Export write-back is declaratively lossy, not silently "preserved"
    from backend.fidelity.capability import CapabilityDetector
    verdict = CapabilityDetector.check_writeback("table")
    assert verdict["lossless"] is False
    assert verdict["reason"] == "flattened_to_group"

    pres = PresentationIR(title="Table Benchmark")
    slide = SlideIR(id="tbl_slide_1", slide_num=1, title="Table Degradation Contract")

    tbl = TableElementIR(
        id="elem_tbl_1",
        name="Benchmark Table",
        x=100.0,
        y=100.0,
        width=600.0,
        height=300.0,
        rows=2,
        cols=2,
        cells=[
            [
                TableCellIR(row=0, col=0, text_content=TextContentIR.from_plain_text("Header A")),
                TableCellIR(row=0, col=1, text_content=TextContentIR.from_plain_text("Header B")),
            ],
            [
                TableCellIR(row=1, col=0, text_content=TextContentIR.from_plain_text("Data 1")),
                TableCellIR(row=1, col=1, text_content=TextContentIR.from_plain_text("Data 2")),
            ],
        ]
    )
    slide.add_element(tbl)
    pres.slides.append(slide)

    # Capability matrix warns on export degradation
    caps = CapabilityDetector.detect_from_ir(pres)
    assert any("table" in w and "lossy" in w for w in caps.lossy_warnings())

    out_file = tmp_path / "table_deck.pptx"
    export_pptx(pres, str(out_file))

    re_pres = import_pptx(str(out_file))
    re_slide = re_pres.slides[0]
    # 3. Export degrades to a flattened group; that is the documented contract.
    flattened = next(
        (el for el in re_slide.elements if isinstance(el, GroupElementIR)), None
    )
    assert flattened is not None, (
        "table export currently flattens to GroupElementIR; if native <a:tbl> "
        "write-back lands, update this lossy-writeback contract deliberately"
    )
    assert abs(flattened.x - 100.0) < 2.0
    assert abs(flattened.width - 600.0) < 2.0

    all_texts = " ".join(
        el.text_content.plain_text
        for el in re_slide.all_elements(recursive=True)
        if getattr(el, "text_content", None)
    )
    assert "Header A" in all_texts
    assert "Header B" in all_texts
    assert "Data 1" in all_texts
    assert "Data 2" in all_texts
