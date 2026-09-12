"""Plan interaction mode: pause for approval, confirm/invalidate/cancel."""

from __future__ import annotations

import asyncio

import pytest

from backend.agent import graph as g
from backend.agent.runtime import AgentRuntime
from backend.ir.models import PresentationIR
from backend.ir.patch import HistoryManager
from backend.session.session import PPTSession


def _make_session(sid: str = "sess_plan") -> PPTSession:
    pres = PresentationIR(title="Plan Deck")
    return PPTSession(session_id=sid, pres=pres)


# ---------------------------------------------------------------------------
# Routing decisions
# ---------------------------------------------------------------------------

def test_planner_routes_directly_to_executor_when_preapproved():
    assert g.should_route_planner(
        {"intent": "generate_presentation", "plan_preapproved": True}
    ) == "executor_node"


def test_plan_mode_pauses_for_confirmation():
    state = {
        "intent": "generate_presentation",
        "interaction_mode": "plan",
        "plan": "先做封面，再做三页内容",
        "plan_review": {"approved": True},
        "plan_iteration": 1,
    }
    assert g.should_route_plan_critic(state) == "await_plan_confirmation_node"
    assert g._needs_plan_confirmation(state) is True


def test_auto_mode_executes_without_confirmation():
    state = {
        "intent": "generate_presentation",
        "interaction_mode": "auto",
        "plan": "plan text",
        "plan_review": {"approved": True},
        "plan_iteration": 1,
    }
    assert g.should_route_plan_critic(state) == "executor_node"


def test_rejected_plan_still_loops_before_confirmation():
    state = {
        "intent": "generate_presentation",
        "interaction_mode": "plan",
        "plan": "bad plan",
        "plan_review": {"approved": False},
        "plan_iteration": 1,
    }
    assert g.should_route_plan_critic(state) == "planner_node"


# ---------------------------------------------------------------------------
# await_plan_confirmation_node
# ---------------------------------------------------------------------------

def test_await_plan_confirmation_node_registers_plan():
    session = _make_session("sess_plan_node")
    events = []

    async def on_ev(ev):
        events.append(ev)

    state = {
        "plan": "封面 + 三页核心内容",
        "plan_review": {"approved": True},
        "user_query": "做一份汇报",
        "intent": "generate_presentation",
        "turn_document_epoch": session.document.epoch,
        "active_slide_id": None,
    }
    out = asyncio.run(
        g.await_plan_confirmation_node(
            state, {"configurable": {"session": session, "on_event": on_ev}}
        )
    )
    assert out["plan_ready"] is True
    assert len(session.pending_plans) == 1
    plan_id = next(iter(session.pending_plans))
    record = session.pending_plans[plan_id]
    assert record["plan"] == "封面 + 三页核心内容"
    assert record["document_epoch"] == session.document.epoch
    assert any(e.get("type") == "plan_ready" for e in events)


# ---------------------------------------------------------------------------
# confirm / cancel lifecycle
# ---------------------------------------------------------------------------

def _runtime_with_stub_turn(monkeypatch):
    runtime = AgentRuntime()
    captured = {}

    async def fake_run_turn(**kwargs):
        captured.update(kwargs)
        return {"reply": "executed", "plan": kwargs.get("approved_plan")}

    monkeypatch.setattr(runtime, "run_turn", fake_run_turn)
    return runtime, captured


def test_confirm_plan_executes_frozen_plan(monkeypatch):
    runtime, captured = _runtime_with_stub_turn(monkeypatch)
    session = _make_session("sess_plan_confirm")
    session.register_pending_plan(
        plan_id="p_ok",
        plan="冻结的计划",
        plan_review={"approved": True},
        user_query="做一份汇报",
        document_epoch=session.document.epoch,
        expected_revision=session.document.presentation.version,
    )

    events = []

    async def on_ev(ev):
        events.append(ev)

    result = asyncio.run(runtime.confirm_plan(session, "p_ok", on_event=on_ev))
    assert result.get("success") is True
    assert captured["approved_plan"] == "冻结的计划"
    assert captured["record_user_message"] is False
    assert captured["mode"] == "plan"
    assert "p_ok" not in session.pending_plans
    assert any(e.get("type") == "plan_approved" for e in events)


