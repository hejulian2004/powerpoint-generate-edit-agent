"""Tests for Session Runtime, Checkpoint Management, and Multi-turn Editing (Phases 5.1 & 5.5)."""

import pytest
import asyncio
from backend.ir.models import (
    PresentationIR, SlideIR, TextElementIR, ShapeElementIR,
    TextContentIR, FontIR
)
from backend.session.session import PPTSession
from backend.session.manager import SessionManager
from backend.agent.runtime import AgentRuntime


def create_test_deck() -> PresentationIR:
    pres = PresentationIR(title="Session Test Presentation")
    slide = SlideIR(
        id="s_intro",
        slide_num=1,
        elements=[
            TextElementIR(
                id="title_node",
                name="Main Title",
                x=120.0,
                y=100.0,
                width=800.0,
                height=60.0,
                text_content=TextContentIR.from_plain_text(
                    "云原生架构演变",
                    font=FontIR(name="Segoe UI", size=36.0, color="#FFFFFF", bold=True)
                )
            ),
            ShapeElementIR(
                id="card_01",
                name="Card 1",
                shape_type="roundRect",
                x=120.0,
                y=220.0,
                width=300.0,
                height=220.0
            )
        ]
    )
    pres.slides = [slide]
    pres.active_slide_id = "s_intro"
    return pres


def test_session_lifecycle_and_checkpoints():
    """Verify PPTSession state, message history, and checkpoint capture / restoration."""
    pres = create_test_deck()
    session = PPTSession(session_id="sess_lifecycle", pres=pres)

    assert session.session_id == "sess_lifecycle"
    assert session.active_slide_id == "s_intro"
    assert len(session.messages) == 0

    # 1. Add message
    msg = session.add_message(role="user", content="把标题改大一点")
    assert len(session.messages) == 1
    assert msg["role"] == "user"

    # 2. Create checkpoint
    cp = session.create_checkpoint(description="Before modification", score=90.0)
    assert cp.id in [c.id for c in session.checkpoints]
    assert cp.score == 90.0

    # 3. Modify presentation
    title_elem = session.pres.slides[0].elements[0]
    title_elem.x = 888.0

    # 4. Restore checkpoint
    success = session.restore_checkpoint(cp.id)
    assert success is True
    assert session.pres.slides[0].elements[0].x == 120.0


def test_session_manager_isolation():
    """Verify SessionManager isolates state between different concurrent sessions."""
    manager = SessionManager()
    s1 = manager.get_or_create("user_alpha", pres_factory=create_test_deck)
    s2 = manager.get_or_create("user_beta", pres_factory=create_test_deck)

    assert s1.session_id != s2.session_id

    # Modify s1 only
    s1.pres.slides[0].elements[0].x = 750.0

    # Verify s2 remains untouched
    assert s2.pres.slides[0].elements[0].x == 120.0

    # Check listing
    sessions = manager.list_sessions()
    assert "user_alpha" in [s["session_id"] for s in sessions]
    assert "user_beta" in [s["session_id"] for s in sessions]


def test_multiturn_contextual_conversation():
    """Verify multi-turn editing continuity: '把标题移动右侧' -> '再往下一点' -> '撤销刚才修改'."""
    async def _run():
        pres = create_test_deck()
        session = PPTSession(session_id="sess_multiturn", pres=pres)
        runtime = AgentRuntime()

        # Turn 1: Move title to right
        res1 = await runtime.run_turn(
            user_message="请把标题移动右侧",
            pres=session.pres,
            history=session.history,
            session=session
        )
        assert res1.get("error") is None
        title_el = session.pres.slides[0].elements[0]
        assert title_el.x == 900.0
        assert session.last_target_id == "title_node"

        # Turn 2: Move further down ("再往下一点")
        orig_y = title_el.y  # 100.0
        res2 = await runtime.run_turn(
            user_message="再往下一点",
            pres=session.pres,
            history=session.history,
            session=session
        )
        assert res2.get("error") is None
        assert title_el.x == 900.0  # Maintained rightward position
        assert title_el.y == orig_y + 50.0  # Relative downward shift
        assert session.last_target_id == "title_node"

        # Turn 3: Natural language Undo ("撤销刚才修改")
        res3 = await runtime.run_turn(
            user_message="撤销刚才修改",
            pres=session.pres,
            history=session.history,
            session=session
        )
        assert res3.get("error") is None
        # Restored to Turn 1 position (y=100.0)
        current_title = session.pres.slides[0].elements[0]
        assert current_title.y == orig_y
        assert current_title.x == 900.0

    asyncio.run(_run())
