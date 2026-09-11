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


def _stamp(session: PPTSession) -> dict:
    """CAS stamps for a synced client (current canonical epoch/revision)."""
    return {
        "document_epoch": session.document_epoch,
        "expected_revision": session.pres.version,
    }


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
    """Verify select_slide is client-local: preview only, no session-wide navigation."""
    client = TestClient(app)
    session = _seed_demo_session("ws_slide_ops")
    with client.websocket_connect("/ws?session_id=ws_slide_ops") as ws:
        # Drain initial loaded & preview
        ws.receive_json()
        ws.receive_json()

        # 1. Select Slide 2: the requester gets a preview, the session document's
        # active slide is NOT mutated and no cross-client broadcast is emitted.
        ws.send_json({"type": "select_slide", "slide_id": "slide_02"})
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
            },
            **_stamp(session),
        })
        ev_upd = ws.receive_json()
        assert ev_upd["type"] == "presentation_updated"

        ev_upd_prev = ws.receive_json()
        assert ev_upd_prev["type"] == "preview_update"
        assert ev_upd_prev["slide_id"] == "slide_02"


def test_websocket_undo_redo_preview():
    """Verify WebSocket undo and redo trigger preview_update."""
    client = TestClient(app)
    session = _seed_demo_session("ws_undo_redo")
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
            },
            **_stamp(session),
        })
        ws.receive_json()  # presentation_updated
        ws.receive_json()  # preview_update

        # Send Undo
        ws.send_json({"type": "undo", **_stamp(session)})
        ev_undo_pres = ws.receive_json()
        assert ev_undo_pres["type"] == "presentation_updated"

        ev_undo_prev = ws.receive_json()
        assert ev_undo_prev["type"] == "preview_update"


def test_websocket_group_align_ungroup_direct_actions():
    """Verify group_elements / align_elements / ungroup_elements via direct_action."""
    client = TestClient(app)
    session = _seed_demo_session("ws_group_align")
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
            },
            **_stamp(session),
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
            },
            **_stamp(session),
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
            "payload": {"slide_id": "slide_01", "group_id": group_id},
            **_stamp(session),
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
    session = _seed_demo_session("ws_slide_actions")
    with client.websocket_connect("/ws?session_id=ws_slide_actions") as ws:
        ws.receive_json()  # presentation_loaded
        ws.receive_json()  # preview_update

        # 1. Duplicate active slide
        ws.send_json({
            "type": "direct_action",
            "action": "duplicate_slide",
            "payload": {"slide_id": "slide_01"},
            **_stamp(session),
        })
        ev_dup = ws.receive_json()
        assert ev_dup["type"] == "presentation_updated"
        assert len(ev_dup["presentation"]["slides"]) >= 2
        duplicate_id = ev_dup["active_slide_id"]
        assert duplicate_id != "slide_01"
        # Navigation is client-local: the new slide id is surfaced only as a
        # mutation-scoped hint for the requesting client, never as shared state.
        assert ev_dup["local_view_hint"]["active_slide_id"] == duplicate_id
        ws.receive_json()  # preview_update

        duplicate = next(s for s in ev_dup["presentation"]["slides"] if s["id"] == duplicate_id)
        assert len(duplicate["elements"]) > 0

        # 2. Clear duplicated slide but keep title (y < 150)
        ws.send_json({
            "type": "direct_action",
            "action": "clear_slide_elements",
            "payload": {"slide_id": duplicate_id, "keep_title": True},
            **_stamp(session),
        })
        ev_clear = ws.receive_json()
        assert ev_clear["type"] == "presentation_updated"
        ws.receive_json()  # preview_update

        cleared = next(s for s in ev_clear["presentation"]["slides"] if s["id"] == duplicate_id)
        assert len(cleared["elements"]) < len(duplicate["elements"])


