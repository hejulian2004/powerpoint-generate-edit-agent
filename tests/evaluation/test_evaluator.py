"""Tests for Visual Evaluator and Rule-Based Defect Detection (PR12 Test 3)."""

import json
from typing import Any, Dict

import pytest

from backend.evaluation.evaluator import OpenAICompatibleVisionEvaluator, RuleBasedEvaluator
from backend.evaluation.schema import IssueSeverity, IssueType
from backend.layout.schema import (
    Canvas,
    ElementStyle,
    ElementType,
    LayoutElement,
    LayoutSpec,
    Rect,
    TextStyle,
)
from backend.slidespec.schema import VisualIntent


def test_detect_text_overflow_500_chars_in_20px_height() -> None:
    """Test 3: title box height=20, text=500 chars -> expects TEXT_OVERFLOW."""
    long_text = (
        "This is an extraordinarily verbose presentation title designed specifically "
        "to test the layout visual evaluator boundary conditions. It contains well over "
        "five hundred characters and cannot possibly fit into a tiny twenty pixel vertical "
        "bounding box without causing severe visual clipping and severe overflow defects "
        "across the presentation canvas. " * 2
    )
    assert len(long_text) >= 500

    slide = LayoutSpec(
        slide_id="slide_overflow_test",
        slide_index=1,
        visual_intent=VisualIntent.TITLE_HERO,
        canvas=Canvas(width=1280, height=720),
        elements=[
            LayoutElement(
                element_id="overflow_title",
                element_type=ElementType.TEXT,
                geometry=Rect(x=100.0, y=50.0, width=600.0, height=20.0),
                style=ElementStyle(text=TextStyle(font_size=24.0)),
                content=long_text,
            )
        ],
    )

    evaluator = RuleBasedEvaluator()
    issues = evaluator.evaluate(slide_image=None, layout_spec=slide)

    overflow_issues = [i for i in issues if i.issue_type == IssueType.TEXT_OVERFLOW]
    assert len(overflow_issues) == 1
    assert overflow_issues[0].element_id == "overflow_title"
    assert overflow_issues[0].severity == IssueSeverity.ERROR
    assert "overflow" in overflow_issues[0].description.lower()


def test_detect_canvas_bounds_overflow() -> None:
    """Verify detection of negative coordinates and canvas boundary violations."""
    slide = LayoutSpec(
        slide_id="slide_bounds_test",
        slide_index=1,
        visual_intent=VisualIntent.BENCHMARK_COMPARISON,
        canvas=Canvas(width=1280, height=720),
        elements=[
            LayoutElement(
                element_id="neg_elem",
                element_type=ElementType.TEXT,
                geometry=Rect(x=-30.0, y=50.0, width=200.0, height=100.0),
                content="Negative X coordinate",
            ),
            LayoutElement(
                element_id="exceed_elem",
                element_type=ElementType.TEXT,
                geometry=Rect(x=1200.0, y=650.0, width=200.0, height=100.0),
                content="Exceeds right and bottom",
            ),
        ],
    )

    evaluator = RuleBasedEvaluator()
    issues = evaluator.evaluate(slide_image=None, layout_spec=slide)

    overflow_issues = [i for i in issues if i.issue_type == IssueType.OVERFLOW]
    assert len(overflow_issues) == 2
    element_ids = {i.element_id for i in overflow_issues}
    assert "neg_elem" in element_ids
    assert "exceed_elem" in element_ids


def test_detect_element_collision_overlap() -> None:
    """Verify detection of overlapping foreground elements."""
    slide = LayoutSpec(
        slide_id="slide_overlap_test",
        slide_index=1,
        visual_intent=VisualIntent.TWO_COLUMN_CONTRAST,
        canvas=Canvas(width=1280, height=720),
        elements=[
            LayoutElement(
                element_id="card_left",
                element_type=ElementType.TEXT,
                geometry=Rect(x=200.0, y=200.0, width=300.0, height=200.0),
                content="Left card text content",
            ),
            LayoutElement(
                element_id="card_right",
                element_type=ElementType.TEXT,
                geometry=Rect(x=250.0, y=250.0, width=300.0, height=200.0),
                content="Right card colliding directly with left card",
            ),
        ],
    )

    evaluator = RuleBasedEvaluator()
    issues = evaluator.evaluate(slide_image=None, layout_spec=slide)

    overlap_issues = [i for i in issues if i.issue_type == IssueType.OVERLAP]
    assert len(overlap_issues) >= 1
    assert overlap_issues[0].severity == IssueSeverity.ERROR


