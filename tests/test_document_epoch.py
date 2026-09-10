"""Document identity (epoch) tests for pending confirmations.

A pending confirmation is bound to a specific document identity (epoch) and
revision. Wholesale deck replacement - import, PPTSpec generation, or checkpoint
restore - must rotate the epoch and drop stale pending calls so an old blocked
mutation can never act on a different deck that shares a version number.
"""

import asyncio

from backend.agent.graphs.generation import persist_session_node
from backend.agent.mutation_gateway import MutationGateway
from backend.ir.models import PresentationIR, SlideIR, TextElementIR, TextContentIR
from backend.ir.patch import HistoryManager
from backend.session.manager import session_manager
from backend.session.session import PPTSession


def _pres_with_title(title="Epoch Deck"):
    pres = PresentationIR(title=title)
    slide = SlideIR(id="slide_1", slide_num=1)
    slide.add_element(TextElementIR(
        id="title_node", x=80.0, y=50.0, width=700.0, height=50.0,
        text_content=TextContentIR.from_plain_text("Quarterly Review")
    ))
    pres.slides.append(slide)
    pres.active_slide_id = slide.id
    return pres


def _flagged_move_call(call_id="call_epoch"):
    return {
        "name": "update_element",
        "arguments": {"element_id": "title_node", "slide_id": "slide_1", "y": 300.0},
        "id": call_id,
        "_resolution_confidence": 0.6,
        "_needs_confirmation": True,
    }


async def _register_pending(session, pres, history, call_id="call_epoch"):
    await MutationGateway.execute_tool_calls(
        [_flagged_move_call(call_id)], pres, history, session=session, source="agent"
    )
    return session.get_pending_confirmation(call_id)


def test_replace_presentation_rotates_epoch_and_clears_pending():
    async def _run():
        pres = _pres_with_title()
        history = HistoryManager()
        session = PPTSession(session_id="sess_epoch_replace", pres=pres)
        epoch_before = session.document_epoch

        await _register_pending(session, pres, history)
        assert session.get_pending_confirmation("call_epoch") is not None

        replacement = PresentationIR(title="Fresh Import", version=1)
        session.replace_presentation(replacement, checkpoint_description="replaced")

        assert session.document_epoch != epoch_before
        assert session.pres is replacement
        assert session.pending_confirmations == {}

    asyncio.run(_run())


def test_confirm_rejects_pending_when_epoch_differs_even_if_version_matches():
    async def _run():
        pres = _pres_with_title()
        history = HistoryManager()
        session = PPTSession(session_id="sess_epoch_confirm", pres=pres)
        await _register_pending(session, pres, history)

        # Simulate a document swap that bypassed clearing (defensive check).
        session.document_epoch = "different-document-epoch"
        assert pres.version == session.get_pending_confirmation("call_epoch")["expected_revision"]

        from backend.agent.runtime import AgentRuntime
        result = await AgentRuntime().confirm_pending(session, "call_epoch")

        assert result["success"] is False
        assert result["error"] == "confirmation_invalidated"
        assert session.get_pending_confirmation("call_epoch") is None
        assert pres.slides[0].get_element("title_node").y == 50.0

    asyncio.run(_run())


def test_restore_checkpoint_rotates_epoch_and_clears_pending():
    async def _run():
        pres = _pres_with_title()
        history = HistoryManager()
        session = PPTSession(session_id="sess_epoch_checkpoint", pres=pres)
        checkpoint = session.create_checkpoint(description="baseline")
        epoch_before = session.document_epoch

        await _register_pending(session, pres, history)
        assert session.get_pending_confirmation("call_epoch") is not None

        assert session.restore_checkpoint(checkpoint.id) is True
        assert session.document_epoch != epoch_before
        assert session.pending_confirmations == {}

    asyncio.run(_run())


def test_generation_persist_rotates_epoch_and_clears_pending():
    async def _run():
        sid = "sess_epoch_generation"
        session = session_manager.get_or_create(sid)
        pres = session.pres
        history = session.history
        epoch_before = session.document_epoch

        await _register_pending(session, pres, history)
        assert session.get_pending_confirmation("call_epoch") is not None

        generated = PresentationIR(title="Generated Deck")
        await persist_session_node(
            {"session_id": sid, "presentation_ir": generated},
            {"configurable": {}},
        )

        assert session.pres is generated
        assert session.document_epoch != epoch_before
        assert session.pending_confirmations == {}

    asyncio.run(_run())
