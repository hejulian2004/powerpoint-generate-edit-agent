"""AgentExecutionService: session-scoped exclusive Agent edit window (S7/S8).

While a session has an active Agent/remediation turn, the frontend may not mutate
the document. The backend enforces this at the MutationGateway, not just in the
UI. A turn owns a ``turn_id``; only mutations that carry a matching ``turn_id``
from an agent-owned source ("agent", "remediation") are allowed through.

Admission is not self-contained here: the caller (``AgentRuntime.run_turn``) must
validate the request CAS and call :meth:`begin_turn` inside the SAME
``document.mutation_lock`` critical section, so a GUI write cannot slip in
between "CAS passed" and "the freeze exists".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

# Sources allowed to write while an Agent turn holds the document freeze.
AGENT_OWNED_SOURCES = frozenset({"agent", "remediation"})

# A second Agent turn attempted to acquire an already-owned session. Distinct from
# a frozen GUI write so the caller can report a precise rejection code.
AGENT_TURN_IN_PROGRESS = "agent_turn_in_progress"


@dataclass
class AgentTurn:
    """A live Agent turn lease, pinned to the document identity it admitted."""

    turn_id: str
    document_epoch: Optional[str] = None
    base_revision: Optional[int] = None
    kind: str = "agent"
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class DocumentFrozen(Exception):
    """Raised when a non-owner attempts to mutate a frozen session."""


class AgentTurnInProgress(Exception):
    """Raised when a second Agent turn tries to acquire an already-owned session."""


class AgentExecutionService:
    """Owns the active Agent turn lease for one session."""

    def __init__(self) -> None:
        self.active_turn: Optional[AgentTurn] = None

    @property
    def is_frozen(self) -> bool:
        return self.active_turn is not None

    @property
    def active_turn_id(self) -> Optional[str]:
        return self.active_turn.turn_id if self.active_turn else None

    def begin_turn(
        self,
        turn_id: str,
        *,
        document_epoch: Optional[str] = None,
        base_revision: Optional[int] = None,
        kind: str = "agent",
    ) -> AgentTurn:
        """Acquires the exclusive edit window for ``turn_id``.

        Fails closed when a different turn already owns the session. Re-entering
        with the SAME ``turn_id`` is idempotent (returns the live lease).
        """
        if self.active_turn is not None:
            if self.active_turn.turn_id == turn_id:
                return self.active_turn
            raise AgentTurnInProgress("another agent turn is already active")
        turn = AgentTurn(
            turn_id=turn_id,
            document_epoch=document_epoch,
            base_revision=base_revision,
            kind=kind,
        )
        self.active_turn = turn
        return turn

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
        return {
            "locked": True,
            "kind": lease.kind,
            "turn_id": lease.turn_id,
            "base_revision": lease.base_revision,
        }
