"""Execution-level tests for the RiskPolicy confirmation gate (PR6-hardening P1).

PR6.1 surfaced `_needs_confirmation` on resolver-generated tool calls, but the
runtime executed them unconditionally. These tests pin the enforcement contract:

- `tools_node` must NOT execute a flagged low-confidence mutation.
- The blocked call must surface a `confirmation_required` telemetry event.
- An explicitly user-confirmed call id (state or configurable) must execute.
"""

import asyncio

from backend.agent.graph import tools_node
from backend.agent.risk_policy import ConfirmationGate
from backend.ir.models import PresentationIR, SlideIR, TextElementIR, TextContentIR
from backend.ir.patch import HistoryManager


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


# =====================================================================
# Gate unit behavior
# =====================================================================

def test_gate_blocks_flagged_call_only():
    assert ConfirmationGate.is_blocked(_flagged_move_call()) is True
    assert ConfirmationGate.is_blocked({"name": "update_element", "arguments": {}}) is False
    unflagged = {**_flagged_move_call(), "_needs_confirmation": False}
    assert ConfirmationGate.is_blocked(unflagged) is False


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


# =====================================================================
# tools_node execution gate
# =====================================================================

def test_tools_node_blocks_unconfirmed_mutation():
    async def _run():
        pres = _pres_with_title()
        history = HistoryManager()
        events = []

        async def on_event(payload):
            events.append(payload)

        state = {"tool_calls": [_flagged_move_call()]}
        config = {
            "configurable": {
                "pres": pres,
                "history": history,
                "on_event": on_event,
            }
        }
        out = await tools_node(state, config)

        elem = pres.slides[0].get_element("elem_title")
        assert elem.y == 50.0  # mutation did NOT happen
        res = out["tool_results"][0]["result"]
        assert res["blocked"] is True
        assert out["tool_results"][0]["requires_confirmation"] is True
        # No target tracking for a blocked call
        assert out["last_target_id"] is None
        # Telemetry surfaced
        assert any(e["type"] == "confirmation_required" for e in events)

    asyncio.run(_run())


def test_tools_node_executes_confirmed_mutation():
    async def _run():
        pres = _pres_with_title()
        history = HistoryManager()
        state = {"tool_calls": [_flagged_move_call()]}
        config = {
            "configurable": {
                "pres": pres,
                "history": history,
                "confirmed_tool_ids": ["call_low_conf"],
            }
        }
        out = await tools_node(state, config)

        elem = pres.slides[0].get_element("elem_title")
        assert elem.y == 260.0  # mutation applied after confirmation
        assert out["tool_results"][0]["result"].get("blocked") is None
        assert out["last_target_id"] == "elem_title"

    asyncio.run(_run())


def test_tools_node_confirmation_via_state():
    async def _run():
        pres = _pres_with_title()
        history = HistoryManager()
        state = {
            "tool_calls": [_flagged_move_call("call_from_state")],
            "confirmed_tool_ids": ["call_from_state"],
        }
        config = {"configurable": {"pres": pres, "history": history}}
        out = await tools_node(state, config)
        assert pres.slides[0].get_element("elem_title").y == 260.0
        assert out["tool_results"][0]["result"].get("blocked") is None

    asyncio.run(_run())