def test_detect_undersized_figure() -> None:
    """Verify detection of abnormally small figure elements (<20% / tiny dimension)."""
    slide = LayoutSpec(
        slide_id="slide_fig_size",
        slide_index=1,
        visual_intent=VisualIntent.PIPELINE_ARCHITECTURE,
        canvas=Canvas(width=1280, height=720),
        elements=[
            LayoutElement(
                element_id="tiny_fig",
                element_type=ElementType.FIGURE,
                geometry=Rect(x=500.0, y=300.0, width=80.0, height=60.0),
                content={"figure_id": "fig_icon"},
            )
        ],
    )

    evaluator = RuleBasedEvaluator()
    issues = evaluator.evaluate(slide_image=None, layout_spec=slide)

    small_issues = [i for i in issues if i.issue_type == IssueType.TOO_SMALL]
    assert len(small_issues) == 1
    assert small_issues[0].element_id == "tiny_fig"


def test_detect_wrong_scale_aspect_ratio() -> None:
    """Verify detection of distorted figure aspect ratios."""
    slide = LayoutSpec(
        slide_id="slide_scale_test",
        slide_index=1,
        visual_intent=VisualIntent.PIPELINE_ARCHITECTURE,
        canvas=Canvas(width=1280, height=720),
        elements=[
            LayoutElement(
                element_id="distorted_fig",
                element_type=ElementType.FIGURE,
                geometry=Rect(x=100.0, y=100.0, width=600.0, height=60.0),  # ratio = 10.0
                content={"figure_id": "fig_banner"},
            )
        ],
    )

    evaluator = RuleBasedEvaluator()
    issues = evaluator.evaluate(slide_image=None, layout_spec=slide)

    scale_issues = [i for i in issues if i.issue_type == IssueType.WRONG_SCALE]
    assert len(scale_issues) == 1
    assert scale_issues[0].element_id == "distorted_fig"


def test_openai_compatible_vision_evaluator_adapter() -> None:
    """Verify OpenAICompatibleVisionEvaluator payload construction and response parsing."""
    mock_response = {
        "choices": [
            {
                "message": {
                    "content": """```json
[
  {
    "slide": "slide_vlm",
    "issue": "LOW_CONTRAST",
    "severity": "WARNING",
    "element": "txt_sub",
    "description": "Subtitle text contrast is insufficient against light background",
    "evidence": {"contrast_ratio": 2.1}
  }
]
```"""
                }
            }
        ]
    }

    def mock_client_fn(payload: Dict[str, Any]) -> Dict[str, Any]:
        # Validate payload format
        assert payload["model"] == "gpt-4o"
        assert len(payload["messages"]) == 2
        return mock_response

    evaluator = OpenAICompatibleVisionEvaluator(
        api_key="mock_key",
        client_fn=mock_client_fn,
    )

    slide = LayoutSpec(
        slide_id="slide_vlm",
        slide_index=1,
        visual_intent=VisualIntent.TITLE_HERO,
        canvas=Canvas(width=1280, height=720),
        elements=[
            LayoutElement(
                element_id="txt_sub",
                element_type=ElementType.TEXT,
                geometry=Rect(x=100.0, y=100.0, width=500.0, height=40.0),
                content="Mock subtitle",
            )
        ],
    )

    issues = evaluator.evaluate(slide_image=None, layout_spec=slide)
    assert len(issues) == 1
    assert issues[0].issue_type == IssueType.LOW_CONTRAST
    assert issues[0].element_id == "txt_sub"
    assert issues[0].severity == IssueSeverity.WARNING


