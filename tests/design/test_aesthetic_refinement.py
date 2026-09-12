"""Bounded aesthetic refinement loop tests (S3 / Phase 8)."""

from __future__ import annotations

import asyncio
import json

from backend.design.aesthetic_refiner import refine_deck_aesthetics, summarize_critiques
from backend.design.layout_compiler import compile_llm_layout, hard_validate_layout
from backend.design.layout_designer import DeckDesignResult
from backend.design.layout_schema import LLMLayoutPlan
from backend.design.visual_critic import critique_slide
from backend.layout.schema import Canvas, DeckLayoutSpec


def _overlap_layout(slide):
    payload = {
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
            },
            {
                "element_id": "body",
                "element_type": "TEXT",
                "x": 100,
                "y": 100,
                "width": 640,
                "height": 200,
                "content": "Body text",
                "font_size": 20,
            },
        ],
    }
    return compile_llm_layout(LLMLayoutPlan.model_validate(payload), slide)


def _base_result(slide) -> DeckDesignResult:
    layout = _overlap_layout(slide)
    deck_layout = DeckLayoutSpec(
        title="Refine Test", canvas=Canvas(), slides=[layout], metadata={"layout_source": "llm"}
    )
    return DeckDesignResult(deck_layout=deck_layout, plans=[])


def test_refine_repairs_flagged_slide(
    design_client_cls, valid_response_builder, deck_spec_two_slides,
    presentation_plan_two_slides, art_direction,
):
    client = design_client_cls(valid_response_builder)
    base = _base_result(deck_spec_two_slides.slides[0])

    refined = asyncio.run(
        refine_deck_aesthetics(
            client,
            base,
            deck_spec_two_slides,
            presentation_plan_two_slides,
            art_direction,
            canvas=Canvas(),
            max_rounds=2,
            include_multimodal=False,
        )
    )

    assert client.calls  # refinement invoked the designer
    assert refined.deck_layout.metadata["aesthetic_rounds"][1] == 1
    assert refined.deck_layout.metadata["critique_scores"][1] == 100.0
    assert hard_validate_layout(
        refined.deck_layout.slides[0], deck_spec_two_slides.slides[0]
    ).is_valid


def test_refine_budget_zero_keeps_layout(
    design_client_cls, valid_response_builder, deck_spec_two_slides,
    presentation_plan_two_slides, art_direction,
):
    client = design_client_cls(valid_response_builder)
    base = _base_result(deck_spec_two_slides.slides[0])

    refined = asyncio.run(
        refine_deck_aesthetics(
            client,
            base,
            deck_spec_two_slides,
            presentation_plan_two_slides,
            art_direction,
            canvas=Canvas(),
            max_rounds=0,
            include_multimodal=False,
        )
    )
    assert refined.deck_layout.metadata["aesthetic_rounds"][1] == 0
    assert client.calls == []
    assert refined.deck_layout.slides[0] is base.deck_layout.slides[0]


def test_refine_without_client_is_noop(
    deck_spec_two_slides, presentation_plan_two_slides, art_direction
):
    base = _base_result(deck_spec_two_slides.slides[0])
    refined = asyncio.run(
        refine_deck_aesthetics(
            None,
            base,
            deck_spec_two_slides,
            presentation_plan_two_slides,
            art_direction,
            canvas=Canvas(),
            include_multimodal=False,
        )
    )
    assert refined.deck_layout.metadata["aesthetic_rounds"][1] == 0


def test_summarize_critiques(deck_spec_two_slides):
    layout = _overlap_layout(deck_spec_two_slides.slides[0])
    critique = asyncio.run(critique_slide(layout, llm_client=None))
    summary = summarize_critiques([critique])
    assert summary["slides"] == 1
    assert summary["flagged"] == 1
    assert summary["min_score"] == summary["mean_score"]


def test_min_aesthetic_gain_constant():
    from backend.design.aesthetic_refiner import MIN_AESTHETIC_GAIN

    assert MIN_AESTHETIC_GAIN == 2.0


def test_low_contrast_candidate_is_rejected(
    design_client_cls, deck_spec_two_slides, presentation_plan_two_slides, art_direction
):
    from tests.design import conftest as design_conftest

    def low_contrast_builder(messages, role="reasoning"):
        payload = design_conftest.valid_layout_payload(
            design_conftest._slide_id_from_messages(messages),
            design_conftest.blocks_from_messages(messages),
        )
        for element in payload["elements"]:
            if element.get("element_type") == "TEXT":
                element["text_color"] = "#F7F7F7"
        return json.dumps(payload)

    client = design_client_cls(low_contrast_builder)
    base = _base_result(deck_spec_two_slides.slides[0])

    refined = asyncio.run(
        refine_deck_aesthetics(
            client,
            base,
            deck_spec_two_slides,
            presentation_plan_two_slides,
            art_direction,
            canvas=Canvas(),
            max_rounds=2,
            include_multimodal=False,
        )
    )

    # The contrast-invalid candidate must not be accepted.
    assert client.calls  # the designer was invoked
    assert refined.deck_layout.slides[0] is base.deck_layout.slides[0]
