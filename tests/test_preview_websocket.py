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


def test_websocket_group_align_ungroup_direct_actions():
    """Verify group_elements / align_elements / ungroup_elements via direct_action."""
    client = TestClient(app)
    _seed_demo_session("ws_group_align")
    with client.websocket_connect("/ws?session_id=ws_group_align") as ws:
        ws.receive_json()  # presentation_loaded
        ws.receive_json()  # preview_update

        # 1. Group two cards
        ws.send_json({
            "type": "direct_action",
            "action": "group_elements",
            "payload": {
                "slide_id": "slide_01",
                "element_ids": ["card_ir", "card_agent"],
                "group_name": "Test Group"
            }
        })
        ev_group = ws.receive_json()
        assert ev_group["type"] == "presentation_updated"
        group_id = ev_group["last_target_id"]
        assert group_id and group_id.startswith("grp_")
        ws.receive_json()  # preview_update

        slide1 = next(s for s in ev_group["presentation"]["slides"] if s["id"] == "slide_01")
        group = next(e for e in slide1["elements"] if e["id"] == group_id)
        assert group["type"] == "group"
        assert len(group["children"]) == 2
        assert not any(e["id"] == "card_ir" for e in slide1["elements"])

        # 2. Align remaining top-level cards
        ws.send_json({
            "type": "direct_action",
            "action": "align_elements",
            "payload": {
                "slide_id": "slide_01",
                "alignment": "top",
                "element_ids": ["card_preview", group_id]
            }
        })
        ev_align = ws.receive_json()
        assert ev_align["type"] == "presentation_updated"
        assert ev_align["last_target_id"] is None
        ws.receive_json()  # preview_update

        slide1 = next(s for s in ev_align["presentation"]["slides"] if s["id"] == "slide_01")
        top_ys = [
            e["y"] for e in slide1["elements"]
            if e["id"] in ("card_preview", group_id)
        ]
        assert len(top_ys) == 2 and abs(top_ys[0] - top_ys[1]) < 1.0

        # 3. Ungroup restores children as top-level elements
        ws.send_json({
            "type": "direct_action",
            "action": "ungroup_elements",
            "payload": {"slide_id": "slide_01", "group_id": group_id}
        })
        ev_ungroup = ws.receive_json()
        assert ev_ungroup["type"] == "presentation_updated"
        assert ev_ungroup["last_target_id"] is None
        ws.receive_json()  # preview_update

        slide1 = next(s for s in ev_ungroup["presentation"]["slides"] if s["id"] == "slide_01")
        top_ids = {e["id"] for e in slide1["elements"]}
        assert "card_ir" in top_ids and "card_agent" in top_ids


def test_websocket_duplicate_and_clear_slide_direct_actions():
    """Verify duplicate_slide and clear_slide_elements via direct_action."""
    client = TestClient(app)
    _seed_demo_session("ws_slide_actions")
    with client.websocket_connect("/ws?session_id=ws_slide_actions") as ws:
        ws.receive_json()  # presentation_loaded
        ws.receive_json()  # preview_update

        # 1. Duplicate active slide
        ws.send_json({
            "type": "direct_action",
            "action": "duplicate_slide",
            "payload": {"slide_id": "slide_01"}
        })
        ev_dup = ws.receive_json()
        assert ev_dup["type"] == "presentation_updated"
        assert len(ev_dup["presentation"]["slides"]) >= 2
        duplicate_id = ev_dup["active_slide_id"]
        assert duplicate_id != "slide_01"
        ws.receive_json()  # preview_update

        duplicate = next(s for s in ev_dup["presentation"]["slides"] if s["id"] == duplicate_id)
        assert len(duplicate["elements"]) > 0

        # 2. Clear duplicated slide but keep title (y < 150)
        ws.send_json({
            "type": "direct_action",
            "action": "clear_slide_elements",
            "payload": {"slide_id": duplicate_id, "keep_title": True}
        })
        ev_clear = ws.receive_json()
        assert ev_clear["type"] == "presentation_updated"
        ws.receive_json()  # preview_update

        cleared = next(s for s in ev_clear["presentation"]["slides"] if s["id"] == duplicate_id)
        assert len(cleared["elements"]) < len(duplicate["elements"])


def test_websocket_generate_slide_layout_direct_action():
    """Verify generate_slide_layout via direct_action populates the target slide."""
    client = TestClient(app)
    _seed_demo_session("ws_layout_archetype")
    with client.websocket_connect("/ws?session_id=ws_layout_archetype") as ws:
        ws.receive_json()  # presentation_loaded
        ws.receive_json()  # preview_update

        ws.send_json({
            "type": "direct_action",
            "action": "generate_slide_layout",
            "payload": {
                "slide_id": "slide_02",
                "layout_type": "timeline",
                "title": "发展历程",
                "clear_existing": True,
                "items": [
                    {"title": "阶段一", "description": "需求分析"},
                    {"title": "阶段二", "description": "架构研发"},
                    {"title": "阶段三", "description": "质检上线"}
                ]
            }
        })
        ev = ws.receive_json()
        assert ev["type"] == "presentation_updated"
        ws.receive_json()  # preview_update

        slide2 = next(s for s in ev["presentation"]["slides"] if s["id"] == "slide_02")
        assert len(slide2["elements"]) > 0
        assert slide2["title"] == "发展历程"
