"""Unit and integration test suite for PR3: Visual Eval & Diff Loop."""

import pytest
import asyncio
from backend.ir.models import (
    PresentationIR,
    SlideIR,
    ShapeElementIR,
    TextElementIR,
    FillStyle,
    BorderStyle,
    ElementStyleIR,
    TextContentIR,
    FontIR
)
from backend.eval.layout_diff import (
    BoundingBox,
    LayoutDiffEngine,
    VisualQualityScore,
    calculate_relative_luminance,
    calculate_contrast_ratio,
    compare_slides
)
from backend.eval.visual_critic import VisualCritic
from backend.agent.tools import tools
from backend.agent.graph import build_ppt_agent_graph, PPTAgentState
from backend.ir.patch import HistoryManager


# =====================================================================
# 1. BoundingBox & Geometric Mathematics Tests
# =====================================================================

def test_bounding_box_geometry_and_iou():
    """Verify BoundingBox calculations: area, intersection, IoU, and containment."""
    box_a = BoundingBox(x=100.0, y=100.0, width=200.0, height=200.0)
    box_b = BoundingBox(x=200.0, y=100.0, width=200.0, height=200.0)

    # Intersection is 100 x 200 = 20,000
    inter = box_a.intersection(box_b)
    assert inter is not None
    assert inter.x == 200.0
    assert inter.y == 100.0
    assert inter.width == 100.0
    assert inter.height == 200.0
    assert inter.area == 20000.0

    # IoU = 20000 / (40000 + 40000 - 20000) = 20000 / 60000 = 1/3 ~ 0.333
    iou = box_a.iou(box_b)
    assert abs(iou - 0.3333) < 0.01

    # Overlap ratio relative to box_a
    assert box_a.overlap_ratio_with(box_b) == 0.5

    # Non-overlapping boxes
    box_c = BoundingBox(x=500.0, y=500.0, width=100.0, height=100.0)
    assert not box_a.intersects(box_c)
    assert box_a.iou(box_c) == 0.0

    # Nested containment
    box_container = BoundingBox(x=100.0, y=100.0, width=400.0, height=300.0)
    box_child = BoundingBox(x=120.0, y=120.0, width=100.0, height=50.0)
    assert box_container.contains(box_child)
    assert not box_child.contains(box_container)


# =====================================================================
# 2. WCAG 2.1 Contrast and Relative Luminance Tests
# =====================================================================

def test_wcag_contrast_and_luminance():
    """Verify WCAG 2.1 relative luminance and contrast ratio calculations."""
    # Pure black and pure white
    lum_black = calculate_relative_luminance((0, 0, 0))
    lum_white = calculate_relative_luminance((255, 255, 255))
    assert lum_black == 0.0
    assert lum_white == 1.0

    # Maximum possible contrast is 21.0:1
    assert calculate_contrast_ratio("#FFFFFF", "#000000") == 21.0
    assert calculate_contrast_ratio("#000000", "#FFFFFF") == 21.0

    # Tech Blue (#2563EB) against white (#FFFFFF)
    ratio_blue_white = calculate_contrast_ratio("#FFFFFF", "#2563EB")
    assert ratio_blue_white >= 4.5  # Meets WCAG AA for normal text

    # Low contrast gray on gray (#777777 on #888888)
    ratio_low = calculate_contrast_ratio("#777777", "#888888")
    assert ratio_low < 2.0


# =====================================================================
# 3. Viewport Boundary & Clipping Detection Tests
# =====================================================================

def test_viewport_clipping_detection():
    """Verify that elements extending outside the 1280x720 canvas are flagged."""
    slide = SlideIR(
        id="test_slide_clip",
        slide_num=1,
        width=1280,
        height=720,
        background=FillStyle(type="solid", color="#FFFFFF")
    )

    # Element clipped to the right edge (x=1150 + width=200 = 1350 > 1280)
    elem_clipped = ShapeElementIR(
        id="clipped_box",
        shape_type="roundRect",
        x=1150.0,
        y=200.0,
        width=200.0,
        height=100.0
    )
    slide.add_element(elem_clipped)

    report = LayoutDiffEngine.evaluate_slide(slide)
    assert report.has_critical_defects
    clipping_defects = [d for d in report.defects if d.defect_type == "viewport_clipping"]
    assert len(clipping_defects) == 1
    assert "clipped_box" in clipping_defects[0].element_ids
    assert clipping_defects[0].suggested_fix is not None
    assert clipping_defects[0].suggested_fix["x"] + clipping_defects[0].suggested_fix["width"] <= 1280.0


