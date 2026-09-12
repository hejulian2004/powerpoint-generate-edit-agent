"""Phase 5 corrective: the websocket resolves an existing session only.

It must never implicitly create one; session creation is exclusively owned by
``WorkspaceManager.create_session``.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app
from backend.session.manager import session_manager


def test_websocket_rejects_missing_session_id():
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "session_error"
        assert msg["error"] == "MISSING_SESSION_ID"


def test_websocket_does_not_implicitly_create_unknown_session():
    client = TestClient(app)
    ghost = "ghost_ws_authority_404"
    session_manager.delete_session(ghost)
    with client.websocket_connect(f"/ws?session_id={ghost}") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "session_error"
        assert msg["error"] == "SESSION_NOT_FOUND"

    # No implicit creation happened.
    assert session_manager.get_session(ghost) is None