def test_confirm_plan_invalidated_when_document_changed(monkeypatch):
    runtime, _ = _runtime_with_stub_turn(monkeypatch)
    session = _make_session("sess_plan_stale")
    session.register_pending_plan(
        plan_id="p_stale",
        plan="旧计划",
        plan_review={"approved": True},
        user_query="q",
        document_epoch="epoch_that_changed",
        expected_revision=0,
    )
    events = []

    async def on_ev(ev):
        events.append(ev)

    result = asyncio.run(runtime.confirm_plan(session, "p_stale", on_event=on_ev))
    assert result["error"] == "plan_invalidated"
    assert "p_stale" not in session.pending_plans
    assert any(e.get("type") == "plan_invalidated" for e in events)


def test_confirm_unknown_plan_fails():
    runtime = AgentRuntime()
    session = _make_session("sess_plan_unknown")
    result = asyncio.run(runtime.confirm_plan(session, "nope"))
    assert result["success"] is False
    assert result["error"] == "unknown_plan"


def test_cancel_plan_discards_without_executing(monkeypatch):
    runtime, captured = _runtime_with_stub_turn(monkeypatch)
    session = _make_session("sess_plan_cancel")
    session.register_pending_plan(
        plan_id="p_cancel",
        plan="取消我",
        plan_review={},
        user_query="q",
        document_epoch=session.document.epoch,
        expected_revision=session.document.presentation.version,
    )
    result = asyncio.run(runtime.cancel_plan(session, "p_cancel"))
    assert result["cancelled"] is True
    assert captured == {}
    assert "p_cancel" not in session.pending_plans


def test_interaction_mode_toggle():
    session = _make_session("sess_plan_mode")
    assert session.interaction_mode == "auto"
    assert session.set_interaction_mode("plan") == "plan"
    assert session.set_interaction_mode("bogus") == "auto"


class _PlanMockLLM:
    """Minimal LLM: plan critic approves; everything else is a no-op."""

    api_key = "plan_mock_key"

    async def chat_completion(self, messages, role="reasoning", **kwargs):
        if role == "vision":
            return {"choices": [{"message": {"content": "【美学评分: 90/100】"}}]}
        sys_msg = next((m["content"] for m in messages if m.get("role") == "system"), "")
        if "第三方 PPT 策划架构评审总监" in sys_msg:
            return {"choices": [{"message": {"content": "【评审结论】: 通过\n【规划健康分: 92/100】"}}]}
        return {"choices": [{"message": {"content": "ok"}}]}


def test_graph_pauses_end_to_end_in_plan_mode():
    app = g.build_ppt_agent_graph()
    pres = PresentationIR(title="Plan Pause")
    history = HistoryManager(pres)
    session = PPTSession(session_id="sess_graph_plan", pres=pres)
    session.set_interaction_mode("plan")
    events = []

    async def on_ev(ev):
        events.append(ev)

    initial = {
        "messages": [],
        "user_query": "做一份商业汇报PPT",
        "intent": "generate_presentation",
        "interaction_mode": "plan",
    }
    final = asyncio.run(
        app.ainvoke(
            initial,
            config={
                "configurable": {
                    "pres": pres,
                    "history": history,
                    "session": session,
                    "llm_client": _PlanMockLLM(),
                    "on_event": on_ev,
                }
            },
        )
    )

    assert final.get("plan_ready") is True
    assert len(session.pending_plans) == 1
    assert any(e.get("type") == "plan_ready" for e in events)
    # The executor never ran: no tool calls were committed.
    assert not final.get("tool_results")
