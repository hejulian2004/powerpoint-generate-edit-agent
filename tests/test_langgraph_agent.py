"""Comprehensive unit and integration tests for LangGraph PPT Generation and Modification Agent."""

import pytest
import asyncio
from backend.ir.models import PresentationIR, SlideIR, TextElementIR, ShapeElementIR, TextContentIR, FontIR
from backend.ir.patch import HistoryManager
from backend.agent.tools import tools
from backend.agent.runtime import AgentRuntime
from backend.agent.graph import build_ppt_agent_graph, PPTAgentState
from backend.agent.llm import LLMClient
from backend.session.session import PPTSession


def test_generate_presentation_tool():
    """Verify generate_presentation creates a structured multi-page deck with layouts."""
    pres = PresentationIR(title="Initial Pres")
    history = HistoryManager()

    res = tools.execute(
        "generate_presentation",
        {
            "topic": "生成式 AI 与 Agentic 系统架构",
            "theme": "monochrome_studio",
            "replace": True,
            "slides": [
                {
                    "title": "生成式 AI 与 Agentic 架构",
                    "layout": "title_slide",
                    "subtitle": "企业级智能化基础设施演进路线"
                },
                {
                    "title": "三层核心技术体系",
                    "layout": "card_grid",
                    "subtitle": "中间表示 · 状态机 · 原生引擎",
                    "items": [
                        {"title": "PPT-IR 状态", "description": "标准 1280x720 坐标体系", "badge": "01"},
                        {"title": "LangGraph 闭环", "description": "状态感知与动态工具规划", "badge": "02"},
                        {"title": "OOXML 转换", "description": "无损导入与双向二进制导出", "badge": "03"}
                    ]
                },
                {
                    "title": "系统演进时间线",
                    "layout": "timeline",
                    "items": [
                        {"title": "原型验证", "description": "底层 IR 数据模型与 SVG 渲染"},
                        {"title": "状态编排", "description": "LangGraph 状态图与多模态自省"},
                        {"title": "商业发布", "description": "高可用企业级交付"}
                    ]
                },
                {
                    "title": "核心效能提升指标",
                    "layout": "kpi_metrics",
                    "items": [
                        {"value": "10x", "label": "出稿效率", "subtext": "秒级排版"},
                        {"value": "99.9%", "label": "排版保真", "subtext": "规范对齐"},
                        {"value": "< 200ms", "label": "重绘延迟", "subtext": "极致流畅"}
                    ]
                },
                {
                    "title": "架构选型对比分析",
                    "layout": "comparison",
                    "items": [
                        {"title": "传统纯代码方案", "description": "缺乏中间表示，耦合严重"},
                        {"title": "PPT-Agent-Studio", "description": "PPT-IR 解耦，LangGraph 智能编排"}
                    ]
                }
            ]
        },
        pres,
        history
    )

    assert res["success"] is True
    assert len(pres.slides) == 5
    assert pres.title == "生成式 AI 与 Agentic 系统架构"

    # Slide 1: title_slide
    s1 = pres.slides[0]
    assert s1.title == "生成式 AI 与 Agentic 架构"
    assert len(s1.elements) >= 2

    # Slide 2: card_grid
    s2 = pres.slides[1]
    assert len(s2.elements) >= 4  # title + 3 cards

    # Slide 3: timeline
    s3 = pres.slides[2]
    # title + 3 step cards + 2 arrow connectors = 6 elements
    assert len(s3.elements) >= 5

    # Slide 4: kpi_metrics
    s4 = pres.slides[3]
    assert len(s4.elements) >= 4

    # Slide 5: comparison
    s5 = pres.slides[4]
    assert len(s5.elements) >= 3


def test_generate_slide_layout_archetypes():
    """Verify generate_slide_layout can populate any slide with specific archetype."""
    pres = PresentationIR(title="Slide Layout Test")
    slide = SlideIR(id="s_test", slide_num=1)
    pres.slides.append(slide)
    history = HistoryManager()

    # 1. Timeline layout
    res1 = tools.execute(
        "generate_slide_layout",
        {
            "slide_id": "s_test",
            "layout_type": "timeline",
            "title": "研发三步走战略",
            "items": [
                {"title": "第一步: 基础构架", "description": "打牢底座"},
                {"title": "第二步: 智能增强", "description": "接入 Agent"},
                {"title": "第三步: 生态拓展", "description": "多端协同"}
            ]
        },
        pres,
        history
    )
    assert res1["success"] is True
    assert slide.title == "研发三步走战略"
    assert len(slide.elements) > 3

    # 2. KPI layout (clear_existing = True)
    res2 = tools.execute(
        "generate_slide_layout",
        {
            "slide_id": "s_test",
            "layout_type": "kpi_metrics",
            "title": "季度增长分析",
            "items": [
                {"value": "+158%", "label": "活跃用户增长"},
                {"value": "99.2%", "label": "任务完成率"}
            ]
        },
        pres,
        history
    )
    assert res2["success"] is True
    assert slide.title == "季度增长分析"
    # Editorial header (kicker/title/rule) + per-metric value/label/sub/rule
    kpi_vals = [e for e in slide.elements if e.name and e.name.startswith("Metric Value")]
    assert len(kpi_vals) == 2


