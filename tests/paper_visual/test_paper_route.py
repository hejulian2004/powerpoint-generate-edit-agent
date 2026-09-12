"""REST integration test for POST /api/paper/analyze (vision-gated)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_paper_analyze_endpoint(multicase_pdf: Path):
    content = multicase_pdf.read_bytes()
    response = client.post(
        "/api/paper/analyze",
        files={"file": ("multicase_10p.pdf", content, "application/pdf")},
    )
    assert response.status_code == 200, response.text
    data = response.json()

    assert data["success"] is True
    assert data["page_count"] == 10
    assert len(data["pages"]) == 10
    assert data["paper_ir"]["metadata"]["page_count"] == 10
    assert data["paper_visual_ir"]["pages"]
    # test mode has no live vision key -> graceful degradation, never a failure
    assert data["vision_model"] is None


def test_paper_analyze_rejects_non_pdf():
    response = client.post(
        "/api/paper/analyze",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400


def test_paper_analyze_rejects_empty_pdf():
    response = client.post(
        "/api/paper/analyze",
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert response.status_code == 400
