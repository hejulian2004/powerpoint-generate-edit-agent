"""Theme ownership: PresentationIR derives deck colors from DeckArtDirection."""

from __future__ import annotations

from backend.compiler.presentation_ir import (
    compile_layout_to_presentation_ir,
    theme_from_art_direction,
)
from backend.design.schema import ColorDirection, DeckArtDirection
from backend.ir.models import ShapeElementIR
from backend.layout.schema import (
    Canvas,
    DeckLayoutSpec,
    ElementStyle,
    ElementType,
    LayoutElement,
    LayoutSpec,
    Rect,
)
from backend.slidespec.schema import VisualIntent


def _art_direction() -> DeckArtDirection:
    return DeckArtDirection(
        design_concept="Editorial",
        visual_language="editorial technical",
        typography_strategy="clear hierarchy",
        spacing_strategy="generous margins",
        figure_strategy="framed",
        table_strategy="compact",
        chart_strategy="minimal",
        decoration_strategy="hairline rules",
        color_direction=ColorDirection(
            background_strategy="warm paper",
            surface_strategy="raised surfaces",
            primary_text="#101418",
            secondary_text="#4B5563",
            background_color="#F7F5F0",
            surface_color="#ECE9E2",
            primary_accent="#B45309",
        ),
    )


def test_theme_from_art_direction_maps_deck_colors():
    theme = theme_from_art_direction(_art_direction())
    assert theme["background_color"] == "#F7F5F0"
    assert theme["card_background"] == "#ECE9E2"
    assert theme["primary_color"] == "#B45309"
    assert theme["secondary_color"] == "#101418"
    assert theme["color_scheme"]["lt1"] == "#F7F5F0"
    assert theme["color_scheme"]["lt2"] == "#ECE9E2"


def test_compiler_owns_slide_background_and_surface():
    deck = DeckLayoutSpec(
        title="Theme Test",
        canvas=Canvas(),
        slides=[
                LayoutSpec(
                    slide_id="slide_1",
                    slide_index=1,
                    canvas=Canvas(),
                    visual_intent=VisualIntent.TITLE_HERO,
                    elements=[
                    LayoutElement(
                        element_id="card",
                        element_type=ElementType.CONTAINER,
                        geometry=Rect(x=80, y=80, width=400, height=200),
                        style=ElementStyle(corner_radius=0.0),
                    )
                ],
            )
        ],
    )
    pres = compile_layout_to_presentation_ir(deck, theme_override=theme_from_art_direction(_art_direction()))
    assert pres.slides[0].background.color == "#F7F5F0"
    card = pres.slides[0].elements[0]
    assert isinstance(card, ShapeElementIR)
    assert card.style.fill.color == "#ECE9E2"
    # Explicit 0 radius must be preserved (no `or` default bump).
    assert card.style.radius == 0.0
