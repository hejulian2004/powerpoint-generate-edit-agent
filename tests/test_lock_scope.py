"""Phase 2.4: mutation lock scope.

LLM turns must NOT hold `session.mutation_lock`; only actual mutations are
serialized through the MutationGateway. This keeps drag/drop, undo, and direct
edits responsive while a slow model is planning.
"""

import asyncio

from fastapi.testclient import TestClient

from backend.agent.mutation_gateway import MutationGateway
from backend.ir.models import PresentationIR, SlideIR, TextElementIR, TextContentIR
from backend.ir.patch import HistoryManager
from backend.main import app
from backend.session.manager import session_manager
from backend.session.session import PPTSession
from backend.state.store import create_default_demo_presentation, store


def _pres_with_title():
    pres = PresentationIR(title="Lock Scope")
    slide = SlideIR(id="slide_1", slide_num=1)
    slide.add_element(TextElementIR(
        id="title_node", x=80.0, y=50.0, width=700.0, height=50.0,
        text_content=TextContentIR.from_plain_text("Quarterly Review")
    ))
    pres.slides.append(slide)
    pres.active_slide_id = slide.id
    return pres


def _seed_session(session_id: str) -> PPTSession:
    session = session_manager.get_or_create(
        session_id, pres_factory=create_default_demo_presentation
    )
    session.replace_presentation(create_default_demo_presentation(), checkpoint_description="seed")
    return session


def _mutation_call():
    return [{
        "name": "update_element",
        "arguments": {"element_id": "title_node", "slide_id": "slide_1", "y": 300.0},
        "id": "call_lock",
    }]


def test_gateway_waits_for_held_session_lock():
    async def _run():
        pres = _pres_with_title()
        history = HistoryManager()
        session = PPTSession(session_id="sess_lock_wait", pres=pres)
        order = []

        async def lock_holder():
            async with session.mutation_lock:
                order.append("holder_start")
                await asyncio.sleep(0.05)
                order.append("holder_end")

        async def gateway_call():
            await asyncio.sleep(0.01)
            await MutationGateway.execute_tool_calls(
                _mutation_call(),
                pres,
                history,
                session=session,
                bypass_confirmation=True,
            )
            order.append("gateway_done")

        await asyncio.gather(lock_holder(), gateway_call())
        assert order == ["holder_start", "holder_end", "gateway_done"]
        assert pres.slides[0].get_element("title_node").y == 300.0

    asyncio.run(_run())


def test_rest_chat_does_not_hold_mutation_lock(monkeypatch):
    client = TestClient(app)
    session_id = "lock_scope_rest"
    session = _seed_session(session_id)
    captured = {}
    original = store.agent_runtime.run_turn

    async def spy(*args, **kwargs):
        captured["locked"] = session.mutation_lock.locked()
        return await original(*args, **kwargs)

    monkeypatch.setattr(store.agent_runtime, "run_turn", spy)
    response = client.post(f"/api/chat?session_id={session_id}", json={"message": "你好"})
    assert response.status_code == 200
    assert captured["locked"] is False


def test_websocket_chat_does_not_hold_mutation_lock(monkeypatch):
    client = TestClient(app)
    session_id = "lock_scope_ws"
    session = _seed_session(session_id)
    captured = {}
    original = store.agent_runtime.run_turn

    async def spy(*args, **kwargs):
        captured["locked"] = session.mutation_lock.locked()
        return await original(*args, **kwargs)

    monkeypatch.setattr(store.agent_runtime, "run_turn", spy)
    with client.websocket_connect(f"/ws?session_id={session_id}") as ws:
        ws.receive_json()  # presentation_loaded
        ws.receive_json()  # preview_update
        ws.send_json({"type": "chat", "message": "你好"})
        for _ in range(20):
            message = ws.receive_json()
            if message.get("type") == "presentation_updated":
                break
    assert captured.get("locked") is False
