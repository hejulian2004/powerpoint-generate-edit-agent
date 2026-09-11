"""Phase 1.6: WebSocket mutation envelope protocol.

Verifies the client-facing contract:
- `presentation_updated` carries `last_mutation_id` / `version` / `document_epoch`.
- A failed direct/batch mutation emits `mutation_rejected` instead of a success.
- `batch_mutation` is atomic and collapses into a single undo step.
"""

from fastapi.testclient import TestClient

from backend.main import app
from backend.session.manager import session_manager
from backend.state.store import create_default_demo_presentation


def _seed_demo_session(session_id: str):
    session = session_manager.get_or_create(
        session_id, pres_factory=create_default_demo_presentation
    )
    session.pres = create_default_demo_presentation()
    session.history.clear()
    return session


def _find_element(presentation, slide_id, element_id):
    slide = next(s for s in presentation["slides"] if s["id"] == slide_id)
    return next(e for e in slide["elements"] if e["id"] == element_id)


def _stamp(session):
    """CAS stamps for a synced client (the current canonical epoch/revision)."""
    return {
        "document_epoch": session.document_epoch,
        "expected_revision": session.pres.version,
    }


def test_direct_update_echoes_mutation_id_and_version():
    client = TestClient(app)
    session = _seed_demo_session("ws_proto_ack")
    with client.websocket_connect("/ws?session_id=ws_proto_ack") as ws:
        ws.receive_json()  # presentation_loaded
        ws.receive_json()  # preview_update

        ws.send_json({
            "type": "direct_update_element",
            "mutation_id": "mut_ack_1",
            "payload": {"slide_id": "slide_01", "element_id": "title_main", "x": 260.0},
            **_stamp(session),
        })
        ev = ws.receive_json()
        assert ev["type"] == "presentation_updated"
        assert ev["last_mutation_id"] == "mut_ack_1"
        assert isinstance(ev["version"], int) and ev["version"] > 0
        ws.receive_json()  # preview_update


def test_direct_update_rejects_unknown_element():
    client = TestClient(app)
    session = _seed_demo_session("ws_proto_reject")
    with client.websocket_connect("/ws?session_id=ws_proto_reject") as ws:
        ws.receive_json()
        ws.receive_json()

        ws.send_json({
            "type": "direct_update_element",
            "mutation_id": "mut_missing",
            "payload": {"slide_id": "slide_01", "element_id": "does_not_exist", "x": 100.0},
            **_stamp(session),
        })
        rejected = ws.receive_json()
        assert rejected["type"] == "mutation_rejected"
        assert rejected["mutation_id"] == "mut_missing"
        assert "not found" in rejected["error"].lower()


def test_batch_mutation_is_one_undo_step():
    client = TestClient(app)
    session = _seed_demo_session("ws_proto_batch")
    with client.websocket_connect("/ws?session_id=ws_proto_batch") as ws:
        loaded = ws.receive_json()
        ws.receive_json()  # preview_update

        title = _find_element(loaded["presentation"], "slide_01", "title_main")
        card = _find_element(loaded["presentation"], "slide_01", "card_ir")

        ws.send_json({
            "type": "batch_mutation",
            "mutation_id": "mut_batch_1",
            "mutations": [
                {"name": "update_element",
                 "payload": {"slide_id": "slide_01", "element_id": "title_main", "x": title["x"] + 30}},
                {"name": "update_element",
                 "payload": {"slide_id": "slide_01", "element_id": "card_ir", "x": card["x"] + 30}},
            ],
            **_stamp(session),
        })
        ev = ws.receive_json()
        assert ev["type"] == "presentation_updated"
        assert ev["last_mutation_id"] == "mut_batch_1"
        moved_title = _find_element(ev["presentation"], "slide_01", "title_main")
        moved_card = _find_element(ev["presentation"], "slide_01", "card_ir")
        assert abs(moved_title["x"] - (title["x"] + 30)) < 0.01
        assert abs(moved_card["x"] - (card["x"] + 30)) < 0.01
        ws.receive_json()  # preview_update

        # One undo restores BOTH operations.
        ws.send_json({"type": "undo", "mutation_id": "mut_batch_undo", **_stamp(session)})
        undo_ev = ws.receive_json()
        assert undo_ev["type"] == "presentation_updated"
        restored_title = _find_element(undo_ev["presentation"], "slide_01", "title_main")
        restored_card = _find_element(undo_ev["presentation"], "slide_01", "card_ir")
        assert abs(restored_title["x"] - title["x"]) < 0.01
        assert abs(restored_card["x"] - card["x"]) < 0.01


def test_batch_mutation_rolls_back_on_failure():
    client = TestClient(app)
    session = _seed_demo_session("ws_proto_batch_fail")
    with client.websocket_connect("/ws?session_id=ws_proto_batch_fail") as ws:
        loaded = ws.receive_json()
        ws.receive_json()

        title = _find_element(loaded["presentation"], "slide_01", "title_main")

        ws.send_json({
            "type": "batch_mutation",
            "mutation_id": "mut_batch_fail",
            "mutations": [
                {"name": "update_element",
                 "payload": {"slide_id": "slide_01", "element_id": "title_main", "x": title["x"] + 77}},
                {"name": "update_element",
                 "payload": {"slide_id": "slide_01", "element_id": "missing_element", "x": 10}},
            ],
            **_stamp(session),
        })
        rejected = ws.receive_json()
        assert rejected["type"] == "mutation_rejected"
        assert rejected["mutation_id"] == "mut_batch_fail"

        # The first op must have been rolled back: a follow-up read sees the original x.
        ws.send_json({
            "type": "direct_update_element",
            "mutation_id": "mut_read",
            "payload": {"slide_id": "slide_01", "element_id": "title_main", "x": title["x"]},
            **_stamp(session),
        })
        ev = ws.receive_json()
        assert ev["type"] == "presentation_updated"
        after = _find_element(ev["presentation"], "slide_01", "title_main")
        assert abs(after["x"] - title["x"]) < 0.01