def test_batch_add_cards_and_align_elements():
    """Verify batch_add_cards and alignment tools."""
    pres = PresentationIR(title="Cards Test")
    slide = SlideIR(id="s_cards", slide_num=1)
    pres.slides.append(slide)
    history = HistoryManager()

    # Batch add cards
    res = tools.execute(
        "batch_add_cards",
        {
            "slide_id": "s_cards",
            "cards": [
                {"title": "特性一", "description": "描述一"},
                {"title": "特性二", "description": "描述二"},
                {"title": "特性三", "description": "描述三"}
            ],
            "start_y": 200,
            "card_height": 300
        },
        pres,
        history
    )
    assert res["success"] is True
    assert res["added_count"] == 3
    # 3 card panels + 3 accent edge bars
    assert len(slide.elements) == 6

    cards = [e for e in slide.elements if not (e.name and e.name.startswith("Card Edge"))]
    card1, card2, card3 = cards[0], cards[1], cards[2]
    assert card1.x < card2.x < card3.x
    assert card1.y == card2.y == card3.y == 200

    # Align middle
    align_res = tools.execute("align_elements", {"slide_id": "s_cards", "alignment": "middle"}, pres, history)
    assert align_res["success"] is True


def test_format_text_and_duplicate_slide():
    """Verify format_text and duplicate_slide tools."""
    pres = PresentationIR(title="Format Test")
    slide = SlideIR(id="s1", slide_num=1)
    slide.add_element(TextElementIR(
        id="txt1",
        x=100,
        y=100,
        text_content=TextElementIR(x=0, y=0).text_content.from_plain_text("初始标题文本")
    ))
    pres.slides.append(slide)
    history = HistoryManager()

    # Format text
    res = tools.execute(
        "format_text",
        {
            "slide_id": "s1",
            "element_id": "txt1",
            "font_size": 36.0,
            "font_color": "#38BDF8",
            "bold": True,
            "align": "center"
        },
        pres,
        history
    )
    assert res["success"] is True
    elem = slide.get_element("txt1")
    run = elem.text_content.paragraphs[0].runs[0]
    assert run.font.size == 36.0
    assert run.font.color == "#38BDF8"
    assert run.font.bold is True
    assert elem.text_content.paragraphs[0].align == "center"

    # Duplicate slide
    dup_res = tools.execute("duplicate_slide", {"slide_id": "s1"}, pres, history)
    assert dup_res["success"] is True
    assert len(pres.slides) == 2
    assert pres.slides[1].id != pres.slides[0].id
    assert pres.slides[1].slide_num == 2


def test_clear_slide_elements():
    """Verify clear_slide_elements tool."""
    pres = PresentationIR(title="Clear Test")
    slide = SlideIR(id="s1", slide_num=1)
    slide.add_element(TextElementIR(id="title", y=80, text_content=TextElementIR(x=0, y=0).text_content.from_plain_text("标题")))
    slide.add_element(ShapeElementIR(id="card1", y=260))
    slide.add_element(ShapeElementIR(id="card2", y=260))
    pres.slides.append(slide)
    history = HistoryManager()

    # Clear with keep_title=True
    res = tools.execute("clear_slide_elements", {"slide_id": "s1", "keep_title": True}, pres, history)
    assert res["success"] is True
    assert len(slide.elements) == 1
    assert slide.elements[0].id == "title"

    # Clear with keep_title=False
    res2 = tools.execute("clear_slide_elements", {"slide_id": "s1", "keep_title": False}, pres, history)
    assert res2["success"] is True
    assert len(slide.elements) == 0


