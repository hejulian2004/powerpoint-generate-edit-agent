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
from backend.layout.engine import generate_layout
from backend.layout.schema import Canvas, DeckLayoutSpec
from backend.presentation.schema import SlideType
from backend.slidespec.schema import (
    BlockRole,
    DeckSpec,
    FigureBlock,
    SlideSpec,
    TableBlock,
    TextBlock,
    VisualIntent,
)
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


def _legacy_deck(deck_spec):
    layouts = []
    for slide_spec in deck_spec.slides:
        layout = generate_layout(slide_spec, validate=True)
        layout.metadata["layout_source"] = "fallback_template"
        layouts.append(layout)
    return DeckLayoutSpec(title="T", canvas=Canvas(), slides=layouts)


def _visual_asset_deck():
    return DeckSpec(
        title="Visuals",
        profile="research_15min",
        slides=[
            SlideSpec(
                index=1,
                slide_type=SlideType.METHOD_DETAIL,
                visual_intent=VisualIntent.PIPELINE_ARCHITECTURE,
                title="Pipeline",
                blocks=[
                    TextBlock(block_id="t1", role=BlockRole.LEAD_SUMMARY, content="Stage 1"),
                    FigureBlock(
                        block_id="fig1",
                        source_figure_id="figure1",
                        caption="First figure",
                    ),
                    FigureBlock(
                        block_id="fig2",
                        source_figure_id="figure2",
                        caption="Second figure",
                    ),
                    TableBlock(
                        block_id="tab1",
                        source_table_id="table1",
                        caption="Results table",
                    ),
                ],
            )
        ],
    )


def test_missing_deck_spec_fails_closed(deck_spec_two_slides, art_direction):
    deck = _compile_deck(deck_spec_two_slides)
    pres = compile_layout_to_presentation_ir(deck)
    result = _run(deck, None, pres, art_direction)
    assert result["status"] == "validation_failed"
    assert "deck_spec is missing" in result["error"]
    assert final_validation_route(result) == "__end__"


def test_legacy_fallback_renders_all_visual_assets():
    deck_spec = _visual_asset_deck()
    deck = _legacy_deck(deck_spec)
    pres = compile_layout_to_presentation_ir(deck)
    # Every figure/table block is compiled (resolved asset or explicit placeholder).
    refs = {getattr(el, "source_ref", None) for slide in pres.slides for el in slide.elements}
    assert {"fig1", "fig2", "tab1"} <= refs
    result = _run(deck, deck_spec, pres, None)
    assert result["status"] == "final_validation_passed"
    assert final_validation_route(result) == "persist_session_node"


def test_missing_visual_asset_element_fails_closed():
    deck_spec = _visual_asset_deck()
    deck = _legacy_deck(deck_spec)
    # Simulate a fallback that silently drops the second figure.
    deck.slides[0].elements = [
        e for e in deck.slides[0].elements if e.source_block_id != "fig2"
    ]
    pres = compile_layout_to_presentation_ir(deck)
    result = _run(deck, deck_spec, pres, None)
    assert result["status"] == "validation_failed"
    assert "figure block 'fig2' is not compiled" in result["error"]
    assert final_validation_route(result) == "__end__"


def test_table_placeholder_metadata_contract():
    from backend.ir.models import ShapeElementIR

    deck_spec = _visual_asset_deck()
    deck = _legacy_deck(deck_spec)
    pres = compile_layout_to_presentation_ir(deck)
    table_el = next(
        el
        for slide in pres.slides
        for el in slide.elements
        if getattr(el, "source_ref", None) == "tab1"
    )
    assert isinstance(table_el, ShapeElementIR)
    assert table_el.metadata["asset_status"] == "placeholder"
    assert table_el.metadata["is_table_placeholder"] is True
    assert table_el.metadata["source_table_id"] == "table1"


def test_table_source_id_mismatch_fails_closed():
    deck_spec = _visual_asset_deck()
    deck = _legacy_deck(deck_spec)
    for element in deck.slides[0].elements:
        if element.source_block_id == "tab1":
            element.content["source_table_id"] = "wrong_table"
    pres = compile_layout_to_presentation_ir(deck)
    result = _run(deck, deck_spec, pres, None)
    assert result["status"] == "validation_failed"
    assert "source_table_id mismatch" in result["error"]

