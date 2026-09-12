"""SessionCheckpoint and CheckpointManager for PPT session snapshotting and restoration."""

from __future__ import annotations
import copy
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List

from ..ir.models import PresentationIR


@dataclass
class SessionCheckpoint:
    """Snapshot of a PresentationIR state at a specific point in time."""
    id: str
    session_id: str
    pres_snapshot: PresentationIR
    version: int
    description: str = ""
    score: Optional[float] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "version": self.version,
            "description": self.description,
            "score": self.score,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }

    def to_snapshot(self) -> Dict[str, Any]:
        """Serializes the checkpoint INCLUDING the presentation snapshot.

        ``to_dict`` is the public/API shape and intentionally omits the (large) IR
        payload; persistence needs it, so it has a dedicated method.
        """
        return {
            "id": self.id,
            "session_id": self.session_id,
            "presentation": self.pres_snapshot.model_dump(),
            "version": self.version,
            "description": self.description,
            "score": self.score,
            "created_at": self.created_at.isoformat(),
            "metadata": copy.deepcopy(self.metadata),
        }

    @classmethod
    def from_snapshot(cls, data: Dict[str, Any]) -> "SessionCheckpoint":
        created_raw = data.get("created_at")
        try:
            created_at = datetime.fromisoformat(created_raw) if created_raw else datetime.now(timezone.utc)
        except (TypeError, ValueError):
            created_at = datetime.now(timezone.utc)
        return cls(
            id=data["id"],
            session_id=data["session_id"],
            pres_snapshot=PresentationIR.model_validate(data["presentation"]),
            version=data.get("version", 1),
            description=data.get("description", ""),
            score=data.get("score"),
            created_at=created_at,
            metadata=copy.deepcopy(data.get("metadata") or {}),
        )


class CheckpointManager:
    """Manages creation, retention, and restoration of session checkpoints."""

    def __init__(self, session_id: str, max_checkpoints: int = 20):
        self.session_id = session_id
        self.max_checkpoints = max_checkpoints
        self.checkpoints: List[SessionCheckpoint] = []

    def create(
        self,
        pres: PresentationIR,
        description: str = "",
        score: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> SessionCheckpoint:
        """Takes an immutable deepcopy snapshot of the current presentation state."""
        cp = SessionCheckpoint(
            id=f"cp_{uuid.uuid4().hex[:8]}",
            session_id=self.session_id,
            pres_snapshot=copy.deepcopy(pres),
            version=pres.version,
            description=description,
            score=score,
            created_at=datetime.now(timezone.utc),
            metadata=copy.deepcopy(metadata) if metadata else {}
        )
        self.checkpoints.append(cp)
        if len(self.checkpoints) > self.max_checkpoints:
            self.checkpoints.pop(0)
        return cp

    def get(self, checkpoint_id: str) -> Optional[SessionCheckpoint]:
        for cp in self.checkpoints:
            if cp.id == checkpoint_id:
                return cp
        return None

    def restore(self, checkpoint_id: str) -> Optional[PresentationIR]:
        """Returns a cloned PresentationIR from the requested checkpoint."""
        cp = self.get(checkpoint_id)
        if not cp:
            return None
        restored = copy.deepcopy(cp.pres_snapshot)
        # Increment version to signify a restore operation
        restored.version += 1
        return restored

    def list_all(self) -> List[Dict[str, Any]]:
        return [cp.to_dict() for cp in self.checkpoints]

    def clear(self):
        self.checkpoints.clear()
