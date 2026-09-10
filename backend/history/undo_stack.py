"""UndoRedoStack managing MutationCommand execution, rollback, and replay."""

from __future__ import annotations
import copy
from typing import List, Dict, Any, Optional
from ..ir.models import PresentationIR
from ..ir.history_event import MutationEvent
from .command import (
    MutationCommand,
    UpdateElementCommand,
    AddElementCommand,
    DeleteElementCommand,
    AddSlideCommand,
    DeleteSlideCommand,
    BatchMutationCommand,
    SnapshotSlideCommand,
    SnapshotCommand
)

# Composite slide tools whose exact inverse-op chain is brittle; they record a
# full before/after slide snapshot instead.
SLIDE_SNAPSHOT_ACTIONS = frozenset({
    "set_slide_background",
    "optimize_layout",
    "group_elements",
    "ungroup_elements",
    "align_elements",
    "batch_add_cards",
    "generate_slide_layout",
    "clear_slide_elements",
})

# Whole-deck tools record a full presentation snapshot.
PRES_SNAPSHOT_ACTIONS = frozenset({
    "apply_theme",
    "generate_presentation",
    "replace_presentation",
})


class UndoRedoStack:
    """Command-pattern Undo/Redo stack for interactive PresentationIR editing."""

    def __init__(self, max_history: int = 50, max_depth: Optional[int] = None):
        self.max_history = max_depth if max_depth is not None else max_history
        self.undo_stack: List[MutationCommand] = []
        self.redo_stack: List[MutationCommand] = []

    def push(self, command: MutationCommand):
        """Pushes an already-executed command onto the undo stack and clears redo."""
        self.undo_stack.append(command)
        if len(self.undo_stack) > self.max_history:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def record(
        self,
        action: str,
        description: str,
        slide_id: Optional[str] = None,
        element_id: Optional[str] = None,
        before: Optional[Dict[str, Any]] = None,
        after: Optional[Dict[str, Any]] = None,
        source: str = "agent_tool",
        position: Optional[int] = None,
        prev_active_slide_id: Optional[str] = None,
        active_after_delete: Optional[str] = None
    ) -> MutationCommand:
        """Constructs and pushes a MutationCommand matching legacy HistoryManager.record()."""
        cmd: MutationCommand
        if action in SLIDE_SNAPSHOT_ACTIONS:
            cmd = SnapshotSlideCommand(
                slide_id=slide_id or "",
                before_dump=before or {},
                after_dump=after or {},
                action=action,
                description=description,
                source=source
            )
        elif action in PRES_SNAPSHOT_ACTIONS:
            cmd = SnapshotCommand(
                before_dump=before or {},
                after_dump=after or {},
                action=action,
                description=description,
                source=source
            )
        elif action in ["create_slide", "duplicate_slide"]:
            cmd = AddSlideCommand(
                slide_id=slide_id or "",
                slide_data=copy.deepcopy(after or {}),
                position=position if position is not None else 0,
                prev_active_slide_id=prev_active_slide_id,
                action=action,
                description=description,
                source=source
            )
        elif action == "delete_slide":
            cmd = DeleteSlideCommand(
                slide_id=slide_id or "",
                slide_data=copy.deepcopy(before or {}),
                position=position if position is not None else 0,
                active_after_delete=active_after_delete,
                action=action,
                description=description,
                source=source
            )
        elif action in ["add_element", "create_element"]:
            elem_data = copy.deepcopy(after or {})
            if element_id and "id" not in elem_data:
                elem_data["id"] = element_id
            cmd = AddElementCommand(
                slide_id=slide_id or "",
                element_data=elem_data,
                action=action,
                description=description,
                source=source
            )
        elif action == "delete_element":
            cmd = DeleteElementCommand(
                slide_id=slide_id or "",
                element_id=element_id or "",
                before_data=copy.deepcopy(before or {}),
                action=action,
                description=description,
                source=source
            )
        else:
            cmd = UpdateElementCommand(
                slide_id=slide_id or "",
                element_id=element_id or "",
                before=before,
                after=after,
                action=action,
                description=description,
                source=source
            )

        self.push(cmd)
        return cmd

    def undo(self, presentation: PresentationIR) -> Optional[MutationCommand]:
        """Reverts the most recent command on the presentation."""
        if not self.undo_stack:
            return None
        cmd = self.undo_stack.pop()
        success = cmd.undo(presentation)
        if success:
            self.redo_stack.append(cmd)
            presentation.version += 1
            return cmd
        else:
            # Restore to undo stack on failure, do not corrupt redo stack
            self.undo_stack.append(cmd)
            return None

    def redo(self, presentation: PresentationIR) -> Optional[MutationCommand]:
        """Re-applies the most recently reverted command on the presentation."""
        if not self.redo_stack:
            return None
        cmd = self.redo_stack.pop()
        success = cmd.redo(presentation)
        if success:
            self.undo_stack.append(cmd)
            presentation.version += 1
            return cmd
        else:
            # Restore to redo stack on failure, do not corrupt undo stack
            self.redo_stack.append(cmd)
            return None

    def can_undo(self) -> bool:
        return len(self.undo_stack) > 0

    def can_redo(self) -> bool:
        return len(self.redo_stack) > 0

    def get_summary(self) -> List[Dict[str, Any]]:
        return [cmd.to_dict() for cmd in self.undo_stack]

    def get_mutation_events(self) -> List[MutationEvent]:
        """Converts undo stack commands into standardized MutationEvent history objects."""
        return [cmd.to_event() for cmd in self.undo_stack]

    def clear(self):
        self.undo_stack.clear()
        self.redo_stack.clear()
