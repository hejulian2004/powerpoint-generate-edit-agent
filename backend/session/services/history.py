"""HistoryService: owns the session's undo/redo command stack.

The stack itself (``UndoRedoStack`` / ``HistoryManager``) remains the unit the
MutationGateway and tools expect as their ``history`` argument, so
``PPTSession.history`` continues to return ``history_service.stack``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ...history.undo_stack import UndoRedoStack


class HistoryService:
    """Owns a single session's reversible mutation history."""

    def __init__(self, stack: Optional[UndoRedoStack] = None):
        self.stack: UndoRedoStack = stack if stack is not None else UndoRedoStack()

    def clear(self) -> None:
        self.stack.clear()

    def record(self, *args: Any, **kwargs: Any) -> Any:
        return self.stack.record(*args, **kwargs)

    def undo(self, presentation: Any) -> Any:
        return self.stack.undo(presentation)

    def redo(self, presentation: Any) -> Any:
        return self.stack.redo(presentation)

    def can_undo(self) -> bool:
        return self.stack.can_undo()

    def can_redo(self) -> bool:
        return self.stack.can_redo()

    def get_summary(self) -> List[Dict[str, Any]]:
        return self.stack.get_summary()
