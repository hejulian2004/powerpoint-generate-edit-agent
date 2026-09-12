"""Transport-neutral canonical document protocol.

Every transport (WebSocket, REST, generation, upload, restore) describes the same
server document with the same envelope, built here. Neither the REST layer nor any
other module should reach into `server.websocket` for this.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def build_canonical_snapshot(
    session: Any,
    *,
    last_mutation_id: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Returns the canonical document snapshot for a session.

    This is the only server-document shape the frontend may adopt. `event_type`
    is transport metadata and is added by `build_presentation_event`, not here.
    """
    snapshot: Dict[str, Any] = {
        "session_id": session.session_id,
        "presentation": session.document.presentation.model_dump(),
        "document_epoch": session.document.epoch,
        "version": session.document.presentation.version,
        "active_slide_id": session.document.active_slide_id,
        "can_undo": session.history_service.can_undo(),
        "can_redo": session.history_service.can_redo(),
        "last_target_id": session.document.last_target_id,
        "last_mutation_id": last_mutation_id,
        "edit_lock": (
            session.agent_execution.edit_lock()
            if getattr(session, "agent_execution", None) is not None
            else {"locked": False, "kind": None, "turn_id": None}
        ),
    }
    if extra:
        snapshot.update(extra)
    return snapshot


def build_presentation_event(
    session: Any,
    event_type: str,
    *,
    last_mutation_id: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Wraps a canonical snapshot in a `presentation_loaded`/`_updated` event."""
    payload: Dict[str, Any] = {"type": event_type}
    payload.update(
        build_canonical_snapshot(
            session, last_mutation_id=last_mutation_id, extra=extra
        )
    )
    return payload
