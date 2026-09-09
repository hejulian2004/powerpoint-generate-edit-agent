"""End-to-end integration tests for backend API, PPTX import/export, and store."""

import io
from fastapi.testclient import TestClient
from backend.main import app
from backend.state.store import store, create_default_demo_presentation
from backend.session.manager import session_manager
from pptx_agent_converter.extractor.pptx_parser import PPTXParser
import tempfile
import os

client = TestClient(app)


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

    imported_pres = store.import_pptx_bytes(pptx_bytes, "demo_input.pptx")
    assert len(imported_pres.slides) >= 1
    assert imported_pres.width == 1280
    assert imported_pres.height == 720

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
    with open("demo_input.pptx", "rb") as f:
        files = {"file": ("demo_input.pptx", f, "application/vnd.openxmlformats-officedocument.presentationml.presentation")}
        upload_resp = client.post("/api/upload", files=files)
        assert upload_resp.status_code == 200
        data = upload_resp.json()
        assert data["success"] is True

    export_resp = client.get("/api/export")
    assert export_resp.status_code == 200
    assert len(export_resp.content) > 0
    assert export_resp.content[:4] == b"PK\x03\x04"


def test_frontend_spa_serving():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "html" in resp.headers.get("content-type", "").lower()
    assert "<!doctype html>" in resp.text.lower()

