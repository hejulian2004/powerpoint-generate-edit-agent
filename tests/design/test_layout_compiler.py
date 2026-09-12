"""Compiler + hard-validation tests for the LLM-native layout path."""

from __future__ import annotations

from backend.design.layout_compiler import (
    compile_llm_deck_layout,
    compile_llm_layout,
    hard_validate_layout,
)
from backend.design.layout_schema import LLMLayoutPlan
from backend.layout.schema import ElementType
from backend.layout.validator import validate_layout


def _valid_payload(slide_id: str = "slide_1") -> dict:
    return {
        "slide_id": slide_id,
        "elements": [
            {
                "element_id": "title",
                "element_type": "TEXT",
                "x": 80,
                "y": 80,
                "width": 900,
                "height": 120,
                "content": "Title",
                "font_size": 40,
                "font_weight": "bold",
                "text_color": "#16181D",
            },
            {
                "element_id": "body",
                "element_type": "TEXT",
                "x": 80,
                "y": 260,
                "width": 640,
                "height": 200,
                "content": "Body text",
                "font_size": 20,
            },
        ],
    }


def _compile(payload: dict, slide_spec):
    plan = LLMLayoutPlan.model_validate(payload)
    return compile_llm_layout(plan, slide_spec)


def test_compile_maps_geometry_and_marks_source(deck_spec_two_slides):
    layout = _compile(_valid_payload(), deck_spec_two_slides.slides[0])
    assert layout.metadata["layout_source"] == "llm"
    assert layout.slide_index == 1
    assert [el.element_id for el in layout.elements] == ["title", "body"]
    assert layout.elements[0].geometry.x == 80
    assert layout.elements[0].style.text.font_weight == "bold"


def test_compile_clamps_corner_radius(deck_spec_two_slides):
    payload = _valid_payload()
    payload["elements"][0]["corner_radius"] = 40
    layout = _compile(payload, deck_spec_two_slides.slides[0])
    assert layout.elements[0].style.corner_radius == 3.0


def test_valid_layout_passes_hard_validation(deck_spec_two_slides):
    layout = _compile(_valid_payload(), deck_spec_two_slides.slides[0])
    report = hard_validate_layout(layout, deck_spec_two_slides.slides[0])
    assert report.is_valid, report.errors


def test_hard_validation_detects_out_of_bounds(deck_spec_two_slides):
    payload = _valid_payload()
    payload["elements"][0]["x"] = 1200
    payload["elements"][0]["width"] = 400
    layout = _compile(payload, deck_spec_two_slides.slides[0])
    report = hard_validate_layout(layout, deck_spec_two_slides.slides[0])
    assert not report.is_valid
    assert any("out of canvas" in e for e in report.errors)


def test_hard_validation_detects_overlap(deck_spec_two_slides):
    payload = _valid_payload()
    payload["elements"][1]["x"] = 100
    payload["elements"][1]["y"] = 100
    layout = _compile(payload, deck_spec_two_slides.slides[0])
    report = hard_validate_layout(layout, deck_spec_two_slides.slides[0])
    assert not report.is_valid
    assert any("Collision" in e for e in report.errors)


def test_hard_validation_detects_unreadable_font(deck_spec_two_slides):
    payload = _valid_payload()
    payload["elements"][1]["font_size"] = 8
    layout = _compile(payload, deck_spec_two_slides.slides[0])
    report = hard_validate_layout(layout, deck_spec_two_slides.slides[0])
    assert not report.is_valid
    assert any("minimum readable" in e for e in report.errors)


def test_hard_validation_detects_unknown_source_block(deck_spec_two_slides):
    payload = _valid_payload()
    payload["elements"][0]["source_block_id"] = "ghost"
    layout = _compile(payload, deck_spec_two_slides.slides[0])
    report = hard_validate_layout(layout, deck_spec_two_slides.slides[0])
    assert not report.is_valid
    assert any("unknown source block" in e for e in report.errors)


def test_hard_validation_detects_corrupted_figure_ratio(deck_spec_two_slides):
    payload = _valid_payload()
    payload["elements"] = [
        {
            "element_id": "fig",
            "element_type": "FIGURE",
            "x": 80,
            "y": 80,
            "width": 1000,
            "height": 10,
            "content": {"source_figure_id": "figure1"},
        }
    ]
    layout = _compile(payload, deck_spec_two_slides.slides[0])
    report = hard_validate_layout(layout, deck_spec_two_slides.slides[0])
    assert not report.is_valid
    assert any("aspect ratio" in e for e in report.errors)


def test_compiled_layout_is_also_base_valid(deck_spec_two_slides):
    layout = _compile(_valid_payload(), deck_spec_two_slides.slides[0])
    assert validate_layout(layout).is_valid


def test_compile_deck_uses_llm_plans(monkeypatch, deck_spec_two_slides):
    from backend.config import settings

    monkeypatch.setattr(settings, "llm_native_layout_enabled", True)
    plans = [
        LLMLayoutPlan.model_validate(_valid_payload("slide_1")),
        LLMLayoutPlan.model_validate(_valid_payload("slide_2")),
    ]
    deck = compile_llm_deck_layout(plans, deck_spec_two_slides)
    assert deck.metadata["layout_source"] == "llm"
    assert deck.metadata["fallback_slide_indices"] == []
    assert all(sl.metadata["layout_source"] == "llm" for sl in deck.slides)


def test_compile_deck_falls_back_for_missing_plan(monkeypatch, deck_spec_two_slides):
    from backend.config import settings

    monkeypatch.setattr(settings, "llm_native_layout_enabled", True)
    plans = [LLMLayoutPlan.model_validate(_valid_payload("slide_1"))]
    deck = compile_llm_deck_layout(plans, deck_spec_two_slides)
    assert deck.metadata["fallback_slide_indices"] == [2]
    assert deck.slides[0].metadata["layout_source"] == "llm"
    assert deck.slides[1].metadata["layout_source"] == "fallback_template"
    assert deck.slides[1].get_elements_by_type(ElementType.TEXT)
