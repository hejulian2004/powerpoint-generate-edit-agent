"""Tests for the unified QualityService facade and canonical quality contracts."""

import pytest

from backend.eval.layout_diff import LayoutDiffEngine
from backend.eval.visual_critic import VisualCritic
from backend.evaluation.evaluator import RuleBasedEvaluator
from backend.evaluation.repair import generate_patches_for_issues
from backend.evaluation.schema import IssueSeverity, IssueType, VisualIssue
from backend.layout.schema import (
    Canvas,
    ElementType,
    DeckLayoutSpec,
    LayoutElement,
    LayoutSpec,
    Rect,
)
from backend.quality import (
    QualityIssue,
    QualityReport,
    QualityService,
    merge_reports,
    normalize_severity,
    quality_issue_from_layout_defect,
    quality_issue_from_visual_issue,
    severity_rank,
)
from backend.slidespec.schema import VisualIntent
from backend.ir.models import FillStyle, ShapeElementIR, SlideIR


def _clipped_slide() -> SlideIR:
    slide = SlideIR(
        id="qs_slide",
        slide_num=1,
        width=1280,
        height=720,
        background=FillStyle(type="solid", color="#FFFFFF"),
    )
    slide.add_element(
        ShapeElementIR(
            id="clipped_box",
            shape_type="roundRect",
            x=1150.0,
            y=200.0,
            width=200.0,
            height=100.0,
        )
    )
    return slide


def _overflow_layout() -> LayoutSpec:
    return LayoutSpec(
        slide_id="qs_layout",
        slide_index=1,
        visual_intent=VisualIntent.TITLE_HERO,
        canvas=Canvas(width=1280, height=720),
        elements=[
            LayoutElement(
                element_id="overflow_title",
                element_type=ElementType.TEXT,
                geometry=Rect(x=100.0, y=50.0, width=600.0, height=20.0),
                content="长" * 600,
            )
        ],
    )


def _overflow_deck() -> DeckLayoutSpec:
    return DeckLayoutSpec(title="QS Deck", slides=[_overflow_layout()])


# =====================================================================
# 1. IR path parity with backend.eval
# =====================================================================

def test_ir_evaluate_slide_parity():
    slide = _clipped_slide()
    direct = LayoutDiffEngine.evaluate_slide(slide)
    via_service = QualityService.evaluate_slide(slide)

    assert via_service.score == direct.score
    assert [d.defect_type for d in via_service.defects] == [d.defect_type for d in direct.defects]
    assert via_service.has_critical_defects is True


def test_ir_plan_remediation_parity():
    slide = _clipped_slide()
    report = QualityService.evaluate_slide(slide)
    direct = VisualCritic.plan_remediations(slide, report)
    via_service = QualityService.plan_remediation(slide, report)

    assert [a.to_dict() for a in via_service.actions] == [a.to_dict() for a in direct.actions]
    assert via_service.has_critical == direct.has_critical


def test_ir_render_parity():
    slide = _clipped_slide()
    assert QualityService.render_metadata(slide).renderer  # metadata reachable
    assert QualityService.render_data_uri(slide, fallback_to_svg=True).startswith("data:image/")
    assert QualityService.render_svg(slide).lstrip().startswith("<")


def test_ir_compare_slides_parity():
    before = _clipped_slide()
    after = _clipped_slide()
    result = QualityService.compare_slides(before, after)
    assert result.score_before == result.score_after
    assert result.score_delta == 0.0


# =====================================================================
# 2. LayoutSpec path parity with backend.evaluation
# =====================================================================

def test_layout_evaluate_parity():
    deck = _overflow_deck()
    direct = RuleBasedEvaluator().evaluate_deck(slide_images=[], deck_spec=deck)
    via_service = QualityService.evaluate_layout(deck)

    assert [i.to_dict() for i in via_service] == [i.to_dict() for i in direct]
    assert any(i.issue_type == IssueType.TEXT_OVERFLOW for i in via_service)


def test_layout_patches_parity():
    layout = _overflow_layout()
    issues = QualityService.evaluate_layout(_overflow_deck())
    direct = generate_patches_for_issues(issues, layout)
    via_service = QualityService.patches_for_issues(issues, layout)

    assert [p.to_dict() for p in via_service] == [p.to_dict() for p in direct]
    assert via_service


