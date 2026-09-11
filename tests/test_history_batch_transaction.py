"""PR22 / WS2: transactional history collector.

Regression: atomic batches inferred "new commands" from `undo_stack` depth and
rolled back by truncating to the old depth. When the stack was already at
`max_history`, each `record()` pushed then evicted the oldest command, so:

- a failed batch left its commands on the stack and permanently lost the oldest
  undo entry (depth never exceeded the recorded baseline), and
- a successful batch was never coalesced into a single undo step.

The collector makes batch recording explicit: commands are buffered until the
batch commits, so `max_history` eviction can only happen once, at push time.
"""

import asyncio

from backend.agent.mutation_gateway import MutationGateway
from backend.agent.tools import tools
from backend.history.command import BatchMutationCommand, UpdateElementCommand
from backend.ir.models import PresentationIR, SlideIR, TextContentIR, TextElementIR
from backend.ir.patch import HistoryManager


def _pres() -> PresentationIR:
    pres = PresentationIR(title="History Batch")
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


def _fill_history(history: HistoryManager, count: int = 50) -> None:
    for _ in range(count):
        history.record(
            action="update_element",
            description="fill",
            slide_id="slide_1",
            element_id="a",
            before={"x": 10.0},
            after={"x": 11.0},
        )


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


def test_full_history_atomic_batch_is_one_undo_step():
    pres = _pres()
    history = HistoryManager(pres, max_history=50)
    _fill_history(history, 50)
    assert len(history.undo_stack) == 50

    batch = asyncio.run(MutationGateway.execute_tool_calls(
        [_move("a", 200.0), _move("b", 300.0)],
        pres,
        history,
        bypass_confirmation=True,
        atomic=True,
    ))

    assert batch.success
    assert len(history.undo_stack) == 50, "bounded history must stay at max_history"
    assert isinstance(history.undo_stack[-1], BatchMutationCommand), (
        "atomic batch must collapse into a single composite undo step"
    )

    history.undo(pres)
    assert pres.slides[0].get_element("a").x == 10.0
    assert pres.slides[0].get_element("b").x == 10.0


def test_full_history_failed_batch_keeps_stack_and_restores_state():
    pres = _pres()
    history = HistoryManager(pres, max_history=50)
    _fill_history(history, 50)
    oldest = history.undo_stack[0]
    version_before = pres.version

    batch = asyncio.run(MutationGateway.execute_tool_calls(
        [_move("a", 200.0), _move_missing()],
        pres,
        history,
        bypass_confirmation=True,
        atomic=True,
    ))

    assert not batch.success
    assert batch.rolled_back
    assert len(history.undo_stack) == 50
    assert history.undo_stack[0] is oldest, "failed batch must not evict the oldest undo entry"
    assert pres.slides[0].get_element("a").x == 10.0
    assert pres.version == version_before


def test_tools_execute_batch_uses_collector_at_full_history():
    pres = _pres()
    history = HistoryManager(pres, max_history=50)
    _fill_history(history, 50)
    oldest = history.undo_stack[0]
    version_before = pres.version

    failed = tools.execute_batch(
        [
            {"name": "update_element", "payload": {"slide_id": "slide_1", "element_id": "a", "x": 200.0}},
            {"name": "update_element", "payload": {"slide_id": "slide_1", "element_id": "ghost", "x": 5.0}},
        ],
        pres,
        history,
    )
    assert failed["success"] is False
    assert len(history.undo_stack) == 50
    assert history.undo_stack[0] is oldest
    assert pres.slides[0].get_element("a").x == 10.0
    assert pres.version == version_before

    ok = tools.execute_batch(
        [
            {"name": "update_element", "payload": {"slide_id": "slide_1", "element_id": "a", "x": 200.0}},
            {"name": "update_element", "payload": {"slide_id": "slide_1", "element_id": "b", "x": 300.0}},
        ],
        pres,
        history,
    )
    assert ok["success"] is True
    assert len(history.undo_stack) == 50
    assert isinstance(history.undo_stack[-1], BatchMutationCommand)
    history.undo(pres)
    assert pres.slides[0].get_element("a").x == 10.0
    assert pres.slides[0].get_element("b").x == 10.0


def test_collector_discards_uncommitted_commands():
    pres = _pres()
    history = HistoryManager(pres)
    depth = len(history.undo_stack)

    with history.batch(description="aborted") as hb:
        history.record(
            action="update_element",
            description="batched",
            slide_id="slide_1",
            element_id="a",
            before={"x": 10.0},
            after={"x": 50.0},
        )
        hb.rollback()

    assert len(history.undo_stack) == depth

    with history.batch(description="committed"):
        history.record(
            action="update_element",
            description="batched",
            slide_id="slide_1",
            element_id="a",
            before={"x": 10.0},
            after={"x": 50.0},
        )

    assert len(history.undo_stack) == depth + 1
    assert isinstance(history.undo_stack[-1], UpdateElementCommand)
