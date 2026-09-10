"""Execution-level tests for the RiskPolicy confirmation gate (PR6-hardening).

PR6.1 surfaced `_needs_confirmation` on resolver-generated tool calls, but the
runtime executed them unconditionally and raw live-LLM calls bypassed risk policy
entirely. This round centralizes execution in `MutationGateway`:

- Every call (LLM or heuristic) is risk-enriched before the gate.
- The gateway must NOT execute a flagged/unassessed risky mutation.
- The blocked call must surface `confirmation_required` and register a pending
  confirmation in the session (original arguments + document epoch + revision).
- An explicitly confirmed call id must execute.
- `AgentRuntime.confirm_pending` executes the ORIGINAL pending call and invalidates
  it when the presentation changed since it was blocked.
"""

import asyncio

from backend.agent.mutation_gateway import MutationGateway
from backend.agent.risk_policy import ConfirmationGate, RiskEnricher
from backend.agent.runtime import AgentRuntime
from backend.ir.models import PresentationIR, SlideIR, TextElementIR, TextContentIR
from backend.ir.patch import HistoryManager
from backend.session.session import PPTSession


def _pres_with_title():
    pres = PresentationIR(title="Gate Test")
    slide = SlideIR(id="slide_1", slide_num=1)
    slide.add_element(TextElementIR(
        id="elem_title", x=80.0, y=50.0, width=700.0, height=50.0,
        text_content=TextContentIR.from_plain_text("Quarterly Review")
    ))
    pres.slides.append(slide)
    pres.active_slide_id = slide.id
    return pres


def _flagged_move_call(call_id="call_low_conf"):
    return {
        "name": "update_element",
        "arguments": {"element_id": "elem_title", "slide_id": "slide_1", "y": 260.0},
        "id": call_id,
        "_resolution_confidence": 0.6,
        "_needs_confirmation": True,
    }


async def _gateway_execute(tool_calls, pres, history, *, session=None, on_event=None, confirmed_ids=None, bypass_confirmation=False):
    return await MutationGateway.execute_tool_calls(
        tool_calls,
        pres,
        history,
        session=session,
        on_event=on_event,
        confirmed_ids=confirmed_ids,
        source="agent",
        bypass_confirmation=bypass_confirmation,
    )


# =====================================================================
# Gate unit behavior
# =====================================================================

def test_gate_blocks_flagged_call_only():
    assert ConfirmationGate.is_blocked(_flagged_move_call()) is True
    unflagged = {**_flagged_move_call(), "_needs_confirmation": False}
    assert ConfirmationGate.is_blocked(unflagged) is False
    # Non-risk tools are never gated, even without enrichment metadata
    assert ConfirmationGate.is_blocked({"name": "create_slide", "arguments": {}}) is False
    assert ConfirmationGate.is_blocked(
        {"name": "generate_presentation", "arguments": {}}
    ) is False


def test_gate_fails_closed_for_unassessed_risky_calls():
    """A risk-mapped action with no risk assessment must NOT slip through."""
    assert ConfirmationGate.is_blocked({"name": "update_element", "arguments": {}}) is True
    assert ConfirmationGate.is_blocked(
        {"name": "delete_element", "arguments": {"element_id": "ghost"}}
    ) is True


def test_gate_allows_explicitly_confirmed_call_id():
    tc = _flagged_move_call()
    assert ConfirmationGate.is_blocked(tc, {"call_low_conf"}) is False
    assert ConfirmationGate.is_blocked(tc, {"other_call"}) is True


def test_blocked_result_contract():
    res = ConfirmationGate.blocked_result(_flagged_move_call())
    assert res["success"] is False
    assert res["blocked"] is True
    assert res["requires_confirmation"] is True
    assert res["error"] == "requires_user_confirmation"
    assert res["call_id"] == "call_low_conf"


# =====================================================================
# RiskEnricher: raw live-LLM calls must be assessed
# =====================================================================

