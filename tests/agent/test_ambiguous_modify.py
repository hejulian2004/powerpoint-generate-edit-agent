"""Phase 6: an ambiguous modify asks for clarification instead of inventing a shape."""

from backend.agent.graph import _heuristic_tool_planner
from backend.ir.models import (
    FillStyle,
    PresentationIR,
    SlideIR,
    TextContentIR,
    TextElementIR,
)


def _pres_with_text() -> PresentationIR:
    pres = PresentationIR(title="Deck", slides=[])
    slide = SlideIR(
        id="s1", slide_num=1, width=1280, height=720,
        background=FillStyle(type="solid", color="#FFFFFF"),
    )
    slide.add_element(TextElementIR(
        id="t1", x=40.0, y=40.0, width=400.0, height=60.0,
        text_content=TextContentIR.from_plain_text("标题"),
    ))
    pres.slides.append(slide)
    pres.active_slide_id = "s1"
    return pres


def test_ambiguous_modify_never_emits_generic_add_shape():
    pres = _pres_with_text()
    calls = _heuristic_tool_planner(
        "modify_elements", "帮我优化一下", pres,
        last_target_id=None, selected_element_ids=[], primary_selected_element_id=None,
    )
    names = [c.get("name") for c in calls]
    assert "add_shape" not in names
    assert names == ["request_clarification"]
    assert calls[0]["arguments"]["question"]


def test_deictic_modify_without_selection_fails_closed_to_empty_plan():
    pres = _pres_with_text()
    calls = _heuristic_tool_planner(
        "modify_elements", "把这个改红", pres,
        last_target_id=None, selected_element_ids=[], primary_selected_element_id=None,
    )
    assert calls == []
