"""REST integration tests for POST /api/paper/generate (S4)."""

from __future__ import annotations

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


def test_paper_generate_requires_session_id():
    response = client.post("/api/paper/generate", json={"paper_ir": _PAPER_IR})
    assert response.status_code == 400
    assert "session_id is required" in response.json()["detail"]


def test_paper_generate_requires_paper_ir():
    session_manager.get_or_create("test_paper_route_no_ir")
    response = client.post(
        "/api/paper/generate", json={"session_id": "test_paper_route_no_ir"}
    )
    assert response.status_code == 400
    assert "paper_ir is required" in response.json()["detail"]
    session_manager.delete_session("test_paper_route_no_ir")


def test_paper_generate_rejects_invalid_paper_ir():
    session_manager.get_or_create("test_paper_route_bad_ir")
    response = client.post(
        "/api/paper/generate",
        json={"session_id": "test_paper_route_bad_ir", "paper_ir": {"metadata": 5}},
    )
    assert response.status_code == 422
    assert "INVALID_PAPER_IR" in response.json()["detail"]
    session_manager.delete_session("test_paper_route_bad_ir")


def test_paper_generate_persists_deck():
    session_id = "test_paper_route_gen"
    session_manager.get_or_create(session_id)

    response = client.post(
        "/api/paper/generate",
        json={"session_id": session_id, "paper_ir": _PAPER_IR, "duration_minutes": 10},
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
