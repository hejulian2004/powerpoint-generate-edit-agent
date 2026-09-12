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

    def to_snapshots(self) -> List[Dict[str, Any]]:
        """Serializes every retained checkpoint including its IR payload."""
        return [cp.to_snapshot() for cp in self.manager.checkpoints]

    def restore_from_snapshots(self, snapshots: List[Dict[str, Any]]) -> None:
        """Replaces the retained checkpoints with deserialized persisted ones."""
        self.manager.checkpoints = [
            SessionCheckpoint.from_snapshot(data) for data in (snapshots or [])
        ]

    def clear(self) -> None:
        self.manager.clear()
