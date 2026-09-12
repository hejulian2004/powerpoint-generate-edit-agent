"""New-conversation reset: clears chat + agent memory, preserves the deck."""

from __future__ import annotations

import asyncio

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
    session.register_pending_confirmation(
        call_id="call_1",
        tool="delete_element",
        arguments={"element_id": "e1"},
        confidence=0.4,
        presentation_version=session.document.presentation.version,
    )
    session.register_pending_plan(
        plan_id="plan_1",
        plan="some plan",
        plan_review={},
        user_query="do something",
        document_epoch=session.document.epoch,
        expected_revision=session.document.presentation.version,
    )
    return session


def test_reset_conversation_clears_chat_and_memory():
    session = _session_with_history()
    slide_count = len(session.document.presentation.slides)
    epoch = session.document.epoch
    version = session.document.presentation.version
    checkpoints = len(session.checkpoints)
    interaction_mode = session.interaction_mode

    asyncio.run(session.reset_conversation())

    assert session.memory.messages == []
    assert session.memory.subagent_memories == {}
    assert session.memory.compressed_anchor is None
    assert session.memory.compression_through_index == 0

    # No orphaned server-side pending actions survive the reset.
    assert session.pending_plans == {}
    assert session.get_pending_confirmation("call_1") is None

    # The deck, identity, interaction mode and undo/checkpoint state are untouched.
    assert len(session.document.presentation.slides) == slide_count
    assert session.document.epoch == epoch
    assert session.document.presentation.version == version
    assert len(session.checkpoints) == checkpoints
    assert session.interaction_mode == interaction_mode


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
