"""Concurrency regressions for the shared conversation-state lock.

Every path that builds model context from the transcript, or writes the
transcript / compression anchor, must hold the SAME lock. These tests prove
that attachment chat and normal agent turns cannot interleave on a stale
transcript, and that a reset waits for an in-flight turn instead of producing a
half-turn transcript.
"""

from __future__ import annotations

import asyncio
import json

from backend.agent.attachment_context import AttachmentChatContext
from backend.agent.runtime import AgentRuntime
from backend.ir.models import PresentationIR
from backend.session.session import PPTSession


class _SlowSpyLLM:
    def __init__(self, delay: float = 0.05):
        self.delay = delay
        self._count = 0
        self.concurrent = 0
        self.max_concurrent = 0
        self.messages_seen = []

    async def chat_completion(self, messages, role="default", **kwargs):
        self.concurrent += 1
        self.max_concurrent = max(self.max_concurrent, self.concurrent)
        self.messages_seen.append(messages)
        await asyncio.sleep(self.delay)
        self.concurrent -= 1
        self._count += 1
        return {"choices": [{"message": {"content": f"answer-{self._count}"}}]}


class _RecordingGraph:
    """Stands in for the LangGraph workflow without running any LLM."""

    def __init__(self):
        self.state = None

    async def ainvoke(self, state, config=None):
        self.state = state
        return {
            "final_summary": "ok",
            "tool_results": [],
            "intent": "chat",
            "final_summary_content": "ok",
        }


