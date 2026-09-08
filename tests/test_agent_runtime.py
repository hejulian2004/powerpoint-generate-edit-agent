"""Tests for Agent tools, runtime, and memory."""

import pytest
import asyncio
from backend.ir.models import PresentationIR, SlideIR
from backend.ir.patch import HistoryManager
from backend.agent.tools import tools
from backend.agent.runtime import AgentRuntime
from backend.agent.llm import LLMClient


def test_tool_create_and_delete_slide():
    pres = PresentationIR(title="Tool Test Pres")
    history = HistoryManager()
    
    # 1. Create slide
    res = tools.execute("create_slide", {"title": "Architecture Overview", "background_color": "#0F172A"}, pres, history)
    assert res["success"] is True
    assert len(pres.slides) == 1
    assert pres.slides[0].title == "Architecture Overview"
    assert pres.slides[0].background.color == "#0F172A"

    # 2. Add second slide
    res2 = tools.execute("create_slide", {"title": "Roadmap"}, pres, history)
    assert res2["success"] is True
    assert len(pres.slides) == 2

    # 3. Delete slide
    res3 = tools.execute("delete_slide", {"slide_id_or_num": "2"}, pres, history)
    assert res3["success"] is True
    assert len(pres.slides) == 1


def test_tool_add_and_update_shape():
    pres = PresentationIR(title="Shape Test Pres")
    slide = SlideIR(id="s1", slide_num=1)
    pres.slides.append(slide)
    history = HistoryManager()

    # 1. Add shape
    res = tools.execute(
        "add_shape",
        {
            "slide_id": "s1",
            "shape_type": "roundRect",
            "x": 100,
            "y": 150,
            "width": 250,
            "height": 140,
            "fill_color": "#3B82F6",
            "text": "Core Engine"
        },
        pres,
        history
    )
    assert res["success"] is True
    elem_id = res["element_id"]
    assert len(slide.elements) == 1
    assert slide.elements[0].id == elem_id

    # 2. Update shape
    up_res = tools.execute(
        "update_element",
        {
            "slide_id": "s1",
            "element_id": elem_id,
            "x": 120,
            "fill_color": "#10B981",
            "text": "Updated Engine"
        },
        pres,
        history
    )
    assert up_res["success"] is True
    assert slide.elements[0].x == 120
    assert slide.elements[0].style.fill.color == "#10B981"
    assert slide.elements[0].text_content.plain_text == "Updated Engine"

    # 3. Undo update
    history.undo(pres)
    assert slide.elements[0].x == 100
    assert slide.elements[0].style.fill.color == "#3B82F6"


def test_agent_runtime_turn():
    async def _inner():
        pres = PresentationIR(title="Agent Test Pres")
        pres.slides.append(SlideIR(id="s1", slide_num=1, title="Intro"))
        history = HistoryManager()

        # Mock client will trigger add_text / add_shape based on prompt keywords
        client = LLMClient(api_key="mock_key")
        runtime = AgentRuntime(llm_client=client)

        events = []
        async def on_event(ev):
            events.append(ev)

        result = await runtime.run_turn(
            user_message="请为我创建标题幻灯片",
            pres=pres,
            history=history,
            on_event=on_event
        )

        assert len(result["tools_executed"]) > 0
        assert len(pres.slides[0].elements) > 0
        assert len(events) > 0

    asyncio.run(_inner())

