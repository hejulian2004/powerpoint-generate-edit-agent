"""Tests for Real-time Preview Service and WebSocket Streaming (Phase 5.3)."""

import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.session.session import PPTSession
from backend.session.manager import session_manager
from backend.state.store import create_default_demo_presentation
from backend.server.websocket import build_preview_update


def _seed_demo_session(session_id: str) -> PPTSession:
    """Seeds a fresh demo presentation into the session so WS tests stay deterministic."""
    session = session_manager.get_or_create(session_id, pres_factory=create_default_demo_presentation)
    session.pres = create_default_demo_presentation()
    session.history.clear()
    return session


def test_build_preview_update_unit():
    """Verify build_preview_update produces valid SVG markup and layout score."""
    pres = create_default_demo_presentation()
    session = PPTSession(session_id="test_preview_unit", pres=pres)

    preview = build_preview_update(session)
    assert preview is not None
    assert preview["type"] == "preview_update"
    assert preview["session_id"] == "test_preview_unit"
    assert preview["slide_id"] == "slide_01"
    assert "<svg" in preview["svg"]
    assert "</svg>" in preview["svg"]
    assert isinstance(preview["score"], float)
    assert 0.0 <= preview["score"] <= 100.0

    # Verify quality_score breakdown
    qs = preview["quality_score"]
    assert "geometry" in qs
    assert "readability" in qs
    assert "contrast" in qs
    assert "balance" in qs
    assert "total" in qs


def test_websocket_connection_and_preview_stream():
    """Verify WebSocket endpoint sends presentation_loaded and initial preview_update."""
    client = TestClient(app)
    _seed_demo_session("ws_stream_test")
    with client.websocket_connect("/ws?session_id=ws_stream_test") as ws:
        # 1. First message: presentation_loaded
        loaded = ws.receive_json()
        assert loaded["type"] == "presentation_loaded"
        assert loaded["session_id"] == "ws_stream_test"
        assert "presentation" in loaded

        # 2. Second message: initial preview_update
        preview = ws.receive_json()
        assert preview["type"] == "preview_update"
        assert preview["session_id"] == "ws_stream_test"
        assert "<svg" in preview["svg"]
        assert preview["score"] >= 70.0

        # 3. Request immediate preview on demand
        ws.send_json({"type": "preview_request", "slide_id": "slide_01"})
        preview_res = ws.receive_json()
        assert preview_res["type"] == "preview_update"
        assert preview_res["slide_id"] == "slide_01"


def test_websocket_slide_selection_and_direct_update():
    """Verify select_slide and direct_update_element trigger preview_update."""
    client = TestClient(app)
    _seed_demo_session("ws_slide_ops")
    with client.websocket_connect("/ws?session_id=ws_slide_ops") as ws:
        # Drain initial loaded & preview
        ws.receive_json()
        ws.receive_json()

        # 1. Select Slide 2
        ws.send_json({"type": "select_slide", "slide_id": "slide_02"})
        ev_slide = ws.receive_json()
        assert ev_slide["type"] == "active_slide_changed"
        assert ev_slide["active_slide_id"] == "slide_02"

        ev_prev = ws.receive_json()
        assert ev_prev["type"] == "preview_update"
        assert ev_prev["slide_id"] == "slide_02"

        # 2. Direct update element
        ws.send_json({
            "type": "direct_update_element",
            "payload": {
                "slide_id": "slide_02",
                "element_id": "s2_title",
                "x": 200.0
            }
        })
        ev_upd = ws.receive_json()
        assert ev_upd["type"] == "presentation_updated"

        ev_upd_prev = ws.receive_json()
        assert ev_upd_prev["type"] == "preview_update"
        assert ev_upd_prev["slide_id"] == "slide_02"


def test_websocket_undo_redo_preview():
    """Verify WebSocket undo and redo trigger preview_update."""
    client = TestClient(app)
    _seed_demo_session("ws_undo_redo")
    with client.websocket_connect("/ws?session_id=ws_undo_redo") as ws:
        # Drain initial loaded & preview
        ws.receive_json()
        ws.receive_json()

        # Modify element
        ws.send_json({
            "type": "direct_update_element",
            "payload": {
                "slide_id": "slide_01",
                "element_id": "title_main",
                "x": 350.0
            }
        })
        ws.receive_json()  # presentation_updated
        ws.receive_json()  # preview_update

        # Send Undo
        ws.send_json({"type": "undo"})
        ev_undo_pres = ws.receive_json()
        assert ev_undo_pres["type"] == "presentation_updated"

        ev_undo_prev = ws.receive_json()
        assert ev_undo_prev["type"] == "preview_update"
