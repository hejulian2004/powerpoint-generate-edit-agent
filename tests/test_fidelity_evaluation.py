import pytest
from PIL import Image
from backend.ir.models import (
    SlideIR, ShapeElementIR, TextElementIR, ElementStyleIR,
    FillStyle, BorderStyle, FontIR, TextContentIR, ParagraphIR, RunIR
)
from backend.eval.fidelity import (
    PixelDiffEngine, TypographyDiffEngine, StyleDiffEngine,
    FidelityEvaluator, FidelityScore
)


def _make_sample_slide(title_color="#1E3A8A", font_name="Segoe UI", font_size=24.0, x=50, y=50):
    slide = SlideIR(id="slide_eval_1", width=960, height=540)

    # Title element
    title_elem = TextElementIR(
        id="elem_eval_title",
        x=x,
        y=y,
        width=500,
        height=60,
        style=ElementStyleIR(
            fill=FillStyle(type="solid", color="#F3F4F6"),
            border=BorderStyle(style="solid", color=title_color, width=2.0)
        ),
        text_content=TextContentIR(
            paragraphs=[
                ParagraphIR(runs=[
                    RunIR(text="Fidelity Evaluation Title", font=FontIR(name=font_name, size=font_size, color=title_color))
                ])
            ]
        )
    )
    slide.add_element(title_elem)

    # Card element
    card_elem = ShapeElementIR(
        id="elem_eval_card",
        shape_type="rectangle",
        x=50,
        y=150,
        width=400,
        height=200,
        style=ElementStyleIR(
            fill=FillStyle(type="solid", color="#FFFFFF"),
            border=BorderStyle(style="solid", color="#E5E7EB", width=1.0)
        )
    )
    slide.add_element(card_elem)
    return slide


def test_pixel_diff_identical_and_different():
    # 1. Identical images
    img1 = Image.new("RGB", (320, 180), color=(255, 255, 255))
    img2 = Image.new("RGB", (320, 180), color=(255, 255, 255))
    res = PixelDiffEngine.compare_images(img1, img2, generate_heatmap=True)

    assert res.ssim >= 0.999
    assert res.mse == 0.0
    assert res.diff_ratio == 0.0
    assert res.diff_image is not None

    # 2. Differing images
    img3 = Image.new("RGB", (320, 180), color=(0, 0, 0))
    res_diff = PixelDiffEngine.compare_images(img1, img3)
    assert res_diff.ssim < 0.1
    assert res_diff.mse > 10000.0
    assert res_diff.diff_ratio == 1.0


def test_typography_diff_identical_and_drift():
    slide1 = _make_sample_slide(font_name="Segoe UI", font_size=24.0)
    slide2 = _make_sample_slide(font_name="Segoe UI", font_size=24.0)

    # Identical typography
    report = TypographyDiffEngine.compare_slides(slide1, slide2)
    assert report.score >= 99.0
    assert report.font_match_rate == 1.0
    assert report.size_match_rate == 1.0
    assert report.text_match_rate == 1.0
    assert len(report.mismatches) == 0

    # Font family equivalence (Segoe UI vs Calibri)
    slide_equiv = _make_sample_slide(font_name="Calibri", font_size=24.0)
    rep_equiv = TypographyDiffEngine.compare_slides(slide1, slide_equiv)
    assert rep_equiv.font_match_rate >= 0.90
    assert rep_equiv.score >= 90.0

    # Drastic font and size drift
    slide_drift = _make_sample_slide(font_name="Consolas", font_size=12.0)
    rep_drift = TypographyDiffEngine.compare_slides(slide1, slide_drift)
    assert rep_drift.size_match_rate < 0.6
    assert len(rep_drift.mismatches) > 0


def test_style_diff_identical_and_color_drift():
    slide1 = _make_sample_slide(title_color="#1E3A8A")
    slide2 = _make_sample_slide(title_color="#1E3A8A")

    # Identical styles
    report = StyleDiffEngine.compare_slides(slide1, slide2)
    assert report.score == 100.0
    assert report.fill_score == 100.0
    assert report.border_score == 100.0
    assert len(report.mismatches) == 0

    # Border color drift
    slide_drift = _make_sample_slide(title_color="#DC2626")
    rep_drift = StyleDiffEngine.compare_slides(slide1, slide_drift)
    assert rep_drift.border_score < 100.0
    assert len(rep_drift.mismatches) > 0


