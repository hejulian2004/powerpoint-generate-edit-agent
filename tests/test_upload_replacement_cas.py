"""Phase 1 contract: upload replacement is a fail-closed CAS transaction.

An import replaces the whole document, so the caller MUST supply the document
epoch + revision it observed. A request without both stamps is rejected before
the file is read; the route must never fall back to the server's current stamp,
which would reopen a "replace whatever is currently present" escape hatch.
"""

from fastapi.testclient import TestClient
import starlette.datastructures as starlette_datastructures

from backend.main import app
from backend.session.manager import session_manager
from backend.state.store import create_default_demo_presentation

client = TestClient(app)

DEMO_PPTX = "demo_input.pptx"
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def _seed_session(session_id: str):
    session = session_manager.get_or_create(
        session_id, pres_factory=create_default_demo_presentation
    )
    session.pres = create_default_demo_presentation()
    session.history.clear()
    return session


def _upload_files():
    handle = open(DEMO_PPTX, "rb")
    return {"file": (DEMO_PPTX, handle, PPTX_MIME)}


def _stamps(session) -> str:
    return (
        f"expected_epoch={session.document_epoch}"
        f"&expected_revision={session.pres.version}"
    )


def test_upload_without_replacement_stamp_is_rejected_before_read(monkeypatch):
    session_id = "upload_cas_missing_stamp"
    session = _seed_session(session_id)
    title_before = session.pres.title
    revision_before = session.pres.version

    read_called = {"value": False}
    real_read = starlette_datastructures.UploadFile.read

    async def tracking_read(self, size: int = -1):
        read_called["value"] = True
        return await real_read(self, size)

    monkeypatch.setattr(starlette_datastructures.UploadFile, "read", tracking_read)

    files = _upload_files()
    try:
        resp = client.post(f"/api/upload?session_id={session_id}", files=files)
    finally:
        files["file"][1].close()

    assert resp.status_code == 409
    assert resp.json()["detail"] == "MISSING_REPLACEMENT_STAMP"
    # Fail closed BEFORE consuming the body and without touching the document.
    assert read_called["value"] is False
    assert session.pres.version == revision_before
    assert session.pres.title == title_before


def test_upload_stamp_is_not_restamped_after_a_slow_read(monkeypatch):
    session_id = "upload_cas_race"
    session = _seed_session(session_id)
    base_revision = session.pres.version

    real_read = starlette_datastructures.UploadFile.read
    bumped = {"done": False}

    async def racing_read(self, size: int = -1):
        data = await real_read(self, size)
        if not bumped["done"]:
            # Simulate a concurrent committed mutation landing while the upload
            # body is still streaming. It must make the caller's stamp stale.
            bumped["done"] = True
            session.pres.version += 1
        return data

    monkeypatch.setattr(starlette_datastructures.UploadFile, "read", racing_read)

    files = _upload_files()
    try:
        resp = client.post(
            f"/api/upload?session_id={session_id}&{_stamps(session)}", files=files
        )
    finally:
        files["file"][1].close()

    assert resp.status_code == 409
    # The racing commit survives; the stale import did not overwrite it.
    assert session.pres.version == base_revision + 1


def test_upload_rejects_stale_revision():
    session_id = "upload_cas_client_stale"
    session = _seed_session(session_id)
    stale_revision = session.pres.version - 1

    files = _upload_files()
    try:
        resp = client.post(
            f"/api/upload?session_id={session_id}"
            f"&expected_epoch={session.document_epoch}"
            f"&expected_revision={stale_revision}",
            files=files,
        )
    finally:
        files["file"][1].close()

    assert resp.status_code == 409


def test_upload_accepts_matching_stamp():
    session_id = "upload_cas_client_ok"
    session = _seed_session(session_id)

    files = _upload_files()
    try:
        resp = client.post(
            f"/api/upload?session_id={session_id}&{_stamps(session)}", files=files
        )
    finally:
        files["file"][1].close()

    assert resp.status_code == 200
    assert resp.json()["success"] is True
