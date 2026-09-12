"""UIContext deictic targeting.

"把这个改红" must bind to the requesting client's selected element, not
`last_target_id` or a textual guess. With no valid selection the planner must
fail closed (clarification / empty plan). The live document must never be
targeted by accident and never mutated during planning.
"""

import asyncio

from backend.agent.subagents.executor import ExecutorSubagent
from backend.agent.uicontext import UIContext
from backend.ir.models import (
    GroupElementIR,
    PresentationIR,
    SlideIR,
    TextContentIR,
    TextElementIR,
)
from backend.session.session import PPTSession


def _text_element(el_id, text="Hello"):
    return TextElementIR(
        id=el_id, x=10.0, y=10.0, width=100.0, height=40.0,
        text_content=TextContentIR.from_plain_text(text),
    )


def _pres(active="slide_1"):
    pres = PresentationIR(title="UI", version=3)
    s1 = SlideIR(id="slide_1", slide_num=1)
    s1.add_element(_text_element("el1", "First"))
    s2 = SlideIR(id="slide_2", slide_num=2)
    s2.add_element(_text_element("el2", "Second"))
    pres.slides.extend([s1, s2])
    pres.active_slide_id = active
    return pres


async def _plan(pres, session, query, ui_context):
    return await ExecutorSubagent.plan_task(
        intent="modify_elements",
        user_query=query,
        plan_desc="",
        pres=pres,
        memory=None,
        llm_client=None,
        session=session,
        ui_context=ui_context,
    )


def test_deictic_binds_to_selected_element():
    async def _run():
        pres = _pres(active="slide_1")
        session = PPTSession(session_id="sess_uic_bind", pres=pres)
        plan = await _plan(
            pres, session, "把这个改红",
            {"selected_element_ids": ["el2"], "primary_selected_element_id": "el2",
             "active_slide_id": "slide_2", "ui_context_revision": 7},
        )
        assert len(plan.tool_calls) == 1
        args = plan.tool_calls[0]["arguments"]
        assert args["element_id"] == "el2"
        assert args["fill_color"] == "#EF4444"

    asyncio.run(_run())


def test_deictic_without_selection_is_clarification():
    async def _run():
        pres = _pres(active="slide_1")
        session = PPTSession(session_id="sess_uic_noselect", pres=pres)
        plan = await _plan(
            pres, session, "把这个改红",
            {"selected_element_ids": [], "active_slide_id": "slide_1"},
        )
        # Fail closed: no tool calls means the user is asked, not guessed at.
        assert plan.tool_calls == []

    asyncio.run(_run())


def test_planning_does_not_mutate_live_active_slide():
    async def _run():
        pres = _pres(active="slide_1")
        session = PPTSession(session_id="sess_uic_local", pres=pres)
        await _plan(
            pres, session, "把这个改蓝",
            {"selected_element_ids": ["el2"], "active_slide_id": "slide_2"},
        )
        # Request-local targeting must not write into the live document.
        assert pres.active_slide_id == "slide_1"

    asyncio.run(_run())


def test_uicontext_roundtrip_and_deictic_detection():
    ctx = UIContext.from_any({
        "client_id": "c1",
        "ui_context_revision": 4,
        "selected_element_ids": ["e1", "e2"],
        "primary_selected_element_id": "e1",
    })
    assert ctx.has_selection
    assert ctx.resolution_primary == "e1"
    assert ctx.is_deictic("把这个改红")
    assert not ctx.is_deictic("生成一份关于 AI 的 PPT")
    assert ctx.to_dict()["client_id"] == "c1"


def test_uicontext_invalid_targets_detection():
    pres = _pres()
    assert UIContext(active_slide_id="slide_1", selected_element_ids=["el1"]).is_valid_for(pres)
    assert UIContext(active_slide_id="slide_missing").invalid_targets(pres) == [
        "slide:slide_missing"
    ]
    invalid = UIContext(
        active_slide_id="slide_1",
        selected_element_ids=["el1", "el_missing"],
        selection_scope=["el_gone"],
        editing_element_id="el_edit_gone",
    ).invalid_targets(pres)
    assert "element:el_missing" in invalid
    assert "element:el_gone" in invalid
    assert "element:el_edit_gone" in invalid


def _pres_with_group():
    pres = PresentationIR(title="GroupUI")
    s1 = SlideIR(id="slide_1", slide_num=1)
    group = GroupElementIR(
        id="grp1", x=0.0, y=0.0, width=200.0, height=100.0,
        children=[_text_element("inner_el", "Nested")],
    )
    s1.add_element(group)
    s2 = SlideIR(id="slide_2", slide_num=2)
    s2.add_element(_text_element("other_el", "Other"))
    pres.slides.extend([s1, s2])
    pres.active_slide_id = "slide_1"
    return pres


