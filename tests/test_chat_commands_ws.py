"""WebSocket integration tests for slash-command control messages."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app
from backend.session.manager import session_manager
from backend.session.session import PPTSession
from backend.state.store import create_default_demo_presentation


def _seed(session_id: str) -> PPTSession:
    session = session_manager.get_or_create(
        session_id, pres_factory=create_default_demo_presentation
    )
    session.pres = create_default_demo_presentation()
    session.history.clear()
    session.memory.clear_conversation()
    return session


def _drain_initial(ws) -> None:
    ws.receive_json()  # presentation_loaded
    ws.receive_json()  # preview_update


def _receive_until(ws, wanted: str, limit: int = 8) -> list[str]:
    seen: list[str] = []
    for _ in range(limit):
        msg = ws.receive_json()
        seen.append(msg.get("type", ""))
        if msg.get("type") == wanted:
            break
    return seen


def test_ws_new_conversation_resets_chat_but_keeps_deck():
    client = TestClient(app)
    session = _seed("ws_cmd_reset")
    session.add_message(role="user", content="hello")
    slides_before = len(session.document.presentation.slides)

    with client.websocket_connect("/ws?session_id=ws_cmd_reset") as ws:
        _drain_initial(ws)
        ws.send_json({"type": "new_conversation"})
        assert "conversation_reset" in _receive_until(ws, "conversation_reset")

    assert session.memory.messages == []
    assert len(session.document.presentation.slides) == slides_before


def test_ws_compress_context_persists_anchor():
    client = TestClient(app)
    session = _seed("ws_cmd_compress")
    for i in range(8):
        session.add_message(role="user", content=f"m{i}")
    raw_before = list(session.memory.messages)

    with client.websocket_connect("/ws?session_id=ws_cmd_compress") as ws:
        _drain_initial(ws)
        ws.send_json({"type": "compress_context"})
        assert "context_compressed" in _receive_until(ws, "context_compressed")

    assert session.memory.compressed_anchor is not None
    assert session.memory.messages == raw_before


def test_ws_set_plan_mode_toggles_session_mode():
    client = TestClient(app)
    session = _seed("ws_cmd_planmode")

    with client.websocket_connect("/ws?session_id=ws_cmd_planmode") as ws:
        _drain_initial(ws)
        ws.send_json({"type": "set_plan_mode", "mode": "plan"})
        assert "plan_mode_changed" in _receive_until(ws, "plan_mode_changed")

    assert session.interaction_mode == "plan"
