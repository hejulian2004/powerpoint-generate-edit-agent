"""Tests for Visual Issue and Layout Patch Schemas (PR12 Test 2)."""

import json

from backend.evaluation.schema import (
    IssueSeverity,
    IssueType,
    LayoutPatch,
    PatchOperation,
    RepairIterationRecord,
    SelfHealingResult,
    VisualIssue,
)


def test_visual_issue_json_roundtrip() -> None:
    """Test 2: VisualIssue serialization and deserialization (issue -> json -> issue)."""
    original = VisualIssue(
        slide_id="slide_intro",
        issue_type=IssueType.TEXT_OVERFLOW,
        severity=IssueSeverity.ERROR,
        element_id="title_hero",
        description="Title exceeds bounding box height",
        evidence={"char_count": 450, "box_height": 24.0, "lines_needed": 8},
    )

    # Serialize to JSON string
    json_str = original.to_json()
    assert "TEXT_OVERFLOW" in json_str
    assert "title_hero" in json_str

    # Restore from JSON
    restored = VisualIssue.from_json(json_str)
    assert restored.slide_id == original.slide_id
    assert restored.issue_type == original.issue_type
    assert restored.severity == original.severity
    assert restored.element_id == original.element_id
    assert restored.description == original.description
    assert restored.evidence == original.evidence


def test_visual_issue_field_aliases() -> None:
    """Ensure aliases like 'slide', 'issue', 'element' match external JSON format."""
    raw_payload = {
        "slide": "slide_3",
        "issue": "OVERLAP",
        "severity": "ERROR",
        "element": "figure_1",
        "description": "Figure overlaps with summary bullet",
        "evidence": {"overlap_ratio": 0.45},
    }

    issue = VisualIssue.from_dict(raw_payload)
    assert issue.slide_id == "slide_3"
    assert issue.issue_type == IssueType.OVERLAP
    assert issue.element_id == "figure_1"
    assert issue.severity == IssueSeverity.ERROR

    # Exported dict with aliases
    dumped = issue.to_dict()
    assert dumped["slide"] == "slide_3"
    assert dumped["issue"] == "OVERLAP"
    assert dumped["element"] == "figure_1"


def test_layout_patch_roundtrip() -> None:
    """Verify LayoutPatch serialization and parameter validation."""
    patch = LayoutPatch(
        slide_id="slide_method",
        target_element="fig_arch",
        operation=PatchOperation.RESIZE,
        parameters={"scale": 1.5, "keep_center": True},
        description="Enlarge architecture diagram to fill canvas",
    )

    p_json = patch.to_json()
    restored = LayoutPatch.from_json(p_json)
    assert restored.slide_id == "slide_method"
    assert restored.target_element == "fig_arch"
    assert restored.operation == PatchOperation.RESIZE
    assert restored.parameters["scale"] == 1.5
    assert restored.parameters["keep_center"] is True


def test_self_healing_result_serialization() -> None:
    """Verify SelfHealingResult model serialization."""
    record = RepairIterationRecord(
        iteration=1,
        issues_detected=[
            VisualIssue(
                slide="s1",
                issue=IssueType.OVERFLOW,
                severity=IssueSeverity.ERROR,
                element="el_1",
                description="Overflow canvas",
            )
        ],
        patches_applied=[
            LayoutPatch(
                slide_id="s1",
                target_element="el_1",
                operation=PatchOperation.CLAMP_TO_CANVAS,
                parameters={"margin": 20.0},
            )
        ],
        screenshot_paths=["slides/1.png"],
        error_count=1,
        warning_count=0,
    )

    result = SelfHealingResult(
        converged=True,
        iterations_run=1,
        final_issues=[],
        history=[record],
        final_pptx_path="out.pptx",
        final_screenshot_paths=["slides/1.png"],
    )

    data = result.model_dump(mode="json")
    assert data["converged"] is True
    assert data["iterations_run"] == 1
    assert len(data["history"]) == 1
    assert data["history"][0]["patches_applied"][0]["operation"] == "CLAMP_TO_CANVAS"
