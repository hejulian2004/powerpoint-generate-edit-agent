"""Unified quality facade over `backend.eval` (SlideIR) and `backend.evaluation` (LayoutSpec).

Import `QualityService` and the canonical contracts from here; the underlying
engines keep their own modules for backward compatibility.
"""

from .contracts import (
    IR_DEFECT_CODE_MAP,
    SEVERITY_CRITICAL,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    QualityIssue,
    QualityReport,
    merge_reports,
    normalize_severity,
    quality_issue_from_fidelity_issue,
    quality_issue_from_layout_defect,
    quality_issue_from_visual_issue,
    severity_rank,
)
from .service import FIDELITY_SOURCE, IR_SOURCE, LAYOUT_SOURCE, QualityService

__all__ = [
    "QualityService",
    "QualityIssue",
    "QualityReport",
    "merge_reports",
    "normalize_severity",
    "severity_rank",
    "quality_issue_from_layout_defect",
    "quality_issue_from_visual_issue",
    "quality_issue_from_fidelity_issue",
    "IR_DEFECT_CODE_MAP",
    "SEVERITY_CRITICAL",
    "SEVERITY_ERROR",
    "SEVERITY_WARNING",
    "SEVERITY_INFO",
    "IR_SOURCE",
    "LAYOUT_SOURCE",
    "FIDELITY_SOURCE",
]
