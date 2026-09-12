"""Free-form layout schema: no template/comp enum, strict JSON round-trip."""

from __future__ import annotations

from backend.design.layout_schema import LayoutElementPlan, LLMLayoutPlan


def _plan_payload() -> dict:
    return {
        "slide_id": "slide_1",
        "design_rationale": "hero figure with a quiet caption",
        "visual_focal_point": "hero",
        "reading_flow": "left to right",
        "elements": [
            {
                "element_id": "hero",
                "source_block_id": "b1",
                "element_type": "FIGURE",
                "x": 60,
                "y": 120,
                "width": 700,
                "height": 460,
                "z_index": 1,
                "content": {"source_figure_id": "figure1"},
            },
            {
                "element_id": "caption",
                "element_type": "TEXT",
                "x": 800,
                "y": 200,
                "width": 380,
                "height": 200,
                "content": "Pipeline overview",
                "font_size": 18,
            },
        ],
    }


def test_no_template_or_layout_type_fields():
    for model in (LLMLayoutPlan, LayoutElementPlan):
        assert "layout_type" not in model.model_fields
        assert "template_name" not in model.model_fields
        assert "composition" not in model.model_fields


def test_plan_helpers():
    plan = LLMLayoutPlan.model_validate(_plan_payload())
    assert plan.element_ids() == ["hero", "caption"]
    assert plan.get_element("hero").element_type == "FIGURE"
    assert plan.get_element("missing") is None


def test_plan_json_roundtrip(tmp_path):
    plan = LLMLayoutPlan.model_validate(_plan_payload())
    path = tmp_path / "plan.json"
    plan.to_json_file(path)
    reloaded = LLMLayoutPlan.from_json_file(path)
    assert reloaded == plan


def test_element_requires_geometry():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        LayoutElementPlan(element_id="x", element_type="TEXT")
