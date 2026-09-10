"""Phase 1.1: auto_correct_node must serialize remediation under the session lock.

Regression: the old guard `elif lock is not None and not lock.locked()` skipped the
lock entirely whenever another mutation was in flight, letting remediation race a
concurrent GUI edit. Layout auto-correction is a runtime mutation and must wait for
the single-writer lock.
"""

import asyncio

from backend.agent.graph import auto_correct_node
from backend.agent.subagents.visual_critic import VisualCriticSubagent
from backend.ir.models import FillStyle, PresentationIR, ShapeElementIR, SlideIR
from backend.ir.patch import HistoryManager
from backend.session.session import PPTSession


def _clipped_slide() -> SlideIR:
    slide = SlideIR(
        id="slide_1",
        slide_num=1,
        title="Clipped",
        width=1280,
        height=720,
        background=FillStyle(type="solid", color="#FFFFFF"),
    )
    slide.add_element(
        ShapeElementIR(
            id="clipped_1",
            shape_type="roundRect",
            x=1150.0,
            y=200.0,
            width=300.0,
            height=120.0,
        )
    )
    return slide


def test_auto_correct_waits_for_session_mutation_lock():
    async def _run():
        pres = PresentationIR(
            id="pres_ac_lock",
            title="Lock",
            slides=[_clipped_slide()],
            active_slide_id="slide_1",
        )
        history = HistoryManager(pres)
        session = PPTSession(session_id="sess_ac_lock", pres=pres)

        review = await VisualCriticSubagent.audit_slide(
            slide=pres.slides[0], llm_client=None, include_multimodal=False
        )
        assert review.to_dict()["needs_auto_correction"] is True, "fixture must be defective"

        state = {
            "visual_review": {
                "slide_id": "slide_1",
                "slides": {"slide_1": review.to_dict()},
            }
        }
        task = None
        async with session.mutation_lock:
            task = asyncio.create_task(
                auto_correct_node(
                    state,
                    {"configurable": {"pres": pres, "history": history, "session": session}},
                )
            )
            await asyncio.sleep(0.05)
            element = pres.slides[0].get_element("clipped_1")
            assert element.x + element.width > 1280.5, (
                "auto-correct must not mutate while the session lock is held"
            )
            assert not task.done(), "auto-correct must wait for the lock, not run unlocked"

        await asyncio.wait_for(task, timeout=5)
        element = pres.slides[0].get_element("clipped_1")
        assert element.x + element.width <= 1280.5

    asyncio.run(_run())