def test_fidelity_evaluator_composite_score():
    slide1 = _make_sample_slide(title_color="#1E3A8A", font_name="Segoe UI", font_size=24.0, x=50, y=50)
    slide2 = _make_sample_slide(title_color="#1E3A8A", font_name="Segoe UI", font_size=24.0, x=51, y=51)

    # Drift is 1px (< 2px threshold) -> Geometry score should be 100%
    score = FidelityEvaluator.evaluate_slides(slide1, slide2)
    assert score.geometry == 100.0
    assert score.text >= 95.0
    assert score.style >= 95.0
    assert score.visual >= 90.0
    assert score.total >= 90.0
    assert score.passed is True

    # Large geometry drift (> 10px)
    slide_drifted = _make_sample_slide(title_color="#1E3A8A", font_name="Segoe UI", font_size=24.0, x=150, y=100)
    score_drifted = FidelityEvaluator.evaluate_slides(slide1, slide_drifted)
    assert score_drifted.geometry < 90.0
    assert any("Geometry drift" in d for d in score_drifted.diagnostics)


def test_evaluator_declares_internal_raster_basis():
    """Internal Pillow raster SSIM measures IR consistency, not PowerPoint WYSIWYG."""
    slide1 = _make_sample_slide()
    slide2 = _make_sample_slide()
    score = FidelityEvaluator.evaluate_slides(slide1, slide2)
    assert score.visual_source == "internal_rasterizer"
    assert score.degraded is False


def test_evaluator_strict_visual_requires_external_raster():
    """strict_visual must fail a PASS when only the internal rasterizer is available."""
    slide1 = _make_sample_slide()
    slide2 = _make_sample_slide()
    score = FidelityEvaluator.evaluate_slides(slide1, slide2, strict_visual=True)
    assert score.visual_source == "internal_rasterizer"
    assert score.degraded is True
    assert score.passed is False
    assert any("strict_visual" in d for d in score.diagnostics)


def test_evaluator_raster_failure_is_degraded_and_never_passes(monkeypatch):
    """A synthesized fallback visual score must not be able to produce a PASS."""
    from backend.eval.renderer_snapshot import PillowSlideRasterizer

    def _boom(*args, **kwargs):
        raise RuntimeError("raster explosion")

    monkeypatch.setattr(PillowSlideRasterizer, "render_to_image", _boom)

    slide1 = _make_sample_slide()
    slide2 = _make_sample_slide()
    score = FidelityEvaluator.evaluate_slides(slide1, slide2)
    assert score.visual_source == "fallback"
    assert score.degraded is True
    assert score.passed is False
    assert any("DEGRADED" in d for d in score.diagnostics)


# =====================================================================
# Size-aware IoU target (full drift-ball worst case)
# =====================================================================

class _Box:
    def __init__(self, w, h):
        self.x = 0.0
        self.y = 0.0
        self.width = float(w)
        self.height = float(h)


def test_iou_target_full_drift_ball_worst_case():
    """Target must equal the IoU of the worst legal <=2px recon.

    Worst case: shifted by 2px on both axes AND grown by 2px on both dims
    (all within max(dx, dy, dw, dh) <= 2). inter = (w-2)(h-2),
    union = w*h + (w+2)(h+2) - inter.
    """
    # 50x50 -> 48*48 / (2500 + 2704 - 2304) = 2304 / 2900
    assert FidelityEvaluator._iou_target(_Box(50, 50)) == pytest.approx(2304 / 2900)
    # 100x20 -> 98*18 / (2000 + 2244 - 1764) = 1764 / 2480
    assert FidelityEvaluator._iou_target(_Box(100, 20)) == pytest.approx(1764 / 2480)
    # Small element -> 10x10 -> 8*8 / (100 + 144 - 64) = 64 / 180
    assert FidelityEvaluator._iou_target(_Box(10, 10)) == pytest.approx(64 / 180)


def test_iou_target_caps_and_degenerate_guards():
    # Large boxes stay capped at the 0.98 acceptance bar
    assert FidelityEvaluator._iou_target(_Box(2000, 2000)) == pytest.approx(0.98)
    # Degenerate sizes have no meaningful target
    assert FidelityEvaluator._iou_target(_Box(2, 100)) == 0.0
    assert FidelityEvaluator._iou_target(_Box(100, 1)) == 0.0


def test_geometry_not_penalized_for_legal_drift_ball():
    """Elements within 2px drift on every parameter must score a perfect 100."""
    # Translation dx=dy=2 (same size): IoU 0.855 > target 0.794
    slide_shifted = _make_sample_slide(x=52, y=52)
    score_shifted = FidelityEvaluator.evaluate_slides(_make_sample_slide(), slide_shifted)
    assert score_shifted.geometry == 100.0

    # Worst legal case: shift +2/+2 AND grow +2/+2 -> IoU exactly equals target
    slide_worst = _make_sample_slide(x=52, y=52)
    for el, o_el in zip(
        slide_worst.all_elements(recursive=True),
        _make_sample_slide().all_elements(recursive=True),
    ):
        el.width = o_el.width + 2.0
        el.height = o_el.height + 2.0
    score_worst = FidelityEvaluator.evaluate_slides(_make_sample_slide(), slide_worst)
    assert score_worst.geometry == 100.0
    assert not any("Geometry IoU" in d for d in score_worst.diagnostics)
