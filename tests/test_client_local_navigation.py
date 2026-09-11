"""Phase 3 contract: navigation is client-local, including over REST.

`POST /presentation/active-slide` used to write the shared
`PresentationIR.active_slide_id` and broadcast `active_slide_changed` to every
client in the session. Navigation now belongs to the requesting client only: the
endpoint must return a preview for the requester and never mutate shared state or
broadcast.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app
from backend.session.manager import session_manager
from backend.state.store import create_default_demo_presentation

client = TestClient(app)
BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"


def _seed_session(session_id: str):
    session = session_manager.get_or_create(
        session_id, pres_factory=create_default_demo_presentation
    )
    session.pres = create_default_demo_presentation()
    session.history.clear()
    return session


def test_rest_active_slide_is_requester_local_preview():
    session_id = "rest_nav_client_local"
    session = _seed_session(session_id)
    original_active = session.active_slide_id
    assert session.pres.get_slide("slide_02") is not None

    resp = client.post(
        f"/api/presentation/active-slide?session_id={session_id}",
        json={"slide_id": "slide_02"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "preview_update"
    assert body["slide_id"] == "slide_02"
    assert "<svg" in body["svg"]
    # The shared document's active slide is NOT touched by navigation.
    assert session.active_slide_id == original_active
    assert session.pres.active_slide_id == original_active


def test_rest_active_slide_unknown_slide_is_404():
    session_id = "rest_nav_unknown"
    session = _seed_session(session_id)
    original_active = session.active_slide_id

    resp = client.post(
        f"/api/presentation/active-slide?session_id={session_id}",
        json={"slide_id": "slide_does_not_exist"},
    )

    assert resp.status_code == 404
    assert session.active_slide_id == original_active


def test_rest_active_slide_handler_has_no_shared_write_or_broadcast():
    source = (BACKEND_ROOT / "api" / "routes.py").read_text(encoding="utf-8")
    start = source.index("async def preview_active_slide")
    end = source.index("@router", start)
    handler = source[start:end]

    assert "session.set_active_slide(" not in handler
    assert "store.broadcast" not in handler
    assert '"active_slide_changed"' not in handler
