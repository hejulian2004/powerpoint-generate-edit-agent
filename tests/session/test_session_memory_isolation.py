"""Phase 2 crossed tests: Agent / Subagent memory is session-owned and isolated.

``AgentRuntime`` is a shared stateless engine; all durable memory (conversation,
``AgentMemory``, per-subagent memories) lives on the session's ``MemoryService``.
"""

from __future__ import annotations

import asyncio

from backend.agent.memory import AgentMemory
from backend.agent.runtime import AgentRuntime
from backend.agent.subagents.memory import SubagentSessionMemory
from backend.ir.models import PresentationIR, SlideIR
from backend.session.factory import SessionFactory


class _SpyGraph:
    """Captures the state the runtime seeds and returns a canned final state."""

    def __init__(self, result=None):
        self.seen_states = []
        self.result = result or {"final_summary": "ok", "tool_results": []}

    async def ainvoke(self, state, config=None):
        self.seen_states.append(dict(state))
        return dict(self.result)


def _deck(title: str) -> PresentationIR:
    pres = PresentationIR(title=title)
    slide = SlideIR(id=f"slide_{title}", slide_num=1, title=title)
    pres.slides.append(slide)
    pres.active_slide_id = slide.id
    return pres


def _plan_memory_with_entry() -> SubagentSessionMemory:
    mem = SubagentSessionMemory("PlanCriticSubagent")
    mem.record_audit(
        input_digest="digest-1",
        approved=False,
        score=5.0,
        critique_summary="needs work",
        defects_or_risks=["too sparse"],
        recommendations=["add detail"],
    )
    return mem


def test_agent_memory_roundtrip():
    mem = AgentMemory()
    mem.log_action("did a thing")
    mem.update_preference("style", "bold")
    restored = AgentMemory.from_dict(mem.to_dict())
    assert restored.preferences == mem.preferences
    assert restored.recent_activities == mem.recent_activities
    assert AgentMemory.from_dict({}).recent_activities == []


def test_run_turn_persists_subagent_memory_across_turns():
    async def _run():
        session = SessionFactory.create(_deck("A"), session_id="mem_turn_a")
        runtime = AgentRuntime()
        spy = _SpyGraph({
            "final_summary": "ok",
            "tool_results": [],
            "subagent_memories": {
                "PlanCriticSubagent": _plan_memory_with_entry().to_dict()
            },
        })
        runtime.graph = spy

        await runtime.run_turn("first", session.pres, session.history, session=session)
        stored = session.memory.subagent_memories.get("PlanCriticSubagent")
        assert stored is not None
        assert len(stored.entries) == 1

        await runtime.run_turn("second", session.pres, session.history, session=session)
        seeded = spy.seen_states[-1]["subagent_memories"]["PlanCriticSubagent"]
        assert seeded["entries_count"] == 1

    asyncio.run(_run())


def test_subagent_memory_does_not_leak_across_sessions():
    async def _run():
        a = SessionFactory.create(_deck("A"), session_id="mem_leak_a")
        b = SessionFactory.create(_deck("B"), session_id="mem_leak_b")
        runtime = AgentRuntime()
        runtime.graph = _SpyGraph({
            "final_summary": "ok",
            "tool_results": [],
            "subagent_memories": {
                "PlanCriticSubagent": _plan_memory_with_entry().to_dict()
            },
        })

        await runtime.run_turn("secret preference", a.pres, a.history, session=a)

        assert "PlanCriticSubagent" in a.memory.subagent_memories
        assert "PlanCriticSubagent" not in b.memory.subagent_memories
        assert [m["content"] for m in a.memory.messages] == ["secret preference", "ok"]
        assert b.memory.messages == []

    asyncio.run(_run())


def test_runtime_does_not_hold_cross_session_memory():
    async def _run():
        a = SessionFactory.create(_deck("A"), session_id="mem_stateless_a")
        b = SessionFactory.create(_deck("B"), session_id="mem_stateless_b")
        runtime = AgentRuntime()

        captured = {}

        class _CaptureGraph:
            async def ainvoke(self, state, config=None):
                captured["memory"] = config["configurable"]["memory"]
                return {"final_summary": "ok", "tool_results": []}

        runtime.graph = _CaptureGraph()
        await runtime.run_turn("a", a.pres, a.history, session=a)
        assert captured["memory"] is a.memory.agent_memory
        await runtime.run_turn("b", b.pres, b.history, session=b)
        assert captured["memory"] is b.memory.agent_memory
        assert a.memory.agent_memory is not b.memory.agent_memory

    asyncio.run(_run())
