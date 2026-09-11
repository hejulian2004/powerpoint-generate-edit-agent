"""Canonical document snapshot protocol tests.

Every transport must describe the server document with the same envelope so the
frontend has a single adoption path and never edits with a stale CAS token.
"""

from fastapi.testclient import TestClient

from backend.main import app
from backend.protocol.presentation import build_canonical_snapshot, build_presentation_event
from backend.session.manager import session_manager

client = TestClient(app)

REQUIRED_KEYS = {
    "session_id",
    "presentation",
    "document_epoch",
    "version",
    "active_slide_id",
    "can_undo",
    "can_redo",
    "last_target_id",
    "last_mutation_id",
}


def test_canonical_snapshot_has_stable_shape():
    sid = "sess_canonical_unit"
    session = session_manager.get_or_create(sid)
    snapshot = build_canonical_snapshot(session)
    assert REQUIRED_KEYS <= set(snapshot.keys())
    assert snapshot["session_id"] == sid
    assert snapshot["document_epoch"] == session.document_epoch
    assert snapshot["version"] == session.pres.version
    session_manager.delete_session(sid)


def test_presentation_event_carries_type_and_snapshot():
    sid = "sess_canonical_event"
    session = session_manager.get_or_create(sid)
    event = build_presentation_event(session, "presentation_updated", last_mutation_id="mut_1")
    assert event["type"] == "presentation_updated"
    assert event["last_mutation_id"] == "mut_1"
    assert REQUIRED_KEYS <= set(event.keys())
    session_manager.delete_session(sid)


def test_presentation_snapshot_endpoint_exposes_cas_stamp():
    sid = "sess_canonical_rest"
    session_manager.get_or_create(sid)
    res = client.get(f"/api/presentation/snapshot?session_id={sid}")
    assert res.status_code == 200
    data = res.json()
    assert REQUIRED_KEYS <= set(data.keys())
    assert data["session_id"] == sid
    session_manager.delete_session(sid)


def test_websocket_loaded_envelope_is_canonical():
    sid = "sess_canonical_ws"
    session_manager.get_or_create(sid)
    with client.websocket_connect(f"/ws?session_id={sid}") as ws:
        loaded = ws.receive_json()
        assert loaded["type"] == "presentation_loaded"
        assert REQUIRED_KEYS <= set(loaded.keys())
        assert loaded["document_epoch"]
    session_manager.delete_session(sid)
