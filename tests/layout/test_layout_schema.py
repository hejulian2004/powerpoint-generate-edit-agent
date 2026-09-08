"""Unit Tests for LayoutSpec Schema & Geometric Primitives (PR10)."""

import json
from pathlib import Path

from backend.layout.schema import (
    Canvas,
    DeckLayoutSpec,
    ElementStyle,
    ElementType,
    LayoutConstraint,
    LayoutElement,
    LayoutSpec,
    Rect,
    TextStyle,
)
from backend.slidespec.schema import BlockRole, VisualIntent


def test_canvas_defaults():
    canvas = Canvas()
    assert canvas.width == 1280.0
    assert canvas.height == 720.0


def test_rect_geometry_and_operations():
    r1 = Rect(x=10.0, y=20.0, width=100.0, height=50.0)
    assert r1.right == 110.0
    assert r1.bottom == 70.0
    assert r1.center_x == 60.0
    assert r1.center_y == 45.0
    assert r1.aspect_ratio == 2.0

    # Contained rect
    r2 = Rect(x=20.0, y=25.0, width=50.0, height=20.0)
    assert r1.contains(r2)
    assert not r2.contains(r1)
    assert r1.intersects(r2)

    # Disjoint rect
    r3 = Rect(x=200.0, y=200.0, width=50.0, height=50.0)
    assert not r1.intersects(r3)
    assert r1.intersection(r3) is None

    # Overlapping rect
    r4 = Rect(x=60.0, y=40.0, width=100.0, height=80.0)
    assert r1.intersects(r4)
    inter = r1.intersection(r4)
    assert inter is not None
    assert inter.x == 60.0
    assert inter.y == 40.0
    assert inter.width == 50.0
    assert inter.height == 30.0


def test_layout_spec_elements_lookup():
    geo = Rect(x=50.0, y=50.0, width=400.0, height=100.0)
    el1 = LayoutElement(
        element_id="el_1",
        element_type=ElementType.TEXT,
        role=BlockRole.HEADING,
        geometry=geo,
        content="Title Sample",
    )
    el2 = LayoutElement(
        element_id="el_2",
        element_type=ElementType.BADGE,
        role=BlockRole.BADGE,
        geometry=Rect(x=50.0, y=160.0, width=100.0, height=30.0),
        content="ICLR 2026",
    )
    spec = LayoutSpec(
        slide_id="slide_1",
        slide_index=1,
        visual_intent=VisualIntent.TITLE_HERO,
        elements=[el1, el2],
    )

    assert spec.get_element("el_1") == el1
    assert spec.get_element("el_unknown") is None
    text_elements = spec.get_elements_by_type(ElementType.TEXT)
    assert len(text_elements) == 1
    assert text_elements[0] == el1
    assert len(spec.get_elements_by_type(ElementType.BADGE)) == 1


def test_layout_spec_json_roundtrip(tmp_path: Path):
    spec = LayoutSpec(
        slide_id="slide_1",
        slide_index=1,
        visual_intent=VisualIntent.TITLE_HERO,
        elements=[
            LayoutElement(
                element_id="title_1",
                element_type=ElementType.TEXT,
                role=BlockRole.HEADING,
                geometry=Rect(x=100.0, y=100.0, width=1000.0, height=80.0),
                style=ElementStyle(
                    text=TextStyle(font_size=32.0, font_weight="bold", alignment="center"),
                    background_color="#FFFFFF",
                ),
                content="Deep Learning Presentation",
            )
        ],
        constraints=[
            LayoutConstraint(
                constraint_type="CANVAS_BOUNDS",
                target_element_ids=["title_1"],
                satisfied=True,
            )
        ],
        speaker_notes="Welcome everyone.",
    )

    deck = DeckLayoutSpec(
        title="Sample Presentation",
        slides=[spec],
    )

    out_file = tmp_path / "deck_layout.json"
    deck.to_json_file(out_file)
    assert out_file.exists()

    reloaded = DeckLayoutSpec.from_json_file(out_file)
    assert reloaded.title == deck.title
    assert reloaded.slide_count == 1
    assert reloaded.slides[0].slide_id == "slide_1"
    assert reloaded.slides[0].elements[0].content == "Deep Learning Presentation"
    assert reloaded.slides[0].constraints[0].constraint_type == "CANVAS_BOUNDS"
