"""New-conversation reset: clears chat + agent memory, preserves the deck."""

from __future__ import annotations

from backend.ir.models import PresentationIR
from backend.session.services.memory import MemoryService
from backend.session.session import PPTSession


def _session_with_history() -> PPTSession:
    pres = PresentationIR(title="Keep Me")
    session = PPTSession(session_id="sess_reset", pres=pres)
    session.add_message(role="user", content="hello")
    session.add_message(role="assistant", content="hi")
    session.agent_memory = session.agent_memory  # touch
    session.memory.compressed_anchor = {"role": "system", "content": "anchor"}
    session.memory.compression_through_index = 2
    session.memory.get_subagent_memory("PlanCriticSubagent")
    return session


def test_reset_conversation_clears_chat_and_memory():
    session = _session_with_history()
    slide_count = len(session.document.presentation.slides)
    epoch = session.document.epoch
    version = session.document.presentation.version
    checkpoints = len(session.checkpoints)

    session.reset_conversation()

    assert session.memory.messages == []
    assert session.memory.subagent_memories == {}
    assert session.memory.compressed_anchor is None
    assert session.memory.compression_through_index == 0

    # The deck, identity and undo/checkpoint state are untouched.
    assert len(session.document.presentation.slides) == slide_count
    assert session.document.epoch == epoch
    assert session.document.presentation.version == version
    assert len(session.checkpoints) == checkpoints


def test_memory_service_clear_conversation_resets_anchor():
    mem = MemoryService()
    mem.add_message(role="user", content="x")
    mem.compressed_anchor = {"role": "system", "content": "a"}
    mem.compression_through_index = 1
    mem.compressed_anchor = {"role": "system", "content": "a"}
    mem.clear_conversation()
    assert mem.messages == []
    assert mem.compressed_anchor is None
    assert mem.compression_through_index == 0
    assert mem.compression_report is None
