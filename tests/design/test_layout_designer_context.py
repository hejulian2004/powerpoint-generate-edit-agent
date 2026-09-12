"""Per-slide layout design context tests."""

from __future__ import annotations

from backend.design.layout_context import build_slide_layout_context


def test_context_includes_direction_content_and_design_goal(
    deck_spec_two_slides, presentation_plan_two_slides, art_direction
):
    context = build_slide_layout_context(
        deck_spec_two_slides.slides[1],
        presentation_plan_two_slides.slides[1],
        art_direction,
    )
    text = context.text
    assert "Design concept" in text
    assert "Method Overview" in text
    assert "Three-stage pipeline" in text
    assert "figure dominates" in text
    assert context.image_paths == []
    assert context.use_vision is False


def test_context_selects_relevant_page_images(
    deck_spec_two_slides, presentation_plan_two_slides, art_direction, paper_visual_ir_fixture
):
    context = build_slide_layout_context(
        deck_spec_two_slides.slides[1],
        presentation_plan_two_slides.slides[1],
        art_direction,
        paper_visual_ir=paper_visual_ir_fixture,
    )
    assert "page_001.png" in context.image_paths
    assert context.use_vision is True


def test_context_includes_repair_feedback(
    deck_spec_two_slides, presentation_plan_two_slides, art_direction
):
    from backend.design.layout_schema import LLMLayoutPlan

    plan = LLMLayoutPlan.model_validate(
        {"slide_id": "slide_1", "elements": [{"element_id": "a", "element_type": "TEXT", "x": 0, "y": 0, "width": 10, "height": 10, "content": "hi"}]}
    )
    context = build_slide_layout_context(
        deck_spec_two_slides.slides[0],
        presentation_plan_two_slides.slides[0],
        art_direction,
        previous_layout=plan,
        previous_feedback="Element 'a' out of canvas bounds",
    )
    assert "PREVIOUS LAYOUT SUMMARY" in context.text
    assert "Element 'a' out of canvas bounds" in context.text
