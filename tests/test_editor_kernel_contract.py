"""Contract tests for the editor interaction kernel.

Covers:
1. Connector geometry updates (translate / endpoint edit / scale) keep the
   endpoint path and the axis-aligned bbox in sync.
2. Group duplication deep-clones children with fresh ids and offsets the whole
   subtree, including connector endpoints.
3. Atomic batch execution groups operations into a single undo step and rolls
   back cleanly when an operation fails.
4. Align/distribute translate groups recursively and are undoable.
"""

from backend.ir.models import (
    PresentationIR,
    SlideIR,
    ConnectorElementIR,
    GroupElementIR,
)
from backend.ir.patch import HistoryManager
from backend.agent.tools import tools


def _slide_with(elements):
    pres = PresentationIR()
    slide = SlideIR(id="slide_kernel", slide_num=1)
    for element in elements:
        slide.add_element(element)
    pres.slides.append(slide)
    pres.active_slide_id = slide.id
    return pres, slide


def _add_connector(pres, history, slide, **kwargs):
    defaults = dict(start_x=100.0, start_y=100.0, end_x=300.0, end_y=200.0)
    defaults.update(kwargs)
    result = tools.execute(
        "add_connector",
        {"slide_id": slide.id, **defaults},
        pres,
        history,
    )
    assert result["success"] is True
    return slide.get_element(result["element_id"])


def test_connector_translate_moves_endpoints_and_syncs_bounds():
    pres = PresentationIR()
    history = HistoryManager()
    slide = SlideIR(id="slide_conn", slide_num=1)
    pres.slides.append(slide)
    pres.active_slide_id = slide.id
    conn = _add_connector(pres, history, slide)

    result = tools.execute(
        "update_element",
        {"element_id": conn.id, "slide_id": slide.id, "x": 150.0, "y": 130.0},
        pres,
        history,
    )

    assert result["success"] is True
    assert conn.start_x == 150.0
    assert conn.start_y == 130.0
    assert conn.end_x == 350.0
    assert conn.end_y == 230.0
    assert conn.x == 150.0
    assert conn.y == 130.0
    assert conn.transform.x == 150.0
    assert conn.transform.y == 130.0


def test_connector_explicit_endpoint_update_syncs_bounds():
    pres = PresentationIR()
    history = HistoryManager()
    slide = SlideIR(id="slide_conn2", slide_num=1)
    pres.slides.append(slide)
    pres.active_slide_id = slide.id
    conn = _add_connector(pres, history, slide)

    result = tools.execute(
        "update_element",
        {
            "element_id": conn.id,
            "slide_id": slide.id,
            "end_x": 500.0,
            "end_y": 400.0,
        },
        pres,
        history,
    )

    assert result["success"] is True
    assert conn.end_x == 500.0
    assert conn.end_y == 400.0
    assert conn.x == 100.0
    assert conn.y == 100.0
    assert conn.width == 400.0
    assert conn.height == 300.0
    assert conn.transform.width == 400.0


def test_connector_scale_resizes_endpoints_proportionally():
    pres = PresentationIR()
    history = HistoryManager()
    slide = SlideIR(id="slide_conn3", slide_num=1)
    pres.slides.append(slide)
    pres.active_slide_id = slide.id
    conn = _add_connector(pres, history, slide)

    result = tools.execute(
        "update_element",
        {"element_id": conn.id, "slide_id": slide.id, "width": 400.0, "height": 200.0},
        pres,
        history,
    )

    assert result["success"] is True
    assert conn.start_x == 100.0
    assert conn.start_y == 100.0
    assert conn.end_x == 500.0
    assert conn.end_y == 300.0
    assert conn.width == 400.0
    assert conn.height == 200.0


def test_duplicate_group_deep_clones_with_new_child_ids_and_offsets():
    pres = PresentationIR()
    history = HistoryManager()
    slide = SlideIR(id="slide_group", slide_num=1)
    pres.slides.append(slide)
    pres.active_slide_id = slide.id

    shape_result = tools.execute(
        "add_shape",
        {"slide_id": slide.id, "x": 100.0, "y": 100.0, "width": 120.0, "height": 60.0},
        pres,
        history,
    )
    conn = _add_connector(pres, history, slide, start_x=100.0, start_y=100.0, end_x=220.0, end_y=160.0)
    shape_id = shape_result["element_id"]

    group_result = tools.execute(
        "group_elements",
        {"slide_id": slide.id, "element_ids": [shape_id, conn.id], "group_name": "Kernel"},
        pres,
        history,
    )
    assert group_result["success"] is True
    group = slide.get_element(group_result["group_id"])
    assert isinstance(group, GroupElementIR)
    child_ids = {child.id for child in group.children}

    dup_result = tools.execute(
        "duplicate_element",
        {"slide_id": slide.id, "element_id": group.id},
        pres,
        history,
    )

    assert dup_result["success"] is True
    clone = slide.get_element(dup_result["new_element_id"])
    assert isinstance(clone, GroupElementIR)
    assert clone.id != group.id
    clone_child_ids = {child.id for child in clone.children}
    assert child_ids.isdisjoint(clone_child_ids)
    assert clone.x == group.x + 20.0
    assert clone.y == group.y + 20.0
    clone_conn = next(child for child in clone.children if isinstance(child, ConnectorElementIR))
    assert clone_conn.start_x == conn.start_x + 20.0
    assert clone_conn.end_x == conn.end_x + 20.0


