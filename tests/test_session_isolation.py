"""Tests for WebSocket Session Isolation and ActionResolver Safe Resolution (PR5.1 Hardening)."""

import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.state.store import store, create_default_demo_presentation
from backend.session.manager import session_manager
from backend.agent.action import AgentAction, ActionResolver
from backend.ir.models import PresentationIR, SlideIR, TextElementIR, TextContentIR


def _seed_demo_session(session_id: str):
    """Seeds a fresh demo presentation into a session for deterministic WS tests."""
    session = session_manager.get_or_create(session_id, pres_factory=create_default_demo_presentation)
    session.pres = create_default_demo_presentation()
    session.history.clear()
    return session


def test_websocket_session_broadcast_isolation():
    """Verify messages broadcast in session A are never received by session B."""
    client = TestClient(app)
    _seed_demo_session("isolated_sess_A")
    _seed_demo_session("isolated_sess_B")

    with client.websocket_connect("/ws?session_id=isolated_sess_A") as ws_a, \
         client.websocket_connect("/ws?session_id=isolated_sess_B") as ws_b:

        # Drain initial presentation_loaded and preview_update for both
        loaded_a = ws_a.receive_json()
        assert loaded_a["session_id"] == "isolated_sess_A"
        preview_a = ws_a.receive_json()

        loaded_b = ws_b.receive_json()
        assert loaded_b["session_id"] == "isolated_sess_B"
        preview_b = ws_b.receive_json()

        # Mutate element exclusively in Session A
        ws_a.send_json({
            "type": "direct_update_element",
            "payload": {
                "slide_id": "slide_01",
                "element_id": "title_main",
                "x": 333.0
            }
        })

        # ws_a should receive presentation_updated and preview_update
        ev_upd_a = ws_a.receive_json()
        assert ev_upd_a["type"] == "presentation_updated"
        assert ev_upd_a["session_id"] == "isolated_sess_A"

        ev_prev_a = ws_a.receive_json()
        assert ev_prev_a["type"] == "preview_update"
        assert ev_prev_a["session_id"] == "isolated_sess_A"

        # Now verify Session B did not receive Session A's updates.
        # Send a harmless preview_request to Session B to ensure its queue is responsive and has only its own event.
        ws_b.send_json({"type": "preview_request", "slide_id": "slide_01"})
        ev_b = ws_b.receive_json()
        # Should be its requested preview_update, NOT Session A's presentation_updated
        assert ev_b["type"] == "preview_update"
        assert ev_b["session_id"] == "isolated_sess_B"


def test_action_resolver_safe_target_resolution_no_fallback():
    """Verify ActionResolver does not silently fallback to slide.elements[0] for unknown targets."""
    pres = PresentationIR(title="Safe Target Deck")
    slide = SlideIR(
        id="s_test",
        slide_num=1,
        elements=[
            TextElementIR(
                id="first_element_never_touch_silently",
                name="Critical Title",
                x=100.0,
                y=100.0,
                width=500.0,
                height=60.0,
                text_content=TextContentIR.from_plain_text("DO NOT TOUCH")
            )
        ]
    )
    pres.slides = [slide]
    pres.active_slide_id = "s_test"

    # 1. Unknown target lookup should return None, NOT elements[0]
    target_elem = ActionResolver.resolve_target_element("nonexistent_element_xyz", slide)
    assert target_elem is None

    # 2. Relative action with unknown target should return None tool call
    act_relative = AgentAction(
        action_type="update_element",
        target="ghost_element",
        parameters={"x": 50.0},
        relative=True
    )
    tool_call_rel = ActionResolver.action_to_tool_call(act_relative, pres)
    assert tool_call_rel is None

    # 3. Absolute formatting action with unknown target should return None
    act_format = AgentAction(
        action_type="format_text",
        target="unknown_text_box",
        parameters={"font_size": 28.0}
    )
    tool_call_fmt = ActionResolver.action_to_tool_call(act_format, pres)
    assert tool_call_fmt is None

    # 4. Global actions like optimize_layout still work
    act_global = AgentAction(
        action_type="optimize_layout",
        target="",
        parameters={"strategy": "auto"}
    )
    tool_call_global = ActionResolver.action_to_tool_call(act_global, pres)
    assert tool_call_global is not None
    assert tool_call_global["name"] == "optimize_layout"


def test_agent_memory_is_session_scoped():
    """Agent activity in one session must never leak into another session's context."""
    s_a = session_manager.get_or_create(
        "memory_sess_A", pres_factory=create_default_demo_presentation
    )
    s_b = session_manager.get_or_create(
        "memory_sess_B", pres_factory=create_default_demo_presentation
    )

    assert s_a.agent_memory is not s_b.agent_memory

    s_a.agent_memory.log_action("session A edited the title")

    assert "session A edited the title" in s_a.agent_memory.build_system_context()
    assert "session A edited the title" not in s_b.agent_memory.build_system_context()


def test_run_turn_uses_session_scoped_memory():
    """AgentRuntime must pass the session's memory to the graph, not a global one."""
    import asyncio
    from backend.agent.runtime import AgentRuntime

    async def _run():
        session = session_manager.get_or_create(
            "memory_sess_C", pres_factory=create_default_demo_presentation
        )
        runtime = AgentRuntime()
        captured = {}

        class _SpyGraph:
            async def ainvoke(self, state, config=None):
                captured.update(config["configurable"])
                return {"final_summary": "ok", "tool_results": []}

        runtime.graph = _SpyGraph()
        await runtime.run_turn("你好", session.pres, session.history, session=session)
        assert captured["memory"] is session.agent_memory
        assert captured["memory"] is not runtime.memory

    asyncio.run(_run())
