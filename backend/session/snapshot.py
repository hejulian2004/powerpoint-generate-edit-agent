"""SessionSnapshot / WorkspaceSnapshot value objects.

These are the persistence shapes (Phase 3). They intentionally contain only
*persistent* state: never a lock, websocket, coroutine, connection, or live
service object. See ``docs/session-workspace-contract.md`` (S10, contract P1/P2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SessionSnapshot:
    """Durable state of one session at a point in time."""

    session_id: str
    presentation: Dict[str, Any]
    document_epoch: str
    messages: List[Dict[str, Any]] = field(default_factory=list)
    agent_memory: Dict[str, Any] = field(default_factory=dict)
    subagent_memories: Dict[str, Any] = field(default_factory=dict)
    checkpoints: List[Dict[str, Any]] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


@dataclass
class WorkspaceSnapshot:
    """Durable workspace metadata: which session was last active."""

    last_active_session_id: Optional[str] = None
    session_ids: List[str] = field(default_factory=list)
