"""Phase 6: Agent edit freeze enforced at the MutationGateway boundary."""

from __future__ import annotations

import asyncio

from backend.agent.mutation_gateway import DOCUMENT_FROZEN, MutationGateway
from backend.agent.runtime import AgentRuntime
from backend.ir.models import PresentationIR, SlideIR, TextContentIR, TextElementIR
from backend.protocol.presentation import build_canonical_snapshot
from backend.session.factory import SessionFactory
from backend.session.services.agent_execution import AgentExecutionService


def _pres() -> PresentationIR:
    pres = PresentationIR(title="Freeze Deck")
    slide = SlideIR(id="slide_1", slide_num=1)
    slide.add_element(TextElementIR(
        id="title_node", x=80.0, y=50.0, width=700.0, height=50.0,
        text_content=TextContentIR.from_plain_text("Hello"),
    ))
    pres.slides.append(slide)
    pres.active_slide_id = slide.id
    return pres


def _call(x: float = 120.0) -> dict:
    return {
        "name": "update_element",
        "arguments": {"slide_id": "slide_1", "element_id": "title_node", "x": x},
        "id": "call_freeze",
    }


def test_agent_execution_service_lease_semantics():
    service = AgentExecutionService()
    assert service.allows("user_direct", None) is True

    service.begin_turn("turn_a")
    assert service.is_frozen is True
    assert service.allows("agent", "turn_a") is True
    assert service.allows("remediation", "turn_a") is True
    assert service.allows("user_direct", None) is False
    assert service.allows("agent", "turn_b") is False

    service.end_turn("turn_b")
    assert service.is_frozen is True
    service.end_turn("turn_a")
    assert service.is_frozen is False


def test_gateway_rejects_frontend_write_while_agent_owns_document():
    session = SessionFactory.create(_pres(), session_id="freeze_gateway")
    session.agent_execution.begin_turn("turn_own")

    blocked = asyncio.run(MutationGateway.execute_tool_calls(
        [_call()], session.pres, session.history, session=session,
        source="user_direct", bypass_confirmation=True,
        document_epoch=session.document_epoch,
        expected_revision=session.pres.version, require_stamps=True,
    ))
    assert blocked.error == DOCUMENT_FROZEN
    assert session.pres.slides[0].elements[0].x == 80.0

    allowed = asyncio.run(MutationGateway.execute_tool_calls(
        [_call()], session.pres, session.history, session=session,
        source="agent", agent_turn_id="turn_own", bypass_confirmation=True,
    ))
    assert allowed.success
    assert session.pres.slides[0].elements[0].x == 120.0


def test_gateway_allows_remediation_with_matching_turn():
    session = SessionFactory.create(_pres(), session_id="freeze_remediation")
    session.agent_execution.begin_turn("turn_r")
    result = MutationGateway.execute_one_sync(
        "update_element",
        {"slide_id": "slide_1", "element_id": "title_node", "y": 200.0},
        session.pres, session.history, session=session,
        source="remediation", agent_turn_id="turn_r",
    )
    assert result.get("error") is None
    assert session.pres.slides[0].elements[0].y == 200.0


def test_canonical_snapshot_exposes_edit_lock():
    session = SessionFactory.create(_pres(), session_id="freeze_snapshot")
    assert build_canonical_snapshot(session)["edit_lock"] == {
        "locked": False, "kind": None, "turn_id": None
    }
    session.agent_execution.begin_turn("turn_x", kind="agent")
    lock = build_canonical_snapshot(session)["edit_lock"]
    assert lock["locked"] is True
    assert lock["turn_id"] == "turn_x"


def test_run_turn_holds_then_releases_the_freeze():
    async def _run():
        session = SessionFactory.create(_pres(), session_id="freeze_turn")
        runtime = AgentRuntime()
        observed = {}

        class _SpyGraph:
            async def ainvoke(self, state, config=None):
                observed["turn_id"] = state.get("agent_turn_id")
                observed["frozen"] = session.agent_execution.is_frozen
                observed["allows_agent"] = session.agent_execution.allows(
                    "agent", state.get("agent_turn_id")
                )
                return {"final_summary": "ok", "tool_results": []}

        runtime.graph = _SpyGraph()
        await runtime.run_turn("freeze please", session.pres, session.history, session=session)

        assert observed["turn_id"]
        assert observed["frozen"] is True
        assert observed["allows_agent"] is True
        assert session.agent_execution.is_frozen is False

    asyncio.run(_run())
