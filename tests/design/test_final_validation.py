"""Pre-persist fail-closed hard correctness gate (merge blocker 3)."""

from __future__ import annotations

import asyncio

from backend.agent.graphs.generation import (
    build_generation_graph,
    final_generation_validation_node,
    final_validation_route,
)
from backend.compiler.presentation_ir import compile_layout_to_presentation_ir
from backend.design.layout_compiler import compile_llm_layout
from backend.design.layout_schema import LLMLayoutPlan
from backend.layout.schema import Canvas, DeckLayoutSpec
from tests.design.conftest import valid_layout_payload


def _compile_deck(deck_spec):
    layouts = []
    for slide_spec in deck_spec.slides:
        blocks = [(b.block_id, b.kind) for b in slide_spec.blocks if b.block_id]
        payload = valid_layout_payload(f"slide_{slide_spec.index}", blocks)
        layouts.append(
            compile_llm_layout(LLMLayoutPlan.model_validate(payload), slide_spec)
        )
    return DeckLayoutSpec(title="T", canvas=Canvas(), slides=layouts)


def _run(deck, deck_spec, pres, art_direction):
    return asyncio.run(
        final_generation_validation_node(
            {
                "deck_layout": deck,
                "deck_spec": deck_spec,
                "presentation_ir": pres,
                "deck_art_direction": art_direction,
            },
            {},
        )
    )


def test_valid_deck_passes_and_routes_to_persist(deck_spec_two_slides, art_direction):
    deck = _compile_deck(deck_spec_two_slides)
    pres = compile_layout_to_presentation_ir(deck)
    result = _run(deck, deck_spec_two_slides, pres, art_direction)
    assert result["status"] == "final_validation_passed"
    assert final_validation_route(result) == "persist_session_node"


def test_unbound_block_fails_closed(deck_spec_two_slides, art_direction):
    deck = _compile_deck(deck_spec_two_slides)
    pres = compile_layout_to_presentation_ir(deck)
    # Drop the badge element so its SlideSpec block is no longer rendered.
    deck.slides[1].elements = [
        e for e in deck.slides[1].elements if e.source_block_id != "badge1"
    ]
    result = _run(deck, deck_spec_two_slides, pres, art_direction)
    assert result["status"] == "validation_failed"
    assert "FINAL_GENERATION_VALIDATION_FAILED" in result["error"]
    assert final_validation_route(result) == "__end__"


def test_ir_length_mismatch_fails_closed(deck_spec_two_slides, art_direction):
    deck = _compile_deck(deck_spec_two_slides)
    pres = compile_layout_to_presentation_ir(deck)
    pres.slides = pres.slides[:1]
    result = _run(deck, deck_spec_two_slides, pres, art_direction)
    assert result["status"] == "validation_failed"
    assert "slide count" in result["error"]


def test_graph_has_no_path_to_persist_bypassing_final_gate():
    edges = build_generation_graph().get_graph().edges
    direct = [
        e
        for e in edges
        if e.source != "final_generation_validation_node"
        and e.target == "persist_session_node"
    ]
    assert direct == []