def test_attachment_chat_turns_serialize_and_see_prior_turn():
    async def _run():
        session = PPTSession(session_id="sess_lock_chat", pres=PresentationIR(title="D"))
        spy = _SlowSpyLLM(delay=0.05)
        runtime = AgentRuntime(llm_client=spy)
        ctx = AttachmentChatContext(text_digest="digest")
        await asyncio.gather(
            runtime.chat_with_attachments(session, "Q1", ctx),
            runtime.chat_with_attachments(session, "Q2", ctx),
        )
        return session, spy

    session, spy = asyncio.run(_run())

    # No two LLM calls ran at once.
    assert spy.max_concurrent == 1
    # Exactly one user/assistant pair per turn, never a half-turn.
    assert [m["role"] for m in session.memory.messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    # The second turn's request must include the first turn.
    second = json.dumps(spy.messages_seen[1], ensure_ascii=False)
    assert "Q1" in second
    assert "answer-1" in second


def test_run_turn_waits_for_inflight_attachment_chat():
    async def _run():
        session = PPTSession(session_id="sess_lock_turn", pres=PresentationIR(title="D"))
        spy = _SlowSpyLLM(delay=0.05)
        chat_runtime = AgentRuntime(llm_client=spy)
        turn_runtime = AgentRuntime()
        graph = _RecordingGraph()
        turn_runtime.graph = graph

        chat = asyncio.create_task(
            chat_runtime.chat_with_attachments(
                session, "Q1", AttachmentChatContext(text_digest="d")
            )
        )
        await asyncio.sleep(0.01)
        turn = asyncio.create_task(
            turn_runtime.run_turn(
                "Q2",
                session.document.presentation,
                session.history,
                session=session,
            )
        )
        await asyncio.gather(chat, turn)
        return session, graph

    session, graph = asyncio.run(_run())

    # The agent turn only started after the attachment chat committed its turn,
    # so its model context already contains Q1 + answer-1 (no stale snapshot).
    joined = json.dumps(graph.state["raw_messages"], ensure_ascii=False)
    assert "Q1" in joined
    assert "answer-1" in joined


def test_run_turn_does_not_freeze_document_while_queued():
    """Admission (and the agent lease) must only happen after the queued turn
    actually owns the conversation lock; a read-only attachment chat holding it
    must not freeze the document against GUI edits before the turn starts."""

    async def _run():
        session = PPTSession(session_id="sess_lock_freeze", pres=PresentationIR(title="D"))
        spy = _SlowSpyLLM(delay=0.08)
        chat_runtime = AgentRuntime(llm_client=spy)
        turn_runtime = AgentRuntime()
        turn_runtime.graph = _RecordingGraph()

        chat = asyncio.create_task(
            chat_runtime.chat_with_attachments(
                session, "Q1", AttachmentChatContext(text_digest="d")
            )
        )
        await asyncio.sleep(0.01)
        turn = asyncio.create_task(
            turn_runtime.run_turn(
                "Q2",
                session.document.presentation,
                session.history,
                session=session,
            )
        )
        await asyncio.sleep(0.02)
        frozen_while_queued = session.agent_execution.is_frozen
        await asyncio.gather(chat, turn)
        return frozen_while_queued, session.agent_execution.is_frozen

    frozen_while_queued, frozen_after = asyncio.run(_run())
    assert frozen_while_queued is False
    assert frozen_after is False


def test_cancelled_queued_turn_leaks_no_agent_lease():
    async def _run():
        session = PPTSession(session_id="sess_lock_cancel", pres=PresentationIR(title="D"))
        spy = _SlowSpyLLM(delay=0.08)
        chat_runtime = AgentRuntime(llm_client=spy)
        turn_runtime = AgentRuntime()
        turn_runtime.graph = _RecordingGraph()

        chat = asyncio.create_task(
            chat_runtime.chat_with_attachments(
                session, "Q1", AttachmentChatContext(text_digest="d")
            )
        )
        await asyncio.sleep(0.01)
        turn = asyncio.create_task(
            turn_runtime.run_turn(
                "Q2",
                session.document.presentation,
                session.history,
                session=session,
            )
        )
        await asyncio.sleep(0.02)
        turn.cancel()
        try:
            await turn
        except asyncio.CancelledError:
            pass
        await chat
        return session.agent_execution.is_frozen

    assert asyncio.run(_run()) is False


class _SlowGraph:
    async def ainvoke(self, state, config=None):
        await asyncio.sleep(10)


def test_cancelled_running_turn_releases_lease():
    async def _run():
        session = PPTSession(session_id="sess_lock_cancel_run", pres=PresentationIR(title="D"))
        runtime = AgentRuntime()
        runtime.graph = _SlowGraph()
        turn = asyncio.create_task(
            runtime.run_turn(
                "Q",
                session.document.presentation,
                session.history,
                session=session,
            )
        )
        for _ in range(200):
            if session.agent_execution.is_frozen:
                break
            await asyncio.sleep(0.001)
        assert session.agent_execution.is_frozen is True
        turn.cancel()
        try:
            await turn
        except asyncio.CancelledError:
            pass
        return session.agent_execution.is_frozen

    assert asyncio.run(_run()) is False


def test_snapshot_for_persistence_waits_and_captures_complete_turn():
    async def _run():
        session = PPTSession(session_id="sess_lock_snapshot", pres=PresentationIR(title="D"))
        spy = _SlowSpyLLM(delay=0.05)
        runtime = AgentRuntime(llm_client=spy)
        chat = asyncio.create_task(
            runtime.chat_with_attachments(
                session, "Q1", AttachmentChatContext(text_digest="d")
            )
        )
        await asyncio.sleep(0.01)
        snapshot = await session.snapshot_for_persistence()
        await chat
        return snapshot

    snapshot = asyncio.run(_run())
    # Persistence must never observe a half-written user/assistant turn.
    assert [m["role"] for m in snapshot.messages] == ["user", "assistant"]


def test_reset_conversation_waits_for_inflight_turn():
    async def _run():
        session = PPTSession(session_id="sess_lock_reset", pres=PresentationIR(title="D"))
        spy = _SlowSpyLLM(delay=0.05)
        runtime = AgentRuntime(llm_client=spy)
        chat = asyncio.create_task(
            runtime.chat_with_attachments(
                session, "Q1", AttachmentChatContext(text_digest="d")
            )
        )
        await asyncio.sleep(0.01)
        reset = asyncio.create_task(session.reset_conversation())
        await asyncio.gather(chat, reset)
        return session

    session = asyncio.run(_run())

    # The reset ran after the whole turn; empty transcript, never a half-turn.
    assert session.memory.messages == []