def test_detect_high_text_density() -> None:
    """Verify detection of high text density (char-to-area ratio)."""
    dense_text = "Dense academic narrative summarizing method components in extreme detail. " * 5
    slide = LayoutSpec(
        slide_id="slide_dense",
        slide_index=1,
        visual_intent=VisualIntent.KEY_TAKEAWAY_LIST,
        canvas=Canvas(width=1280, height=720),
        elements=[
            LayoutElement(
                element_id="dense_box",
                element_type=ElementType.TEXT,
                geometry=Rect(x=100.0, y=100.0, width=200.0, height=100.0),
                content=dense_text,
            )
        ],
    )

    evaluator = RuleBasedEvaluator()
    issues = evaluator.evaluate(slide_image=None, layout_spec=slide)
    density_issues = [i for i in issues if i.issue_type == IssueType.TEXT_DENSITY_HIGH]
    assert len(density_issues) >= 1
    assert density_issues[0].element_id == "dense_box"


def test_evaluator_unconfigured_vlm_graceful_degradation() -> None:
    """Unconfigured VLM evaluator returns empty issues without throwing exceptions."""
    evaluator = OpenAICompatibleVisionEvaluator(api_key="", client_fn=None)
    assert evaluator.is_configured() is False
    slide = LayoutSpec(
        slide_id="s1",
        slide_index=1,
        visual_intent=VisualIntent.TITLE_HERO,
        canvas=Canvas(width=1280, height=720),
        elements=[],
    )
    assert evaluator.evaluate(None, slide) == []


def test_empty_text_no_false_positive_overflow() -> None:
    """Empty or whitespace-only text elements must not trigger false TEXT_OVERFLOW."""
    slide = LayoutSpec(
        slide_id="slide_empty_text",
        slide_index=1,
        visual_intent=VisualIntent.TITLE_HERO,
        canvas=Canvas(width=1280, height=720),
        elements=[
            LayoutElement(
                element_id="empty_box",
                element_type=ElementType.TEXT,
                geometry=Rect(x=100.0, y=100.0, width=500.0, height=15.0),
                content="   \n  ",
            )
        ],
    )

    evaluator = RuleBasedEvaluator()
    issues = evaluator.evaluate(slide_image=None, layout_spec=slide)
    overflow_issues = [i for i in issues if i.issue_type == IssueType.TEXT_OVERFLOW]
    assert len(overflow_issues) == 0


def test_vlm_evaluator_raises_on_error_or_malformed_json() -> None:
    """Configured VLM evaluator raises VisualEvaluationError on API errors or malformed JSON."""
    from backend.evaluation.schema import VisualEvaluationError

    # 1. API exception / timeout
    def failing_client(payload):
        raise TimeoutError("Connection timed out after 30s")

    evaluator = OpenAICompatibleVisionEvaluator(api_key="sk-fake", client_fn=failing_client)
    slide = LayoutSpec(
        slide_id="s1",
        slide_index=1,
        visual_intent=VisualIntent.TITLE_HERO,
        canvas=Canvas(width=1280, height=720),
        elements=[],
    )
    with pytest.raises(VisualEvaluationError, match="Connection timed out"):
        evaluator.evaluate(None, slide)

    # 2. Malformed JSON response
    def malformed_client(payload):
        return {"choices": [{"message": {"content": "This is plain text not JSON"}}]}

    evaluator2 = OpenAICompatibleVisionEvaluator(api_key="sk-fake", client_fn=malformed_client)
    with pytest.raises(VisualEvaluationError, match="not valid JSON"):
        evaluator2.evaluate(None, slide)

    # 3. Valid JSON but violates schema
    def invalid_schema_client(payload):
        return {"choices": [{"message": {"content": json.dumps({"unrelated": "payload"})}}]}

    evaluator3 = OpenAICompatibleVisionEvaluator(api_key="sk-fake", client_fn=invalid_schema_client)
    with pytest.raises(VisualEvaluationError, match="missing 'issues' field"):
        evaluator3.evaluate(None, slide)