def test_risk_enricher_marks_raw_llm_calls():
    pres = _pres_with_title()

    exact = {"name": "delete_element", "arguments": {"element_id": "elem_title"}, "id": "c1"}
    RiskEnricher.enrich_tool_call(exact, pres)
    assert exact["_needs_confirmation"] is False
    assert exact["_resolution_confidence"] == 1.0

    ghost = {"name": "update_element", "arguments": {"element_id": "ghost", "y": 10}, "id": "c2"}
    RiskEnricher.enrich_tool_call(ghost, pres)
    assert ghost["_needs_confirmation"] is True
    assert ghost["_resolution_confidence"] is None
    assert ghost["_risk_action_type"] == "move_element"

    # Existing ActionResolver metadata is preserved (more precise semantic intent)
    flagged = _flagged_move_call()
    RiskEnricher.enrich_tool_call(flagged, pres)
    assert flagged["_needs_confirmation"] is True
    assert flagged["_resolution_confidence"] == 0.6


def test_risk_enricher_ignores_non_risk_tools():
    pres = _pres_with_title()
    tc = {"name": "generate_slide_layout", "arguments": {"layout_type": "card_grid"}, "id": "c3"}
    RiskEnricher.enrich_tool_call(tc, pres)
    assert "_needs_confirmation" not in tc


# =====================================================================
# MutationGateway execution gate
# =====================================================================

def test_gateway_blocks_unconfirmed_mutation():
    async def _run():
        pres = _pres_with_title()
        history = HistoryManager()
        events = []

        async def on_event(payload):
            events.append(payload)

        batch = await _gateway_execute(
            [_flagged_move_call()], pres, history, on_event=on_event
        )

        elem = pres.slides[0].get_element("elem_title")
        assert elem.y == 50.0  # mutation did NOT happen
        res = batch.results[0]["result"]
        assert res["blocked"] is True
        assert batch.results[0]["requires_confirmation"] is True
        # No target tracking for a blocked call
        assert batch.last_target_id is None
        # Telemetry surfaced
        assert any(e["type"] == "confirmation_required" for e in events)

    asyncio.run(_run())


def test_gateway_executes_confirmed_mutation():
    async def _run():
        pres = _pres_with_title()
        history = HistoryManager()
        batch = await _gateway_execute(
            [_flagged_move_call()], pres, history, confirmed_ids=["call_low_conf"]
        )

        elem = pres.slides[0].get_element("elem_title")
        assert elem.y == 260.0  # mutation applied after confirmation
        assert batch.results[0]["result"].get("blocked") is None
        assert batch.last_target_id == "elem_title"

    asyncio.run(_run())


def test_gateway_blocks_raw_llm_call_with_unresolved_target():
    async def _run():
        pres = _pres_with_title()
        history = HistoryManager()
        session = PPTSession(session_id="sess_gate", pres=pres)
        events = []

        async def on_event(payload):
            events.append(payload)

        batch = await _gateway_execute(
            [{
                "name": "delete_element",
                "arguments": {"element_id": "ghost_element", "slide_id": "slide_1"},
                "id": "call_llm_ghost",
            }],
            pres,
            history,
            session=session,
            on_event=on_event,
        )

        assert pres.slides[0].get_element("elem_title") is not None  # not deleted
        assert batch.results[0]["result"]["blocked"] is True
        assert any(
            e["type"] == "confirmation_required" and e.get("call_id") == "call_llm_ghost"
            for e in events
        )
        pending = session.get_pending_confirmation("call_llm_ghost")
        assert pending is not None
        assert pending["presentation_version"] == pres.version
        assert pending["expected_revision"] == pres.version
        assert pending["document_epoch"] == session.document_epoch
        assert pending["arguments"] == {"element_id": "ghost_element", "slide_id": "slide_1"}

    asyncio.run(_run())


def test_gateway_executes_raw_llm_call_with_resolved_target():
    async def _run():
        pres = _pres_with_title()
        history = HistoryManager()
        batch = await _gateway_execute(
            [{
                "name": "delete_element",
                "arguments": {"element_id": "elem_title", "slide_id": "slide_1"},
                "id": "call_llm_ok",
            }],
            pres,
            history,
        )

        assert pres.slides[0].get_element("elem_title") is None  # deleted
        assert batch.results[0]["result"].get("blocked") is None

    asyncio.run(_run())


