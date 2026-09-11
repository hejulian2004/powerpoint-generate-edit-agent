"""Transcript ownership tests.

`AgentRuntime.run_turn` is the single owner of the conversation transcript:
the user turn is appended exactly once, the assistant reply is appended exactly
once, and compression is model-facing only (it never rewrites `session.messages`).
WebSocket and REST transports must therefore produce identical transcripts.
"""

import asyncio

from fastapi.testclient import TestClient

from backend.agent.context_compressor import ContextCompressor
from backend.agent.runtime import AgentRuntime
from backend.ir.models import PresentationIR
from backend.ir.patch import HistoryManager
from backend.main import app
from backend.session.manager import session_manager
from backend.session.session import PPTSession
from backend.state.store import create_default_demo_presentation


class _SpyGraph:
    def __init__(self):
        self.calls = []

    async def ainvoke(self, state, config=None):
        self.calls.append(state)
        return {"final_summary": "已处理。", "tool_results": []}


def test_run_turn_appends_user_and_assistant_exactly_once():
    async def _run():
        pres = PresentationIR(title="Transcript")
        history = HistoryManager()
        session = PPTSession(session_id="sess_transcript", pres=pres)
        runtime = AgentRuntime()
        runtime.graph = _SpyGraph()

        await runtime.run_turn("你好", pres, history, session=session)

        assert [m["role"] for m in session.messages] == ["user", "assistant"]
        assert session.messages[0]["content"] == "你好"
        assert session.messages[1]["content"] == "已处理。"

    asyncio.run(_run())


def test_compressor_receives_each_user_turn_once(monkeypatch):
    captured = []
    original = ContextCompressor.evaluate_and_compress

    def spy(cls, messages, max_tokens=256 * 1024, context_key="256k", force_compress=False):
        captured.append(list(messages))
        return original(
            messages,
            max_tokens=max_tokens,
            context_key=context_key,
            force_compress=force_compress,
        )

    monkeypatch.setattr(ContextCompressor, "evaluate_and_compress", classmethod(spy))

    async def _run():
        pres = PresentationIR(title="Transcript")
        history = HistoryManager()
        session = PPTSession(session_id="sess_transcript_ctx", pres=pres)
        runtime = AgentRuntime()
        runtime.graph = _SpyGraph()

        await runtime.run_turn("第一轮", pres, history, session=session)
        await runtime.run_turn("第二轮", pres, history, session=session)

        # First turn: exactly one user message. Second turn: user, assistant, user.
        assert [m["role"] for m in captured[0]] == ["user"]
        assert [m["role"] for m in captured[1]] == ["user", "assistant", "user"]
        assert [m["content"] for m in captured[1]] == ["第一轮", "已处理。", "第二轮"]

    asyncio.run(_run())


def _seed_session(session_id: str) -> PPTSession:
    session = session_manager.get_or_create(
        session_id, pres_factory=create_default_demo_presentation
    )
    session._unsafe_install_for_bootstrap(
        create_default_demo_presentation(),
        checkpoint_description="test seed",
    )
    return session


def _drain_until(ws, expected_type: str, limit: int = 20):
    seen = []
    for _ in range(limit):
        message = ws.receive_json()
        seen.append(message)
        if message.get("type") == expected_type:
            return message, seen
    raise AssertionError(f"Did not receive '{expected_type}' within {limit} messages: {seen}")


def test_websocket_and_rest_chat_produce_identical_transcripts():
    client = TestClient(app)
    ws_session_id = "transcript_ws"
    rest_session_id = "transcript_rest"
    ws_seed = _seed_session(ws_session_id)
    rest_seed = _seed_session(rest_session_id)

    with client.websocket_connect(f"/ws?session_id={ws_session_id}") as ws:
        ws.receive_json()  # presentation_loaded
        ws.receive_json()  # preview_update
        ws.send_json({
            "type": "chat",
            "message": "你好",
            "document_epoch": ws_seed.document_epoch,
            "base_revision": ws_seed.pres.version,
        })
        _drain_until(ws, "presentation_updated")

    response = client.post(
        f"/api/chat?session_id={rest_session_id}",
        json={
            "message": "你好",
            "document_epoch": rest_seed.document_epoch,
            "base_revision": rest_seed.pres.version,
        },
    )
    assert response.status_code == 200

    ws_session = session_manager.get_session(ws_session_id)
    rest_session = session_manager.get_session(rest_session_id)

    ws_roles = [m["role"] for m in ws_session.messages]
    rest_roles = [m["role"] for m in rest_session.messages]
    assert ws_roles == ["user", "assistant"]
    assert rest_roles == ["user", "assistant"]
    assert ws_session.messages[0]["content"] == rest_session.messages[0]["content"] == "你好"
