"""CheckpointService: owns a session's checkpoint manager and retained snapshots."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..checkpoint import CheckpointManager, SessionCheckpoint


class CheckpointService:
    """Owns the session's ``CheckpointManager``.

    ``PPTSession.checkpoints`` returns ``checkpoint_service.items`` for backward
    compatibility; new code should call the explicit methods here.
    """

    def __init__(self, session_id: str, max_checkpoints: int = 20):
        self.session_id = session_id
        self.manager = CheckpointManager(session_id=session_id, max_checkpoints=max_checkpoints)

    @property
    def items(self) -> List[SessionCheckpoint]:
        return self.manager.checkpoints

    def create(
        self,
        pres: Any,
        description: str = "",
        score: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SessionCheckpoint:
        return self.manager.create(pres, description=description, score=score, metadata=metadata)

    def get(self, checkpoint_id: str) -> Optional[SessionCheckpoint]:
        return self.manager.get(checkpoint_id)

    def restore(self, checkpoint_id: str) -> Optional[Any]:
        return self.manager.restore(checkpoint_id)

    def list_all(self) -> List[Dict[str, Any]]:
        return self.manager.list_all()

    def clear(self) -> None:
        self.manager.clear()
