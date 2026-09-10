"""Canonical quality contracts shared by the IR and LayoutSpec pipelines.

`backend.eval` (SlideIR) and `backend.evaluation` (LayoutSpec) remain the
implementation engines; this module defines the single vocabulary that
consumers, telemetry and future code should use for issues, severity and
aggregate reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

SEVERITY_CRITICAL = "critical"
SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"

_SEVERITY_ORDER: Dict[str, int] = {
    SEVERITY_CRITICAL: 0,
    SEVERITY_ERROR: 1,
    SEVERITY_WARNING: 2,
    SEVERITY_INFO: 3,
}

_BLOCKING_SEVERITIES = frozenset({SEVERITY_CRITICAL, SEVERITY_ERROR})

# `backend.eval.fidelity` uses a high/medium/low scale; map it onto the
# canonical severity vocabulary used by both engines.
_LEGACY_SEVERITY_ALIASES: Dict[str, str] = {
    "fatal": SEVERITY_CRITICAL,
    "high": SEVERITY_ERROR,
    "medium": SEVERITY_WARNING,
    "low": SEVERITY_INFO,
}

# SlideIR defect types -> canonical machine-readable issue codes.
IR_DEFECT_CODE_MAP: Dict[str, str] = {
    "viewport_clipping": "overflow",
    "margin_intrusion": "margin_violation",
    "collision_overlap": "overlap",
    "text_overflow": "text_overflow",
    "low_contrast": "low_contrast",
    "misaligned": "misalignment",
    "poor_whitespace": "poor_whitespace",
    "garish_color": "garish_color",
    "color_disharmony": "color_disharmony",
    "oversized_card_radius": "oversized_radius",
    "weak_hierarchy": "weak_hierarchy",
}


def normalize_severity(value: Any) -> str:
    """Normalize any engine severity value onto the canonical vocabulary."""
    raw = getattr(value, "value", value)
    text = str(raw or "").strip().lower()
    if text in _SEVERITY_ORDER:
        return text
    return _LEGACY_SEVERITY_ALIASES.get(text, SEVERITY_INFO)


def severity_rank(value: Any) -> int:
    """Sort key: lower is more severe (critical=0 ... info=3)."""
    return _SEVERITY_ORDER[normalize_severity(value)]


@dataclass
class QualityIssue:
    """Engine-agnostic issue representation."""

    code: str
    severity: str
    message: str = ""
    slide_id: Optional[str] = None
    element_ids: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)
    suggested_fix: Optional[Dict[str, Any]] = None
    source: str = "ir"

    @property
    def is_blocking(self) -> bool:
        return self.severity in _BLOCKING_SEVERITIES

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "slide_id": self.slide_id,
            "element_ids": list(self.element_ids),
            "details": dict(self.details),
            "suggested_fix": dict(self.suggested_fix) if self.suggested_fix else None,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QualityIssue":
        return cls(
            code=str(data.get("code", "unknown")),
            severity=normalize_severity(data.get("severity")),
            message=str(data.get("message", "")),
            slide_id=data.get("slide_id"),
            element_ids=list(data.get("element_ids") or []),
            details=dict(data.get("details") or {}),
            suggested_fix=dict(data["suggested_fix"]) if data.get("suggested_fix") else None,
            source=str(data.get("source", "unknown")),
        )


def quality_issue_from_layout_defect(
    defect: Any,
    *,
    slide_id: Optional[str] = None,
    source: str = "ir",
) -> QualityIssue:
    """Adapt `backend.eval.layout_diff.LayoutDefect` to the canonical contract."""
    defect_type = str(getattr(defect, "defect_type", "unknown"))
    return QualityIssue(
        code=IR_DEFECT_CODE_MAP.get(defect_type, defect_type),
        severity=normalize_severity(getattr(defect, "severity", SEVERITY_INFO)),
        message=str(getattr(defect, "description", "")),
        slide_id=slide_id,
        element_ids=list(getattr(defect, "element_ids", None) or []),
        details=dict(getattr(defect, "details", None) or {}),
        suggested_fix=(
            dict(defect.suggested_fix) if getattr(defect, "suggested_fix", None) else None
        ),
        source=source,
    )


def quality_issue_from_visual_issue(issue: Any, *, source: str = "layout") -> QualityIssue:
    """Adapt `backend.evaluation.schema.VisualIssue` to the canonical contract."""
    element_id = getattr(issue, "element_id", None)
    issue_type = getattr(issue, "issue_type", "unknown")
    return QualityIssue(
        code=str(getattr(issue_type, "value", issue_type)).lower(),
        severity=normalize_severity(getattr(issue, "severity", SEVERITY_INFO)),
        message=str(getattr(issue, "description", "")),
        slide_id=getattr(issue, "slide_id", None),
        element_ids=[element_id] if element_id else [],
        details=dict(getattr(issue, "evidence", None) or {}),
        source=source,
    )


def quality_issue_from_fidelity_issue(
    issue: Any,
    *,
    slide_id: Optional[str] = None,
    source: str = "fidelity",
) -> QualityIssue:
    """Adapt `backend.eval.fidelity.report.FidelityIssue` to the canonical contract."""
    element = getattr(issue, "element", None)
    issue_type = getattr(issue, "type", "fidelity_issue")
    expected = getattr(issue, "expected", None)
    actual = getattr(issue, "actual", None)
    return QualityIssue(
        code=str(issue_type),
        severity=normalize_severity(getattr(issue, "severity", SEVERITY_INFO)),
        message=f"expected={expected!r}, actual={actual!r}",
        slide_id=slide_id,
        element_ids=[element] if element else [],
        details={"expected": expected, "actual": actual},
        source=source,
    )


def _dedupe_issues(issues: Iterable[QualityIssue]) -> List[QualityIssue]:
    seen = set()
    result: List[QualityIssue] = []
    for issue in issues:
        key = (issue.slide_id, issue.code, tuple(sorted(issue.element_ids)))
        if key in seen:
            continue
        seen.add(key)
        result.append(issue)
    return result


@dataclass
class QualityReport:
    """Unified quality report for a slide or deck.

    `dimensions` keeps engine-native metric names (IR: geometry/readability/
    contrast/balance/aesthetics; fidelity: geometry/text/style/visual). Scores
    are never averaged across engines: `merge_reports` keeps the worst score
    while preserving every issue.
    """

    source: str = "ir"
    slide_id: Optional[str] = None
    score: Optional[float] = None
    dimensions: Dict[str, float] = field(default_factory=dict)
    issues: List[QualityIssue] = field(default_factory=list)
    degraded: bool = False
    visual_source: Optional[str] = None
    passed: bool = True
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def has_blocking_issues(self) -> bool:
        return any(i.is_blocking for i in self.issues)

    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == SEVERITY_CRITICAL)

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == SEVERITY_WARNING)

    @property
    def info_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == SEVERITY_INFO)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "slide_id": self.slide_id,
            "score": self.score,
            "dimensions": dict(self.dimensions),
            "issues": [i.to_dict() for i in self.issues],
            "degraded": self.degraded,
            "visual_source": self.visual_source,
            "passed": self.passed,
            "has_blocking_issues": self.has_blocking_issues,
            "counts": {
                "critical": self.critical_count,
                "warning": self.warning_count,
                "info": self.info_count,
            },
            "meta": dict(self.meta),
        }

    @classmethod
    def from_health_report(cls, report: Any, *, source: str = "ir") -> "QualityReport":
        dimensions = {
            k: float(v)
            for k, v in report.quality_score.to_dict().items()
            if k != "total" and isinstance(v, (int, float))
        }
        return cls(
            source=source,
            slide_id=getattr(report, "slide_id", None),
            score=float(report.score),
            dimensions=dimensions,
            issues=[
                quality_issue_from_layout_defect(d, slide_id=getattr(report, "slide_id", None))
                for d in report.defects
            ],
            passed=not report.has_critical_defects,
        )

    @classmethod
    def from_visual_issues(
        cls,
        issues: Iterable[Any],
        *,
        slide_id: Optional[str] = None,
        source: str = "layout",
    ) -> "QualityReport":
        converted = [quality_issue_from_visual_issue(i) for i in issues]
        return cls(
            source=source,
            slide_id=slide_id,
            issues=converted,
            passed=not any(i.is_blocking for i in converted),
        )

    @classmethod
    def from_fidelity_score(
        cls,
        score: Any,
        *,
        slide_id: Optional[str] = None,
        source: str = "fidelity",
    ) -> "QualityReport":
        return cls(
            source=source,
            slide_id=slide_id,
            score=float(score.total),
            dimensions={
                "geometry": float(score.geometry),
                "text": float(score.text),
                "style": float(score.style),
                "visual": float(score.visual),
            },
            degraded=bool(score.degraded),
            visual_source=getattr(score, "visual_source", None),
            passed=bool(score.passed),
        )


def merge_reports(*reports: Optional[QualityReport], source: str = "aggregate") -> QualityReport:
    """Merge reports from different engines without averaging scores.

    Semantics: worst score wins, issues are concatenated and deduplicated,
    `degraded`/`passed` are AND/OR aggregated by their pessimistic value.
    """
    present = [r for r in reports if r is not None]
    if not present:
        return QualityReport(source=source)

    scores = [r.score for r in present if r.score is not None]
    dimensions: Dict[str, float] = {}
    for report in present:
        dimensions.update(report.dimensions)

    return QualityReport(
        source=source,
        slide_id=next((r.slide_id for r in present if r.slide_id), None),
        score=min(scores) if scores else None,
        dimensions=dimensions,
        issues=_dedupe_issues(i for r in present for i in r.issues),
        degraded=any(r.degraded for r in present),
        visual_source=next((r.visual_source for r in present if r.visual_source), None),
        passed=all(r.passed for r in present),
        meta={"sources": [r.source for r in present]},
    )
