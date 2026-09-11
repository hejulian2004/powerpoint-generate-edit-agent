"""Export preflight contract tests (PR6-hardening round 2).

Native Table write-back flattens to a group of styled rectangles. Production export
must declare that before/while exporting instead of silently degrading:

- `evaluate_export_preflight` reports lossy/unsupported features from the IR.
- `export_pptx(..., allow_lossy=False)` refuses lossy write-back.
- `/api/export` exposes warnings via headers and supports a strict 409 mode.
- `/api/upload` reports importer provenance (fidelity vs legacy fallback).
"""

from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app
from backend.fidelity.preflight import evaluate_export_preflight, LossyWritebackError
from backend.ir.converter import export_pptx
from backend.ir.models import (
    PresentationIR, SlideIR, TextElementIR, TextContentIR,
    TableElementIR, TableCellIR,
)
from backend.state.store import store

client = TestClient(app)


def _table_pres() -> PresentationIR:
    pres = PresentationIR(title="Lossy Table Deck")
    slide = SlideIR(id="s_tbl", slide_num=1)
    slide.add_element(TableElementIR(
        id="tbl_1",
        name="Lossy Table",
        x=80.0,
        y=100.0,
        width=600.0,
        height=200.0,
        rows=2,
        cols=2,
        cells=[
            [
                TableCellIR(row=0, col=0, text_content=TextContentIR.from_plain_text("A")),
                TableCellIR(row=0, col=1, text_content=TextContentIR.from_plain_text("B")),
            ],
            [
                TableCellIR(row=1, col=0, text_content=TextContentIR.from_plain_text("1")),
                TableCellIR(row=1, col=1, text_content=TextContentIR.from_plain_text("2")),
            ],
        ],
    ))
    pres.slides.append(slide)
    pres.active_slide_id = slide.id
    return pres


def _clean_pres() -> PresentationIR:
    pres = PresentationIR(title="Clean Deck")
    slide = SlideIR(id="s_clean", slide_num=1)
    slide.add_element(TextElementIR(
        id="t1", x=80.0, y=80.0, width=400.0, height=60.0,
        text_content=TextContentIR.from_plain_text("Hello"),
    ))
    pres.slides.append(slide)
    pres.active_slide_id = slide.id
    return pres


# =====================================================================
# Preflight + canonical exporter
# =====================================================================

def test_preflight_reports_table_lossy():
    pf = evaluate_export_preflight(_table_pres())
    assert pf.has_lossy is True
    assert pf.lossy_features == [{"feature": "table", "reason": "flattened_to_group"}]
    assert any("table" in w and "lossy" in w for w in pf.warnings)
    assert pf.to_dict()["has_lossy"] is True


def test_preflight_clean_for_text_only_deck():
    pf = evaluate_export_preflight(_clean_pres())
    assert pf.clean is True
    assert pf.has_lossy is False
    assert pf.warnings == []


def test_export_refuses_lossy_writeback_when_disallowed(tmp_path: Path):
    out = tmp_path / "table.pptx"
    try:
        export_pptx(_table_pres(), out, allow_lossy=False)
        raise AssertionError("lossy export should have been refused")
    except LossyWritebackError as exc:
        assert exc.preflight.has_lossy is True
    assert not out.exists()

    # Default (allow_lossy=True) still exports, preserving backwards compatibility
    export_pptx(_table_pres(), out)
    assert out.exists()


def test_store_export_preflight_and_strict_mode():
    pres = _table_pres()
    pf = store.export_preflight(pres=pres)
    assert pf["has_lossy"] is True
    try:
        store.export_pptx_bytes(pres=pres, allow_lossy=False)
        raise AssertionError("lossy export should have been refused")
    except LossyWritebackError:
        pass
    assert store.export_pptx_bytes(pres=pres)[:4] == b"PK\x03\x04"


# =====================================================================
# API surface: preflight endpoint, strict 409, warning headers
# =====================================================================

def _api_session_with(pres: PresentationIR):
    return store.session_manager.create_session(pres=pres, session_id="sess_export_preflight")


def test_api_export_preflight_endpoint():
    session = _api_session_with(_table_pres())
    try:
        resp = client.get(f"/api/export/preflight?session_id={session.session_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_lossy"] is True
        assert data["lossy_features"][0]["feature"] == "table"
    finally:
        store.session_manager.delete_session(session.session_id)


def test_api_export_strict_mode_returns_409():
    session = _api_session_with(_table_pres())
    try:
        resp = client.get(
            f"/api/export?session_id={session.session_id}&allow_lossy=false"
        )
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["error"] == "lossy_export_requires_confirmation"
        assert detail["has_lossy"] is True
    finally:
        store.session_manager.delete_session(session.session_id)


def test_api_export_default_attaches_warning_headers():
    session = _api_session_with(_table_pres())
    try:
        resp = client.get(f"/api/export?session_id={session.session_id}")
        assert resp.status_code == 200
        assert resp.content[:4] == b"PK\x03\x04"
        assert resp.headers.get("x-export-lossy") == "true"
        assert "table" in resp.headers.get("x-fidelity-warnings", "")
    finally:
        store.session_manager.delete_session(session.session_id)


def test_api_upload_reports_importer_provenance():
    session = _api_session_with(_clean_pres())
    try:
        with open("demo_input.pptx", "rb") as f:
            files = {"file": ("demo_input.pptx", f, "application/vnd.openxmlformats-officedocument.presentationml.presentation")}
            resp = client.post(
                f"/api/upload?session_id={session.session_id}"
                f"&expected_epoch={session.document_epoch}"
                f"&expected_revision={session.pres.version}",
                files=files,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["importer"] == "fidelity"
        assert data["degraded"] is False
        assert data["fallback_reason"] is None
    finally:
        store.session_manager.delete_session(session.session_id)
