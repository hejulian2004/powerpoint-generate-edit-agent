"""SessionSnapshot / WorkspaceSnapshot value objects.

These are the persistence shapes (Phase 3). They intentionally contain only
*persistent* state: never a lock, websocket, coroutine, connection, or live
service object. See ``docs/session-workspace-contract.md`` (S10, contract P1/P2).
"""

from __future__ import annotations

import copy
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


# ----------------------------------------------------------------------
# (De)serialization between a live PPTSession and a durable SessionSnapshot
# ----------------------------------------------------------------------

def session_to_snapshot(session: Any) -> SessionSnapshot:
    """Captures only persistent state from a live session.

    Ephemeral state (locks, sockets, active Agent turn, pending confirmations,
    the idempotency cache) is deliberately excluded (contract P1/P2).
    """
    mem = session.memory
    return SessionSnapshot(
        session_id=session.session_id,
        presentation=session.document.presentation.model_dump(),
        document_epoch=session.document.epoch,
        messages=copy.deepcopy(mem.messages),
        agent_memory=mem.agent_memory.to_dict(),
        subagent_memories={name: m.to_dict() for name, m in mem.subagent_memories.items()},
        checkpoints=session.checkpoint_service.to_snapshots(),
        created_at=session.created_at.isoformat(),
        updated_at=session.updated_at.isoformat(),
    )


def snapshot_to_session(snapshot: SessionSnapshot) -> Any:
    """Reconstructs a live session from durable state (used on restore/restart)."""
    from .factory import SessionFactory
    from ..agent.memory import AgentMemory
    from ..agent.subagents.memory import SubagentSessionMemory

    session = SessionFactory.restore(snapshot, init_baseline=False)
    session.memory.messages = copy.deepcopy(snapshot.messages)
    session.memory.agent_memory = AgentMemory.from_dict(snapshot.agent_memory)
    session.memory.subagent_memories = {
        name: SubagentSessionMemory.from_dict(payload)
        for name, payload in (snapshot.subagent_memories or {}).items()
    }
    session.checkpoint_service.restore_from_snapshots(snapshot.checkpoints)
    return session
