"""Deck-level source-aware critic tests (Batch 2.7 / 2.8)."""

from __future__ import annotations

import asyncio
import json
import re

from backend.design.deck_critic import review_deck
from backend.design.layout_compiler import compile_llm_layout
from backend.design.layout_schema import LLMLayoutPlan
from backend.design.visual_critic import critique_slide

_SLIDE_RE = re.compile(r"Slide '([^']+)'")


def _compile(slide_spec, slide_id):
    payload = {
        "slide_id": slide_id,
        "elements": [
            {
                "element_id": "title",
                "source_block_id": "header_title",
                "element_type": "TEXT",
                "x": 80,
                "y": 40,
                "width": 1120,
                "height": 80,
                "content": "T",
                "font_size": 32,
            },
            {
                "element_id": "body",
                "source_block_id": "b1",
                "element_type": "TEXT",
                "x": 80,
                "y": 200,
                "width": 1120,
                "height": 120,
                "content": "B",
                "font_size": 20,
            },
        ],
    }
    return compile_llm_layout(LLMLayoutPlan.model_validate(payload), slide_spec)


def _score_builder(messages, role="reasoning"):
    text = ""
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text += block.get("text", "")
    match = _SLIDE_RE.search(text)
    slide_id = match.group(1) if match else "slide_1"
    if slide_id == "slide_1":
        return json.dumps(
            {
                "aesthetic_score": 40,
                "defects": [
                    {"element_id": None, "severity": "error", "description": "misaligned"}
                ],
                "recommendations": ["realign"],
            }
        )
    return json.dumps({"aesthetic_score": 100, "defects": [], "recommendations": []})


def test_review_deck_flags_only_low_scoring_slides(design_client_cls, deck_spec_two_slides):
    client = design_client_cls(_score_builder)
    layouts = [
        _compile(deck_spec_two_slides.slides[0], "slide_1"),
        _compile(deck_spec_two_slides.slides[1], "slide_2"),
    ]
    rasters = {"slide_1": "data:image/png;base64,AAAA", "slide_2": "data:image/png;base64,BBBB"}

    review = asyncio.run(
        review_deck(layouts, client, raster_data_uris=rasters)
    )
    assert review.slides_to_revisit == [1]
    assert review.reviewed == 2


def test_visual_critic_receives_source_images(design_client_cls, deck_spec_two_slides):
    captured = {}

    def builder(messages, role="reasoning"):
        captured["messages"] = messages
        return json.dumps({"aesthetic_score": 90, "defects": [], "recommendations": []})

    client = design_client_cls(builder)
    layout = _compile(deck_spec_two_slides.slides[0], "slide_1")
    asyncio.run(
        critique_slide(
            layout,
            llm_client=client,
            raster_data_uri="data:image/png;base64,SLIDE",
            source_image_data_uris=["data:image/webp;base64,SOURCE"],
        )
    )
    content = captured["messages"][1]["content"]
    urls = [b["image_url"]["url"] for b in content if b.get("type") == "image_url"]
    assert "data:image/png;base64,SLIDE" in urls
    assert "data:image/webp;base64,SOURCE" in urls


def test_refine_only_targets_requested_slides(
    design_client_cls, deck_spec_two_slides, presentation_plan_two_slides, art_direction
):
    from tests.design import conftest as design_conftest
    from backend.design.aesthetic_refiner import refine_deck_aesthetics
    from backend.design.layout_designer import DeckDesignResult
    from backend.layout.schema import Canvas, DeckLayoutSpec

    good = _compile(deck_spec_two_slides.slides[0], "slide_1")
    overlap_payload = {
        "slide_id": "slide_2",
        "elements": [
            {
                "element_id": "title",
                "source_block_id": "header_title",
                "element_type": "TEXT",
                "x": 80,
                "y": 80,
                "width": 900,
                "height": 120,
                "content": "T",
                "font_size": 32,
            },
            {
                "element_id": "body",
                "source_block_id": "b1",
                "element_type": "TEXT",
                "x": 100,
                "y": 100,
                "width": 640,
                "height": 200,
                "content": "B",
                "font_size": 20,
            },
        ],
    }
    bad = compile_llm_layout(
        LLMLayoutPlan.model_validate(overlap_payload), deck_spec_two_slides.slides[1]
    )
    base = DeckDesignResult(
        deck_layout=DeckLayoutSpec(title="T", canvas=Canvas(), slides=[good, bad]), plans=[]
    )
    client = design_client_cls(design_conftest.always_valid_builder("layout"))

    refined = asyncio.run(
        refine_deck_aesthetics(
            client,
            base,
            deck_spec_two_slides,
            presentation_plan_two_slides,
            art_direction,
            canvas=Canvas(),
            only_slide_indices=[2],
            include_multimodal=False,
            max_rounds=1,
        )
    )
    assert client.calls  # slide 2 (flagged) was revisited
    assert refined.deck_layout.slides[0] is good  # slide 1 untouched
    assert refined.deck_layout.metadata["aesthetic_rounds"][1] == 0