def test_batch_mutation_is_single_undo_step():
    pres = PresentationIR()
    history = HistoryManager()
    slide = SlideIR(id="slide_batch", slide_num=1)
    pres.slides.append(slide)
    pres.active_slide_id = slide.id
    shape_a = tools.execute("add_shape", {"slide_id": slide.id, "x": 10.0, "y": 10.0}, pres, history)["element_id"]
    shape_b = tools.execute("add_shape", {"slide_id": slide.id, "x": 200.0, "y": 10.0}, pres, history)["element_id"]
    undo_depth = len(history.undo_stack)

    result = tools.execute_batch(
        [
            {"name": "update_element", "payload": {"slide_id": slide.id, "element_id": shape_a, "x": 40.0, "y": 40.0}},
            {"name": "update_element", "payload": {"slide_id": slide.id, "element_id": shape_b, "x": 240.0, "y": 40.0}},
        ],
        pres,
        history,
    )

    assert result["success"] is True
    assert len(history.undo_stack) == undo_depth + 1
    assert slide.get_element(shape_a).x == 40.0
    assert slide.get_element(shape_b).x == 240.0

    history.undo(pres)
    assert slide.get_element(shape_a).x == 10.0
    assert slide.get_element(shape_b).x == 200.0


def test_batch_mutation_rolls_back_previous_operations_on_failure():
    pres = PresentationIR()
    history = HistoryManager()
    slide = SlideIR(id="slide_batch_fail", slide_num=1)
    pres.slides.append(slide)
    pres.active_slide_id = slide.id
    shape_a = tools.execute("add_shape", {"slide_id": slide.id, "x": 10.0, "y": 10.0}, pres, history)["element_id"]
    undo_depth = len(history.undo_stack)

    result = tools.execute_batch(
        [
            {"name": "update_element", "payload": {"slide_id": slide.id, "element_id": shape_a, "x": 90.0, "y": 90.0}},
            {"name": "update_element", "payload": {"slide_id": slide.id, "element_id": "missing_id", "x": 5.0}},
        ],
        pres,
        history,
    )

    assert result["success"] is False
    assert slide.get_element(shape_a).x == 10.0
    assert slide.get_element(shape_a).y == 10.0
    assert len(history.undo_stack) == undo_depth


def test_align_translates_group_children_and_is_undoable():
    pres = PresentationIR()
    history = HistoryManager()
    slide = SlideIR(id="slide_align", slide_num=1)
    pres.slides.append(slide)
    pres.active_slide_id = slide.id
    shape_a = tools.execute("add_shape", {"slide_id": slide.id, "x": 100.0, "y": 100.0}, pres, history)["element_id"]
    shape_b = tools.execute("add_shape", {"slide_id": slide.id, "x": 400.0, "y": 100.0}, pres, history)["element_id"]
    group_id = tools.execute(
        "group_elements",
        {"slide_id": slide.id, "element_ids": [shape_a, shape_b]},
        pres,
        history,
    )["group_id"]

    child_x_before = [child.x for child in slide.get_element(group_id).children]
    result = tools.execute(
        "align_elements",
        {"slide_id": slide.id, "element_ids": [group_id], "alignment": "left"},
        pres,
        history,
    )
    assert result["success"] is True

    group = slide.get_element(group_id)
    child_x_after = [child.x for child in group.children]
    assert child_x_after == child_x_before

    other = tools.execute("add_shape", {"slide_id": slide.id, "x": 40.0, "y": 300.0}, pres, history)["element_id"]
    result = tools.execute(
        "align_elements",
        {"slide_id": slide.id, "element_ids": [group_id, other], "alignment": "left"},
        pres,
        history,
    )
    assert result["success"] is True
    group = slide.get_element(group_id)
    assert group.x == 40.0
    assert [child.x for child in group.children] == [x - 60.0 for x in child_x_after]

    history.undo(pres)
    assert slide.get_element(group_id).x == 100.0
    assert [child.x for child in slide.get_element(group_id).children] == child_x_after


