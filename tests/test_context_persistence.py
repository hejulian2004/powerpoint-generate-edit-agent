"""Manual (user-triggered) context compression persistence."""

from __future__ import annotations

import asyncio

from backend.agent.context_compressor import ContextCompressor
from backend.agent.runtime import AgentRuntime
from backend.ir.models import PresentationIR
from backend.session.session import PPTSession
from backend.session.snapshot import session_to_snapshot, snapshot_to_session


def _seed_messages(session: PPTSession, count: int = 10) -> None:
    for i in range(count):
        session.add_message(role="user" if i % 2 == 0 else "assistant", content=f"message-{i}")


def test_build_anchor_covers_older_messages():
    messages = [{"role": "user", "content": f"m{i}"} for i in range(10)]
    anchor, through, report = ContextCompressor.build_anchor(messages, keep_recent=4)
    assert anchor is not None
    assert through == 6
    assert report.is_compressed is True
    assert report.tokens_saved >= 0

    assembled = ContextCompressor.assemble_model_messages(messages, anchor, through)
    assert assembled[0] is anchor
    assert len(assembled) == 1 + 4
    # Raw transcript is untouched.
    assert len(messages) == 10


def test_build_anchor_noop_when_short():
    messages = [{"role": "user", "content": "only"}]
    anchor, through, report = ContextCompressor.build_anchor(messages, keep_recent=4)
    assert anchor is None
    assert through == 0
    assert report.is_compressed is False


def test_assemble_without_anchor_returns_messages():
    messages = [{"role": "user", "content": "a"}]
    assert ContextCompressor.assemble_model_messages(messages, None, 0) == messages


def test_compress_context_persists_anchor_without_rewriting_transcript():
    session = PPTSession(session_id="sess_compress", pres=PresentationIR(title="D"))
    _seed_messages(session, 10)
    raw_before = list(session.memory.messages)

    events = []

    async def on_ev(ev):
        events.append(ev)

    result = asyncio.run(AgentRuntime().compress_context(session, on_event=on_ev))

    assert result["applied"] is True
    assert session.memory.compressed_anchor is not None
    assert session.memory.compression_through_index == 6
    assert session.memory.messages == raw_before
    assert any(e.get("type") == "context_usage" for e in events)
    assert any(e.get("type") == "context_compressed" for e in events)


def test_compression_anchor_survives_snapshot_roundtrip():
    session = PPTSession(session_id="sess_compress_rt", pres=PresentationIR(title="D"))
    _seed_messages(session, 10)
    asyncio.run(AgentRuntime().compress_context(session))

    snapshot = session_to_snapshot(session)
    restored = snapshot_to_session(snapshot)

    assert restored.memory.compressed_anchor == session.memory.compressed_anchor
    assert restored.memory.compression_through_index == session.memory.compression_through_index
