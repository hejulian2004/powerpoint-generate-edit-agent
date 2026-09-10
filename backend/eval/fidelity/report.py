"""Structured fidelity report (PR6.1 Task 6).

Aggregates the raw fidelity diffs into a single machine-readable report an agent (PR7)
can consume to know exactly where and how to repair a slide:

    {
      "overall": 93.5,
      "dimensions": {"geometry": 96.0, "text": 92.0, "style": 95.0, "visual": 91.0},
      "issues": [
        {"type": "FONT_MISMATCH", "element": "title_001",
         "expected": "Calibri", "actual": "Arial", "severity": "medium"}
      ]
    }
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

from ...ir.models import SlideIR, PresentationIR
from .fidelity_score import FidelityEvaluator, FidelityScore
from .typography_diff import TypographyDiffEngine, TypographyDiffReport
from .style_diff import StyleDiffEngine, StyleDiffReport
from ...fidelity.fidelity_diff import FidelityDiffEngine, FidelityDiffReport


@dataclass
class FidelityIssue:
    type: str
    element: str
    expected: str = ""
    actual: str = ""
    severity: str = "medium"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "element": self.element,
            "expected": self.expected,
            "actual": self.actual,
            "severity": self.severity,
        }


@dataclass
class FidelityReport:
    overall: float = 100.0
    dimensions: Dict[str, float] = field(default_factory=dict)
    issues: List[FidelityIssue] = field(default_factory=list)
    passed: bool = True
    degraded: bool = False
    visual_source: str = "internal_rasterizer"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall": round(self.overall, 1),
            "dimensions": {k: round(v, 1) for k, v in self.dimensions.items()},
            "issues": [i.to_dict() for i in self.issues],
            "passed": self.passed,
            "degraded": self.degraded,
            "visual_source": self.visual_source,
        }

    def issues_by_severity(self, severity: str) -> List[FidelityIssue]:
        return [i for i in self.issues if i.severity == severity]

    @property
    def critical_issues(self) -> List[FidelityIssue]:
        return self.issues_by_severity("high")


def build_fidelity_report(
    orig_slide: SlideIR,
    recon_slide: SlideIR,
    scale: float = 0.5,
    *,
    orig_image: Any = None,
    recon_image: Any = None,
    strict_visual: bool = False,
) -> FidelityReport:
    """Builds a structured fidelity report comparing original vs reconstructed slide.

    ``passed`` / ``degraded`` / ``visual_source`` are propagated from the underlying
    ``FidelityScore`` so consumers can distinguish a real WYSIWYG screenshot score
    from an internal-rasterizer or fallback score.
    """
    score = FidelityEvaluator.evaluate_slides(
        orig_slide,
        recon_slide,
        orig_image=orig_image,
        recon_image=recon_image,
        scale=scale,
        strict_visual=strict_visual,
    )
    issues: List[FidelityIssue] = []

    _append_dedup(issues, _geometry_and_structure_issues(orig_slide, recon_slide))
    _append_dedup(issues, _typography_issues(orig_slide, recon_slide))
    _append_dedup(issues, _style_issues(orig_slide, recon_slide))

    return FidelityReport(
        overall=score.total,
        dimensions={
            "geometry": score.geometry,
            "text": score.text,
            "style": score.style,
            "visual": score.visual,
        },
        issues=issues,
        passed=score.passed,
        degraded=score.degraded,
        visual_source=score.visual_source,
    )


def _worst_visual_source(sources: List[str]) -> str:
    """Precedence: fallback > internal_rasterizer > external_raster."""
    if any(s == "fallback" for s in sources):
        return "fallback"
    if any(s == "internal_rasterizer" for s in sources):
        return "internal_rasterizer"
    return "external_raster"


def build_presentation_report(
    orig_pres: PresentationIR,
    recon_pres: PresentationIR,
    scale: float = 0.5,
    *,
    orig_images: Optional[List[Any]] = None,
    recon_images: Optional[List[Any]] = None,
    strict_visual: bool = False,
) -> Dict[str, Any]:
    """Aggregates per-slide reports into a presentation-level summary.

    ``passed`` requires every slide to pass; ``degraded`` is true when any slide is
    degraded, and the aggregate ``visual_source`` reflects the weakest basis used.
    """
    slides = []
    for idx, o_slide in enumerate(orig_pres.slides):
        r_slide = recon_pres.slides[idx] if idx < len(recon_pres.slides) else None
        if r_slide is None:
            slides.append({
                "slide_num": o_slide.slide_num,
                "overall": 0.0,
                "passed": False,
                "degraded": True,
                "visual_source": "fallback",
                "issues": [{
                    "type": "MISSING_SLIDE",
                    "element": o_slide.id,
                    "expected": "slide present",
                    "actual": "slide missing",
                    "severity": "high",
                }],
            })
            continue
        o_img = orig_images[idx] if orig_images and idx < len(orig_images) else None
        r_img = recon_images[idx] if recon_images and idx < len(recon_images) else None
        report = build_fidelity_report(
            o_slide,
            r_slide,
            scale=scale,
            orig_image=o_img,
            recon_image=r_img,
            strict_visual=strict_visual,
        )
        slides.append({"slide_num": o_slide.slide_num, **report.to_dict()})

    if not slides:
        return {
            "overall": 100.0, "slides": [], "passed": True,
            "degraded": False, "visual_source": "external_raster",
        }

    overall = sum(s["overall"] for s in slides) / len(slides)
    return {
        "overall": round(overall, 1),
        "slides": slides,
        "passed": all(s.get("passed", False) for s in slides),
        "degraded": any(s.get("degraded", False) for s in slides),
        "visual_source": _worst_visual_source(
            [s.get("visual_source", "fallback") for s in slides]
        ),
    }


# =====================================================================
# Issue extractors
# =====================================================================

def _geometry_and_structure_issues(
    orig_slide: SlideIR, recon_slide: SlideIR
) -> List[FidelityIssue]:
    diff: FidelityDiffReport = FidelityDiffEngine.compare_slides(orig_slide, recon_slide)
    issues: List[FidelityIssue] = []

    for eid in diff.missing_elements:
        issues.append(FidelityIssue(
            type="MISSING_ELEMENT", element=eid,
            expected="present", actual="missing", severity="high"
        ))
    for eid in diff.added_elements:
        issues.append(FidelityIssue(
            type="ADDED_ELEMENT", element=eid,
            expected="absent", actual="added", severity="high"
        ))

    for drift in diff.element_drifts:
        err = drift.max_coordinate_error
        if err > 2.0:
            issues.append(FidelityIssue(
                type="GEOMETRY_DRIFT", element=drift.element_id,
                expected="within 2px",
                actual=f"max error {err:.1f}px",
                severity="high" if err > 10.0 else "medium",
            ))
        if drift.font_mismatch:
            issues.append(FidelityIssue(
                type="FONT_MISMATCH", element=drift.element_id,
                expected=drift.font_expected, actual=drift.font_actual, severity="medium"
            ))
        if drift.color_mismatch:
            issues.append(FidelityIssue(
                type="COLOR_MISMATCH", element=drift.element_id,
                expected=drift.color_expected, actual=drift.color_actual, severity="medium"
            ))
        if drift.text_mismatch:
            issues.append(FidelityIssue(
                type="TEXT_MISMATCH", element=drift.element_id,
                expected="text matches", actual="text differs", severity="medium"
            ))
    return issues


def _typography_issues(
    orig_slide: SlideIR, recon_slide: SlideIR
) -> List[FidelityIssue]:
    rep: TypographyDiffReport = TypographyDiffEngine.compare_slides(orig_slide, recon_slide)
    issues: List[FidelityIssue] = []
    for m in rep.mismatches:
        if m.expected_font != m.actual_font:
            issues.append(FidelityIssue(
                type="FONT_MISMATCH", element=m.element_id,
                expected=m.expected_font, actual=m.actual_font, severity="medium"
            ))
        if abs(m.expected_size - m.actual_size) > 0.5:
            issues.append(FidelityIssue(
                type="FONT_SIZE_MISMATCH", element=m.element_id,
                expected=f"{m.expected_size}pt", actual=f"{m.actual_size}pt", severity="medium"
            ))
        if m.expected_text != m.actual_text:
            issues.append(FidelityIssue(
                type="TEXT_MISMATCH", element=m.element_id,
                expected=m.expected_text, actual=m.actual_text, severity="medium"
            ))
    return issues


def _style_issues(
    orig_slide: SlideIR, recon_slide: SlideIR
) -> List[FidelityIssue]:
    rep: StyleDiffReport = StyleDiffEngine.compare_slides(orig_slide, recon_slide)
    issues: List[FidelityIssue] = []
    for m in rep.mismatches:
        issues.append(FidelityIssue(
            type="STYLE_MISMATCH", element=m.element_id,
            expected=f"{m.property_name}={m.expected_value}",
            actual=f"{m.property_name}={m.actual_value}",
            severity="low",
        ))
    return issues


def _append_dedup(target: List[FidelityIssue], incoming: List[FidelityIssue]) -> None:
    seen = {(i.type, i.element) for i in target}
    for issue in incoming:
        key = (issue.type, issue.element)
        if key in seen:
            continue
        seen.add(key)
        target.append(issue)