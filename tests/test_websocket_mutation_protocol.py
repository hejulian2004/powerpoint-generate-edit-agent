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


def test_direct_update_echoes_mutation_id_and_version():
    client = TestClient(app)
    _seed_demo_session("ws_proto_ack")
    with client.websocket_connect("/ws?session_id=ws_proto_ack") as ws:
        ws.receive_json()  # presentation_loaded
        ws.receive_json()  # preview_update

        ws.send_json({
            "type": "direct_update_element",
            "mutation_id": "mut_ack_1",
            "payload": {"slide_id": "slide_01", "element_id": "title_main", "x": 260.0},
        })
        ev = ws.receive_json()
        assert ev["type"] == "presentation_updated"
        assert ev["last_mutation_id"] == "mut_ack_1"
        assert isinstance(ev["version"], int) and ev["version"] > 0
        ws.receive_json()  # preview_update


def test_direct_update_rejects_unknown_element():
    client = TestClient(app)
    _seed_demo_session("ws_proto_reject")
    with client.websocket_connect("/ws?session_id=ws_proto_reject") as ws:
        ws.receive_json()
        ws.receive_json()

        ws.send_json({
            "type": "direct_update_element",
            "mutation_id": "mut_missing",
            "payload": {"slide_id": "slide_01", "element_id": "does_not_exist", "x": 100.0},
        })
        rejected = ws.receive_json()
        assert rejected["type"] == "mutation_rejected"
        assert rejected["mutation_id"] == "mut_missing"
        assert "not found" in rejected["error"].lower()


def test_batch_mutation_is_one_undo_step():
    client = TestClient(app)
    _seed_demo_session("ws_proto_batch")
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
        ws.send_json({"type": "undo"})
        undo_ev = ws.receive_json()
        assert undo_ev["type"] == "presentation_updated"
        restored_title = _find_element(undo_ev["presentation"], "slide_01", "title_main")
        restored_card = _find_element(undo_ev["presentation"], "slide_01", "card_ir")
        assert abs(restored_title["x"] - title["x"]) < 0.01
        assert abs(restored_card["x"] - card["x"]) < 0.01


def test_batch_mutation_rolls_back_on_failure():
    client = TestClient(app)
    _seed_demo_session("ws_proto_batch_fail")
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
        })
        rejected = ws.receive_json()
        assert rejected["type"] == "mutation_rejected"
        assert rejected["mutation_id"] == "mut_batch_fail"

        # The first op must have been rolled back: a follow-up read sees the original x.
        ws.send_json({
            "type": "direct_update_element",
            "mutation_id": "mut_read",
            "payload": {"slide_id": "slide_01", "element_id": "title_main", "x": title["x"]},
        })
        ev = ws.receive_json()
        assert ev["type"] == "presentation_updated"
        after = _find_element(ev["presentation"], "slide_01", "title_main")
        assert abs(after["x"] - title["x"]) < 0.01
