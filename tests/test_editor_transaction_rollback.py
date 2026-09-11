"""Transactional rollback must restore content, version, AND history.

Regression: a failed atomic batch previously advanced `presentation.version`
and/or retained history entries, so a failed edit could still invalidate CAS
expectations and pending confirmations.
"""

from backend.agent.tools import tools
from backend.history.command import BatchMutationCommand, UpdateElementCommand
from backend.ir.models import PresentationIR, SlideIR
from backend.ir.patch import HistoryManager


def _pres_with_shape():
    pres = PresentationIR()
    history = HistoryManager()
    slide = SlideIR(id="slide_tx", slide_num=1)
    pres.slides.append(slide)
    pres.active_slide_id = slide.id
    shape_id = tools.execute(
        "add_shape",
        {"slide_id": slide.id, "x": 10.0, "y": 10.0, "width": 100.0, "height": 50.0},
        pres,
        history,
    )["element_id"]
    return pres, history, slide, shape_id


def test_failed_batch_restores_version_and_history_depth():
    pres, history, slide, shape_id = _pres_with_shape()
    version_before = pres.version
    undo_before = len(history.undo_stack)

    result = tools.execute_batch(
        [
            {"name": "update_element", "payload": {"slide_id": slide.id, "element_id": shape_id, "x": 90.0}},
            {"name": "update_element", "payload": {"slide_id": slide.id, "element_id": "missing_id", "x": 5.0}},
        ],
        pres,
        history,
    )

    assert result["success"] is False
    assert slide.get_element(shape_id).x == 10.0
    assert pres.version == version_before, "rollback must restore the presentation version"
    assert len(history.undo_stack) == undo_before, "failed batch must leave no history entry"
    assert len(history.redo_stack) == 0


def test_batch_command_rolls_back_executed_operations_on_failure():
    pres, history, slide, shape_id = _pres_with_shape()
    before = slide.get_element(shape_id).model_dump()

    good = UpdateElementCommand(
        slide_id=slide.id,
        element_id=shape_id,
        before=before,
        after={**before, "x": 90.0},
    )
    bad = UpdateElementCommand(
        slide_id=slide.id,
        element_id="missing_id",
        before={},
        after={"x": 5.0},
    )
    batch = BatchMutationCommand(commands=[good, bad], description="atomic")

    assert batch.execute(pres) is False
    assert slide.get_element(shape_id).x == 10.0
