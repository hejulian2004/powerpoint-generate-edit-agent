"""Phase 5: single writable frontend per session (newest tab wins)."""

from __future__ import annotations

import asyncio

import pytest

from backend.session.services.connection import (
    ConnectionService,
    ConnectionTakenOver,
    SESSION_TAKEN_OVER,
)


def test_connection_service_binds_newest_and_rejects_old():
    service = ConnectionService()
    old, gen_old = service.attach("ws_old")
    assert old is None
    assert gen_old == 1

    previous, gen_new = service.attach("ws_new")
    assert previous == "ws_old"
    assert gen_new == 2

    assert service.is_current("ws_new") is True
    assert service.is_current("ws_old") is False
    with pytest.raises(ConnectionTakenOver):
        service.assert_current("ws_old", gen_old)
    # Server-bound generation: a superseded generation never becomes valid again.
    with pytest.raises(ConnectionTakenOver):
        service.assert_current("ws_new", gen_old)
    service.assert_current("ws_new", gen_new)


def test_detach_only_clears_the_current_owner():
    service = ConnectionService()
    service.attach("ws_a")
    service.detach("ws_stale")
    assert service.websocket == "ws_a"
    service.detach("ws_a")
    assert service.websocket is None


def test_second_tab_takes_over_and_old_socket_is_closed():
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.state.store import store

    client = TestClient(app)
    sid = "ws_takeover_test"
    # The websocket never implicitly creates a session, so seed it first.
    store.session_manager.create_session(session_id=sid)
    try:
        with client.websocket_connect(f"/ws?session_id={sid}") as first:
            first_msg = first.receive_json()
            assert first_msg["type"] == "presentation_loaded"
            assert first_msg.get("connection_generation") == 1

            with client.websocket_connect(f"/ws?session_id={sid}") as second:
                second_msg = second.receive_json()
                assert second_msg["type"] == "presentation_loaded"
                assert second_msg.get("connection_generation") == 2

                takeover = first.receive_json()
                assert takeover["type"] == SESSION_TAKEN_OVER
                assert takeover["session_id"] == sid

                session = store.session_manager.get_session(sid)
                assert session.connection.connection_generation == 2
                assert session.connection.websocket is not None
    finally:
        store.session_manager.delete_session(sid)


def test_superseded_mutation_is_rejected_at_commit_boundary():
    """An old tab's mutation, queued on the lock, must not commit after takeover.

    The connection generation is re-checked INSIDE the mutation_lock critical
    section, so a mutation accepted before a newer tab attached is still rejected.
    """
    from backend.agent.mutation_gateway import MutationGateway
    from backend.ir.models import (
        PresentationIR,
        SlideIR,
        TextContentIR,
        TextElementIR,
    )
    from backend.session.factory import SessionFactory
    from backend.session.services.connection import (
        STALE_CONNECTION,
        TransportOwnership,
    )

    async def _run():
        pres = PresentationIR(title="Ownership Deck")
        slide = SlideIR(id="slide_1", slide_num=1)
        slide.add_element(TextElementIR(
            id="title_node", x=80.0, y=50.0, width=700.0, height=50.0,
            text_content=TextContentIR.from_plain_text("Hello"),
        ))
        pres.slides.append(slide)
        pres.active_slide_id = slide.id
        session = SessionFactory.create(pres, session_id="ownership_race")

        old_ws = object()
        new_ws = object()
        _, gen_old = session.connection.attach(old_ws)
        transport = TransportOwnership(old_ws, gen_old)

        entered = asyncio.Event()
        release = asyncio.Event()

        async def holder():
            async with session.document.mutation_lock:
                entered.set()
                await release.wait()

        holder_task = asyncio.create_task(holder())
        await entered.wait()

        call = {
            "name": "update_element",
            "arguments": {"slide_id": "slide_1", "element_id": "title_node", "x": 300.0},
            "id": "call_old",
        }
        old_task = asyncio.create_task(MutationGateway.execute_tool_calls(
            [call], session.pres, session.history, session=session,
            source="user_direct", bypass_confirmation=True,
            document_epoch=session.document_epoch,
            expected_revision=session.pres.version,
            require_stamps=True,
            transport=transport,
        ))
        await asyncio.sleep(0)

        # A newer tab takes over while the old mutation is queued on the lock.
        session.connection.attach(new_ws)

        release.set()
        await holder_task
        batch = await old_task

        assert batch.error == STALE_CONNECTION
        assert session.pres.slides[0].elements[0].x == 80.0
        assert session.history_service.can_undo() is False

    asyncio.run(_run())
