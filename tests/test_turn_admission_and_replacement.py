"""Phase 1 (round 4) invariants.

- F1: a whole-document replacement is recognised from the OPERATION, rotates the
  document identity atomically, and rejects malformed replacement envelopes.
- F8: session-backed user mutations require CAS stamps before any write.
- F2: a chat turn is bound to its admission epoch/revision; a stale request is
  rejected before the transcript is touched.
- F6: a pending confirmation is claimed exactly once (no TOCTOU double-execute).
"""

import asyncio

from backend.agent.mutation_gateway import (
    INVALID_REPLACEMENT_ENVELOPE,
    MISSING_MUTATION_STAMP,
    MutationGateway,
)
from backend.agent.runtime import AgentRuntime
from backend.ir.models import PresentationIR, SlideIR, TextContentIR, TextElementIR
from backend.ir.patch import HistoryManager
from backend.session.session import PPTSession


def _pres_with_title():
    pres = PresentationIR(title="Admission")
    slide = SlideIR(id="slide_1", slide_num=1)
    slide.add_element(TextElementIR(
        id="elem_title", x=80.0, y=50.0, width=700.0, height=50.0,
        text_content=TextContentIR.from_plain_text("Quarterly Review"),
    ))
    pres.slides.append(slide)
    pres.active_slide_id = slide.id
    return pres


def _generate_call(*, replace=None, call_id="call_gen"):
    args = {
        "topic": "新主题",
        "slides": [{"title": "第一页", "layout": "card_grid", "items": []}],
    }
    if replace is not None:
        args["replace"] = replace
    return {"name": "generate_presentation", "arguments": args, "id": call_id}


def _move_call(call_id="call_move"):
    return {
        "name": "update_element",
        "arguments": {"slide_id": "slide_1", "element_id": "elem_title", "y": 260.0},
        "id": call_id,
    }


# =====================================================================
# F1 - replacement authority
# =====================================================================

def test_replacement_rotates_epoch_and_resets_lifecycle():
    async def _run():
        pres = _pres_with_title()
        session = PPTSession(session_id="sess_replacement", pres=pres)
        history = session.history
        old_epoch = session.document_epoch

        history.record(
            action="update_element", description="prior edit",
            slide_id="slide_1", element_id="elem_title",
            before={"y": 40.0}, after={"y": 50.0},
        )
        session.register_pending_confirmation(
            call_id="pending_1", tool="update_element",
            arguments={"element_id": "elem_title", "y": 10.0},
            confidence=0.4, presentation_version=pres.version,
        )
        session.remember_mutation_result("mut_old", object(), document_epoch=old_epoch)

        batch = await MutationGateway.execute_tool_calls(
            [_generate_call()],
            pres,
            history,
            session=session,
            bypass_confirmation=True,
            document_epoch=old_epoch,
            expected_revision=pres.version,
        )

        assert batch.error is None
        assert batch.replaced_document is True
        assert session.document_epoch != old_epoch
        assert batch.document_epoch == session.document_epoch
        assert session.pres is pres, "replacement must preserve object identity"
        assert pres.version == 1
        assert batch.version == 1
        assert len(pres.slides) == 1
        assert history.can_undo() is False
        assert session.get_pending_confirmation("pending_1") is None
        assert session.last_target_id is None
        assert session.last_action_type is None
        assert session.get_cached_mutation_result("mut_old", document_epoch=old_epoch) is None

    asyncio.run(_run())


def test_additive_generation_is_not_a_replacement():
    async def _run():
        pres = _pres_with_title()
        session = PPTSession(session_id="sess_additive", pres=pres)
        old_epoch = session.document_epoch
        old_slide_ids = [s.id for s in pres.slides]

        batch = await MutationGateway.execute_tool_calls(
            [_generate_call(replace=False)],
            pres,
            session.history,
            session=session,
            bypass_confirmation=True,
            document_epoch=old_epoch,
            expected_revision=pres.version,
        )

        assert batch.error is None
        assert batch.replaced_document is False
        assert session.document_epoch == old_epoch
        assert old_slide_ids[0] in [s.id for s in pres.slides]
        assert len(pres.slides) == 2

    asyncio.run(_run())


