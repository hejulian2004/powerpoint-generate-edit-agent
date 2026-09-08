"""Tests for BatchMutationCommand Atomic Rollback and UndoRedoStack Failure Protection (PR5.1 Hardening)."""

import pytest
from typing import Dict, Any, Optional
from backend.ir.models import (
    PresentationIR, SlideIR, ShapeElementIR, TextElementIR,
    TextContentIR, FontIR
)
from backend.ir.history_event import MutationEvent
from backend.history.command import (
    MutationCommand,
    UpdateElementCommand,
    AddElementCommand,
    DeleteElementCommand,
    BatchMutationCommand
)
from backend.history.undo_stack import UndoRedoStack


class FailingCommand(MutationCommand):
    """A command designed to fail during execute, undo, or redo for atomic testing."""

    def __init__(
        self,
        fail_on_execute: bool = False,
        fail_on_undo: bool = False,
        fail_on_redo: bool = False,
        description: str = "Mock Failing Command"
    ):
        super().__init__(
            action="mock_failing",
            description=description,
            source="test"
        )
        self.fail_on_execute = fail_on_execute
        self.fail_on_undo = fail_on_undo
        self.fail_on_redo = fail_on_redo
        self.execute_count = 0
        self.undo_count = 0
        self.redo_count = 0

    def execute(self, pres: PresentationIR) -> bool:
        self.execute_count += 1
        return not self.fail_on_execute

    def undo(self, pres: PresentationIR) -> bool:
        self.undo_count += 1
        return not self.fail_on_undo

    def redo(self, pres: PresentationIR) -> bool:
        self.redo_count += 1
        return not self.fail_on_redo

    def to_event(self) -> MutationEvent:
        return MutationEvent(
            action=self.action,
            element_id="",
            before={},
            after={},
            timestamp=str(self.timestamp),
            source=self.source
        )


def create_sample_deck() -> PresentationIR:
    pres = PresentationIR(title="Batch Atomic Test Deck")
    slide = SlideIR(
        id="s1",
        slide_num=1,
        elements=[
            TextElementIR(
                id="title1",
                name="Title",
                x=100.0,
                y=100.0,
                width=600.0,
                height=50.0,
                text_content=TextContentIR.from_plain_text("Original Title")
            ),
            ShapeElementIR(
                id="shape1",
                name="Box",
                shape_type="rect",
                x=200.0,
                y=200.0,
                width=300.0,
                height=150.0
            )
        ]
    )
    pres.slides = [slide]
    pres.active_slide_id = "s1"
    return pres


def test_batch_mutation_command_success():
    """Verify standard BatchMutationCommand executes all sub-commands and can undo/redo completely."""
    pres = create_sample_deck()

    cmd1 = UpdateElementCommand(
        slide_id="s1",
        element_id="title1",
        before={"x": 100.0},
        after={"x": 500.0}
    )
    cmd2 = UpdateElementCommand(
        slide_id="s1",
        element_id="shape1",
        before={"y": 200.0},
        after={"y": 400.0}
    )

    batch = BatchMutationCommand(commands=[cmd1, cmd2], description="Move both elements")
    success = batch.execute(pres)
    assert success is True
    assert pres.slides[0].elements[0].x == 500.0
    assert pres.slides[0].elements[1].y == 400.0

    # Undo
    undo_ok = batch.undo(pres)
    assert undo_ok is True
    assert pres.slides[0].elements[0].x == 100.0
    assert pres.slides[0].elements[1].y == 200.0

    # Redo
    redo_ok = batch.redo(pres)
    assert redo_ok is True
    assert pres.slides[0].elements[0].x == 500.0
    assert pres.slides[0].elements[1].y == 400.0


def test_batch_mutation_command_atomic_rollback_on_execute():
    """Verify that if an intermediate command fails in BatchMutationCommand.execute, prior commands rollback."""
    pres = create_sample_deck()

    # cmd1 succeeds
    cmd1 = UpdateElementCommand(
        slide_id="s1",
        element_id="title1",
        before={"x": 100.0},
        after={"x": 888.0}
    )
    # cmd2 fails
    cmd2 = FailingCommand(fail_on_execute=True)

    batch = BatchMutationCommand(commands=[cmd1, cmd2], description="Atomic Failure Test")
    success = batch.execute(pres)

    # Batch should fail overall
    assert success is False

    # cmd1 should have been rolled back to its original state (x=100.0)
    assert pres.slides[0].elements[0].x == 100.0


def test_batch_mutation_command_atomic_rollback_on_redo():
    """Verify that if an intermediate command fails in BatchMutationCommand.redo, prior redone commands rollback."""
    pres = create_sample_deck()

    cmd1 = UpdateElementCommand(
        slide_id="s1",
        element_id="title1",
        before={"x": 100.0},
        after={"x": 777.0}
    )
    cmd2 = FailingCommand(fail_on_execute=False, fail_on_redo=True)

    batch = BatchMutationCommand(commands=[cmd1, cmd2], description="Atomic Redo Failure Test")

    # Initial execute succeeds
    assert batch.execute(pres) is True
    assert pres.slides[0].elements[0].x == 777.0

    # Undo succeeds
    assert batch.undo(pres) is True
    assert pres.slides[0].elements[0].x == 100.0

    # Redo fails on cmd2, cmd1 must be rolled back to 100.0
    redo_success = batch.redo(pres)
    assert redo_success is False
    assert pres.slides[0].elements[0].x == 100.0


def test_undoredo_stack_failure_state_preservation():
    """Verify UndoRedoStack preserves command on stack if undo() or redo() fails."""
    pres = create_sample_deck()
    stack = UndoRedoStack()

    # 1. Test failing undo
    failing_undo_cmd = FailingCommand(fail_on_undo=True)
    stack.push(failing_undo_cmd)
    assert stack.can_undo() is True
    assert stack.can_redo() is False

    # Perform undo - should return None because it failed
    undone = stack.undo(pres)
    assert undone is None

    # The command should STILL be on undo_stack, redo_stack must NOT be corrupted
    assert stack.can_undo() is True
    assert stack.can_redo() is False
    assert len(stack.undo_stack) == 1
    assert len(stack.redo_stack) == 0

    # 2. Test failing redo
    normal_cmd = FailingCommand(fail_on_undo=False, fail_on_redo=True)
    stack2 = UndoRedoStack()
    stack2.push(normal_cmd)

    # First undo succeeds
    assert stack2.undo(pres) is not None
    assert stack2.can_undo() is False
    assert stack2.can_redo() is True

    # Redo fails
    redone = stack2.redo(pres)
    assert redone is None

    # The command should STILL be on redo_stack, undo_stack must NOT be corrupted
    assert stack2.can_redo() is True
    assert stack2.can_undo() is False
    assert len(stack2.redo_stack) == 1
    assert len(stack2.undo_stack) == 0