# =====================================================================
# 4. Collision and Containment Discrimination Tests
# =====================================================================

def test_collision_detection_vs_intentional_containment():
    """Verify accidental collisions are flagged while valid container nesting is allowed."""
    slide = SlideIR(
        id="test_slide_collision",
        slide_num=1,
        width=1280,
        height=720,
        background=FillStyle(type="solid", color="#FFFFFF")
    )

    # 1. Intentional nesting: Container Card with Child Textbox
    card = ShapeElementIR(
        id="container_card",
        shape_type="roundRect",
        x=100.0,
        y=100.0,
        width=300.0,
        height=200.0,
        style=ElementStyleIR(fill=FillStyle(type="solid", color="#F8FAFC"))
    )
    text_inside = TextElementIR(
        id="child_label",
        x=120.0,
        y=120.0,
        width=260.0,
        height=40.0,
        text_content=TextContentIR.from_plain_text("内部文字标签", font=FontIR(size=16.0, color="#0F172A"))
    )
    slide.add_element(card)
    slide.add_element(text_inside)

    report_contained = LayoutDiffEngine.evaluate_slide(slide)
    overlap_defects = [d for d in report_contained.defects if d.defect_type == "collision_overlap"]
    # Container nesting must NOT be flagged as accidental collision
    assert len(overlap_defects) == 0

    # 2. Accidental Collision: Add sibling card that partially collides with container_card
    colliding_card = ShapeElementIR(
        id="colliding_card",
        shape_type="roundRect",
        x=200.0,
        y=150.0,
        width=300.0,
        height=200.0,
        style=ElementStyleIR(fill=FillStyle(type="solid", color="#FFFFFF"))
    )
    slide.add_element(colliding_card)

    report_collided = LayoutDiffEngine.evaluate_slide(slide)
    overlap_defects_2 = [d for d in report_collided.defects if d.defect_type == "collision_overlap"]
    assert len(overlap_defects_2) >= 1
    assert any("colliding_card" in d.element_ids for d in overlap_defects_2)


# =====================================================================
# 5. Low Contrast Detection Tests
# =====================================================================

def test_low_contrast_detection():
    """Verify that text colors with low contrast against backgrounds are caught."""
    slide = SlideIR(
        id="test_slide_contrast",
        slide_num=1,
        width=1280,
        height=720,
        background=FillStyle(type="solid", color="#FFFFFF")
    )

    # Unreadable light gray text on white background
    low_contrast_text = TextElementIR(
        id="hard_to_read_text",
        x=100.0,
        y=100.0,
        width=300.0,
        height=50.0,
        text_content=TextContentIR.from_plain_text(
            "浅灰不可读文本",
            font=FontIR(size=16.0, color="#E2E8F0")
        )
    )
    slide.add_element(low_contrast_text)

    report = LayoutDiffEngine.evaluate_slide(slide)
    contrast_defects = [d for d in report.defects if d.defect_type == "low_contrast"]
    assert len(contrast_defects) >= 1
    assert contrast_defects[0].suggested_fix is not None
    assert "font_color" in contrast_defects[0].suggested_fix


# =====================================================================
# 6. Slide Comparison / Diff Tests
# =====================================================================

def test_slide_diff_and_health_delta():
    """Verify slide comparison correctly tracks added, removed, modified elements and score delta."""
    before = SlideIR(id="s1", slide_num=1, width=1280, height=720)
    card_a = ShapeElementIR(id="ca", x=100.0, y=100.0, width=300.0, height=200.0)
    card_b = ShapeElementIR(id="cb", x=150.0, y=150.0, width=300.0, height=200.0)  # Overlapping
    before.add_element(card_a)
    before.add_element(card_b)

    after = SlideIR(id="s1", slide_num=1, width=1280, height=720)
    card_a_fixed = ShapeElementIR(id="ca", x=100.0, y=100.0, width=280.0, height=200.0)
    card_b_fixed = ShapeElementIR(id="cb", x=420.0, y=100.0, width=280.0, height=200.0)  # Separated
    card_c_new = ShapeElementIR(id="cc", x=740.0, y=100.0, width=280.0, height=200.0)
    after.add_element(card_a_fixed)
    after.add_element(card_b_fixed)
    after.add_element(card_c_new)

    diff = compare_slides(before, after)
    assert diff.added_element_ids == ["cc"]
    assert "cb" in diff.modified_element_ids
    assert diff.score_after > diff.score_before
    assert diff.score_delta > 0
    assert len(diff.resolved_defects) >= 1


