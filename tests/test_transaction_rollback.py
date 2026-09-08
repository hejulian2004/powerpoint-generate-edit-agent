"""Transaction & Rollback Guard Hardening Suite (Task 1).

Verifies that PresentationTransaction and PresentationSnapshot guarantee:
1. Complete state restoration across elements, nested groups, metadata, version, active_slide.
2. Complete history stack rollback (clears undo records generated during aborted transaction).
3. Context manager auto-rollback on uncaught exceptions.
4. Pre-transaction deepcopy comparison (pres == before).
"""

import copy
import pytest
from backend.ir.models import (
    PresentationIR, SlideIR, ShapeElementIR, TextElementIR,
    GroupElementIR, PresentationSnapshot, PresentationTransaction
)
from backend.ir.patch import HistoryManager
from backend.agent.tools import tools


def test_visual_fix_rollback_deep_equality():
    """Verifies that rolling back an aborted transaction perfectly restores presentation to pre-transaction state."""
    pres = PresentationIR(title="Original Presentation", version=5)
    pres.metadata["custom_key"] = "initial_value"
    pres.metadata["visual_fix_iterations"] = 1

    slide1 = SlideIR(id="slide_1", slide_num=1, title="Slide 1")
    s1 = ShapeElementIR(id="shape_1", x=100.0, y=100.0, width=200.0, height=150.0)
    g_child1 = ShapeElementIR(id="g_c1", x=400.0, y=100.0, width=100.0, height=80.0)
    g_child2 = ShapeElementIR(id="g_c2", x=520.0, y=100.0, width=100.0, height=80.0)
    group1 = GroupElementIR(id="grp_1", x=400.0, y=100.0, width=220.0, height=80.0, children=[g_child1, g_child2])
    slide1.add_element(s1)
    slide1.add_element(group1)
    pres.slides.append(slide1)
    pres.active_slide_id = "slide_1"

    history = HistoryManager()
    history.record("initial_setup", "Initial slide setup", slide_id="slide_1")
    initial_history_len = len(history.undo_stack)

    # Capture complete pre-modification state
    before = copy.deepcopy(pres)

    # Start transaction and perform multiple mutations
    with pres.transaction("test_bad_fix", history=history) as tx:
        # Tool 1: update element
        tools.execute("update_element", {"element_id": "shape_1", "x": 999.0, "y": 888.0}, pres, history)
        # Tool 2: update group
        tools.execute("update_element", {"element_id": "grp_1", "x": 50.0, "y": 50.0}, pres, history)
        # Mutate metadata and version
        pres.metadata["visual_fix_iterations"] = 2
        pres.version = 99
        pres.active_slide_id = None

        # Verify presentation changed inside transaction
        assert pres.version == 99
        assert len(history.undo_stack) > initial_history_len

        # Abort and rollback
        tx.rollback("Degraded layout score")

    # Verification: All fields, elements, groups, metadata, version, active_slide must match before
    assert pres.model_dump() == before.model_dump()
    assert pres == before
    assert pres.version == before.version
    assert pres.metadata == before.metadata
    assert pres.active_slide_id == before.active_slide_id
    assert len(history.undo_stack) == initial_history_len
    assert tx.is_aborted is True
    assert tx.rollback_reason == "Degraded layout score"


def test_transaction_exception_auto_rollback():
    """Verifies that an unhandled exception inside a transaction cleanly triggers rollback."""
    pres = PresentationIR(title="Exception Test", version=1)
    slide = SlideIR(id="s_err", slide_num=1)
    slide.add_element(ShapeElementIR(id="e_err", x=50.0, y=50.0, width=100.0, height=50.0))
    pres.slides.append(slide)

    history = HistoryManager()
    before = copy.deepcopy(pres)

    with pytest.raises(RuntimeError, match="Simulated crash"):
        with pres.transaction("crashing_tx", history=history) as tx:
            tools.execute("update_element", {"element_id": "e_err", "x": 500.0}, pres, history)
            assert pres.slides[0].elements[0].x == 500.0
            raise RuntimeError("Simulated crash")

    # State must be completely restored
    assert pres == before
    assert pres.slides[0].elements[0].x == 50.0
    assert len(history.undo_stack) == 0


def test_transaction_commit_persists_changes():
    """Verifies that committing a transaction retains all changes."""
    pres = PresentationIR(title="Commit Test", version=1)
    slide = SlideIR(id="s_ok", slide_num=1)
    slide.add_element(ShapeElementIR(id="e_ok", x=50.0, y=50.0, width=100.0, height=50.0))
    pres.slides.append(slide)

    history = HistoryManager()

    with pres.transaction("successful_tx", history=history) as tx:
        tools.execute("update_element", {"element_id": "e_ok", "x": 200.0}, pres, history)
        tx.commit()

    assert pres.slides[0].elements[0].x == 200.0
    assert tx.is_committed is True
    assert len(history.undo_stack) == 1
