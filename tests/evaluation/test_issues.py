"""Tests for Visual Issue utilities and aggregators (PR12)."""

import json

from backend.evaluation.issues import (
    deduplicate_issues,
    deserialize_issues_json,
    filter_issues_by_severity,
    group_issues_by_slide,
    has_blocking_errors,
    serialize_issues_json,
)
from backend.evaluation.schema import IssueSeverity, IssueType, VisualIssue


def test_group_issues_by_slide() -> None:
    issues = [
        VisualIssue(slide="s1", issue=IssueType.OVERFLOW, description="err1"),
        VisualIssue(slide="s1", issue=IssueType.TOO_SMALL, description="warn1"),
        VisualIssue(slide="s2", issue=IssueType.TEXT_OVERFLOW, description="err2"),
    ]

    grouped = group_issues_by_slide(issues)
    assert len(grouped) == 2
    assert len(grouped["s1"]) == 2
    assert len(grouped["s2"]) == 1


def test_filter_issues_by_severity() -> None:
    issues = [
        VisualIssue(slide="s1", issue=IssueType.TOO_SMALL, severity=IssueSeverity.INFO, description="i"),
        VisualIssue(slide="s1", issue=IssueType.TOO_SMALL, severity=IssueSeverity.WARNING, description="w"),
        VisualIssue(slide="s1", issue=IssueType.OVERFLOW, severity=IssueSeverity.ERROR, description="e"),
        VisualIssue(slide="s1", issue=IssueType.OVERFLOW, severity=IssueSeverity.CRITICAL, description="c"),
    ]

    warnings_up = filter_issues_by_severity(issues, IssueSeverity.WARNING)
    assert len(warnings_up) == 3

    errors_up = filter_issues_by_severity(issues, IssueSeverity.ERROR)
    assert len(errors_up) == 2
    assert {i.severity for i in errors_up} == {IssueSeverity.ERROR, IssueSeverity.CRITICAL}


def test_has_blocking_errors() -> None:
    warning_only = [
        VisualIssue(slide="s1", issue=IssueType.TOO_SMALL, severity=IssueSeverity.WARNING, description="w"),
    ]
    assert has_blocking_errors(warning_only) is False

    with_error = warning_only + [
        VisualIssue(slide="s1", issue=IssueType.OVERFLOW, severity=IssueSeverity.ERROR, description="e"),
    ]
    assert has_blocking_errors(with_error) is True


def test_deduplicate_issues() -> None:
    issues = [
        VisualIssue(slide="s1", issue=IssueType.OVERFLOW, element="e1", description="first"),
        VisualIssue(slide="s1", issue=IssueType.OVERFLOW, element="e1", description="duplicate"),
        VisualIssue(slide="s1", issue=IssueType.OVERFLOW, element="e2", description="different elem"),
    ]

    deduped = deduplicate_issues(issues)
    assert len(deduped) == 2
    assert deduped[0].description == "first"
    assert deduped[1].element_id == "e2"


def test_serialize_and_deserialize_issues_json() -> None:
    issues = [
        VisualIssue(
            slide="slide_a",
            issue=IssueType.OVERFLOW,
            severity=IssueSeverity.ERROR,
            element="box1",
            description="Box overflows",
            evidence={"margin": 0},
        ),
        VisualIssue(
            slide="slide_b",
            issue=IssueType.BAD_ALIGNMENT,
            severity=IssueSeverity.WARNING,
            element="box2",
            description="Box misaligned",
        ),
    ]

    serialized = serialize_issues_json(issues)
    restored = deserialize_issues_json(serialized)
    assert len(restored) == 2
    assert restored[0].slide_id == "slide_a"
    assert restored[0].issue_type == IssueType.OVERFLOW
    assert restored[1].slide_id == "slide_b"
    assert restored[1].issue_type == IssueType.BAD_ALIGNMENT
