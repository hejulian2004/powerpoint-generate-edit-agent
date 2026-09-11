"""Generation must not overwrite edits made while it was running.

The final persist is a CAS commit against the document identity captured when
generation started. If the user (or another writer) advanced the revision, the
generated deck is discarded instead of replacing the newer document.
"""

import asyncio

from backend.agent.graphs.generation import persist_session_node
from backend.ir.models import PresentationIR, SlideIR
from backend.session.manager import session_manager

def _generated(title="Generated"):
    pres = PresentationIR(title=title, version=1)
    pres.slides.append(SlideIR(id="gen_slide", slide_num=1))
    pres.active_slide_id = "gen_slide"
    return pres


def test_persist_commits_when_document_unchanged():
    async def _run():
        sid = "sess_gen_commit_ok"
        session = session_manager.get_or_create(sid)
        base_epoch = session.document_epoch
        base_revision = session.pres.version

        generated = _generated()
        new_state = await persist_session_node(
            {
                "session_id": sid,
                "presentation_ir": generated,
                "base_document_epoch": base_epoch,
                "base_revision": base_revision,
            },
            {"configurable": {}},
        )

        assert new_state["status"] == "completed"
        assert session.pres is generated
        session_manager.delete_session(sid)

    asyncio.run(_run())


def test_persist_rejects_when_user_edited_during_generation():
    async def _run():
        sid = "sess_gen_stale"
        session = session_manager.get_or_create(sid)
        base_epoch = session.document_epoch
        base_revision = session.pres.version
        original_pres = session.pres

        # User edits the deck while generation is running.
        session.pres.version = base_revision + 1

        generated = _generated()
        new_state = await persist_session_node(
            {
                "session_id": sid,
                "presentation_ir": generated,
                "base_document_epoch": base_epoch,
                "base_revision": base_revision,
            },
            {"configurable": {}},
        )

        assert new_state["status"] == "stale_generation"
        assert session.pres is original_pres
        assert session.pres.version == base_revision + 1
        session_manager.delete_session(sid)

    asyncio.run(_run())


def test_generate_route_returns_409_when_document_edited_during_generation(monkeypatch):
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.agent.graphs.generation import generation_graph

    client = TestClient(app)
    raw_text = """
    # Route Concurrency Deck

    ## Slide 1: 竞态
    - 内容要点
    """
    sid = "sess_gen_route_stale"
    norm = client.post("/api/pptspec/normalize", json={"content": raw_text, "session_id": sid})
    assert norm.status_code == 200
    norm_id = norm.json()["normalization_id"]

    session = session_manager.get_or_create(sid)
    orig_ainvoke = generation_graph.ainvoke

    async def mock_ainvoke(*args, **kwargs):
        # Simulate a user edit landing while generation is running.
        session.pres.version += 1
        return await orig_ainvoke(*args, **kwargs)

    monkeypatch.setattr(generation_graph, "ainvoke", mock_ainvoke)

    res = client.post(
        "/api/pptspec/generate",
        json={"normalization_id": norm_id, "session_id": sid},
    )
    assert res.status_code == 409
    assert "STALE_GENERATION" in res.json()["detail"]

    session_manager.delete_session(sid)
