"""Tests for Layout Patch Engine (PR12 Test 4)."""

import pytest

from backend.evaluation.patch import apply_deck_patches, apply_patch, apply_patches
from backend.evaluation.schema import LayoutPatch, PatchOperation
from backend.layout.schema import (
    Canvas,
    DeckLayoutSpec,
    ElementStyle,
    ElementType,
    LayoutElement,
    LayoutSpec,
    Rect,
    TextStyle,
)
from backend.slidespec.schema import VisualIntent


@pytest.fixture
def base_slide() -> LayoutSpec:
    return LayoutSpec(
        slide_id="slide_test",
        slide_index=1,
        visual_intent=VisualIntent.PIPELINE_ARCHITECTURE,
        canvas=Canvas(width=1280, height=720),
        elements=[
            LayoutElement(
                element_id="fig_main",
                element_type=ElementType.FIGURE,
                geometry=Rect(x=100.0, y=100.0, width=200.0, height=150.0),
                content={"figure_id": "fig_1"},
            ),
            LayoutElement(
                element_id="txt_title",
                element_type=ElementType.TEXT,
                geometry=Rect(x=80.0, y=40.0, width=800.0, height=50.0),
                style=ElementStyle(text=TextStyle(font_size=28.0)),
                content="Architecture Pipeline",
            ),
        ],
    )


def test_patch_apply_resize_2x(base_slide: LayoutSpec) -> None:
    """Test 4: Input figure width=200, Patch resize 2x, Output width=400."""
    patch = LayoutPatch(
        slide_id="slide_test",
        target_element="fig_main",
        operation=PatchOperation.RESIZE,
        parameters={"scale": 2.0},
    )

    patched_slide = apply_patch(base_slide, patch)

    # Verify original is untouched (immutability)
    assert base_slide.get_element("fig_main").geometry.width == 200.0

    # Verify patched element width is doubled to 400.0
    patched_fig = patched_slide.get_element("fig_main")
    assert patched_fig.geometry.width == 400.0
    assert patched_fig.geometry.height == 300.0


def test_patch_apply_move(base_slide: LayoutSpec) -> None:
    """Verify MOVE operation shifts x and y by dx and dy."""
    patch = LayoutPatch(
        slide_id="slide_test",
        target_element="fig_main",
        operation=PatchOperation.MOVE,
        parameters={"dx": 20.0, "dy": 15.0},
    )

    patched_slide = apply_patch(base_slide, patch)
    patched_fig = patched_slide.get_element("fig_main")
    assert patched_fig.geometry.x == 120.0
    assert patched_fig.geometry.y == 115.0
    assert patched_fig.geometry.width == 200.0


def test_patch_apply_change_font_size(base_slide: LayoutSpec) -> None:
    """Verify CHANGE_FONT_SIZE modifies typography with minimum size guard."""
    patch = LayoutPatch(
        slide_id="slide_test",
        target_element="txt_title",
        operation=PatchOperation.CHANGE_FONT_SIZE,
        parameters={"delta": -4.0},
    )

    patched_slide = apply_patch(base_slide, patch)
    patched_txt = patched_slide.get_element("txt_title")
    assert patched_txt.style.text.font_size == 24.0

    # Test minimum font size guard (never below 6.0 pt)
    extreme_patch = LayoutPatch(
        slide_id="slide_test",
        target_element="txt_title",
        operation=PatchOperation.CHANGE_FONT_SIZE,
        parameters={"delta": -50.0},
    )
    clamped_slide = apply_patch(patched_slide, extreme_patch)
    assert clamped_slide.get_element("txt_title").style.text.font_size == 6.0


def test_patch_apply_clamp_to_canvas(base_slide: LayoutSpec) -> None:
    """Verify CLAMP_TO_CANVAS pulls overflowing elements into safety margin."""
    # Place an element partially beyond the canvas edge
    overflow_slide = base_slide.model_copy(deep=True)
    overflow_slide.elements.append(
        LayoutElement(
            element_id="overflow_card",
            element_type=ElementType.CONTAINER,
            geometry=Rect(x=1200.0, y=650.0, width=200.0, height=120.0),
        )
    )

    patch = LayoutPatch(
        slide_id="slide_test",
        target_element="overflow_card",
        operation=PatchOperation.CLAMP_TO_CANVAS,
        parameters={"margin": 24.0},
    )

    patched_slide = apply_patch(overflow_slide, patch)
    card = patched_slide.get_element("overflow_card")
    assert card.geometry.right <= (1280.0 - 24.0)
    assert card.geometry.bottom <= (720.0 - 24.0)
    assert card.geometry.x >= 24.0
    assert card.geometry.y >= 24.0


def test_apply_deck_patches(base_slide: LayoutSpec) -> None:
    """Verify applying patches across multiple slides in a DeckLayoutSpec."""
    slide2 = base_slide.model_copy(deep=True)
    slide2.slide_id = "slide_2"
    slide2.slide_index = 2

    deck = DeckLayoutSpec(
        title="Test Deck",
        slides=[base_slide, slide2],
    )

    patches = [
        LayoutPatch(
            slide_id="slide_test",
            target_element="fig_main",
            operation=PatchOperation.MOVE,
            parameters={"dx": 50.0},
        ),
        LayoutPatch(
            slide_id="slide_2",
            target_element="txt_title",
            operation=PatchOperation.CHANGE_FONT_SIZE,
            parameters={"font_size": 32.0},
        ),
    ]

    patched_deck = apply_deck_patches(deck, patches)
    assert patched_deck.slides[0].get_element("fig_main").geometry.x == 150.0
    assert patched_deck.slides[1].get_element("txt_title").style.text.font_size == 32.0


def test_patch_change_padding(base_slide: LayoutSpec) -> None:
    """Verify CHANGE_PADDING operation."""
    patch = LayoutPatch(
        slide_id="slide_test",
        target_element="txt_title",
        operation=PatchOperation.CHANGE_PADDING,
        parameters={"padding": 12.0},
    )
    patched = apply_patch(base_slide, patch)
    assert patched.get_element("txt_title").style.padding == 12.0


def test_patch_set_coordinates(base_slide: LayoutSpec) -> None:
    """Verify SET_COORDINATES directly sets bounding box."""
    patch = LayoutPatch(
        slide_id="slide_test",
        target_element="fig_main",
        operation=PatchOperation.SET_COORDINATES,
        parameters={"x": 300.0, "y": 250.0, "width": 500.0, "height": 350.0},
    )
    patched = apply_patch(base_slide, patch)
    geo = patched.get_element("fig_main").geometry
    assert geo.x == 300.0 and geo.y == 250.0
    assert geo.width == 500.0 and geo.height == 350.0


def test_patch_safeguards_missing_element_and_mismatched_slide(base_slide: LayoutSpec) -> None:
    """Verify non-existent element or wrong slide_id returns original spec without crash."""
    patch_wrong_slide = LayoutPatch(
        slide_id="another_slide",
        target_element="fig_main",
        operation=PatchOperation.MOVE,
        parameters={"dx": 100.0},
    )
    res1 = apply_patch(base_slide, patch_wrong_slide)
    assert res1.get_element("fig_main").geometry.x == 100.0

    patch_missing_elem = LayoutPatch(
        slide_id="slide_test",
        target_element="non_existent",
        operation=PatchOperation.MOVE,
        parameters={"dx": 100.0},
    )
    res2 = apply_patch(base_slide, patch_missing_elem)
    assert res2.get_element("fig_main").geometry.x == 100.0