def test_langgraph_agent_full_turn_generation():
    """Verify full LangGraph agent turn executing multi-slide generation."""
    async def _run():
        pres = PresentationIR(title="Test Deck")
        pres.slides.append(SlideIR(id="init", slide_num=1))
        history = HistoryManager()
        # Whole-document generation is a replacement, which requires a session.
        session = PPTSession(session_id="sess_full_turn_gen", pres=pres)

        runtime = AgentRuntime()
        events = []

        async def on_event(ev):
            events.append(ev)

        result = await runtime.run_turn(
            user_message="请为我生成一份关于企业数字化转型的完整PPT演示文稿",
            pres=pres,
            history=history,
            session=session,
            on_event=on_event
        )

        assert result["intent"] == "generate_presentation"
        assert len(result["tools_executed"]) > 0
        assert len(pres.slides) >= 3
        assert "企业数字化转型" in pres.title or len(pres.slides) > 1

        # Check events emitted
        event_types = [e["type"] for e in events]
        assert "agent_thinking" in event_types
        assert "tool_executing" in event_types
        assert "tool_completed" in event_types
        assert "agent_finished" in event_types

    asyncio.run(_run())


def test_langgraph_agent_full_turn_timeline():
    """Verify full LangGraph agent turn executing timeline slide creation."""
    async def _run():
        pres = PresentationIR(title="Timeline Deck")
        s = SlideIR(id="s1", slide_num=1)
        pres.slides.append(s)
        history = HistoryManager()

        runtime = AgentRuntime()
        result = await runtime.run_turn(
            user_message="为当前幻灯片新增一页项目实施时间线",
            pres=pres,
            history=history
        )

        assert result["intent"] == "generate_slide"
        assert len(result["tools_executed"]) > 0
        assert len(s.elements) > 2

    asyncio.run(_run())


def test_update_element_typography_and_geometry():
    """Verify update_element supports font_family, font_size, bold, italic, align, radius, opacity, and bounds."""
    pres = PresentationIR(title="Typography & Geometry Test")
    slide = SlideIR(id="s_typo", slide_num=1)

    # Add a shape card with text
    card = ShapeElementIR(
        id="card_1",
        shape_type="roundRect",
        x=100.0,
        y=150.0,
        width=300.0,
        height=200.0,
        text_content=TextContentIR.from_plain_text("卡片文本内容", font=FontIR(name="Inter", size=16.0))
    )
    slide.add_element(card)
    pres.slides.append(slide)
    history = HistoryManager()

    # Update geometry and styling via update_element
    res = tools.execute(
        "update_element",
        {
            "slide_id": "s_typo",
            "element_id": "card_1",
            "x": 200.0,
            "y": 250.0,
            "width": 450.0,
            "height": 280.0,
            "radius": 24.0,
            "opacity": 0.95,
            "fill_color": "#12131A",
            "border_color": "#3B82F6",
            "border_width": 2.0,
            "font_family": "Microsoft YaHei",
            "font_size": 24.0,
            "font_color": "#FFFFFF",
            "bold": True,
            "italic": True,
            "align": "center"
        },
        pres,
        history
    )

    assert res["success"] is True
    elem = slide.get_element("card_1")
    assert elem.x == 200.0
    assert elem.y == 250.0
    assert elem.width == 450.0
    assert elem.height == 280.0
    assert elem.style.radius == 24.0
    assert elem.style.opacity == 0.95
    assert elem.style.fill.color == "#12131A"
    assert elem.style.border.color == "#3B82F6"
    assert elem.style.border.width == 2.0

    para = elem.text_content.paragraphs[0]
    assert para.align == "center"
    run = para.runs[0]
    assert run.font.name == "Microsoft YaHei"
    assert run.font.size == 24.0
    assert run.font.color == "#FFFFFF"
    assert run.font.bold is True
    assert run.font.italic is True


def test_langgraph_agent_full_turn_layout_and_theme():
    """Verify full LangGraph agent turn executing theme switch and layout alignment."""
    async def _run():
        pres = PresentationIR(title="Theme Deck")
        s = SlideIR(id="s1", slide_num=1)
        s.add_element(ShapeElementIR(id="c1", x=100, y=200, width=200, height=200))
        s.add_element(ShapeElementIR(id="c2", x=350, y=200, width=200, height=200))
        pres.slides.append(s)
        history = HistoryManager()

        runtime = AgentRuntime()

        # 1. Apply theme
        res_theme = await runtime.run_turn(
            user_message="切换为科技蓝主题风格",
            pres=pres,
            history=history
        )
        assert res_theme["intent"] == "apply_theme"
        assert pres.theme.get("name") == "tech_blue"

        # 2. Optimize layout
        res_layout = await runtime.run_turn(
            user_message="自适应规整排版卡片",
            pres=pres,
            history=history
        )
        assert res_layout["intent"] == "optimize_layout"

    asyncio.run(_run())
