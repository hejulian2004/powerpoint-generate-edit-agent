"""Phase 1.2: MutationGateway batch semantics.

Covers:
- One atomic envelope = one undo step (composite command).
- Any failure restores content, version, and history (all-or-nothing).
- Compare-and-swap rejects stale revisions / rotated document epochs with zero
  side effects.
- `MutationEnvelope` / `MutationOperation` round-trip the transport payload.
"""

import asyncio

from backend.agent.mutation_gateway import (
    DOCUMENT_EPOCH_MISMATCH,
    STALE_MUTATION,
    MutationEnvelope,
    MutationOperation,
    MutationGateway,
)
from backend.ir.models import PresentationIR, SlideIR, TextContentIR, TextElementIR
from backend.ir.patch import HistoryManager
from backend.session.session import PPTSession


def _pres() -> PresentationIR:
    pres = PresentationIR(title="Batch")
    slide = SlideIR(id="slide_1", slide_num=1)
    slide.add_element(TextElementIR(
        id="a", x=10.0, y=10.0, width=100.0, height=40.0,
        text_content=TextContentIR.from_plain_text("A"),
    ))
    slide.add_element(TextElementIR(
        id="b", x=10.0, y=100.0, width=100.0, height=40.0,
        text_content=TextContentIR.from_plain_text("B"),
    ))
    pres.slides.append(slide)
    pres.active_slide_id = "slide_1"
    return pres


def _move(element_id: str, x: float) -> dict:
    return {
        "name": "update_element",
        "arguments": {"slide_id": "slide_1", "element_id": element_id, "x": x},
        "id": f"call_{element_id}",
    }


def _move_missing() -> dict:
    return {
        "name": "update_element",
        "arguments": {"slide_id": "slide_1", "element_id": "ghost", "x": 5.0},
        "id": "call_ghost",
    }


def test_atomic_batch_is_one_undo_step():
    async def _run():
        pres = _pres()
        history = HistoryManager(pres)
        batch = await MutationGateway.execute_tool_calls(
            [_move("a", 200.0), _move("b", 300.0)],
            pres,
            history,
            bypass_confirmation=True,
            atomic=True,
        )

        assert batch.success
        assert batch.successful == 2 and batch.failed == 0
        assert batch.rolled_back is False
        assert pres.slides[0].get_element("a").x == 200.0
        assert pres.slides[0].get_element("b").x == 300.0
        assert len(history.undo_stack) == 1, "batch must collapse to a single undo step"

        history.undo(pres)
        assert pres.slides[0].get_element("a").x == 10.0
        assert pres.slides[0].get_element("b").x == 10.0

    asyncio.run(_run())


def test_atomic_batch_rolls_back_content_version_and_history_on_failure():
    async def _run():
        pres = _pres()
        history = HistoryManager(pres)
        version_before = pres.version

        batch = await MutationGateway.execute_tool_calls(
            [_move("a", 200.0), _move_missing()],
            pres,
            history,
            bypass_confirmation=True,
            atomic=True,
        )

        assert batch.error, "failed atomic batch must report an error"
        assert batch.rolled_back is True
        assert pres.slides[0].get_element("a").x == 10.0, "earlier op must be rolled back"
        assert pres.version == version_before
        assert len(history.undo_stack) == 0

    asyncio.run(_run())


def test_expected_revision_mismatch_rejected_without_side_effect():
    async def _run():
        pres = _pres()
        history = HistoryManager(pres)
        batch = await MutationGateway.execute_tool_calls(
            [_move("a", 200.0)],
            pres,
            history,
            bypass_confirmation=True,
            atomic=True,
            expected_revision=pres.version + 1,
        )
        assert batch.error == STALE_MUTATION
        assert pres.slides[0].get_element("a").x == 10.0
        assert len(history.undo_stack) == 0

    asyncio.run(_run())


def test_document_epoch_mismatch_rejected_without_side_effect():
    async def _run():
        pres = _pres()
        history = HistoryManager(pres)
        session = PPTSession(session_id="sess_cas_epoch", pres=pres)
        batch = await MutationGateway.execute_tool_calls(
            [_move("a", 200.0)],
            pres,
            history,
            session=session,
            bypass_confirmation=True,
            atomic=True,
            document_epoch="stale_epoch",
        )
        assert batch.error == DOCUMENT_EPOCH_MISMATCH
        assert pres.slides[0].get_element("a").x == 10.0

    asyncio.run(_run())


def test_envelope_and_operation_round_trip():
    env = MutationEnvelope.from_tool_calls(
        [{"name": "update_element", "arguments": {"x": 1.0}, "id": "c1"}],
        source="user_direct",
        atomic=True,
        expected_revision=3,
        mutation_id="mut_known",
    )
    assert env.atomic is True
    assert env.expected_revision == 3
    assert env.mutation_id == "mut_known"
    assert len(env.operations) == 1
    assert isinstance(env.operations[0], MutationOperation)
    calls = env.to_calls()
    assert calls[0]["name"] == "update_element"
    assert calls[0]["id"] == "c1"
