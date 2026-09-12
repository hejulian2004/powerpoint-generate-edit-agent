"""Undo/redo precision tests for composite slide/deck tools.

Every mutating tool must push a command with a valid inverse; a command whose
undo() fails (a "poison" command) would permanently block the undo stack.
"""

import pytest

from backend.agent.mutation_gateway import MutationGateway
from backend.ir.models import (
    BorderStyle,
    ElementStyleIR,
    FillStyle,
    FontIR,
    PresentationIR,
    ShapeElementIR,
    SlideIR,
    TextContentIR,
    TextElementIR,
)
from backend.ir.patch import HistoryManager


def _make_slide() -> SlideIR:
    slide = SlideIR(
        id="slide_1",
        slide_num=1,
        title="Test Slide",
        background=FillStyle(type="solid", color="#FFFFFF"),
    )
    card_style = ElementStyleIR(
        fill=FillStyle(type="solid", color="#F8FAFC"),
        border=BorderStyle(color="#E2E8F0", width=1.0),
        radius=2.0,
    )
    slide.add_element(
        ShapeElementIR(
            id="card_a", name="Card A", shape_type="roundRect",
            x=100.0, y=200.0, width=300.0, height=320.0, style=card_style,
        )
    )
    slide.add_element(
        ShapeElementIR(
            id="card_b", name="Card B", shape_type="roundRect",
            x=450.0, y=210.0, width=300.0, height=320.0, style=card_style,
        )
    )
    slide.add_element(
        TextElementIR(
            id="title_txt", name="Title",
            x=80.0, y=60.0, width=600.0, height=60.0,
            text_content=TextContentIR.from_plain_text(
                "Test Title", font=FontIR(size=32.0, color="#111111")
            ),
        )
    )
    return slide


def _make_pres() -> PresentationIR:
    return PresentationIR(
        id="pres_test",
        title="Undo Precision",
        slides=[_make_slide()],
        active_slide_id="slide_1",
    )


def _state(pres: PresentationIR) -> dict:
    data = pres.model_dump()
    data.pop("version", None)
    return data


def _invoke(name: str, args: dict, pres: PresentationIR, history: HistoryManager) -> dict:
    return MutationGateway.execute_one_sync(
        name, args, pres, history, source="test", bypass_confirmation=True
    )


def _assert_undo_redo_roundtrip(name: str, args: dict) -> None:
    pres = _make_pres()
    history = HistoryManager(pres)
    before = _state(pres)

    result = _invoke(name, args, pres, history)
    assert result.get("success") is True, f"{name} failed: {result}"
    after = _state(pres)
    assert after != before, f"{name} did not mutate the presentation"

    assert history.can_undo(), f"{name} recorded no undo command"
    assert history.undo(pres) is not None, f"{name} undo returned None (poison command)"
    assert _state(pres) == before, f"{name} undo did not restore the previous state"

    assert history.redo(pres) is not None, f"{name} redo returned None"
    assert _state(pres) == after, f"{name} redo did not re-apply the mutation"


def _undo_all(pres: PresentationIR, history: HistoryManager) -> int:
    count = 0
    while history.can_undo():
        assert history.undo(pres) is not None, "hit a poison command while undoing"
        count += 1
    return count


def _redo_all(pres: PresentationIR, history: HistoryManager) -> int:
    count = 0
    while history.can_redo():
        assert history.redo(pres) is not None, "hit a poison command while redoing"
        count += 1
    return count


COMPOSITE_CASES = [
    ("set_slide_background", {"color": "#111418", "slide_id": "slide_1"}),
    ("group_elements", {"element_ids": ["card_a", "card_b"], "slide_id": "slide_1"}),
    ("optimize_layout", {"slide_id": "slide_1", "layout_mode": "horizontal_cards"}),
    ("align_elements", {"alignment": "top", "slide_id": "slide_1"}),
    ("batch_add_cards", {"cards": [{"title": "A"}, {"title": "B"}], "slide_id": "slide_1"}),
    ("clear_slide_elements", {"slide_id": "slide_1", "keep_title": False}),
    ("generate_slide_layout", {"title": "Gen", "layout_type": "card_grid", "slide_id": "slide_1"}),
    ("apply_theme", {"theme_preset": "engineering_dark"}),
    ("duplicate_slide", {"slide_id": "slide_1"}),
    ("format_text", {"element_id": "title_txt", "font_size": 44.0, "font_color": "#C2410C", "slide_id": "slide_1"}),
]


@pytest.mark.parametrize("name,args", COMPOSITE_CASES, ids=[c[0] for c in COMPOSITE_CASES])
def test_composite_tool_undo_redo_roundtrip(name, args):
    _assert_undo_redo_roundtrip(name, args)


def test_generate_presentation_undo_redo_roundtrip():
    _assert_undo_redo_roundtrip(
        "generate_presentation",
        {
            "topic": "Deck",
            # Session-less callers cannot replace the document (no session identity
            # to rotate), so request additive generation.
            "replace": False,
            "slides": [{"title": "S1", "layout": "card_grid"}],
        },
    )


def test_ungroup_elements_undo_redo_roundtrip():
    pres = _make_pres()
    slide = pres.slides[0]
    group = slide.group_elements(["card_a", "card_b"], group_name="Grouped")
    assert group is not None

    history = HistoryManager(pres)
    before = _state(pres)
    result = _invoke("ungroup_elements", {"group_id": group.id, "slide_id": slide.id}, pres, history)
    assert result.get("success") is True, result
    after = _state(pres)

    assert history.undo(pres) is not None
    assert _state(pres) == before
    assert history.redo(pres) is not None
    assert _state(pres) == after


def test_delete_slide_undo_restores_slide_and_order():
    pres = _make_pres()
    pres.slides.append(
        SlideIR(
            id="slide_2",
            slide_num=2,
            title="Second",
            background=FillStyle(type="solid", color="#FFFFFF"),
        )
    )
    pres.active_slide_id = "slide_1"
    history = HistoryManager(pres)
    before = _state(pres)

    result = _invoke("delete_slide", {"slide_id_or_num": "slide_1"}, pres, history)
    assert result.get("success") is True, result
    after = _state(pres)

    assert history.undo(pres) is not None
    assert _state(pres) == before
    assert history.redo(pres) is not None
    assert _state(pres) == after


def test_auto_fix_layout_leaves_no_poison_commands():
    pres = _make_pres()
    slide = pres.slides[0]
    slide.add_element(
        ShapeElementIR(
            id="clipped_card", name="Clipped", shape_type="roundRect",
            x=1150.0, y=200.0, width=300.0, height=120.0,
        )
    )
    history = HistoryManager(pres)
    # `visual_fix_iterations` is intentionally persisted telemetry, not slide state.
    def _content_state() -> dict:
        data = _state(pres)
        data.pop("metadata", None)
        return data

    before = _content_state()

    result = _invoke("auto_fix_layout", {"slide_id": slide.id, "only_critical": True}, pres, history)
    assert result.get("success") is True, result
    assert result.get("applied_count", 0) > 0, result
    after = _content_state()

    undone = _undo_all(pres, history)
    assert undone > 0
    assert _content_state() == before, "full undo did not restore the pre-remediation state"

    _redo_all(pres, history)
    assert _content_state() == after, "full redo did not reproduce the remediation state"
