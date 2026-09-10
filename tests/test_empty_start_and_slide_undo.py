"""Regression tests locking in two invariants:

1. New sessions start blank (no default demo presentation, no preview).
2. Slide-level operations (create/delete/duplicate) are fully undoable/redoable.
"""

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.session.manager import session_manager
from backend.ir.patch import HistoryManager
from backend.ir.models import PresentationIR
from backend.agent.tools import tools


# =====================================================================
# 1. Empty start invariant
# =====================================================================

def test_fresh_session_starts_empty():
    """A brand-new session must start with a blank, zero-slide presentation."""
    session_manager.delete_session("empty_start_unit")
    session = session_manager.get_or_create("empty_start_unit")

    assert session.pres.slides == []
    assert session.active_slide_id is None

    session_manager.delete_session("empty_start_unit")


def test_ws_fresh_session_starts_empty():
    """A fresh WS session receives presentation_loaded with zero slides and no preview."""
    client = TestClient(app)
    sid = "ws_empty_start"
    session_manager.delete_session(sid)

    with client.websocket_connect(f"/ws?session_id={sid}") as ws:
        loaded = ws.receive_json()
        assert loaded["type"] == "presentation_loaded"
        assert loaded["presentation"]["slides"] == []
        assert loaded["active_slide_id"] is None


def test_ws_create_undo_redo_slide():
    """New page creation and its undo/redo flow correctly over the WebSocket."""
    client = TestClient(app)
    sid = "ws_slide_undo_redo"
    session_manager.delete_session(sid)

    with client.websocket_connect(f"/ws?session_id={sid}") as ws:
        loaded = ws.receive_json()
        assert loaded["type"] == "presentation_loaded"

        # Create a slide
        ws.send_json({
            "type": "direct_action",
            "action": "create_slide",
            "payload": {"title": "T1", "background_color": "#FFFFFF"}
        })
        ev = ws.receive_json()
        assert ev["type"] == "presentation_updated"
        assert len(ev["presentation"]["slides"]) == 1
        new_slide_id = ev["presentation"]["slides"][0]["id"]
        assert ev["active_slide_id"] == new_slide_id

        ev_prev = ws.receive_json()
        assert ev_prev["type"] == "preview_update"
        assert ev_prev["slide_id"] == new_slide_id

        # Undo creation
        ws.send_json({"type": "undo"})
        ev_undo = ws.receive_json()
        assert ev_undo["type"] == "presentation_updated"
        assert ev_undo["presentation"]["slides"] == []

        # Redo creation
        ws.send_json({"type": "redo"})
        ev_redo = ws.receive_json()
        assert ev_redo["type"] == "presentation_updated"
        assert len(ev_redo["presentation"]["slides"]) == 1
        assert ev_redo["presentation"]["slides"][0]["id"] == new_slide_id


# =====================================================================
# 2. Slide-level undo/redo invariants
# =====================================================================

def test_create_slide_undo_redo():
    pres = PresentationIR(title="Test Deck")
    history = HistoryManager()

    res = tools.execute("create_slide", {"title": "S1"}, pres, history)
    assert res["success"]
    assert len(pres.slides) == 1
    sid = res["slide_id"]
    assert pres.active_slide_id == sid

    cmd = history.undo(pres)
    assert cmd is not None
    assert pres.slides == []
    assert pres.active_slide_id is None

    cmd = history.redo(pres)
    assert cmd is not None
    assert len(pres.slides) == 1
    assert pres.slides[0].id == sid
    assert pres.active_slide_id == sid


def test_create_slide_out_of_range_position_undo_redo():
    """Out-of-range position appends at end; undo/redo must round-trip identically."""
    pres = PresentationIR(title="Test Deck")
    history = HistoryManager()

    for i in range(3):
        tools.execute("create_slide", {"title": f"S{i}"}, pres, history)

    res = tools.execute("create_slide", {"title": "OUT", "position": 10}, pres, history)
    assert res["success"]
    assert [s.slide_num for s in pres.slides] == [1, 2, 3, 4]
    assert [s.title for s in pres.slides] == ["S0", "S1", "S2", "OUT"]
    sid = res["slide_id"]

    cmd = history.undo(pres)
    assert cmd is not None
    assert [s.title for s in pres.slides] == ["S0", "S1", "S2"]

    cmd = history.redo(pres)
    assert cmd is not None
    assert [s.title for s in pres.slides] == ["S0", "S1", "S2", "OUT"]
    assert [s.slide_num for s in pres.slides] == [1, 2, 3, 4]
    assert pres.get_slide(sid) is not None


def test_delete_slide_undo_redo():
    pres = PresentationIR(title="Test Deck")
    history = HistoryManager()

    tools.execute("create_slide", {"title": "S1"}, pres, history)
    tools.execute("create_slide", {"title": "S2"}, pres, history)
    tools.execute("create_slide", {"title": "S3"}, pres, history)

    s2_id = pres.slides[1].id
    res = tools.execute("delete_slide", {"slide_id_or_num": s2_id}, pres, history)
    assert res["success"]
    assert len(pres.slides) == 2
    assert [s.title for s in pres.slides] == ["S1", "S3"]

    cmd = history.undo(pres)
    assert cmd is not None
    assert len(pres.slides) == 3
    assert pres.slides[1].id == s2_id
    assert pres.slides[1].slide_num == 2
    assert pres.active_slide_id == s2_id

    cmd = history.redo(pres)
    assert cmd is not None
    assert len(pres.slides) == 2
    assert [s.title for s in pres.slides] == ["S1", "S3"]
    assert all(s.id != s2_id for s in pres.slides)


def test_duplicate_slide_undo_redo():
    pres = PresentationIR(title="Test Deck")
    history = HistoryManager()

    tools.execute("create_slide", {"title": "S1"}, pres, history)
    orig_id = pres.slides[0].id

    res = tools.execute("duplicate_slide", {"slide_id": orig_id}, pres, history)
    assert res["success"]
    assert len(pres.slides) == 2
    dup_id = res["new_slide_id"]
    assert pres.active_slide_id == dup_id

    cmd = history.undo(pres)
    assert cmd is not None
    assert len(pres.slides) == 1
    assert pres.slides[0].id == orig_id
    assert pres.active_slide_id == orig_id

    cmd = history.redo(pres)
    assert cmd is not None
    assert len(pres.slides) == 2
    assert pres.active_slide_id == dup_id