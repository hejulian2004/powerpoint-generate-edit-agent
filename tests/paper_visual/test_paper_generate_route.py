"""REST integration tests for POST /api/paper/generate (S4).

The endpoint now consumes a trusted ``cache_key`` capability handle (never a
client filesystem path); the server reloads PaperIR + PaperVisualIR from the
content-addressed cache and re-canonicalizes every asset path.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.session.manager import session_manager

client = TestClient(app)

_PAPER_IR = {
    "source_filename": "route_paper.pdf",
    "metadata": {"title": "Route Paper", "authors": ["A. Author"], "page_count": 2},
    "abstract": "A short abstract for the route test.",
    "sections": [
        {
            "number": "1",
            "title": "Introduction",
            "level": 1,
            "page": 1,
            "paragraphs": ["Prior work motivates this study."],
        },
        {
            "number": "2",
            "title": "Method",
            "level": 1,
            "page": 2,
            "paragraphs": ["Our method has three stages."],
        },
    ],
}


def _seed_cache(root: Path, key: str, *, image_path: str | None = None) -> Path:
    """Create a well-formed paper cache bundle and return its directory."""
    cache_dir = root / key
    pages_dir = cache_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    page_image = pages_dir / "page_001.webp"
    page_image.write_bytes(b"RIFF\x00\x00\x00\x00WEBP")
    resolved_image = image_path or str(page_image)

    visual_ir = {
        "source_filename": "route_paper.pdf",
        "source_sha256": "0" * 64,
        "vision_model": None,
        "pages": [
            {
                "page_number": 1,
                "page_asset": {
                    "page_number": 1,
                    "image_path": resolved_image,
                    "width": 1280,
                    "height": 720,
                    "dpi": 144,
                },
                "visual_summary": "single figure page",
                "visual_importance": 0.8,
                "regions": [],
            }
        ],
    }
    (cache_dir / "paper_ir.json").write_text(json.dumps(_PAPER_IR), encoding="utf-8")
    (cache_dir / "paper_visual_ir.json").write_text(
        json.dumps(visual_ir), encoding="utf-8"
    )
    from backend.paper_visual.cache import save_analysis_identity

    save_analysis_identity(cache_dir, None)
    return cache_dir


@pytest.fixture
def cache_root(tmp_path, monkeypatch):
    root = tmp_path / "paper_cache"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("backend.paper_visual.paths.DEFAULT_CACHE_ROOT", root)
    return root


_CACHE_KEY = "a" * 64


def test_paper_generate_requires_session_id(cache_root):
    _seed_cache(cache_root, _CACHE_KEY)
    response = client.post("/api/paper/generate", json={"cache_key": _CACHE_KEY})
    assert response.status_code == 400
    assert "session_id is required" in response.json()["detail"]


def test_paper_generate_requires_cache_key():
    session_manager.get_or_create("test_paper_route_no_key")
    response = client.post(
        "/api/paper/generate", json={"session_id": "test_paper_route_no_key"}
    )
    assert response.status_code == 400
    assert "cache_key is required" in response.json()["detail"]
    session_manager.delete_session("test_paper_route_no_key")


def test_paper_generate_rejects_invalid_cache_key():
    session_manager.get_or_create("test_paper_route_bad_key")
    response = client.post(
        "/api/paper/generate",
        json={"session_id": "test_paper_route_bad_key", "cache_key": "../../etc/passwd"},
    )
    assert response.status_code == 422
    assert "INVALID_CACHE_KEY" in response.json()["detail"]
    session_manager.delete_session("test_paper_route_bad_key")


def test_paper_generate_missing_cached_ir(cache_root):
    session_manager.get_or_create("test_paper_route_missing_ir")
    response = client.post(
        "/api/paper/generate",
        json={"session_id": "test_paper_route_missing_ir", "cache_key": _CACHE_KEY},
    )
    assert response.status_code == 422
    assert "PAPER_IR_NOT_CACHED" in response.json()["detail"]
    session_manager.delete_session("test_paper_route_missing_ir")


def test_paper_generate_rejects_path_escape(cache_root, tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("top secret", encoding="utf-8")
    _seed_cache(cache_root, _CACHE_KEY, image_path=str(outside))

    session_manager.get_or_create("test_paper_route_escape")
    response = client.post(
        "/api/paper/generate",
        json={"session_id": "test_paper_route_escape", "cache_key": _CACHE_KEY},
    )
    assert response.status_code == 422
    assert "INVALID_VISUAL_ASSET_PATH" in response.json()["detail"]
    session_manager.delete_session("test_paper_route_escape")


def test_paper_generate_persists_deck(cache_root):
    session_id = "test_paper_route_gen"
    _seed_cache(cache_root, _CACHE_KEY)
    session_manager.get_or_create(session_id)

    response = client.post(
        "/api/paper/generate",
        json={"session_id": session_id, "cache_key": _CACHE_KEY, "duration_minutes": 10},
    )
    assert response.status_code == 200, response.text
    data = response.json()

    assert data["success"] is True
    assert data["source_filename"] == "route_paper.pdf"
    assert data["slide_count"] > 0
    assert data["generation"]["source_type"] == "paper"
    assert data["generation"]["duration_minutes"] == 10

    session = session_manager.get_session(session_id)
    assert session is not None
    assert len(session.pres.slides) == data["slide_count"]
    assert session.pres.metadata["generation"]["source_type"] == "paper"

    session_manager.delete_session(session_id)