# =====================================================================
# 7. Self-Healing Tool Execution Tests
# =====================================================================

def test_auto_fix_layout_tool():
    """Verify tools.execute('auto_fix_layout') repairs layout and elevates score."""
    pres = PresentationIR(title="Self-Healing Deck")
    slide = SlideIR(id="slide_heal", slide_num=1, width=1280, height=720)
    pres.slides = [slide]
    pres.active_slide_id = slide.id

    # Add overlapping cards and low contrast text
    c1 = ShapeElementIR(
        id="card1",
        shape_type="roundRect",
        x=100.0,
        y=150.0,
        width=300.0,
        height=200.0,
        style=ElementStyleIR(fill=FillStyle(type="solid", color="#2563EB"))
    )
    c2 = ShapeElementIR(
        id="card2",
        shape_type="roundRect",
        x=200.0,
        y=180.0,
        width=300.0,
        height=200.0,
        style=ElementStyleIR(fill=FillStyle(type="solid", color="#2563EB"))
    )
    slide.add_element(c1)
    slide.add_element(c2)

    history = HistoryManager()
    res = tools.execute("auto_fix_layout", {"slide_id": slide.id}, pres, history)

    assert res["success"] is True
    assert res["score_after"] > res["score_before"]
    assert len(res["applied_fixes"]) >= 1


# =====================================================================
# 8. LangGraph StateGraph Closed-Loop Auto-Correction Tests
# =====================================================================

def test_langgraph_vision_critique_closed_loop():
    """Verify that LangGraph detects layout defects, routes to auto_correct_node, and cures defects."""
    async def _run():
        graph = build_ppt_agent_graph()

        pres = PresentationIR(title="Closed-Loop Graph Deck")
        slide = SlideIR(id="slide_graph_test", slide_num=1, width=1280, height=720)
        pres.slides = [slide]
        pres.active_slide_id = slide.id

        history = HistoryManager()

        # Create slide elements that clip beyond canvas
        c_clipped = ShapeElementIR(
            id="card_overhang",
            shape_type="roundRect",
            x=1200.0,
            y=200.0,
            width=250.0,
            height=180.0
        )
        slide.add_element(c_clipped)

        events = []
        async def on_event(ev):
            events.append(ev)

        state: PPTAgentState = {
            "user_query": "优化当前页面的排版与布局",
            "messages": [{"role": "user", "content": "优化当前页面的排版与布局"}],
            "iteration": 0,
            "max_iterations": 5,
            "active_slide_id": slide.id,
            "presentation_version": pres.version
        }

        config = {
            "configurable": {
                "pres": pres,
                "history": history,
                "on_event": on_event,
                "memory": None
            }
        }

        final_state = await graph.ainvoke(state, config=config)

        # Verify visual critique ran and auto-corrected
        assert "final_summary" in final_state
        assert final_state.get("visual_review") is not None
        # Verify the element is pulled back within safe viewport bounds
        assert c_clipped.x + c_clipped.width <= 1280.0

    asyncio.run(_run())


# =====================================================================
# 9. Multidimensional Visual Quality Score Tests
# =====================================================================

def test_multidimensional_visual_quality_score_weights():
    """Verify that VisualQualityScore breaks down into geometry 30%, readability 20%, contrast 15%, balance 15%, aesthetics 20%."""
    slide = SlideIR(id="score_slide", slide_num=1, width=1280, height=720)

    # Clean slide: 100 on all dimensions
    clean_report = LayoutDiffEngine.evaluate_slide(slide)
    qs = clean_report.quality_score
    assert qs.geometry == 100.0
    assert qs.readability == 100.0
    assert qs.contrast == 100.0
    assert qs.balance == 100.0
    assert qs.aesthetics == 100.0
    assert qs.total == 100.0
    assert clean_report.score == 100.0

    # Introduce a viewport clipping defect (affects geometry dimension)
    clip_elem = ShapeElementIR(id="clip_e", x=1250.0, y=100.0, width=100.0, height=100.0)
    slide.add_element(clip_elem)

    clip_report = LayoutDiffEngine.evaluate_slide(slide)
    qs_clip = clip_report.quality_score
    assert qs_clip.geometry < 100.0
    assert qs_clip.readability == 100.0
    assert qs_clip.contrast == 100.0
    assert qs_clip.balance == 100.0
    assert qs_clip.aesthetics == 100.0
    # Expected weighted composite: 0.30 * G + 0.20 * 100 + 0.15 * 100 + 0.15 * 100 + 0.20 * 100
    expected_total = round(0.30 * qs_clip.geometry + 0.20 * 100.0 + 0.15 * 100.0 + 0.15 * 100.0 + 0.20 * 100.0, 1)
    assert qs_clip.total == expected_total
    assert clip_report.score == expected_total
    assert "quality_score" in clip_report.to_dict()
    assert "aesthetics" in clip_report.to_dict()["quality_score"]