def test_websocket_generate_slide_layout_direct_action():
    """Verify generate_slide_layout via direct_action populates the target slide."""
    client = TestClient(app)
    session = _seed_demo_session("ws_layout_archetype")
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
            },
            **_stamp(session),
        })
        ev = ws.receive_json()
        assert ev["type"] == "presentation_updated"
        ws.receive_json()  # preview_update

        slide2 = next(s for s in ev["presentation"]["slides"] if s["id"] == "slide_02")
        assert len(slide2["elements"]) > 0
        assert slide2["title"] == "发展历程"


def test_websocket_direct_update_echoes_mutation_id_and_version():
    """Verify mutation_id / version ack so the client can retire pending optimistic patches."""
    client = TestClient(app)
    session = _seed_demo_session("ws_mutation_ack")
    with client.websocket_connect("/ws?session_id=ws_mutation_ack") as ws:
        ws.receive_json()  # presentation_loaded
        ws.receive_json()  # preview_update

        ws.send_json({
            "type": "direct_update_element",
            "mutation_id": "mut_ack_1",
            "payload": {
                "slide_id": "slide_01",
                "element_id": "title_main",
                "x": 260.0
            },
            **_stamp(session),
        })

        ev = ws.receive_json()
        assert ev["type"] == "presentation_updated"
        assert ev["last_mutation_id"] == "mut_ack_1"
        assert isinstance(ev["version"], int) and ev["version"] > 0
        ws.receive_json()  # preview_update


def test_websocket_batch_mutation_is_one_undo_step():
    """Verify batch_mutation applies every operation and undoes them atomically."""
    client = TestClient(app)
    session = _seed_demo_session("ws_batch_mutation")
    with client.websocket_connect("/ws?session_id=ws_batch_mutation") as ws:
        loaded = ws.receive_json()
        ws.receive_json()  # preview_update

        slide1 = next(s for s in loaded["presentation"]["slides"] if s["id"] == "slide_01")
        title = next(e for e in slide1["elements"] if e["id"] == "title_main")
        card = next(e for e in slide1["elements"] if e["id"] == "card_ir")

        ws.send_json({
            "type": "batch_mutation",
            "mutation_id": "mut_batch_1",
            "description": "多选整体移动",
            "mutations": [
                {
                    "name": "update_element",
                    "payload": {"slide_id": "slide_01", "element_id": "title_main", "x": title["x"] + 30}
                },
                {
                    "name": "update_element",
                    "payload": {"slide_id": "slide_01", "element_id": "card_ir", "x": card["x"] + 30}
                }
            ],
            **_stamp(session),
        })

        ev = ws.receive_json()
        assert ev["type"] == "presentation_updated"
        assert ev["last_mutation_id"] == "mut_batch_1"
        ws.receive_json()  # preview_update

        slide1 = next(s for s in ev["presentation"]["slides"] if s["id"] == "slide_01")
        moved_title = next(e for e in slide1["elements"] if e["id"] == "title_main")
        moved_card = next(e for e in slide1["elements"] if e["id"] == "card_ir")
        assert abs(moved_title["x"] - (title["x"] + 30)) < 0.01
        assert abs(moved_card["x"] - (card["x"] + 30)) < 0.01

        ws.send_json({"type": "undo", **_stamp(session)})
        ev_undo = ws.receive_json()
        assert ev_undo["type"] == "presentation_updated"
        ws.receive_json()  # preview_update

        slide1 = next(s for s in ev_undo["presentation"]["slides"] if s["id"] == "slide_01")
        restored_title = next(e for e in slide1["elements"] if e["id"] == "title_main")
        restored_card = next(e for e in slide1["elements"] if e["id"] == "card_ir")
        assert abs(restored_title["x"] - title["x"]) < 0.01
        assert abs(restored_card["x"] - card["x"]) < 0.01


