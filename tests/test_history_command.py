"""Tests for Command Pattern and UndoRedoStack (Phase 5.2)."""

import pytest
from backend.ir.models import PresentationIR, SlideIR, ShapeElementIR, TextElementIR, TextContentIR
from backend.history.command import (
    MutationCommand,
    UpdateElementCommand,
    AddElementCommand,
    DeleteElementCommand,
    BatchMutationCommand
)
from backend.history.undo_stack import UndoRedoStack
from backend.ir.patch import HistoryManager
from backend.ir.history_event import MutationEvent


@pytest.fixture
def sample_pres():
    pres = PresentationIR(title="Command Test Deck")
    slide = SlideIR(
        id="s1",
        slide_num=1,
        elements=[
            TextElementIR(
                id="t1",
                x=100.0,
                y=100.0,
                width=300.0,
                height=50.0,
                text_content=TextContentIR.from_plain_text("Initial Title")
            )
        ]
    )
    pres.slides = [slide]
    pres.active_slide_id = "s1"
    return pres


def test_update_element_command(sample_pres):
    """Verify UpdateElementCommand execute, undo, and redo."""
    cmd = UpdateElementCommand(
        slide_id="s1",
        element_id="t1",
        before={"x": 100.0, "y": 100.0},
        after={"x": 500.0, "y": 250.0},
        source="user_edit"
    )

    # 1. Execute
    assert cmd.execute(sample_pres) is True
    assert sample_pres.slides[0].elements[0].x == 500.0
    assert sample_pres.slides[0].elements[0].y == 250.0

    # 2. Undo
    assert cmd.undo(sample_pres) is True
    assert sample_pres.slides[0].elements[0].x == 100.0
    assert sample_pres.slides[0].elements[0].y == 100.0

    # 3. Redo
    assert cmd.redo(sample_pres) is True
    assert sample_pres.slides[0].elements[0].x == 500.0
    assert sample_pres.slides[0].elements[0].y == 250.0

    # 4. Mutation event conversion
    event = cmd.to_event()
    assert isinstance(event, MutationEvent)
    assert event.action == "update_element"
    assert event.element_id == "t1"
    assert event.before["x"] == 100.0
    assert event.after["x"] == 500.0
    assert event.source == "user_edit"


def test_add_and_delete_element_command(sample_pres):
    """Verify AddElementCommand and DeleteElementCommand execute, undo, and redo."""
    new_data = {
        "id": "new_box",
        "type": "shape",
        "shape_type": "roundRect",
        "x": 200.0,
        "y": 300.0,
        "width": 150.0,
        "height": 100.0
    }
    add_cmd = AddElementCommand(slide_id="s1", element_data=new_data, source="agent_tool")

    # Execute Add
    assert add_cmd.execute(sample_pres) is True
    assert len(sample_pres.slides[0].elements) == 2
    assert sample_pres.slides[0].elements[1].id == "new_box"

    # Undo Add (removes it)
    assert add_cmd.undo(sample_pres) is True
    assert len(sample_pres.slides[0].elements) == 1

    # Redo Add (adds it back)
    assert add_cmd.redo(sample_pres) is True
    assert len(sample_pres.slides[0].elements) == 2

    # Test Delete
    del_cmd = DeleteElementCommand(slide_id="s1", element_id="new_box", before_data=new_data)
    assert del_cmd.execute(sample_pres) is True
    assert len(sample_pres.slides[0].elements) == 1

    assert del_cmd.undo(sample_pres) is True
    assert len(sample_pres.slides[0].elements) == 2

    assert del_cmd.redo(sample_pres) is True
    assert len(sample_pres.slides[0].elements) == 1


def test_batch_mutation_command(sample_pres):
    """Verify BatchMutationCommand coordinates multiple atomic mutations."""
    cmd1 = UpdateElementCommand(slide_id="s1", element_id="t1", before={"x": 100.0}, after={"x": 200.0})
    new_data = {"id": "box2", "type": "shape", "shape_type": "rect", "x": 50.0, "y": 50.0, "width": 50.0, "height": 50.0}
    cmd2 = AddElementCommand(slide_id="s1", element_data=new_data)

    batch = BatchMutationCommand(commands=[cmd1, cmd2], description="Batch layout tweak")
    assert batch.execute(sample_pres) is True
    assert sample_pres.slides[0].elements[0].x == 200.0
    assert len(sample_pres.slides[0].elements) == 2

    # Undo in reverse
    assert batch.undo(sample_pres) is True
    assert sample_pres.slides[0].elements[0].x == 100.0
    assert len(sample_pres.slides[0].elements) == 1

    # Redo
    assert batch.redo(sample_pres) is True
    assert sample_pres.slides[0].elements[0].x == 200.0
    assert len(sample_pres.slides[0].elements) == 2


def test_undo_redo_stack(sample_pres):
    """Verify UndoRedoStack manages push, undo, redo, and limits."""
    stack = UndoRedoStack(max_depth=5)
    assert stack.can_undo() is False
    assert stack.can_redo() is False

    cmd = UpdateElementCommand(slide_id="s1", element_id="t1", before={"x": 100.0}, after={"x": 300.0})
    cmd.execute(sample_pres)
    stack.push(cmd)

    assert stack.can_undo() is True
    assert stack.can_redo() is False

    # Undo
    popped = stack.undo(sample_pres)
    assert popped is cmd
    assert sample_pres.slides[0].elements[0].x == 100.0
    assert stack.can_undo() is False
    assert stack.can_redo() is True

    # Redo
    redone = stack.redo(sample_pres)
    assert redone is cmd
    assert sample_pres.slides[0].elements[0].x == 300.0
    assert stack.can_undo() is True
    assert stack.can_redo() is False


def test_history_manager_is_undo_redo_stack():
    """Verify that HistoryManager seamlessly subclasses UndoRedoStack."""
    hm = HistoryManager()
    assert isinstance(hm, UndoRedoStack)
    pres = PresentationIR(title="HM Test")
    slide = SlideIR(id="s1", slide_num=1, elements=[TextElementIR(id="t1", x=10.0, y=10.0, width=100.0, height=30.0)])
    pres.slides = [slide]

    rec = hm.record(action="update_element", description="test update", slide_id="s1", element_id="t1", before={"x": 10.0}, after={"x": 80.0})
    assert hm.can_undo() is True
    events = hm.get_mutation_events()
    assert len(events) == 1
    assert events[0].after["x"] == 80.0
