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
    # Persisted manual context-compression anchor (raw transcript is untouched).
    compressed_anchor: Optional[Dict[str, Any]] = None
    compression_through_index: int = 0
    conversation_generation: int = 0
    completed_requests: List[Dict[str, Any]] = field(default_factory=list)
    completed_tombstones: List[Dict[str, Any]] = field(default_factory=list)
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
    """Captures persistent state from a live session.

    Ephemeral state (locks, sockets, active Agent turn, pending confirmations,
    in-flight requests) is deliberately excluded. Completed replay journal entries
    and conversation_generation ARE persisted to ensure exactly-once semantics
    survive restarts.
    """
    mem = session.memory

    completed = []
    if hasattr(session, "completed_requests") and session.completed_requests:
        for r in list(session.completed_requests.values()):
            completed.append({
                "request_id": r.request_id,
                "fingerprint": r.fingerprint,
                "response": copy.deepcopy(r.response),
                "admitted_generation": r.admitted_generation,
                "size_bytes": r.size_bytes,
            })

    # Contract: SQLite request_tombstones table is the sole durable authority for 7-day replay protection.
    # Snapshot JSON does NOT persist tombstones (completed_tombstones = []) to eliminate dual-source-of-truth.
    return SessionSnapshot(
        session_id=session.session_id,
        presentation=session.document.presentation.model_dump(),
        document_epoch=session.document.epoch,
        messages=copy.deepcopy(mem.messages),
        agent_memory=mem.agent_memory.to_dict(),
        subagent_memories={name: m.to_dict() for name, m in mem.subagent_memories.items()},
        compressed_anchor=copy.deepcopy(mem.compressed_anchor),
        compression_through_index=mem.compression_through_index,
        conversation_generation=getattr(session, "conversation_generation", 0) or 0,
        completed_requests=completed,
        completed_tombstones=[],
        checkpoints=session.checkpoint_service.to_snapshots(),
        created_at=session.created_at.isoformat(),
        updated_at=session.updated_at.isoformat(),
    )


def snapshot_to_session(snapshot: SessionSnapshot) -> Any:
    """Reconstructs a live session from durable state (used on restore/restart)."""
    import json
    from .factory import SessionFactory
    from ..agent.memory import AgentMemory
    from ..agent.subagents.memory import SubagentSessionMemory
    from .session import (
        CompletedRequestRecord,
        RequestTombstone,
        MAX_COMPLETED_REQUESTS,
        MAX_COMPLETED_REQUEST_BYTES,
        MAX_COMPLETED_REQUEST_RECORD_BYTES,
        MAX_COMPLETED_TOMBSTONES,
    )

    session = SessionFactory.restore(snapshot, init_baseline=False)
    session.memory.messages = copy.deepcopy(snapshot.messages)
    session.memory.agent_memory = AgentMemory.from_dict(snapshot.agent_memory)
    session.memory.subagent_memories = {
        name: SubagentSessionMemory.from_dict(payload)
        for name, payload in (snapshot.subagent_memories or {}).items()
    }
    session.memory.compressed_anchor = copy.deepcopy(getattr(snapshot, "compressed_anchor", None))
    session.memory.compression_through_index = int(
        getattr(snapshot, "compression_through_index", 0) or 0
    )
    session.conversation_generation = int(getattr(snapshot, "conversation_generation", 0) or 0)

    # Clear in-memory tombstones on restore; SQLite request_tombstones table is sole durable authority
    # and tombstones will be warm-cached on-demand through WorkspaceManager authoritative lookups.
    session.completed_tombstones.clear()
    session.pending_tombstones.clear()

    # Re-validate and recalculate completed_requests budgets independently on restore
    session.completed_requests.clear()
    total_bytes = 0
    for item in getattr(snapshot, "completed_requests", []) or []:
        req_id = item.get("request_id")
        fingerprint = item.get("fingerprint")
        resp = item.get("response")
        admitted_gen = item.get("admitted_generation", 0)
        if not req_id or not fingerprint or not isinstance(resp, dict):
            continue
        try:
            actual_size = len(
                json.dumps(resp, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            )
        except Exception:
            continue
        if actual_size > MAX_COMPLETED_REQUEST_RECORD_BYTES:
            continue

        # Also ensure every completed request has a tombstone
        if req_id not in session.completed_tombstones:
            session.completed_tombstones[req_id] = RequestTombstone(
                request_id=req_id,
                fingerprint=fingerprint,
                admitted_generation=admitted_gen,
            )

        # Check total budget
        if total_bytes + actual_size > MAX_COMPLETED_REQUEST_BYTES or len(session.completed_requests) >= MAX_COMPLETED_REQUESTS:
            break

        total_bytes += actual_size
        session.completed_requests[req_id] = CompletedRequestRecord(
            request_id=req_id,
            fingerprint=fingerprint,
            response=resp,
            admitted_generation=admitted_gen,
            size_bytes=actual_size,
            durable=True,
        )

    session.checkpoint_service.restore_from_snapshots(snapshot.checkpoints)
    return session