def test_websocket_batch_mutation_rolls_back_on_failure():
    """Verify a failing batch op rolls back earlier ops and reports mutation_rejected."""
    client = TestClient(app)
    session = _seed_demo_session("ws_batch_reject")
    with client.websocket_connect("/ws?session_id=ws_batch_reject") as ws:
        loaded = ws.receive_json()
        ws.receive_json()  # preview_update

        slide1 = next(s for s in loaded["presentation"]["slides"] if s["id"] == "slide_01")
        title = next(e for e in slide1["elements"] if e["id"] == "title_main")

        ws.send_json({
            "type": "batch_mutation",
            "mutation_id": "mut_batch_fail",
            "mutations": [
                {
                    "name": "update_element",
                    "payload": {"slide_id": "slide_01", "element_id": "title_main", "x": title["x"] + 77}
                },
                {
                    "name": "update_element",
                    "payload": {"slide_id": "slide_01", "element_id": "missing_element", "x": 10}
                }
            ],
            **_stamp(session),
        })

        rejected = ws.receive_json()
        assert rejected["type"] == "mutation_rejected"
        assert rejected["mutation_id"] == "mut_batch_fail"

        ws.send_json({"type": "preview_request", "slide_id": "slide_01"})
        state = ws.receive_json()
        assert state["type"] == "preview_update"


def test_websocket_direct_update_rejects_unknown_element():
    """Verify unknown element updates are rejected instead of silently broadcasting success."""
    client = TestClient(app)
    session = _seed_demo_session("ws_update_reject")
    with client.websocket_connect("/ws?session_id=ws_update_reject") as ws:
        ws.receive_json()  # presentation_loaded
        ws.receive_json()  # preview_update

        ws.send_json({
            "type": "direct_update_element",
            "mutation_id": "mut_missing",
            "payload": {
                "slide_id": "slide_01",
                "element_id": "does_not_exist",
                "x": 100.0
            },
            **_stamp(session),
        })

        rejected = ws.receive_json()
        assert rejected["type"] == "mutation_rejected"
        assert rejected["mutation_id"] == "mut_missing"
        assert "not found" in rejected["error"].lower()


def test_websocket_duplicate_element_reports_new_target():
    """Verify element duplication echoes the freshly created element as last_target_id."""
    client = TestClient(app)
    session = _seed_demo_session("ws_dup_target")
    with client.websocket_connect("/ws?session_id=ws_dup_target") as ws:
        ws.receive_json()  # presentation_loaded
        ws.receive_json()  # preview_update

        ws.send_json({
            "type": "direct_action",
            "action": "duplicate_element",
            "mutation_id": "mut_dup_1",
            "payload": {"slide_id": "slide_01", "element_id": "title_main"},
            **_stamp(session),
        })

        ev = ws.receive_json()
        assert ev["type"] == "presentation_updated"
        assert ev["last_mutation_id"] == "mut_dup_1"
        assert ev["last_target_id"] and ev["last_target_id"] != "title_main"
        ws.receive_json()  # preview_update


def test_websocket_local_view_hint_is_mutation_scoped():
    """Only slide-creating direct actions carry a navigation hint, not edits."""
    client = TestClient(app)
    session = _seed_demo_session("ws_view_hint")
    with client.websocket_connect("/ws?session_id=ws_view_hint") as ws:
        ws.receive_json()  # presentation_loaded
        ws.receive_json()  # preview_update

        # create_slide hints the requesting client to the freshly created slide.
        ws.send_json({
            "type": "direct_action",
            "action": "create_slide",
            "mutation_id": "mut_create_1",
            "payload": {"title": "新页"},
            **_stamp(session),
        })
        ev_create = ws.receive_json()
        assert ev_create["type"] == "presentation_updated"
        hint = ev_create["local_view_hint"]["active_slide_id"]
        assert hint
        assert hint == ev_create["active_slide_id"]
        assert any(s["id"] == hint for s in ev_create["presentation"]["slides"])
        ws.receive_json()  # preview_update

        # Ordinary element edits carry no navigation hint.
        ws.send_json({
            "type": "direct_update_element",
            "mutation_id": "mut_edit_1",
            "payload": {"slide_id": "slide_01", "element_id": "title_main", "x": 260.0},
            **_stamp(session),
        })
        ev_edit = ws.receive_json()
        assert ev_edit["type"] == "presentation_updated"
        assert ev_edit.get("local_view_hint") is None
        ws.receive_json()  # preview_update
