"""Tests for AgentAction Contract, ActionResolver, and AgentIteration (Phases 5.5 & 5.6)."""

import pytest
from backend.ir.models import (
    PresentationIR, SlideIR, TextElementIR, ShapeElementIR,
    TextContentIR, FontIR
)
from backend.agent.action import AgentAction, ActionResolver
from backend.agent.iteration import AgentIteration


@pytest.fixture
def mock_presentation():
    pres = PresentationIR(title="Action Contract Deck")
    slide = SlideIR(
        id="slide_01",
        slide_num=1,
        elements=[
            TextElementIR(
                id="title_main",
                name="Title",
                x=120.0,
                y=80.0,
                width=800.0,
                height=60.0,
                text_content=TextContentIR.from_plain_text(
                    "AI 智能创新方案",
                    font=FontIR(name="Segoe UI", size=36.0, color="#FFFFFF", bold=True)
                )
            ),
            ShapeElementIR(
                id="card_01",
                name="Feature Card",
                shape_type="roundRect",
                x=120.0,
                y=200.0,
                width=300.0,
                height=200.0
            )
        ]
    )
    pres.slides = [slide]
    pres.active_slide_id = "slide_01"
    return pres


def test_agent_action_model_and_serialization():
    """Verify AgentAction serialization and roundtrip."""
    act = AgentAction(
        action_type="update_element",
        target="title_main",
        parameters={"x": 900.0, "y": 120.0},
        confidence=0.95,
        reason="User requested title move",
        relative=False
    )
    d = act.to_dict()
    assert d["action_type"] == "update_element"
    assert d["target"] == "title_main"
    assert d["parameters"]["x"] == 900.0
    assert d["confidence"] == 0.95
    assert d["relative"] is False

    reconstructed = AgentAction.from_dict(d)
    assert reconstructed.action_type == act.action_type
    assert reconstructed.target == act.target
    assert reconstructed.parameters == act.parameters
    assert reconstructed.relative == act.relative


def test_action_resolver_target_resolution(mock_presentation):
    """Verify semantic and ID-based target element resolution."""
    slide = mock_presentation.get_active_slide()

    # 1. Exact ID match
    el1 = ActionResolver.resolve_target_element("title_main", slide)
    assert el1 is not None
    assert el1.id == "title_main"

    # 2. Semantic "title" / "标题"
    el_title = ActionResolver.resolve_target_element("title", slide)
    assert el_title is not None
    assert el_title.id == "title_main"

    el_cn_title = ActionResolver.resolve_target_element("标题", slide)
    assert el_cn_title is not None
    assert el_cn_title.id == "title_main"

    # 3. Semantic "card" / "shape"
    el_card = ActionResolver.resolve_target_element("card", slide)
    assert el_card is not None
    assert el_card.id == "card_01"

    # 4. Contextual "last_target" resolution
    el_last = ActionResolver.resolve_target_element("last_target", slide, last_target_id="card_01")
    assert el_last is not None
    assert el_last.id == "card_01"


def test_action_resolver_relative_coordinates(mock_presentation):
    """Verify relative movement adds delta to current element coordinates."""
    # Target title_main at x=120.0, y=80.0
    act_move_down = AgentAction(
        action_type="update_element",
        target="last_target",
        parameters={"y": 50.0},
        relative=True,
        reason="Move down slightly"
    )

    tc = ActionResolver.action_to_tool_call(act_move_down, mock_presentation, last_target_id="title_main")
    assert tc is not None
    assert tc["name"] == "update_element"
    assert tc["arguments"]["element_id"] == "title_main"
    assert tc["arguments"]["y"] == 130.0  # 80.0 + 50.0

    act_move_right = AgentAction(
        action_type="update_element",
        target="title",
        parameters={"x": 100.0},
        relative=True
    )
    tc2 = ActionResolver.action_to_tool_call(act_move_right, mock_presentation)
    assert tc2 is not None
    assert tc2["arguments"]["x"] == 220.0  # 120.0 + 100.0


def test_action_resolver_formatting_actions(mock_presentation):
    """Verify format and style action conversions."""
    act_format = AgentAction(
        action_type="resize_text",
        target="title",
        parameters={"font_size": 44.0, "bold": True}
    )
    tc = ActionResolver.action_to_tool_call(act_format, mock_presentation)
    assert tc is not None
    assert tc["name"] == "format_text"
    assert tc["arguments"]["element_id"] == "title_main"
    assert tc["arguments"]["font_size"] == 44.0
    assert tc["arguments"]["bold"] is True


def test_agent_iteration_tracking():
    """Verify AgentIteration records score improvement and delta computation."""
    it = AgentIteration(
        iteration=1,
        score_before=75.0,
        score_after=92.5,
        changes=[{"tool": "align_elements"}],
        critique="Resolved overlap on card 1",
        applied_fixes=["reposition_element"]
    )
    assert it.iteration == 1
    assert it.delta == 17.5
    d = it.to_dict()
    assert d["delta"] == 17.5
    assert d["score_before"] == 75.0
    assert d["score_after"] == 92.5
    assert d["applied_fixes"] == ["reposition_element"]
