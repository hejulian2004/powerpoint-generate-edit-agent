"""End-to-end integration tests for backend API, PPTX import/export, and store."""

import io
from pathlib import Path
from fastapi.testclient import TestClient
import pytest
from backend.main import app
from backend.state.store import store, create_default_demo_presentation
from backend.session.manager import session_manager
from pptx_agent_converter.extractor.pptx_parser import PPTXParser
import tempfile
import os

client = TestClient(app)

_FRONTEND_DIST_INDEX = Path(__file__).resolve().parents[1] / "frontend" / "dist" / "index.html"


def _seed_default_demo():
    """Seeds a fresh demo presentation into the default session for deterministic API tests."""
    session = session_manager.get_or_create("default")
    session.pres = create_default_demo_presentation()
    session.history.clear()
    return session


def test_api_get_presentation():
    _seed_default_demo()
    resp = client.get("/api/presentation")
    assert resp.status_code == 200
    data = resp.json()
    assert "slides" in data
    assert len(data["slides"]) >= 1


def test_api_slide_svg():
    _seed_default_demo()
    pres = store.get_presentation()
    first_slide_id = pres.slides[0].id
    resp = client.get(f"/api/slide/{first_slide_id}/svg")
    assert resp.status_code == 200
    assert "image/svg+xml" in resp.headers["content-type"]
    assert "<svg" in resp.text


