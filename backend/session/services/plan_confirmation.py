"""PlanConfirmationService: owns a session's plans awaiting user approval.

When the session is in "plan" interaction mode the graph pauses after the plan
critic approves, registers the frozen plan here, and returns control to the user.
A pending plan is bound to the document identity it was drafted against
(``document_epoch`` + ``expected_revision``); if the document changes before the
user confirms, the plan is invalidated rather than silently executed.

Like :class:`ConfirmationService` this is ephemeral process state and is never
persisted across a backend restart (contract P2).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional


class PlanConfirmationService:
    """Owns the pending-plan registry for one session."""

    def __init__(self) -> None:
        self.pending: Dict[str, Dict[str, Any]] = {}

    def register(
        self,
        plan_id: str,
        plan: str,
        plan_review: Optional[Dict[str, Any]],
        user_query: str,
        document_epoch: Optional[str],
        expected_revision: Optional[int],
        active_slide_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        record = {
            "plan_id": plan_id,
            "plan": plan,
            "plan_review": dict(plan_review or {}),
            "user_query": user_query,
            "document_epoch": document_epoch,
            "expected_revision": expected_revision,
            "active_slide_id": active_slide_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.pending[plan_id] = record
        return record

    def get(self, plan_id: str) -> Optional[Dict[str, Any]]:
        return self.pending.get(plan_id)

    def consume(self, plan_id: str) -> Optional[Dict[str, Any]]:
        return self.pending.pop(plan_id, None)

    def clear(self) -> bool:
        if self.pending:
            self.pending.clear()
            return True
        return False