def test_malformed_replacement_envelope_is_rejected_with_zero_writes():
    async def _run():
        pres = _pres_with_title()
        session = PPTSession(session_id="sess_bad_replacement", pres=pres)
        old_epoch = session.document_epoch
        before_pres = pres.model_dump()

        batch = await MutationGateway.execute_tool_calls(
            [_generate_call(), _move_call()],
            pres,
            session.history,
            session=session,
            bypass_confirmation=True,
            document_epoch=old_epoch,
            expected_revision=pres.version,
        )

        assert batch.error == INVALID_REPLACEMENT_ENVELOPE
        assert session.document_epoch == old_epoch
        assert pres.model_dump() == before_pres

    asyncio.run(_run())


# =====================================================================
# F8 - required CAS stamps
# =====================================================================

def test_missing_stamps_fail_closed_before_write():
    async def _run():
        pres = _pres_with_title()
        session = PPTSession(session_id="sess_missing_stamp", pres=pres)
        before = pres.slides[0].get_element("elem_title").y

        batch = await MutationGateway.execute_tool_calls(
            [_move_call()],
            pres,
            session.history,
            session=session,
            bypass_confirmation=True,
            require_stamps=True,
        )

        assert batch.error == MISSING_MUTATION_STAMP
        assert pres.slides[0].get_element("elem_title").y == before

    asyncio.run(_run())


# =====================================================================
# F2 - request admission
# =====================================================================

def _stub_graph_that_must_not_run():
    class _Graph:
        called = False

        async def ainvoke(self, state, config=None):
            _Graph.called = True
            return {"final_summary": "should not happen", "tool_results": []}

    return _Graph()


def test_run_turn_rejects_stale_epoch_without_appending_transcript():
    async def _run():
        pres = _pres_with_title()
        session = PPTSession(session_id="sess_turn_epoch", pres=pres)
        runtime = AgentRuntime()
        runtime.graph = _stub_graph_that_must_not_run()

        result = await runtime.run_turn(
            "修改标题", pres, session.history, session=session,
            request_document_epoch="stale_epoch",
            request_base_revision=pres.version,
        )

        assert result["turn_rejected"] is True
        assert result["error"] == "request_epoch_mismatch"
        assert session.messages == []
        assert type(runtime.graph).called is False

    asyncio.run(_run())


def test_run_turn_rejects_stale_revision_without_appending_transcript():
    async def _run():
        pres = _pres_with_title()
        session = PPTSession(session_id="sess_turn_rev", pres=pres)
        runtime = AgentRuntime()
        runtime.graph = _stub_graph_that_must_not_run()

        result = await runtime.run_turn(
            "修改标题", pres, session.history, session=session,
            request_document_epoch=session.document_epoch,
            request_base_revision=pres.version + 5,
        )

        assert result["turn_rejected"] is True
        assert result["error"] == "request_stale"
        assert session.messages == []

    asyncio.run(_run())


# =====================================================================
# F6 - single-claim confirmation
# =====================================================================

def test_concurrent_confirmation_executes_once():
    async def _run():
        pres = _pres_with_title()
        session = PPTSession(session_id="sess_race_confirm", pres=pres)
        session.register_pending_confirmation(
            call_id="call_race", tool="update_element",
            arguments={"slide_id": "slide_1", "element_id": "elem_title", "y": 260.0},
            confidence=0.4, presentation_version=pres.version,
        )
        runtime = AgentRuntime()

        first, second = await asyncio.gather(
            runtime.confirm_pending(session, "call_race"),
            runtime.confirm_pending(session, "call_race"),
        )

        outcomes = {first.get("success"), second.get("success")}
        assert outcomes == {True, False}
        losers = [r for r in (first, second) if not r.get("success")]
        assert losers[0]["error"] == "unknown_confirmation"
        assert pres.slides[0].get_element("elem_title").y == 260.0

    asyncio.run(_run())
