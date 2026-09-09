"""Visual Issue Utilities and Aggregators (PR12).

Provides helper routines for filtering, grouping, deduplicating,
and serializing collections of VisualIssue records.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

from .schema import IssueSeverity, IssueType, VisualIssue

SEVERITY_ORDER = {
    IssueSeverity.INFO: 0,
    IssueSeverity.WARNING: 1,
    IssueSeverity.ERROR: 2,
    IssueSeverity.CRITICAL: 3,
}


def group_issues_by_slide(issues: List[VisualIssue]) -> Dict[str, List[VisualIssue]]:
    """Group issues by their associated slide_id."""
    grouped: Dict[str, List[VisualIssue]] = defaultdict(list)
    for issue in issues:
        grouped[issue.slide_id].append(issue)
    return dict(grouped)


def filter_issues_by_severity(
    issues: List[VisualIssue],
    min_severity: IssueSeverity = IssueSeverity.WARNING,
) -> List[VisualIssue]:
    """Filter issues to retain only those >= min_severity."""
    threshold = SEVERITY_ORDER.get(min_severity, 0)
    return [issue for issue in issues if SEVERITY_ORDER.get(issue.severity, 0) >= threshold]


def has_blocking_errors(issues: List[VisualIssue]) -> bool:
    """Check if any issues have ERROR or CRITICAL severity."""
    return any(issue.severity in (IssueSeverity.ERROR, IssueSeverity.CRITICAL) for issue in issues)


def deduplicate_issues(issues: List[VisualIssue]) -> List[VisualIssue]:
    """Deduplicate issues having identical (slide_id, issue_type, element_id)."""
    seen: Set[Tuple[str, IssueType, Optional[str]]] = set()
    deduped: List[VisualIssue] = []
    for issue in issues:
        key = (issue.slide_id, issue.issue_type, issue.element_id)
        if key not in seen:
            seen.add(key)
            deduped.append(issue)
    return deduped


def serialize_issues_json(issues: List[VisualIssue], indent: Optional[int] = 2) -> str:
    """Serialize a list of VisualIssue objects into standard JSON string."""
    data = [issue.to_dict() for issue in issues]
    return json.dumps(data, indent=indent)


def deserialize_issues_json(json_str: str) -> List[VisualIssue]:
    """Deserialize a JSON string into a list of VisualIssue objects."""
    raw = json.loads(json_str)
    if isinstance(raw, dict) and "issues" in raw:
        raw = raw["issues"]
    if not isinstance(raw, list):
        raw = [raw]
    return [VisualIssue.from_dict(item) for item in raw]
