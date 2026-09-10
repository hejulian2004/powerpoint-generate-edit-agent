"""Phase 1.3: stale execution-plan detection.

The GUI stays editable while the Executor LLM is planning. If the deck changes
(revision bump or document-epoch rotation) after the plan was built, `mutation_node`
must refuse to commit the stale plan and route back to the executor instead.
"""

import asyncio

from backend.agent.graph import mutation_node, should_route_mutation
from backend.ir.models import PresentationIR, SlideIR, TextContentIR, TextElementIR
from backend.ir.patch import HistoryManager
from backend.session.session import PPTSession


def _pres() -> PresentationIR:
    pres = PresentationIR(title="Stale")
    slide = SlideIR(id="slide_1", slide_num=1)
    slide.add_element(TextElementIR(
        id="a", x=10.0, y=10.0, width=100.0, height=40.0,
        text_content=TextContentIR.from_plain_text("A"),
    ))
    pres.slides.append(slide)
    pres.active_slide_id = "slide_1"
    return pres


def _plan() -> list:
    return [{
        "name": "update_element",
        "arguments": {"slide_id": "slide_1", "element_id": "a", "x": 400.0},
        "id": "call_plan",
    }]


def test_mutation_node_replans_when_revision_changed():
    async def _run():
        pres = _pres()
        history = HistoryManager(pres)
        state = {
            "intent": "modify_elements",
            "execution_plan": _plan(),
            "plan_base_revision": pres.version,
            "plan_document_epoch": None,
        }
        # A GUI edit lands while the executor was planning.
        pres.version += 1

        result = await mutation_node(
            state, {"configurable": {"pres": pres, "history": history, "session": None}}
        )

        assert result["stale_plan"] is True
        assert result["execution_plan"] == []
        assert result["stale_replan_count"] == 1
        assert pres.slides[0].get_element("a").x == 10.0, "stale plan must not be committed"

    asyncio.run(_run())


def test_mutation_node_replans_when_epoch_rotated():
    async def _run():
        pres = _pres()
        history = HistoryManager(pres)
        session = PPTSession(session_id="sess_stale_epoch", pres=pres)
        state = {
            "intent": "modify_elements",
            "execution_plan": _plan(),
            "plan_base_revision": pres.version,
            "plan_document_epoch": session.document_epoch,
        }
        session.document_epoch = "rotated_epoch"

        result = await mutation_node(
            state, {"configurable": {"pres": pres, "history": history, "session": session}}
        )

        assert result["stale_plan"] is True
        assert pres.slides[0].get_element("a").x == 10.0

    asyncio.run(_run())


def test_fresh_plan_commits():
    async def _run():
        pres = _pres()
        history = HistoryManager(pres)
        state = {
            "intent": "modify_elements",
            "execution_plan": _plan(),
            "plan_base_revision": pres.version,
            "plan_document_epoch": None,
        }
        result = await mutation_node(
            state, {"configurable": {"pres": pres, "history": history, "session": None}}
        )
        assert result["stale_plan"] is False
        assert pres.slides[0].get_element("a").x == 400.0

    asyncio.run(_run())


def test_should_route_mutation_bounded_replan():
    assert should_route_mutation({"stale_plan": True, "stale_replan_count": 1}) == "executor_node"
    assert should_route_mutation({"stale_plan": True, "stale_replan_count": 2}) == "executor_node"
    assert should_route_mutation({"stale_plan": True, "stale_replan_count": 3}) == "content_critic_node"
    assert should_route_mutation({"stale_plan": False}) == "content_critic_node"
