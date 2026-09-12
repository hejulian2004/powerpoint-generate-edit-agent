"""Crossed session-isolation tests for the Phase 1 service aggregate (S2/S3)."""

from __future__ import annotations

import asyncio

from backend.agent.memory import AgentMemory
from backend.ir.models import PresentationIR, SlideIR
from backend.session.factory import SessionFactory
from backend.session.manager import SessionManager


def _deck(title: str) -> PresentationIR:
    pres = PresentationIR(title=title)
    slide = SlideIR(id=f"slide_{title}", slide_num=1, title=title)
    pres.slides.append(slide)
    pres.active_slide_id = slide.id
    return pres


def test_sessions_own_distinct_document_and_services():
    a = SessionFactory.create(_deck("A"), session_id="iso_a")
    b = SessionFactory.create(_deck("B"), session_id="iso_b")

    assert a.pres is not b.pres
    assert a.document is not b.document
    assert a.history_service is not b.history_service
    assert a.checkpoint_service is not b.checkpoint_service
    assert a.memory is not b.memory
    assert a.confirmations is not b.confirmations


def test_replacement_in_a_does_not_touch_b():
    async def _run():
        a = SessionFactory.create(_deck("A"), session_id="iso_rep_a")
        b = SessionFactory.create(_deck("B"), session_id="iso_rep_b")
        b_epoch = b.document_epoch
        b_title = b.pres.title

        result = await a.commit_replacement(
            _deck("A2"),
            expected_epoch=a.document_epoch,
            expected_revision=a.pres.version,
        )
        assert result.committed
        assert a.pres.title == "A2"
        assert b.pres.title == b_title
        assert b.document_epoch == b_epoch

    asyncio.run(_run())


def test_history_is_isolated():
    a = SessionFactory.create(_deck("A"), session_id="iso_hist_a")
    b = SessionFactory.create(_deck("B"), session_id="iso_hist_b")

    a.history_service.record(
        action="update", description="a edit", slide_id="x", element_id="y"
    )
    assert a.history_service.can_undo() is True
    assert b.history_service.can_undo() is False


def test_confirmations_are_isolated():
    a = SessionFactory.create(_deck("A"), session_id="iso_conf_a")
    b = SessionFactory.create(_deck("B"), session_id="iso_conf_b")

    a.register_pending_confirmation(
        call_id="call_1",
        tool="delete_element",
        arguments={"element_id": "e1"},
        confidence=0.2,
        presentation_version=a.pres.version,
    )
    assert a.get_pending_confirmation("call_1") is not None
    assert b.get_pending_confirmation("call_1") is None


def test_checkpoints_are_isolated():
    a = SessionFactory.create(_deck("A"), session_id="iso_cp_a")
    b = SessionFactory.create(_deck("B"), session_id="iso_cp_b")

    a.create_checkpoint(description="a-only")
    labels = [cp.description for cp in b.checkpoints]
    assert "a-only" not in labels


def test_memory_is_isolated():
    a = SessionFactory.create(_deck("A"), session_id="iso_mem_a")
    b = SessionFactory.create(_deck("B"), session_id="iso_mem_b")

    assert a.agent_memory is not b.agent_memory
    a.agent_memory.log_action("a did a thing")
    assert "a did a thing" in a.agent_memory.build_system_context()
    assert "a did a thing" not in b.agent_memory.build_system_context()
    assert a.memory.messages == []
    assert b.memory.messages == []


def test_factory_restore_suppresses_synthetic_baseline():
    pres = _deck("Restored")
    session = SessionFactory.create(pres, session_id="iso_restore", init_baseline=False)
    assert session.checkpoints == []


def test_manager_keeps_sessions_isolated():
    manager = SessionManager()
    a = manager.create_session(pres=_deck("A"), session_id="mgr_a")
    b = manager.create_session(pres=_deck("B"), session_id="mgr_b")
    assert a.pres is not b.pres
    assert manager.get_session("mgr_a") is a
    assert manager.get_session("mgr_b") is b
