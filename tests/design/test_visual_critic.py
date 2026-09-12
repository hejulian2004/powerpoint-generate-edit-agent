"""Visual critic tests (deterministic + optional multimodal, read-only)."""

from __future__ import annotations

import asyncio
import json

from backend.design.layout_compiler import compile_llm_layout
from backend.design.layout_schema import LLMLayoutPlan
from backend.design.visual_critic import (
    critique_deck,
    critique_slide,
    format_critique_feedback,
    format_layout_manifest,
)


def _compile(payload: dict, slide):
    return compile_llm_layout(LLMLayoutPlan.model_validate(payload), slide)


def _valid_payload() -> dict:
    return {
        "slide_id": "slide_1",
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
                "text_color": "#16181D",
            },
        ],
    }


def _overlap_payload() -> dict:
    payload = _valid_payload()
    payload["elements"][1]["x"] = 100
    payload["elements"][1]["y"] = 100
    return payload


def test_manifest_lists_geometry(deck_spec_two_slides):
    layout = _compile(_valid_payload(), deck_spec_two_slides.slides[0])
    manifest = format_layout_manifest(layout)
    assert "title" in manifest
    assert "Rect:" in manifest


def test_critique_valid_layout_no_refinement(deck_spec_two_slides):
    layout = _compile(_valid_payload(), deck_spec_two_slides.slides[0])
    critique = asyncio.run(critique_slide(layout, llm_client=None))
    assert critique.hard_valid
    assert critique.score == 100.0
    assert not critique.needs_refinement
    assert critique.vision_status["mode"] == "rules_only"


def test_critique_flags_overlap(deck_spec_two_slides):
    layout = _compile(_overlap_payload(), deck_spec_two_slides.slides[0])
    critique = asyncio.run(critique_slide(layout, llm_client=None))
    assert not critique.hard_valid
    assert critique.has_error
    assert critique.needs_refinement
    assert critique.defects


def test_critique_manifest_only_uses_reasoning_role(
    design_client_cls, deck_spec_two_slides
):
    client = design_client_cls(
        lambda messages, role="reasoning": json.dumps(
            {"aesthetic_score": 90, "defects": [], "recommendations": []}
        )
    )
    layout = _compile(_valid_payload(), deck_spec_two_slides.slides[0])
    asyncio.run(critique_slide(layout, llm_client=client))
    assert client.roles == ["reasoning"]


def test_critique_source_images_only_use_vision_role(
    design_client_cls, deck_spec_two_slides
):
    client = design_client_cls(
        lambda messages, role="reasoning": json.dumps(
            {"aesthetic_score": 90, "defects": [], "recommendations": []}
        )
    )
    layout = _compile(_valid_payload(), deck_spec_two_slides.slides[0])
    critique = asyncio.run(
        critique_slide(
            layout,
            llm_client=client,
            source_image_data_uris=["data:image/webp;base64,SOURCE"],
        )
    )
    # An image-bearing request must never go out on the reasoning role, even when
    # the slide raster is unavailable.
    assert client.roles == ["vision"]
    assert critique.vision_status["mode"] == "source_only"


def test_critique_multimodal_fuses_score(design_client_cls, deck_spec_two_slides):
    def builder(messages, role="reasoning"):
        return json.dumps(
            {
                "aesthetic_score": 40,
                "defects": [
                    {"element_id": "body", "severity": "error", "description": "tight spacing"}
                ],
                "recommendations": ["increase whitespace"],
            }
        )

    client = design_client_cls(builder)
    layout = _compile(_valid_payload(), deck_spec_two_slides.slides[0])
    critique = asyncio.run(
        critique_slide(
            layout,
            llm_client=client,
            raster_data_uri="data:image/png;base64,AAAA",
        )
    )
    assert client.roles == ["vision"]
    assert critique.vision_status["mode"] == "multimodal"
    assert critique.aesthetics == 70.0  # 0.5 * 100 + 0.5 * 40
    assert critique.recommendations == ["increase whitespace"]
    assert critique.needs_refinement  # fused score below 80


def test_critique_model_failure_degrades(design_client_cls, deck_spec_two_slides):
    def broken(messages, role="reasoning"):
        raise RuntimeError("vision down")

    client = design_client_cls(broken)
    layout = _compile(_valid_payload(), deck_spec_two_slides.slides[0])
    critique = asyncio.run(critique_slide(layout, llm_client=client))
    assert critique.vision_status["mode"] == "rules_only"
    assert not critique.needs_refinement


def test_critique_deck_returns_per_slide(design_client_cls, deck_spec_two_slides):
    layout = _compile(_valid_payload(), deck_spec_two_slides.slides[0])
    critiques = asyncio.run(
        critique_deck([layout], llm_client=None, include_multimodal=False)
    )
    assert len(critiques) == 1
    assert critiques[0].slide_id == layout.slide_id


def test_feedback_directive_mentions_replacement_and_content(deck_spec_two_slides):
    layout = _compile(_overlap_payload(), deck_spec_two_slides.slides[0])
    critique = asyncio.run(critique_slide(layout, llm_client=None))
    feedback = format_critique_feedback(critique)
    assert "HARD DEFECTS" in feedback
    assert "COMPLETE replacement layout" in feedback
    assert "Preserve all text content exactly" in feedback
