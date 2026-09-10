"""Structured fidelity report tests (PR6.1 Task 6).

Verifies build_fidelity_report aggregates raw diffs into a machine-readable report with
overall score, per-dimension scores, and typed issues (FONT_MISMATCH, GEOMETRY_DRIFT,
STYLE_MISMATCH, ...) an agent can act on.
"""

import copy

from PIL import Image

from backend.eval.fidelity import (
    build_fidelity_report, build_presentation_report, FidelityIssue, FidelityReport
)
from backend.fidelity import FidelityEngine
from backend.ir.models import (
    PresentationIR, SlideIR, ShapeElementIR, TextElementIR,
    ElementStyleIR, FillStyle, TextContentIR, FontIR,
)


def _baseline_slide() -> SlideIR:
    slide = SlideIR(id="slide_1", slide_num=1)
    slide.add_element(TextElementIR(
        id="title", name="Slide Title", x=80.0, y=50.0, width=700.0, height=50.0,
        text_content=TextContentIR.from_plain_text(
            "Quarterly Performance Review", font=FontIR(name="Calibri", size=26.0, bold=True)
        )
    ))
    slide.add_element(ShapeElementIR(
        id="card", name="KPI Card", shape_type="roundRect",
        x=80.0, y=160.0, width=300.0, height=140.0,
        style=ElementStyleIR(fill=FillStyle(type="solid", color="#2563EB"))
    ))
    return slide


def _mutated_slide() -> SlideIR:
    slide = _baseline_slide()
    title = slide.get_element("title")
    title.text_content.paragraphs[0].runs[0].font.name = "Arial"
    title.text_content.paragraphs[0].runs[0].font.size = 18.0
    card = slide.get_element("card")
    card.x = 200.0   # 120px geometry drift
    card.style.fill.color = "#DC2626"
    return slide


def test_report_structure_matches_spec():
    report = build_fidelity_report(_baseline_slide(), _mutated_slide())
    data = report.to_dict()
    assert "overall" in data
    assert "dimensions" in data
    assert set(data["dimensions"].keys()) == {"geometry", "text", "style", "visual"}
    assert isinstance(data["issues"], list)
    assert data["overall"] < 95.0


def test_report_contains_font_mismatch_issue():
    report = build_fidelity_report(_baseline_slide(), _mutated_slide())
    font_issues = [i for i in report.issues if i.type == "FONT_MISMATCH"]
    assert font_issues, "expected a FONT_MISMATCH issue"
    issue = font_issues[0]
    assert issue.element == "title"
    assert issue.expected == "Calibri"
    assert issue.actual == "Arial"
    assert issue.severity == "medium"


def test_report_contains_geometry_drift_issue():
    report = build_fidelity_report(_baseline_slide(), _mutated_slide())
    geom = [i for i in report.issues if i.type == "GEOMETRY_DRIFT"]
    assert geom, "expected a GEOMETRY_DRIFT issue"
    assert geom[0].element == "card"
    assert geom[0].severity == "high"  # >10px drift


def test_report_contains_style_mismatch_issue():
    report = build_fidelity_report(_baseline_slide(), _mutated_slide())
    style = [i for i in report.issues if i.type == "STYLE_MISMATCH"]
    assert style, "expected a STYLE_MISMATCH issue"


def test_report_has_no_issues_when_lossless():
    report = build_fidelity_report(_baseline_slide(), copy.deepcopy(_baseline_slide()))
    assert report.overall >= 95.0
    assert report.critical_issues == []


def test_report_issue_dedup():
    report = build_fidelity_report(_baseline_slide(), _mutated_slide())
    keys = [(i.type, i.element) for i in report.issues]
    assert len(keys) == len(set(keys)), "duplicate issues must be deduplicated"


def test_missing_element_flagged_high():
    recon = _baseline_slide()
    recon.elements = [el for el in recon.elements if el.id != "card"]
    report = build_fidelity_report(_baseline_slide(), recon)
    missing = [i for i in report.issues if i.type == "MISSING_ELEMENT"]
    assert missing and missing[0].element == "card"
    assert missing[0].severity == "high"


# =====================================================================
# Honest fidelity contract through the public facade (PR6-hardening r2)
# =====================================================================

def test_report_exposes_honesty_contract_fields():
    report = build_fidelity_report(_baseline_slide(), copy.deepcopy(_baseline_slide()))
    assert report.passed is True
    assert report.degraded is False
    assert report.visual_source == "internal_rasterizer"
    data = report.to_dict()
    assert data["passed"] is True
    assert data["degraded"] is False
    assert data["visual_source"] == "internal_rasterizer"


def test_facade_evaluate_accepts_external_screenshots():
    slide = _baseline_slide()
    img = Image.new("RGB", (160, 90), color=(255, 255, 255))
    score = FidelityEngine.evaluate(
        slide, copy.deepcopy(slide), orig_image=img, recon_image=img
    )
    assert score.visual_source == "external_raster"
    assert score.degraded is False


def test_facade_evaluate_strict_visual_degrades_without_screenshots():
    slide = _baseline_slide()
    score = FidelityEngine.evaluate(slide, copy.deepcopy(slide), strict_visual=True)
    assert score.visual_source == "internal_rasterizer"
    assert score.degraded is True
    assert score.passed is False


def test_facade_report_exposes_honesty_contract():
    slide = _baseline_slide()
    report = FidelityEngine.report(slide, copy.deepcopy(slide), strict_visual=True)
    assert report.passed is False
    assert report.degraded is True
    assert report.visual_source == "internal_rasterizer"
    external = FidelityEngine.report(
        slide,
        copy.deepcopy(slide),
        orig_image=Image.new("RGB", (160, 90)),
        recon_image=Image.new("RGB", (160, 90)),
    )
    assert external.visual_source == "external_raster"
    assert external.degraded is False


def test_presentation_report_propagates_passed_degraded_visual_source():
    orig = PresentationIR(title="Aggregate")
    orig.slides.append(_baseline_slide())
    recon = PresentationIR(title="Aggregate")
    recon.slides.append(copy.deepcopy(_baseline_slide()))

    healthy = build_presentation_report(orig, recon)
    assert healthy["passed"] is True
    assert healthy["degraded"] is False
    assert healthy["visual_source"] == "internal_rasterizer"
    assert healthy["slides"][0]["visual_source"] == "internal_rasterizer"

    strict = build_presentation_report(orig, recon, strict_visual=True)
    assert strict["passed"] is False
    assert strict["degraded"] is True


def test_presentation_report_missing_slide_fails_aggregate():
    orig = PresentationIR(title="Aggregate")
    orig.slides.append(_baseline_slide())
    recon = PresentationIR(title="Aggregate")  # no slides

    summary = build_presentation_report(orig, recon)
    assert summary["passed"] is False
    assert summary["degraded"] is True
    assert summary["visual_source"] == "fallback"