def test_layout_apply_patches_parity():
    from backend.evaluation.patch import apply_deck_patches

    deck = _overflow_deck()
    issues = QualityService.evaluate_layout(deck)
    patches = QualityService.patches_for_issues(issues, deck.slides[0])

    service_deck, service_results = QualityService.apply_layout_patches(deck, patches)
    direct_deck, direct_results = apply_deck_patches(deck, patches, enforce_transaction=True)

    assert service_deck.model_dump() == direct_deck.model_dump()
    assert [r.success for r in service_results] == [r.success for r in direct_results]


# =====================================================================
# 3. Canonical contracts
# =====================================================================

def test_normalize_severity_vocabulary():
    assert normalize_severity("CRITICAL") == "critical"
    assert normalize_severity(IssueSeverity.ERROR) == "error"
    assert normalize_severity("high") == "error"
    assert normalize_severity("medium") == "warning"
    assert normalize_severity("low") == "info"
    assert normalize_severity(None) == "info"
    assert normalize_severity("unknown-value") == "info"
    assert severity_rank("critical") < severity_rank("warning") < severity_rank("info")


def test_layout_defect_to_quality_issue():
    slide = _clipped_slide()
    report = QualityService.evaluate_slide(slide)
    defect = next(d for d in report.defects if d.defect_type == "viewport_clipping")

    issue = quality_issue_from_layout_defect(defect, slide_id=slide.id)
    assert issue.code == "overflow"
    assert issue.severity == "critical"
    assert issue.is_blocking
    assert "clipped_box" in issue.element_ids
    assert issue.suggested_fix is not None
    assert issue.to_dict()["source"] == "ir"


def test_visual_issue_to_quality_issue():
    issue = VisualIssue(
        slide_id="s1",
        issue_type=IssueType.OVERLAP,
        severity=IssueSeverity.ERROR,
        element_id="card_left",
        description="cards overlap",
        evidence={"iou": 0.4},
    )
    converted = quality_issue_from_visual_issue(issue)
    assert converted.code == "overlap"
    assert converted.severity == "error"
    assert converted.is_blocking
    assert converted.element_ids == ["card_left"]
    assert converted.details == {"iou": 0.4}


def test_quality_report_from_health_report():
    report = QualityService.evaluate_slide(_clipped_slide())
    quality = QualityService.report_from_health_report(report)

    assert quality.source == "ir"
    assert quality.slide_id == report.slide_id
    assert quality.score == report.score
    assert set(quality.dimensions) == {"geometry", "readability", "contrast", "balance", "aesthetics"}
    assert quality.passed is False
    assert quality.critical_count >= 1
    payload = quality.to_dict()
    assert payload["counts"]["critical"] >= 1
    round_tripped = [QualityIssue.from_dict(i) for i in payload["issues"]]
    assert round_tripped[0].code == payload["issues"][0]["code"]


def test_quality_report_from_visual_issues():
    issues = QualityService.evaluate_layout(_overflow_deck())
    quality = QualityService.report_from_issues(issues, slide_id="qs_layout")

    assert quality.source == "layout"
    assert quality.passed is False
    assert quality.has_blocking_issues is True
    assert all(i.source == "layout" for i in quality.issues)


def test_merge_reports_keeps_worst_score_and_dedupes():
    ir_report = QualityService.report_from_health_report(QualityService.evaluate_slide(_clipped_slide()))
    layout_report = QualityService.report_from_issues(
        QualityService.evaluate_layout(_overflow_deck()), slide_id="qs_layout"
    )

    merged = merge_reports(ir_report, layout_report)
    assert merged.source == "aggregate"
    assert layout_report.score is None
    assert merged.score == ir_report.score
    assert merged.passed is False
    assert merged.meta["sources"] == ["ir", "layout"]
    assert len(merged.issues) == len(ir_report.issues) + len(layout_report.issues)

    duplicated = merge_reports(ir_report, ir_report)
    assert len(duplicated.issues) == len(ir_report.issues)
    assert merge_reports().source == "aggregate"


def test_quality_report_from_fidelity_score():
    score = QualityService.score_fidelity(_clipped_slide(), _clipped_slide())
    quality = QualityService.report_from_fidelity(score, slide_id="qs_slide")

    assert quality.source == "fidelity"
    assert quality.score == score.total
    assert set(quality.dimensions) == {"geometry", "text", "style", "visual"}
    assert quality.degraded == score.degraded
    assert quality.passed == score.passed
