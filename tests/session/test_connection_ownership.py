"""Phase 5: single writable frontend per session (newest tab wins)."""

from __future__ import annotations

import pytest

from backend.session.services.connection import (
    ConnectionService,
    ConnectionTakenOver,
    SESSION_TAKEN_OVER,
)


def test_connection_service_binds_newest_and_rejects_old():
    service = ConnectionService()
    old, gen_old = service.attach("ws_old")
    assert old is None
    assert gen_old == 1

    previous, gen_new = service.attach("ws_new")
    assert previous == "ws_old"
    assert gen_new == 2

    assert service.is_current("ws_new") is True
    assert service.is_current("ws_old") is False
    with pytest.raises(ConnectionTakenOver):
        service.assert_current("ws_old", gen_old)
    # Server-bound generation: a superseded generation never becomes valid again.
    with pytest.raises(ConnectionTakenOver):
        service.assert_current("ws_new", gen_old)
    service.assert_current("ws_new", gen_new)


def test_detach_only_clears_the_current_owner():
    service = ConnectionService()
    service.attach("ws_a")
    service.detach("ws_stale")
    assert service.websocket == "ws_a"
    service.detach("ws_a")
    assert service.websocket is None


def test_second_tab_takes_over_and_old_socket_is_closed():
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.state.store import store

    client = TestClient(app)
    sid = "ws_takeover_test"
    try:
        with client.websocket_connect(f"/ws?session_id={sid}") as first:
            first_msg = first.receive_json()
            assert first_msg["type"] == "presentation_loaded"
            assert first_msg.get("connection_generation") == 1

            with client.websocket_connect(f"/ws?session_id={sid}") as second:
                second_msg = second.receive_json()
                assert second_msg["type"] == "presentation_loaded"
                assert second_msg.get("connection_generation") == 2

                takeover = first.receive_json()
                assert takeover["type"] == SESSION_TAKEN_OVER
                assert takeover["session_id"] == sid

                session = store.session_manager.get_session(sid)
                assert session.connection.connection_generation == 2
                assert session.connection.websocket is not None
    finally:
        store.session_manager.delete_session(sid)
