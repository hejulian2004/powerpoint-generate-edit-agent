"""Semantic color direction + WCAG contrast validation tests."""

from __future__ import annotations

from backend.design.art_director import default_art_direction
from backend.design.color_validator import (
    validate_color_direction,
    validate_deck_colors,
)
from backend.design.layout_compiler import compile_llm_layout
from backend.design.layout_schema import LLMLayoutPlan


def _compile(payload: dict, slide):
    return compile_llm_layout(LLMLayoutPlan.model_validate(payload), slide)


def _text_payload(color: str, background: str | None = None) -> dict:
    element = {
        "element_id": "body",
        "element_type": "TEXT",
        "x": 80,
        "y": 80,
        "width": 900,
        "height": 120,
        "content": "Hello",
        "font_size": 20,
        "text_color": color,
    }
    if background:
        element["fill_color"] = background
    return {"slide_id": "slide_1", "elements": [element]}


def test_valid_direction_has_no_issues(art_direction):
    assert validate_color_direction(art_direction) == []


def test_invalid_hex_color_is_error():
    direction = default_art_direction()
    direction.color_direction.primary_text = "steelblue"
    issues = validate_color_direction(direction)
    assert any(i.kind == "invalid_color" and i.severity == "error" for i in issues)


def test_duplicate_semantic_binding_is_warning(art_direction):
    art_direction.color_direction.bindings.append(
        type(art_direction.color_direction.bindings[0])(
            semantic_key="ours", color="#000000"
        )
    )
    issues = validate_color_direction(art_direction)
    assert any(i.kind == "semantic_drift" for i in issues)


def test_low_contrast_is_detected(deck_spec_two_slides, art_direction):
    layout = _compile(_text_payload("#EEEEEE"), deck_spec_two_slides.slides[0])
    report = validate_deck_colors(art_direction, [layout])
    assert not report.is_valid
    assert any(i.kind == "low_contrast" and i.severity == "error" for i in report.issues)
    assert report.checked_elements == 1


def test_good_contrast_passes(deck_spec_two_slides, art_direction):
    layout = _compile(_text_payload("#16181D"), deck_spec_two_slides.slides[0])
    report = validate_deck_colors(art_direction, [layout])
    assert report.is_valid
    assert report.min_contrast and report.min_contrast >= 4.5


def test_container_background_is_used(deck_spec_two_slides, art_direction):
    payload = {
        "slide_id": "slide_1",
        "elements": [
            {
                "element_id": "bg",
                "element_type": "CONTAINER",
                "x": 0,
                "y": 0,
                "width": 1280,
                "height": 720,
                "fill_color": "#101010",
            },
            {
                "element_id": "body",
                "element_type": "TEXT",
                "x": 80,
                "y": 80,
                "width": 900,
                "height": 120,
                "content": "Hello",
                "font_size": 20,
                "text_color": "#FFFFFF",
            },
        ],
    }
    layout = _compile(payload, deck_spec_two_slides.slides[0])
    report = validate_deck_colors(art_direction, [layout])
    assert report.is_valid, report.to_dict()


def test_large_text_uses_lower_threshold(deck_spec_two_slides, art_direction):
    payload = _text_payload("#949494")  # mid-gray: fails body 4.5, passes large 3.0
    payload["elements"][0]["font_size"] = 32
    layout = _compile(payload, deck_spec_two_slides.slides[0])
    report = validate_deck_colors(art_direction, [layout])
    assert report.is_valid
