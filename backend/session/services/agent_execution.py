"""AgentExecutionService: session-scoped exclusive Agent edit window (S7/S8).

While a session has an active Agent/remediation turn, the frontend may not mutate
the document. The backend enforces this at the MutationGateway, not just in the
UI. A turn owns a ``turn_id``; only mutations that carry a matching ``turn_id``
from an agent-owned source ("agent", "remediation") are allowed through.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Sources allowed to write while an Agent turn holds the document freeze.
AGENT_OWNED_SOURCES = frozenset({"agent", "remediation"})


@dataclass
class AgentTurnLease:
    turn_id: str
    kind: str = "agent"


class DocumentFrozen(Exception):
    """Raised when a non-owner attempts to mutate a frozen session."""


class AgentExecutionService:
    """Owns the active Agent turn lease for one session."""

    def __init__(self) -> None:
        self.active_turn: Optional[AgentTurnLease] = None

    @property
    def is_frozen(self) -> bool:
        return self.active_turn is not None

    @property
    def active_turn_id(self) -> Optional[str]:
        return self.active_turn.turn_id if self.active_turn else None

    def begin_turn(self, turn_id: str, kind: str = "agent") -> AgentTurnLease:
        """Acquires the exclusive edit window for ``turn_id``.

        Fails closed when a different turn already owns the session.
        """
        if self.active_turn is not None and self.active_turn.turn_id != turn_id:
            raise DocumentFrozen("another agent turn is already active")
        lease = AgentTurnLease(turn_id=turn_id, kind=kind)
        self.active_turn = lease
        return lease

    def end_turn(self, turn_id: str) -> None:
        if self.active_turn is not None and self.active_turn.turn_id == turn_id:
            self.active_turn = None

    def allows(self, source: str, agent_turn_id: Optional[str]) -> bool:
        """True when a mutation from ``source``/``agent_turn_id`` may write."""
        lease = self.active_turn
        if lease is None:
            return True
        return source in AGENT_OWNED_SOURCES and agent_turn_id == lease.turn_id

    def assert_writable(self, source: str, agent_turn_id: Optional[str]) -> None:
        if not self.allows(source, agent_turn_id):
            raise DocumentFrozen("document is frozen by an active agent turn")

    def edit_lock(self) -> dict:
        lease = self.active_turn
        if lease is None:
            return {"locked": False, "kind": None, "turn_id": None}
        return {"locked": True, "kind": lease.kind, "turn_id": lease.turn_id}
