"""Tests for Session Concurrency Safety and Mutation Lock Serialization (PR5.1 Hardening)."""

import asyncio
import time
import pytest
from backend.ir.models import (
    PresentationIR, SlideIR, TextElementIR, TextContentIR, FontIR
)
from backend.session.session import PPTSession
from backend.session.manager import SessionManager
from backend.agent.tools import tools


def create_deck(title: str = "Concurrency Deck") -> PresentationIR:
    pres = PresentationIR(title=title)
    slide = SlideIR(
        id="s_conc",
        slide_num=1,
        elements=[
            TextElementIR(
                id="counter_elem",
                name="Counter",
                x=100.0,
                y=100.0,
                width=400.0,
                height=50.0,
                text_content=TextContentIR.from_plain_text("Count: 0")
            )
        ]
    )
    pres.slides = [slide]
    pres.active_slide_id = "s_conc"
    return pres


def test_session_mutation_lock_serializes_updates():
    """Verify PPTSession.mutation_lock safely serializes concurrent mutate calls."""
    async def _run():
        pres = create_deck()
        session = PPTSession(session_id="sess_concurrent_1", pres=pres)

        execution_order = []

        async def worker(worker_id: int, delay: float):
            async with session.mutation_lock:
                execution_order.append(f"start_{worker_id}")
                # Simulate non-trivial mutation work
                await asyncio.sleep(delay)
                # Apply tool update
                elem = session.pres.slides[0].elements[0]
                tools.execute(
                    "update_element",
                    {"slide_id": "s_conc", "element_id": "counter_elem", "x": elem.x + 10.0},
                    session.pres,
                    session.history
                )
                execution_order.append(f"end_{worker_id}")

        # Launch 5 concurrent workers
        tasks = [
            worker(1, 0.05),
            worker(2, 0.02),
            worker(3, 0.04),
            worker(4, 0.01),
            worker(5, 0.03)
        ]
        await asyncio.gather(*tasks)

        # Verify all 5 mutations executed cleanly
        assert session.pres.slides[0].elements[0].x == 150.0  # 100 + 5 * 10
        assert len(session.history.undo_stack) == 5

        # Verify execution was strictly serialized (no start before previous end)
        for i in range(0, len(execution_order), 2):
            start_tag = execution_order[i]
            end_tag = execution_order[i + 1]
            worker_id = start_tag.split("_")[1]
            assert start_tag == f"start_{worker_id}"
            assert end_tag == f"end_{worker_id}"

    asyncio.run(_run())


def test_independent_sessions_do_not_block_each_other():
    """Verify that locks are per-session: session A does not block session B."""
    async def _run():
        mgr = SessionManager()
        s1 = mgr.get_or_create("sess_a", pres_factory=lambda: create_deck("Deck A"))
        s2 = mgr.get_or_create("sess_b", pres_factory=lambda: create_deck("Deck B"))

        timestamps = {}

        async def worker_a():
            async with s1.mutation_lock:
                timestamps["s1_start"] = time.perf_counter()
                await asyncio.sleep(0.08)
                timestamps["s1_end"] = time.perf_counter()

        async def worker_b():
            # Should not wait for s1 to finish
            await asyncio.sleep(0.01)
            async with s2.mutation_lock:
                timestamps["s2_start"] = time.perf_counter()
                await asyncio.sleep(0.02)
                timestamps["s2_end"] = time.perf_counter()

        await asyncio.gather(worker_a(), worker_b())

        # s2 must start and finish BEFORE s1 finishes
        assert timestamps["s2_start"] < timestamps["s1_end"]
        assert timestamps["s2_end"] < timestamps["s1_end"]

    asyncio.run(_run())


def test_checkpoint_restore_clears_undo_history():
    """Verify restoring a checkpoint clears undo/redo stack to prevent invalid delta application."""
    pres = create_deck()
    session = PPTSession(session_id="sess_cp_clean", pres=pres)

    # Initial checkpoint
    cp = session.create_checkpoint(description="Baseline")

    # Add mutations
    tools.execute(
        "update_element",
        {"slide_id": "s_conc", "element_id": "counter_elem", "x": 999.0},
        session.pres,
        session.history
    )
    assert session.history.can_undo() is True
    assert len(session.history.undo_stack) == 1

    # Restore with clear_history=True (default)
    success = session._restore_checkpoint_unchecked(cp.id)
    assert success is True
    assert session.pres.slides[0].elements[0].x == 100.0
    # Stack must be cleanly emptied
    assert session.history.can_undo() is False
    assert session.history.can_redo() is False
    assert len(session.history.undo_stack) == 0
    assert len(session.history.redo_stack) == 0
