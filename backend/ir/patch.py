"""Patch and Version Control engine for PPT-IR.

Generates reversible command records for every modification, supporting:
- Undo
- Redo
- Rollback
- Visual history inspection
"""

from __future__ import annotations
import time
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from .models import PresentationIR
from .history_event import MutationEvent
from ..history.command import (
    MutationCommand,
    UpdateElementCommand,
    AddElementCommand,
    DeleteElementCommand,
    BatchMutationCommand
)
from ..history.undo_stack import UndoRedoStack


class PatchRecord(BaseModel):
    id: str = Field(default_factory=lambda: f"patch_{int(time.time()*1000)}")
    timestamp: float = Field(default_factory=time.time)
    action: str = "update"
    description: str = ""
    slide_id: Optional[str] = None
    element_id: Optional[str] = None
    before: Optional[Dict[str, Any]] = None
    after: Optional[Dict[str, Any]] = None
    source: str = "agent_tool"


class HistoryManager(UndoRedoStack):
    """Manages Undo/Redo and version rollback for a PresentationIR.

    Inherits from UndoRedoStack, leveraging the Command Pattern for reversible PPT mutations.

    The first positional argument is accepted for backward compatibility with legacy
    `HistoryManager(pres)` call sites and never corrupts the stack configuration.
    """

    def __init__(
        self,
        pres: Optional[PresentationIR] = None,
        max_history: int = 50,
        max_depth: Optional[int] = None,
    ):
        super().__init__(max_history=max_history, max_depth=max_depth)
        self.presentation = pres


__all__ = [
    "PatchRecord",
    "HistoryManager",
    "MutationCommand",
    "UpdateElementCommand",
    "AddElementCommand",
    "DeleteElementCommand",
    "BatchMutationCommand",
    "UndoRedoStack"
]
