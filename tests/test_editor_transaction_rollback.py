"""Phase 2.2: transactional rollback must restore content, version, AND history.

Regression: the old `MutationTransaction.rollback()` undid collected commands but
never restored `presentation.version`, so a failed batch still advanced the
revision and could invalidate CAS expectations / pending confirmations.
"""

from backend.agent.tools import tools
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


def test_transaction_exception_restores_version_and_history():
    pres, history, _, shape_id = _pres_with_shape()
    version_before = pres.version
    undo_before = len(history.undo_stack)

    try:
        with history.transaction(pres, description="crash"):
            tools.execute(
                "update_element",
                {"slide_id": "slide_tx", "element_id": shape_id, "x": 400.0},
                pres,
                history,
            )
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    assert pres.get_slide("slide_tx").get_element(shape_id).x == 10.0
    assert pres.version == version_before
    assert len(history.undo_stack) == undo_before
