"""PR22 / WS3: recursive (nested) group / ungroup.

The frontend lets users enter a group and group/ungroup elements inside it, but
the backend model only scanned `self.elements` (slide root). These tests pin the
nested behaviour:

- grouping elements that already live inside a parent group creates the new
  group *inside that parent* and recomputes the parent's bounds;
- ungrouping a nested group splices its children back into the parent;
- grouping across different parents fails closed instead of silently flattening.
"""

from backend.agent.tools import tools
from backend.ir.models import (
    GroupElementIR,
    PresentationIR,
    ShapeElementIR,
    SlideIR,
)
from backend.ir.patch import HistoryManager


def _slide_with_three_cards() -> SlideIR:
    slide = SlideIR(id="slide_nested", slide_num=1)
    slide.add_element(ShapeElementIR(id="a", x=0.0, y=0.0, width=100.0, height=50.0))
    slide.add_element(ShapeElementIR(id="b", x=200.0, y=0.0, width=100.0, height=50.0))
    slide.add_element(ShapeElementIR(id="c", x=400.0, y=0.0, width=100.0, height=50.0))
    return slide


def _three_shapes() -> tuple[PresentationIR, SlideIR, HistoryManager]:
    pres = PresentationIR(title="Nested Grouping")
    slide = _slide_with_three_cards()
    pres.slides.append(slide)
    pres.active_slide_id = slide.id
    return pres, slide, HistoryManager(pres)


def test_group_elements_inside_a_parent_group():
    pres, slide, history = _three_shapes()

    top = tools.execute(
        "group_elements",
        {"element_ids": ["a", "b", "c"], "group_name": "Outer"},
        pres,
        history,
    )
    assert top["success"] is True
    outer = slide.get_element(top["group_id"])
    assert isinstance(outer, GroupElementIR)
    assert outer.width == 500.0

    nested = tools.execute(
        "group_elements",
        {"element_ids": ["a", "b"], "group_name": "Inner"},
        pres,
        history,
    )
    assert nested["success"] is True
    inner = outer.get_child(nested["group_id"])
    assert isinstance(inner, GroupElementIR)
    assert inner.children and [c.id for c in inner.children] == ["a", "b"]

    # The inner group is inserted inside the outer group, not on the slide root.
    assert [el.id for el in outer.children] == [nested["group_id"], "c"]
    assert outer.get_child(nested["group_id"]) is inner

    # Outer bounds recomputed to cover inner (0..300) and c (400..500).
    assert outer.x == 0.0
    assert outer.y == 0.0
    assert outer.width == 500.0
    assert outer.height == 50.0


def test_ungroup_nested_group_restores_siblings():
    pres, slide, history = _three_shapes()

    top = tools.execute(
        "group_elements", {"element_ids": ["a", "b", "c"]}, pres, history
    )
    outer = slide.get_element(top["group_id"])
    assert isinstance(outer, GroupElementIR)

    nested = tools.execute(
        "group_elements", {"element_ids": ["a", "b"]}, pres, history
    )
    inner_id = nested["group_id"]

    result = tools.execute(
        "ungroup_elements", {"group_id": inner_id}, pres, history
    )
    assert result["success"] is True
    assert result["restored_count"] == 2

    # Children are spliced back into the outer group at the inner group's index.
    assert [el.id for el in outer.children] == ["a", "b", "c"]
    assert outer.get_child(inner_id) is None
    assert outer.get_child("a") is not None
    assert outer.get_child("b") is not None
    # Bounds still cover all three children.
    assert outer.width == 500.0


def test_group_across_parents_fails_closed():
    pres, slide, history = _three_shapes()

    top = tools.execute(
        "group_elements", {"element_ids": ["a", "b"]}, pres, history
    )
    outer = slide.get_element(top["group_id"])
    assert isinstance(outer, GroupElementIR)
    before = slide.model_dump()

    across = tools.execute(
        "group_elements", {"element_ids": ["a", "c"]}, pres, history
    )
    assert across["success"] is False
    assert slide.model_dump() == before


def test_nested_grouping_is_undoable_in_one_step():
    pres, slide, history = _three_shapes()
    top = tools.execute(
        "group_elements", {"element_ids": ["a", "b", "c"]}, pres, history
    )
    outer = slide.get_element(top["group_id"])
    assert isinstance(outer, GroupElementIR)

    nested = tools.execute(
        "group_elements", {"element_ids": ["a", "b"]}, pres, history
    )
    assert slide.get_element(nested["group_id"]) is outer.get_child(nested["group_id"])

    # One undo reverts the nested grouping (outer group and all 3 children remain).
    history.undo(pres)
    restored_outer = slide.get_element(top["group_id"])
    assert isinstance(restored_outer, GroupElementIR)
    assert [el.id for el in restored_outer.children] == ["a", "b", "c"]
    assert restored_outer.get_child(nested["group_id"]) is None