def test_distribute_v_is_implemented():
    pres = PresentationIR()
    history = HistoryManager()
    slide = SlideIR(id="slide_dist", slide_num=1)
    pres.slides.append(slide)
    pres.active_slide_id = slide.id
    ids = [
        tools.execute("add_shape", {"slide_id": slide.id, "x": 0.0, "y": 0.0, "height": 50.0}, pres, history)["element_id"],
        tools.execute("add_shape", {"slide_id": slide.id, "x": 0.0, "y": 100.0, "height": 50.0}, pres, history)["element_id"],
        tools.execute("add_shape", {"slide_id": slide.id, "x": 0.0, "y": 400.0, "height": 50.0}, pres, history)["element_id"],
    ]

    result = tools.execute(
        "align_elements",
        {"slide_id": slide.id, "element_ids": ids, "alignment": "distribute_v"},
        pres,
        history,
    )

    assert result["success"] is True
    sorted_targets = sorted((slide.get_element(i) for i in ids), key=lambda e: e.y)
    gaps = [
        sorted_targets[i + 1].y - (sorted_targets[i].y + sorted_targets[i].height)
        for i in range(len(sorted_targets) - 1)
    ]
    assert abs(gaps[0] - gaps[1]) < 0.5


def _make_grouped_pair(pres, history, slide):
    """Creates two shapes in a group and returns (group_id, first_child_id)."""
    a = tools.execute(
        "add_shape",
        {"slide_id": slide.id, "x": 100.0, "y": 100.0, "width": 100.0, "height": 50.0},
        pres,
        history,
    )["element_id"]
    b = tools.execute(
        "add_shape",
        {"slide_id": slide.id, "x": 260.0, "y": 100.0, "width": 100.0, "height": 50.0},
        pres,
        history,
    )["element_id"]
    group_id = tools.execute(
        "group_elements",
        {"slide_id": slide.id, "element_ids": [a, b]},
        pres,
        history,
    )["group_id"]
    return group_id, a


def test_nested_child_update_recomputes_group_bounds_and_undo_restores():
    pres = PresentationIR()
    history = HistoryManager()
    slide = SlideIR(id="slide_nested_update", slide_num=1)
    pres.slides.append(slide)
    pres.active_slide_id = slide.id
    group_id, child_id = _make_grouped_pair(pres, history, slide)

    group = slide.get_element(group_id)
    assert (group.x, group.y, group.width, group.height) == (100.0, 100.0, 260.0, 50.0)

    result = tools.execute(
        "update_element",
        {"slide_id": slide.id, "element_id": child_id, "x": 80.0, "y": 60.0},
        pres,
        history,
    )
    assert result["success"] is True

    group = slide.get_element(group_id)
    assert (group.x, group.y, group.width, group.height) == (80.0, 60.0, 280.0, 90.0)

    history.undo(pres)
    child = slide.get_element(child_id)
    group = slide.get_element(group_id)
    assert (child.x, child.y) == (100.0, 100.0)
    assert (group.x, group.y, group.width, group.height) == (100.0, 100.0, 260.0, 50.0)


def test_nested_delete_undo_restores_child_into_parent_group():
    pres = PresentationIR()
    history = HistoryManager()
    slide = SlideIR(id="slide_nested_delete", slide_num=1)
    pres.slides.append(slide)
    pres.active_slide_id = slide.id
    group_id, child_id = _make_grouped_pair(pres, history, slide)

    result = tools.execute(
        "delete_element",
        {"slide_id": slide.id, "element_id": child_id},
        pres,
        history,
    )
    assert result["success"] is True
    assert slide.get_element(child_id) is None
    assert child_id not in {el.id for el in slide.elements}
    group = slide.get_element(group_id)
    assert child_id not in {c.id for c in group.children}
    assert (group.x, group.y, group.width, group.height) == (260.0, 100.0, 100.0, 50.0)

    history.undo(pres)
    group = slide.get_element(group_id)
    assert child_id in {c.id for c in group.children}
    assert child_id not in {el.id for el in slide.elements}
    assert (group.x, group.y, group.width, group.height) == (100.0, 100.0, 260.0, 50.0)


def test_batch_rollback_restores_nested_group_bounds():
    pres = PresentationIR()
    history = HistoryManager()
    slide = SlideIR(id="slide_batch_nested", slide_num=1)
    pres.slides.append(slide)
    pres.active_slide_id = slide.id
    group_id, child_id = _make_grouped_pair(pres, history, slide)

    result = tools.execute_batch(
        [
            {"name": "update_element", "payload": {"slide_id": slide.id, "element_id": child_id, "x": 500.0, "y": 400.0}},
            {"name": "update_element", "payload": {"slide_id": slide.id, "element_id": "missing_id", "x": 0.0}},
        ],
        pres,
        history,
    )

    assert result["success"] is False
    child = slide.get_element(child_id)
    group = slide.get_element(group_id)
    assert (child.x, child.y) == (100.0, 100.0)
    assert (group.x, group.y, group.width, group.height) == (100.0, 100.0, 260.0, 50.0)