def test_uicontext_accepts_nested_group_member():
    pres = _pres_with_group()
    # Recursive membership: a group child is a valid target.
    assert UIContext(
        active_slide_id="slide_1", selected_element_ids=["inner_el"]
    ).invalid_targets(pres) == []
    # Deck-wide validation (no active slide) is likewise recursive.
    assert UIContext(selected_element_ids=["inner_el"]).invalid_targets(pres) == []


def test_uicontext_rejects_cross_slide_selection():
    pres = _pres_with_group()
    # `other_el` exists in the deck but NOT on the requested active slide: a
    # cross-slide selection cannot be bound and must fail closed.
    assert UIContext(
        active_slide_id="slide_1", selected_element_ids=["other_el"]
    ).invalid_targets(pres) == ["element:other_el"]
    # Without an active slide the context is deck-wide and accepts either slide.
    assert UIContext(
        selected_element_ids=["other_el", "inner_el"]
    ).invalid_targets(pres) == []


def test_cross_slide_selection_fails_closed_with_zero_tool_calls():
    async def _run():
        pres = _pres_with_group()
        session = PPTSession(session_id="sess_uic_cross", pres=pres)
        plan = await ExecutorSubagent.plan_task(
            intent="modify_elements",
            user_query="把其他页的元素改红",
            plan_desc="",
            pres=pres,
            memory=None,
            llm_client=_StubExecutorLLM(),
            session=session,
            ui_context={
                "active_slide_id": "slide_1",
                "selected_element_ids": ["other_el"],
                "ui_context_revision": 9,
            },
        )
        assert plan.tool_calls == []
        assert "other_el" in plan.summary_message

    asyncio.run(_run())


class _StubExecutorLLM:
    """Live-looking LLM that returns a slide-scoped call WITHOUT a slide id."""

    def __init__(self):
        self.api_key = "sk-live-test"

    async def chat_completion(self, messages, role="reasoning", **kwargs):
        import json as _json
        return {
            "choices": [{
                "message": {
                    "tool_calls": [{
                        "id": "call_llm_1",
                        "function": {
                            "name": "generate_slide_layout",
                            "arguments": _json.dumps({"title": "T", "layout_type": "card_grid"}),
                        },
                    }]
                }
            }]
        }


def test_planned_tool_call_threads_uic_active_slide():
    """The requesting client's active slide is bound onto the concrete tool call."""
    async def _run():
        pres = _pres(active="slide_1")
        session = PPTSession(session_id="sess_uic_thread", pres=pres)
        plan = await ExecutorSubagent.plan_task(
            intent="generate_slide",
            user_query="新增一页时间线",
            plan_desc="",
            pres=pres,
            memory=None,
            llm_client=None,
            session=session,
            ui_context={"active_slide_id": "slide_2", "ui_context_revision": 2},
        )
        assert plan.tool_calls
        call = plan.tool_calls[0]
        assert call["arguments"]["slide_id"] == "slide_2"
        # Planning is request-scoped: the live document is untouched.
        assert pres.active_slide_id == "slide_1"

    asyncio.run(_run())


def test_llm_tool_call_without_slide_id_is_threaded_from_uic():
    """A live-LLM call that omits slide_id must not fall back to the live active slide."""
    async def _run():
        pres = _pres(active="slide_1")
        session = PPTSession(session_id="sess_uic_llm", pres=pres)
        plan = await ExecutorSubagent.plan_task(
            intent="modify_elements",
            user_query="重做这一页排版",
            plan_desc="",
            pres=pres,
            memory=None,
            llm_client=_StubExecutorLLM(),
            session=session,
            ui_context={"active_slide_id": "slide_2", "ui_context_revision": 3},
        )
        assert plan.tool_calls
        assert plan.tool_calls[0]["arguments"]["slide_id"] == "slide_2"

    asyncio.run(_run())


def test_invalid_uic_active_slide_fails_closed():
    """A stale/invalid client active slide makes planning fail closed.

    The plan must be empty (zero tool execution) so a slide-scoped call can never
    silently fall back to the session's live active slide at execution time.
    """
    async def _run():
        pres = _pres(active="slide_1")
        session = PPTSession(session_id="sess_uic_invalid", pres=pres)
        plan = await ExecutorSubagent.plan_task(
            intent="generate_slide",
            user_query="新增一页时间线",
            plan_desc="",
            pres=pres,
            memory=None,
            llm_client=_StubExecutorLLM(),
            session=session,
            ui_context={"active_slide_id": "slide_missing", "ui_context_revision": 5},
        )
        assert plan.tool_calls == []
        assert "slide_missing" in plan.summary_message

    asyncio.run(_run())
