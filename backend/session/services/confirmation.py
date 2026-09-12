"""ConfirmationService: owns a session's pending low-confidence tool calls.

A pending confirmation is bound to the document identity it was blocked on
(``document_epoch`` + ``expected_revision`` + tool arguments). It is ephemeral
process state and is never persisted across a backend restart (contract P2).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional


class ConfirmationService:
    """Owns the pending-confirmation registry for one session."""

    def __init__(self) -> None:
        self.pending: Dict[str, Dict[str, Any]] = {}

    def register(
        self,
        call_id: str,
        tool: str,
        arguments: Dict[str, Any],
        confidence: Optional[float],
        presentation_version: int,
        target_element_id: Optional[str] = None,
        document_epoch: Optional[str] = None,
        expected_revision: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Stores a blocked call so the user can confirm the *original* invocation."""
        record = {
            "call_id": call_id,
            "tool": tool,
            "arguments": dict(arguments or {}),
            "confidence": confidence,
            "presentation_version": presentation_version,
            "expected_revision": (
                expected_revision if expected_revision is not None else presentation_version
            ),
            "document_epoch": document_epoch,
            "target_element_id": target_element_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.pending[call_id] = record
        return record

    def get(self, call_id: str) -> Optional[Dict[str, Any]]:
        return self.pending.get(call_id)

    def consume(self, call_id: str) -> Optional[Dict[str, Any]]:
        return self.pending.pop(call_id, None)

    def clear(self) -> bool:
        if self.pending:
            self.pending.clear()
            return True
        return False
