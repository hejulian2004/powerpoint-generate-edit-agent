"""Interactive PPTSession representing a stateful, multi-turn editing workspace."""

from __future__ import annotations
import uuid
import copy
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List

from ..ir.models import PresentationIR, SlideIR
from ..history.undo_stack import UndoRedoStack
from ..history.command import MutationCommand
from .checkpoint import SessionCheckpoint, CheckpointManager


@dataclass
class PPTSession:
    """A persistent interactive session with presentation state, history, checkpoints, and dialogue."""
    session_id: str
    pres: PresentationIR
    history: UndoRedoStack = field(default_factory=UndoRedoStack)
    messages: List[Dict[str, Any]] = field(default_factory=list)
    checkpoint_mgr: CheckpointManager = field(init=False)
    iterations: List[Dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_target_id: Optional[str] = None
    last_action_type: Optional[str] = None

    def __post_init__(self):
        self.checkpoint_mgr = CheckpointManager(session_id=self.session_id)
        # Create initial baseline checkpoint
        self.checkpoint_mgr.create(self.pres, description="Initial session state")

    @property
    def checkpoints(self) -> List[SessionCheckpoint]:
        return self.checkpoint_mgr.checkpoints

    @property
    def active_slide_id(self) -> Optional[str]:
        return self.pres.active_slide_id

    @active_slide_id.setter
    def active_slide_id(self, val: Optional[str]):
        self.pres.active_slide_id = val

    def get_active_slide(self) -> Optional[SlideIR]:
        return self.pres.get_active_slide()

    def set_active_slide(self, slide_id: str) -> bool:
        slide = self.pres.get_slide(slide_id)
        if slide:
            self.pres.active_slide_id = slide_id
            self.updated_at = datetime.now(timezone.utc)
            return True
        return False

    def add_message(
        self,
        role: str,
        content: str,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        vision_critique: Optional[str] = None,
        visual_review: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        msg = {
            "id": f"msg_{uuid.uuid4().hex[:8]}",
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).timestamp(),
            "tool_calls": tool_calls or [],
            "vision_critique": vision_critique,
            "visual_review": visual_review
        }
        self.messages.append(msg)
        self.updated_at = datetime.now(timezone.utc)
        return msg

    def create_checkpoint(
        self,
        description: str = "",
        score: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> SessionCheckpoint:
        cp = self.checkpoint_mgr.create(
            pres=self.pres,
            description=description,
            score=score,
            metadata=metadata
        )
        self.updated_at = datetime.now(timezone.utc)
        return cp

    def restore_checkpoint(self, checkpoint_id: str) -> bool:
        restored = self.checkpoint_mgr.restore(checkpoint_id)
        if restored:
            self.pres = restored
            # Record a restoration mutation event in history
            self.history.record(
                action="restore_checkpoint",
                description=f"Restored to checkpoint {checkpoint_id}",
                source="session_checkpoint"
            )
            self.updated_at = datetime.now(timezone.utc)
            return True
        return False

    def undo(self) -> Optional[MutationCommand]:
        cmd = self.history.undo(self.pres)
        if cmd:
            self.updated_at = datetime.now(timezone.utc)
        return cmd

    def redo(self) -> Optional[MutationCommand]:
        cmd = self.history.redo(self.pres)
        if cmd:
            self.updated_at = datetime.now(timezone.utc)
        return cmd

    def record_iteration(self, iteration_data: Any):
        if hasattr(iteration_data, "to_dict"):
            self.iterations.append(iteration_data.to_dict())
        else:
            self.iterations.append(iteration_data)
        self.updated_at = datetime.now(timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "title": self.pres.title,
            "slides_count": len(self.pres.slides),
            "active_slide_id": self.active_slide_id,
            "version": self.pres.version,
            "messages_count": len(self.messages),
            "checkpoints_count": len(self.checkpoints),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "can_undo": self.history.can_undo(),
            "can_redo": self.history.can_redo(),
            "last_target_id": self.last_target_id,
        }