def test_undo_routes_through_gateway_with_mutation_id_and_cas():
    client = TestClient(app)
    session = _seed_demo_session("ws_proto_undo_gateway")
    with client.websocket_connect("/ws?session_id=ws_proto_undo_gateway") as ws:
        loaded = ws.receive_json()
        ws.receive_json()  # preview_update
        title = _find_element(loaded["presentation"], "slide_01", "title_main")

        ws.send_json({
            "type": "direct_update_element",
            "mutation_id": "mut_edit_1",
            "payload": {"slide_id": "slide_01", "element_id": "title_main", "x": title["x"] + 42},
            **_stamp(session),
        })
        edit_ev = ws.receive_json()
        assert edit_ev["type"] == "presentation_updated"
        ws.receive_json()  # preview_update
        moved_version = edit_ev["version"]

        ws.send_json({
            "type": "undo",
            "mutation_id": "mut_undo_1",
            "document_epoch": loaded.get("document_epoch"),
            "expected_revision": moved_version,
        })
        undo_ev = ws.receive_json()
        assert undo_ev["type"] == "presentation_updated"
        assert undo_ev["last_mutation_id"] == "mut_undo_1"
        assert undo_ev["version"] == moved_version + 1
        restored = _find_element(undo_ev["presentation"], "slide_01", "title_main")
        assert abs(restored["x"] - title["x"]) < 0.01
        ws.receive_json()  # preview_update

        # A stale expected_revision is refused by CAS instead of replaying blindly.
        ws.send_json({
            "type": "redo",
            "mutation_id": "mut_redo_stale",
            "document_epoch": loaded.get("document_epoch"),
            "expected_revision": moved_version,
        })
        rejected = ws.receive_json()
        assert rejected["type"] == "mutation_rejected"
        assert rejected["mutation_id"] == "mut_redo_stale"
        assert rejected["error"] == "stale_mutation"
        # CAS-class rejections must carry the authoritative snapshot for atomic resync.
        assert rejected["presentation"] is not None
        assert rejected["active_slide_id"] == "slide_01"


def test_undo_with_empty_history_is_acknowledged_noop():
    client = TestClient(app)
    session = _seed_demo_session("ws_proto_undo_noop")
    with client.websocket_connect("/ws?session_id=ws_proto_undo_noop") as ws:
        ws.receive_json()
        ws.receive_json()

        ws.send_json({"type": "undo", "mutation_id": "mut_noop", **_stamp(session)})
        ev = ws.receive_json()
        assert ev["type"] == "presentation_updated"
        assert ev["last_mutation_id"] == "mut_noop"


def test_replayed_mutation_id_is_idempotent():
    """A committed mutation whose ACK was lost must not execute twice on replay."""
    client = TestClient(app)
    session = _seed_demo_session("ws_proto_idem")
    with client.websocket_connect("/ws?session_id=ws_proto_idem") as ws:
        loaded = ws.receive_json()
        ws.receive_json()  # preview_update
        slides_before = len(loaded["presentation"]["slides"])

        payload = {
            "type": "direct_action",
            "mutation_id": "mut_create_1",
            "action": "create_slide",
            "payload": {"title": "新增"},
            # A lost-ACK retry reuses the ORIGINAL attempt stamp, not a restamped one.
            **_stamp(session),
        }
        ws.send_json(payload)
        first = ws.receive_json()
        assert first["type"] == "presentation_updated"
        assert first["last_mutation_id"] == "mut_create_1"
        assert len(first["presentation"]["slides"]) == slides_before + 1
        version_after = first["version"]
        undo_depth_after = len(session.history.undo_stack)
        ws.receive_json()  # preview_update

        # Replay the exact same mutation_id (ACK loss / reconnect).
        ws.send_json(payload)
        second = ws.receive_json()
        assert second["type"] == "presentation_updated"
        assert second["last_mutation_id"] == "mut_create_1"
        assert len(second["presentation"]["slides"]) == slides_before + 1
        assert second["version"] == version_after
        assert len(session.history.undo_stack) == undo_depth_after


def test_replayed_empty_undo_stays_noop_even_after_new_history():
    """An acknowledged empty-history undo is a terminal no-op under replay."""
    client = TestClient(app)
    session = _seed_demo_session("ws_proto_idem_undo")
    with client.websocket_connect("/ws?session_id=ws_proto_idem_undo") as ws:
        ws.receive_json()
        ws.receive_json()

        replay = {"type": "undo", "mutation_id": "mut_noop_1", **_stamp(session)}
        ws.send_json(replay)
        first = ws.receive_json()
        assert first["type"] == "presentation_updated"
        assert first["last_mutation_id"] == "mut_noop_1"
        ws.receive_json()  # preview_update

        # History gains an entry after the no-op was acknowledged.
        session.history.record(
            action="update_element",
            description="later edit",
            slide_id="slide_01",
            element_id="title_main",
            before={"x": 1.0},
            after={"x": 2.0},
        )
        assert session.history.can_undo() is True

        # Replaying the same mutation_id (and original stamp) must stay the no-op.
        ws.send_json(replay)
        second = ws.receive_json()
        assert second["type"] == "presentation_updated"
        assert second["last_mutation_id"] == "mut_noop_1"
        assert session.history.can_undo() is True
        assert session.history.undo_stack[-1].description == "later edit"