def test_aesthetic_quality_scoring():
    """Verify that LayoutDiffEngine penalises aesthetic flaws: oversized radius, garish colors, weak hierarchy."""
    # 1. Slide with oversized card radius (violating no-large-rounded-card rule)
    slide_round = SlideIR(id="slide_round", slide_num=1, width=1280, height=720)
    pill_card = ShapeElementIR(
        id="pill_card",
        shape_type="roundRect",
        x=100.0,
        y=100.0,
        width=300.0,
        height=200.0,
        style=ElementStyleIR(fill=FillStyle(type="solid", color="#F8FAFC"), radius=24.0)
    )
    slide_round.add_element(pill_card)
    rep_round = LayoutDiffEngine.evaluate_slide(slide_round)
    assert rep_round.quality_score.aesthetics < 100.0
    assert any(d.defect_type == "oversized_card_radius" for d in rep_round.defects)

    # 2. Slide with garish primary color (neon green)
    slide_garish = SlideIR(id="slide_garish", slide_num=1, width=1280, height=720)
    neon_card = ShapeElementIR(
        id="neon_card",
        x=100.0,
        y=100.0,
        width=200.0,
        height=100.0,
        style=ElementStyleIR(fill=FillStyle(type="solid", color="#00FF00"))
    )
    slide_garish.add_element(neon_card)
    rep_garish = LayoutDiffEngine.evaluate_slide(slide_garish)
    assert rep_garish.quality_score.aesthetics < 100.0
    assert any(d.defect_type == "garish_color" for d in rep_garish.defects)

    # 3. Slide with weak typographic hierarchy (title 16px, body 15px)
    slide_weak = SlideIR(id="slide_weak", slide_num=1, width=1280, height=720)
    t1 = TextElementIR(
        id="t1", x=100, y=100, width=400, height=40,
        text_content=TextContentIR.from_plain_text("标题", font=FontIR(size=16.0, color="#16181D"))
    )
    t2 = TextElementIR(
        id="t2", x=100, y=150, width=400, height=40,
        text_content=TextContentIR.from_plain_text("正文一", font=FontIR(size=15.0, color="#5A6472"))
    )
    t3 = TextElementIR(
        id="t3", x=100, y=200, width=400, height=40,
        text_content=TextContentIR.from_plain_text("正文二", font=FontIR(size=15.0, color="#5A6472"))
    )
    slide_weak.add_element(t1)
    slide_weak.add_element(t2)
    slide_weak.add_element(t3)
    rep_weak = LayoutDiffEngine.evaluate_slide(slide_weak)
    assert any(d.defect_type == "weak_hierarchy" for d in rep_weak.defects)


def test_visual_critic_multimodal_aesthetic_fusion():
    """Verify that VisualCritic parses Vision Model aesthetic score and fuses into quality_score."""
    class MockVisionLLM:
        api_key = "test_key_vision"
        async def chat_completion(self, messages, role="vision", **kwargs):
            return {
                "choices": [{
                    "message": {
                        "content": "排版平衡度好，质感较高。\n【美学评分: 80/100】"
                    }
                }]
            }

    async def _run():
        slide = SlideIR(id="slide_fusion", slide_num=1, width=1280, height=720)
        # Clean slide rule aesthetics = 100.0
        # Vision model gives 80.0
        # Fused aesthetics should be 0.5 * 100 + 0.5 * 80 = 90.0
        review = await VisualCritic.review_slide(
            slide=slide,
            llm_client=MockVisionLLM(),
            include_multimodal=True
        )
        assert review.health_report.quality_score.aesthetics == 90.0
        # Total score should reflect fused aesthetics
        # 0.30*100 + 0.20*100 + 0.15*100 + 0.15*100 + 0.20*90.0 = 98.0
        assert review.health_report.quality_score.total == 98.0
        assert review.health_report.score == 98.0

    asyncio.run(_run())