def test_api_models_list(monkeypatch):
    """POST /api/models proxies the provider /models endpoint and returns model ids."""
    import httpx

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [{"id": "gemini-3.8-flash-high"}, {"id": "gemini-3.1-flash-image"}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.headers = {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, headers=None):
            self.called_url = url
            self.headers = headers or {}
            return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    resp = client.post("/api/models", json={
        "base_url": "https://txy.hejulian.org:8317/v1",
        "api_key": "sk-test"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["models"] == ["gemini-3.8-flash-high", "gemini-3.1-flash-image"]
    assert data["base_url"] == "https://txy.hejulian.org:8317/v1"


def test_api_models_empty_base_url_falls_back_to_settings(monkeypatch):
    """Empty base_url falls back to the configured default, not a 400."""
    import httpx
    from backend.config import settings

    monkeypatch.setattr(settings, "openai_base_url", "https://fallback.example/v1")

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [{"id": "fallback-model"}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, headers=None):
            self.called_url = url
            return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    resp = client.post("/api/models", json={"base_url": "", "api_key": ""})
    assert resp.status_code == 200
    data = resp.json()
    assert data["models"] == ["fallback-model"]
    assert data["base_url"] == "https://fallback.example/v1"


def test_api_models_provider_error(monkeypatch):
    """Provider HTTP errors surface as 502 with a readable message."""
    import httpx

    class FakeResp:
        def raise_for_status(self):
            class _Resp:
                status_code = 401
                text = '{"error": "unauthorized"}'
            raise httpx.HTTPStatusError("401 Unauthorized", request=None, response=_Resp())

        @property
        def status_code(self):
            return 401

        @property
        def text(self):
            return '{"error": "unauthorized"}'

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, headers=None):
            return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    resp = client.post("/api/models", json={"base_url": "https://invalid.example/v1"})
    assert resp.status_code == 502
    assert "unauthorized" in resp.json()["detail"]


def test_api_settings_update():
    get_resp = client.get("/api/settings")
    assert get_resp.status_code == 200
    
    post_resp = client.post("/api/settings", json={"default_model": "gpt-4o-custom"})
    assert post_resp.status_code == 200
    assert post_resp.json()["success"] is True

    verify_resp = client.get("/api/settings")
    assert verify_resp.json()["default_model"] == "gpt-4o-custom"


def test_pptx_import_export_roundtrip():
    # 1. Import existing demo_input.pptx
    with open("demo_input.pptx", "rb") as f:
        pptx_bytes = f.read()

    imported_pres = store.parse_pptx_bytes(pptx_bytes, "demo_input.pptx")
    assert len(imported_pres.slides) >= 1
    assert imported_pres.width == 1280
    assert imported_pres.height == 720

    # Commit through the CAS-guarded replacement API (production path).
    import asyncio

    session = store.active_session
    result = asyncio.run(session.commit_replacement(
        imported_pres,
        expected_epoch=session.document_epoch,
        expected_revision=session.pres.version,
        checkpoint_description="demo_input.pptx",
    ))
    assert result.committed is True

    # 2. Export back to PPTX
    exported_bytes = store.export_pptx_bytes()
    assert len(exported_bytes) > 0
    # ZIP magic bytes: PK\x03\x04
    assert exported_bytes[:4] == b"PK\x03\x04"

    # 3. Verify that the exported PPTX is valid OOXML by reparsing it
    with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as tmp:
        tmp.write(exported_bytes)
        tmp_path = tmp.name

    try:
        re_parser = PPTXParser(tmp_path)
        re_pres = re_parser.parse()
        assert len(re_pres.slides) == len(imported_pres.slides)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def test_api_upload_and_export():
    session = store.active_session
    with open("demo_input.pptx", "rb") as f:
        files = {"file": ("demo_input.pptx", f, "application/vnd.openxmlformats-officedocument.presentationml.presentation")}
        upload_resp = client.post(
            f"/api/upload?expected_epoch={session.document_epoch}"
            f"&expected_revision={session.pres.version}",
            files=files,
        )
        assert upload_resp.status_code == 200
        data = upload_resp.json()
        assert data["success"] is True

    export_resp = client.get("/api/export")
    assert export_resp.status_code == 200
    assert len(export_resp.content) > 0
    assert export_resp.content[:4] == b"PK\x03\x04"
    # Export is pinned to one epoch/revision so a concurrent edit cannot produce
    # a mixed-revision file.
    assert export_resp.headers.get("x-document-epoch")
    assert export_resp.headers.get("x-document-revision")


@pytest.mark.skipif(
    not _FRONTEND_DIST_INDEX.exists(),
    reason="frontend not built (run `npm run build` in frontend/ to enable SPA serving test)"
)
def test_frontend_spa_serving():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "html" in resp.headers.get("content-type", "").lower()
    assert "<!doctype html>" in resp.text.lower()


def test_api_confirm_pending_lifecycle():
    session = store.active_session
    pres = store.get_presentation()
    slide = pres.slides[0]
    elem = slide.elements[0]
    original_y = elem.y

    session.clear_pending_confirmations()
    session.register_pending_confirmation(
        call_id="api_call_1",
        tool="update_element",
        arguments={"element_id": elem.id, "y": original_y + 40.0},
        confidence=0.5,
        presentation_version=pres.version,
    )

    pending_resp = client.get("/api/confirm/pending")
    assert pending_resp.status_code == 200
    assert any(p["call_id"] == "api_call_1" for p in pending_resp.json()["pending"])

    resp = client.post("/api/confirm", json={"call_id": "api_call_1"})
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert slide.get_element(elem.id).y == original_y + 40.0
    assert session.get_pending_confirmation("api_call_1") is None

    # Cleanup: restore the demo element through the session undo stack
    session.undo()


def test_api_confirm_unknown_call_id():
    resp = client.post("/api/confirm", json={"call_id": "does_not_exist"})
    assert resp.status_code == 200
    assert resp.json()["success"] is False
    assert resp.json()["error"] == "unknown_confirmation"


def test_api_confirm_requires_call_id():
    resp = client.post("/api/confirm", json={})
    assert resp.status_code == 400


def test_api_chat_accepts_confirmed_tool_ids():
    session = store.active_session
    resp = client.post(
        "/api/chat",
        json={
            "message": "你好",
            "confirmed_tool_ids": ["call_nonexistent"],
            "document_epoch": session.document_epoch,
            "base_revision": session.pres.version,
        },
    )
    assert resp.status_code == 200
    assert "reply" in resp.json()

