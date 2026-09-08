"""ActionRiskPolicy tests (PR6.1 Task 2).

Verifies per-action-type risk thresholds gate semantic resolution confirmation:
- delete requires confidence >= 0.95
- move / resize require confidence >= 0.85
- style (color) changes require confidence >= 0.75
- unknown action types fall back to the default threshold 0.80
- ActionResolver.action_to_tool_call surfaces _needs_confirmation per the policy
"""

import pytest

from backend.agent.risk_policy import (
    ActionRiskPolicy,
    RISK_LEVELS,
    DEFAULT_THRESHOLD,
)
from backend.agent.action import ActionResolver, AgentAction
from backend.ir.models import PresentationIR, SlideIR, TextElementIR, TextContentIR


# =====================================================================
# Policy unit tests
# =====================================================================

def test_delete_requires_highest_confidence():
    assert ActionRiskPolicy.threshold("delete_element") == 0.95
    assert ActionRiskPolicy.threshold("delete_slide") == 0.95
    assert ActionRiskPolicy.threshold("clear_slide_elements") == 0.95
    # 0.94 is not enough for delete
    assert ActionRiskPolicy.needs_confirmation(0.94, "delete_element") is True
    assert ActionRiskPolicy.needs_confirmation(0.95, "delete_element") is False


def test_move_and_resize_require_085():
    assert ActionRiskPolicy.threshold("move_element") == 0.85
    assert ActionRiskPolicy.threshold("reposition_element") == 0.85
    assert ActionRiskPolicy.threshold("resize_text") == 0.85
    assert ActionRiskPolicy.threshold("resize_element") == 0.85
    # 0.80 is not enough for move
    assert ActionRiskPolicy.needs_confirmation(0.80, "move_element") is True
    assert ActionRiskPolicy.needs_confirmation(0.85, "resize_text") is False


def test_style_color_change_is_low_risk():
    assert ActionRiskPolicy.threshold("format_text") == 0.75
    assert ActionRiskPolicy.threshold("update_element") == 0.75
    assert ActionRiskPolicy.threshold("set_color") == 0.75
    # 0.75 suffices for color styling
    assert ActionRiskPolicy.needs_confirmation(0.75, "set_color") is False
    assert ActionRiskPolicy.needs_confirmation(0.74, "format_text") is True


def test_unknown_action_type_falls_back_to_default():
    assert ActionRiskPolicy.threshold("totally_unknown_action") == DEFAULT_THRESHOLD
    assert ActionRiskPolicy.threshold("apply_theme") == DEFAULT_THRESHOLD
    assert ActionRiskPolicy.needs_confirmation(DEFAULT_THRESHOLD - 0.01, "apply_theme") is True
    assert ActionRiskPolicy.needs_confirmation(DEFAULT_THRESHOLD, "apply_theme") is False


def test_none_confidence_always_confirms():
    assert ActionRiskPolicy.needs_confirmation(None, "format_text") is True
    assert ActionRiskPolicy.needs_confirmation(None, "delete_element") is True


def test_risk_levels_monotonic():
    assert RISK_LEVELS["DELETE"] > RISK_LEVELS["MOVE"]
    assert RISK_LEVELS["MOVE"] >= RISK_LEVELS["RESIZE"]
    assert RISK_LEVELS["RESIZE"] > RISK_LEVELS["STYLE"]


# =====================================================================
# ActionResolver integration
# =====================================================================

def _pres_with_title():
    pres = PresentationIR(title="T")
    slide = SlideIR(id="slide_1", slide_num=1)
    slide.add_element(TextElementIR(
        id="elem_title", x=80.0, y=50.0, width=700.0, height=50.0,
        text_content=TextContentIR.from_plain_text("Quarterly Review")
    ))
    pres.slides.append(slide)
    pres.active_slide_id = slide.id
    return pres


def test_resolver_uses_per_action_threshold(monkeypatch):
    """Same resolution confidence yields different confirmation per action risk level."""
    monkeypatch.setattr(
        "backend.agent.risk_policy.RISK_LEVELS",
        {"DELETE": 0.99, "MOVE": 0.97, "RESIZE": 0.96, "STYLE": 0.01},
    )
    pres = _pres_with_title()  # title resolves at confidence 0.95

    style = ActionResolver.action_to_tool_call(
        AgentAction(action_type="format_text", target="title", parameters={"font_color": "#FF0000"}),
        pres
    )
    move = ActionResolver.action_to_tool_call(
        AgentAction(action_type="move_element", target="title", parameters={"x": 10}),
        pres
    )
    delete = ActionResolver.action_to_tool_call(
        AgentAction(action_type="delete_element", target="title", parameters={}),
        pres
    )
    assert style["_resolution_confidence"] == 0.95
    # 0.95 clears the STYLE bar (0.01) but not MOVE (0.97) nor DELETE (0.99)
    assert style["_needs_confirmation"] is False
    assert move["_needs_confirmation"] is True
    assert delete["_needs_confirmation"] is True


def test_exact_id_never_confirms_even_for_delete():
    pres = _pres_with_title()
    tool = ActionResolver.action_to_tool_call(
        AgentAction(action_type="delete_element", target="elem_title", parameters={}),
        pres
    )
    assert tool is not None
    assert tool["_resolution_confidence"] == 1.0
    assert tool["_needs_confirmation"] is False