"""Tests for MutationEvent and Mutation History Tracking (Task 4)."""

import pytest
from backend.ir.models import PresentationIR, SlideIR, ShapeElementIR, TextElementIR, TextContentIR
from backend.ir.history_event import MutationEvent
from backend.ir.patch import HistoryManager
from backend.agent.tools import tools


def test_mutation_event_dataclass_and_serialization():
    """Verify MutationEvent fields and serialization roundtrip."""
    ev = MutationEvent(
        action="update_element",
        element_id="elem_42",
        before={"x": 100.0, "y": 150.0},
        after={"x": 900.0, "y": 150.0},
        timestamp="1234567.89",
        source="agent_tool"
    )

    d = ev.to_dict()
    assert d["action"] == "update_element"
    assert d["element_id"] == "elem_42"
    assert d["before"]["x"] == 100.0
    assert d["after"]["x"] == 900.0
    assert d["source"] == "agent_tool"

    rebuilt = MutationEvent.from_dict(d)
    assert rebuilt.action == ev.action
    assert rebuilt.element_id == ev.element_id
    assert rebuilt.before == ev.before
    assert rebuilt.after == ev.after
    assert rebuilt.source == ev.source


def test_history_manager_produces_mutation_events():
    """Verify that tools executed against PresentationIR produce structured MutationEvents in HistoryManager."""
    pres = PresentationIR(title="Mutation Test Deck")
    slide = SlideIR(id="slide_mut_1", slide_num=1, width=1280, height=720)
    pres.slides = [slide]
    history = HistoryManager()

    # 1. Execute tool: add_text
    res1 = tools.execute("add_text", {"text": "Original Title", "x": 100, "y": 100, "slide_id": "slide_mut_1"}, pres, history)
    assert res1["success"] is True
    elem_id = res1["element_id"]

    # 2. Execute tool: update_element
    res2 = tools.execute("update_element", {"element_id": elem_id, "x": 900, "slide_id": "slide_mut_1"}, pres, history)
    assert res2["success"] is True

    # 3. Retrieve mutation events from history
    events = history.get_mutation_events()
    assert len(events) == 2
    assert isinstance(events[0], MutationEvent)
    assert events[0].action == "add_element"
    assert events[0].element_id == elem_id
    assert events[0].after.get("x") == 100

    assert events[1].action == "update_element"
    assert events[1].element_id == elem_id
    assert events[1].before.get("x") == 100
    assert events[1].after.get("x") == 900


def test_mutation_event_source_attribute_differentiation():
    """Verify that source attribute correctly distinguishes agent tool mutations from remediation fixes."""
    history = HistoryManager()
    pres = PresentationIR(title="Source Test Deck")
    slide = SlideIR(id="s1", slide_num=1, width=1280, height=720)
    pres.slides = [slide]

    # Record agent tool mutation
    history.record(
        action="update_element",
        description="Agent moved title",
        slide_id="s1",
        element_id="title_1",
        before={"x": 100.0},
        after={"x": 900.0},
        source="agent_tool"
    )

    # Record remediation auto-fix mutation
    history.record(
        action="clamp_viewport",
        description="Remediation clamped container",
        slide_id="s1",
        element_id="card_1",
        before={"width": 1400.0},
        after={"width": 1200.0},
        source="remediation"
    )

    events = history.get_mutation_events()
    assert len(events) == 2
    assert events[0].source == "agent_tool"
    assert events[0].action == "update_element"
    assert events[1].source == "remediation"
    assert events[1].action == "clamp_viewport"


def test_mutation_history_delete_element():
    """Verify that deleting an element preserves before state in MutationEvent."""
    history = HistoryManager()
    pres = PresentationIR(title="Delete Deck")
    slide = SlideIR(id="s_del", slide_num=1, width=1280, height=720)
    shape = ShapeElementIR(id="box_to_delete", x=50.0, y=50.0, width=200.0, height=100.0)
    slide.add_element(shape)
    pres.slides = [slide]

    res = tools.execute("delete_element", {"element_id": "box_to_delete", "slide_id": "s_del"}, pres, history)
    assert res["success"] is True

    events = history.get_mutation_events()
    assert len(events) == 1
    assert events[0].action == "delete_element"
    assert events[0].element_id == "box_to_delete"
    assert events[0].before.get("id") == "box_to_delete"
