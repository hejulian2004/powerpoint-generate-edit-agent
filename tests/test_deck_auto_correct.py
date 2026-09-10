"""Deck-level auto-correction: every failed slide must be remediated, not just one."""

import asyncio

from backend.agent.graph import auto_correct_node
from backend.agent.subagents.visual_critic import VisualCriticSubagent
from backend.ir.models import FillStyle, PresentationIR, ShapeElementIR, SlideIR
from backend.ir.patch import HistoryManager


def _clipped_slide(index: int) -> SlideIR:
    slide = SlideIR(
        id=f"slide_{index}",
        slide_num=index,
        title=f"Slide {index}",
        width=1280,
        height=720,
        background=FillStyle(type="solid", color="#FFFFFF"),
    )
    slide.add_element(
        ShapeElementIR(
            id=f"clipped_{index}",
            shape_type="roundRect",
            x=1150.0,
            y=200.0,
            width=300.0,
            height=120.0,
        )
    )
    return slide


def test_auto_correct_repairs_all_failed_slides():
    async def _run():
        pres = PresentationIR(
            id="pres_deck_fix",
            title="Deck Fix",
            slides=[_clipped_slide(1), _clipped_slide(2)],
            active_slide_id="slide_1",
        )
        history = HistoryManager(pres)

        reviews = {}
        for slide in pres.slides:
            review = await VisualCriticSubagent.audit_slide(
                slide=slide, llm_client=None, include_multimodal=False
            )
            review_dict = review.to_dict()
            assert review_dict["needs_auto_correction"] is True, "fixture must be defective"
            reviews[slide.id] = review_dict

        state = {
            "visual_review": {
                "slide_id": "slide_1",
                "slides": reviews,
                "reviewed_slide_ids": list(reviews),
            }
        }
        events = []

        async def on_event(event):
            events.append(event)

        result = await auto_correct_node(
            state,
            {"configurable": {"pres": pres, "history": history, "session": None, "on_event": on_event}},
        )

        assert result["correction_count"] == 1
        assert len(result["tool_results"]) >= 2
        assert all(r.get("auto_correct") for r in result["tool_results"])

        # Both slides must be back inside the canvas.
        for slide in pres.slides:
            element = slide.get_element(f"clipped_{slide.slide_num}")
            assert element.x + element.width <= 1280.5
            assert element.y + element.height <= 720.5

        # Remediation commands were recorded for each failed slide.
        recorded_slides = {cmd.slide_id for cmd in history.undo_stack}
        assert {"slide_1", "slide_2"} <= recorded_slides

        diagnosed = [e for e in events if e.get("type") == "visual_remediation"]
        assert diagnosed or events

    asyncio.run(_run())


def test_auto_correct_skips_healthy_slides():
    async def _run():
        healthy = SlideIR(
            id="slide_ok",
            slide_num=1,
            width=1280,
            height=720,
            background=FillStyle(type="solid", color="#FFFFFF"),
        )
        healthy.add_element(
            ShapeElementIR(
                id="card_ok",
                shape_type="roundRect",
                x=200.0,
                y=200.0,
                width=400.0,
                height=240.0,
            )
        )
        pres = PresentationIR(id="pres_ok", title="Deck", slides=[healthy], active_slide_id="slide_ok")
        history = HistoryManager(pres)

        review = await VisualCriticSubagent.audit_slide(
            slide=healthy, llm_client=None, include_multimodal=False
        )
        state = {
            "visual_review": {
                "slide_id": "slide_ok",
                "slides": {"slide_ok": review.to_dict()},
                "reviewed_slide_ids": ["slide_ok"],
            }
        }
        result = await auto_correct_node(
            state, {"configurable": {"pres": pres, "history": history, "session": None}}
        )

        assert result["tool_results"] == []
        assert len(history.undo_stack) == 0

    asyncio.run(_run())