def test_gateway_fails_closed_for_unknown_tool():
    async def _run():
        pres = _pres_with_title()
        history = HistoryManager()
        batch = await _gateway_execute(
            [{"name": "not_a_tool", "arguments": {}, "id": "c_unknown"}],
            pres,
            history,
        )
        res = batch.results[0]["result"]
        assert res["success"] is False
        assert "Unknown tool" in res["error"]

    asyncio.run(_run())


# =====================================================================
# Pending confirmation lifecycle
# =====================================================================

def test_confirm_pending_executes_original_call_and_clears():
    async def _run():
        pres = _pres_with_title()
        history = HistoryManager()
        session = PPTSession(session_id="sess_pending", pres=pres)
        runtime = AgentRuntime()
        events = []

        async def on_event(payload):
            events.append(payload)

        await _gateway_execute(
            [_flagged_move_call()], pres, history, session=session, on_event=on_event
        )
        assert session.get_pending_confirmation("call_low_conf") is not None
        assert pres.slides[0].get_element("elem_title").y == 50.0

        result = await runtime.confirm_pending(session, "call_low_conf", on_event=on_event)

        assert result["success"] is True
        assert result["tool"] == "update_element"
        assert pres.slides[0].get_element("elem_title").y == 260.0
        assert session.get_pending_confirmation("call_low_conf") is None
        assert any(e["type"] == "confirmation_approved" for e in events)
        assert any(e["type"] == "confirmation_resolved" for e in events)

    asyncio.run(_run())


def test_confirm_pending_unknown_call_id():
    async def _run():
        pres = _pres_with_title()
        session = PPTSession(session_id="sess_unknown", pres=pres)
        runtime = AgentRuntime()
        result = await runtime.confirm_pending(session, "does_not_exist")
        assert result["success"] is False
        assert result["error"] == "unknown_confirmation"

    asyncio.run(_run())


def test_stale_pending_confirmation_is_invalidated():
    async def _run():
        pres = _pres_with_title()
        history = HistoryManager()
        session = PPTSession(session_id="sess_stale", pres=pres)
        runtime = AgentRuntime()
        events = []

        async def on_event(payload):
            events.append(payload)

        await _gateway_execute(
            [_flagged_move_call()], pres, history, session=session, on_event=on_event
        )
        assert session.get_pending_confirmation("call_low_conf") is not None

        # The presentation changes while the call waits for confirmation
        pres.version += 1

        result = await runtime.confirm_pending(session, "call_low_conf", on_event=on_event)

        assert result["success"] is False
        assert result["error"] == "confirmation_invalidated"
        assert pres.slides[0].get_element("elem_title").y == 50.0  # unchanged
        assert session.get_pending_confirmation("call_low_conf") is None
        assert any(e["type"] == "confirmation_invalidated" for e in events)

    asyncio.run(_run())


def test_cancel_pending_discards_call():
    async def _run():
        pres = _pres_with_title()
        history = HistoryManager()
        session = PPTSession(session_id="sess_cancel", pres=pres)
        runtime = AgentRuntime()
        await _gateway_execute(
            [_flagged_move_call()], pres, history, session=session
        )

        result = await runtime.cancel_pending(session, "call_low_conf")

        assert result["success"] is True
        assert result["cancelled"] is True
        assert session.get_pending_confirmation("call_low_conf") is None
        assert pres.slides[0].get_element("elem_title").y == 50.0

    asyncio.run(_run())


def test_run_turn_forwards_confirmed_tool_ids():
    async def _run():
        pres = _pres_with_title()
        history = HistoryManager()
        runtime = AgentRuntime()

        class _SpyGraph:
            def __init__(self):
                self.captured = None

            async def ainvoke(self, state, config=None):
                self.captured = (state, config)
                return {"final_summary": "ok", "tool_results": []}

        runtime.graph = _SpyGraph()
        await runtime.run_turn(
            "你好", pres, history, confirmed_tool_ids=["call_x", "call_y"]
        )

        state, config = runtime.graph.captured
        assert state["confirmed_tool_ids"] == ["call_x", "call_y"]
        assert config["configurable"]["confirmed_tool_ids"] == ["call_x", "call_y"]

    asyncio.run(_run())
