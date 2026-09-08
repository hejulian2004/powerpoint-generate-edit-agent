"""Unit Tests for Layout Validator and Constraint Checking (PR10)."""

import pytest

from backend.layout.schema import (
    Canvas,
    ElementType,
    LayoutElement,
    LayoutSpec,
    Rect,
)
from backend.layout.validator import (
    LayoutValidationError,
    validate_layout,
)
from backend.slidespec.schema import BlockRole, VisualIntent


def _build_base_layout() -> LayoutSpec:
    return LayoutSpec(
        slide_id="test_slide",
        slide_index=1,
        visual_intent=VisualIntent.KEY_TAKEAWAY_LIST,
        canvas=Canvas(width=1280.0, height=720.0),
        elements=[
            LayoutElement(
                element_id="el_header",
                element_type=ElementType.TEXT,
                role=BlockRole.HEADING,
                geometry=Rect(x=64.0, y=40.0, width=1152.0, height=50.0),
                content="Valid Header",
            ),
            LayoutElement(
                element_id="el_body",
                element_type=ElementType.TEXT,
                role=BlockRole.BULLET_ITEM,
                geometry=Rect(x=64.0, y=140.0, width=1152.0, height=100.0),
                content="Valid Body Text",
            ),
        ],
    )


def test_validator_passes_clean_layout():
    layout = _build_base_layout()
    report = validate_layout(layout, strict=True)
    assert report.is_valid is True
    assert len(report.errors) == 0


def test_validator_catches_negative_coordinate():
    layout = _build_base_layout()
    # Inject negative x
    layout.elements[1].geometry.x = -10.0

    report = validate_layout(layout, strict=False)
    assert report.is_valid is False
    assert any("out of canvas bounds" in err or "negative" in err for err in report.errors)

    with pytest.raises(LayoutValidationError):
        validate_layout(layout, strict=True)


def test_validator_catches_exceeding_canvas_width():
    layout = _build_base_layout()
    # Width pushes right to 1300.0 (canvas is 1280.0)
    layout.elements[1].geometry.width = 1250.0

    report = validate_layout(layout, strict=False)
    assert report.is_valid is False
    assert any("out of canvas bounds" in err for err in report.errors)


def test_validator_catches_collision_overlap():
    layout = _build_base_layout()
    # Move body so it collides with header
    layout.elements[1].geometry.y = 50.0

    report = validate_layout(layout, strict=False)
    assert report.is_valid is False
    assert any("Collision detected" in err for err in report.errors)


def test_validator_catches_empty_text():
    layout = _build_base_layout()
    layout.elements[1].content = "   "

    report = validate_layout(layout, strict=False)
    assert report.is_valid is False
    assert any("empty content" in err for err in report.errors)


def test_validator_catches_missing_figure_id():
    layout = _build_base_layout()
    fig_element = LayoutElement(
        element_id="el_fig",
        element_type=ElementType.FIGURE,
        geometry=Rect(x=64.0, y=260.0, width=500.0, height=300.0),
        content={"caption": "Missing ID caption"},
    )
    layout.elements.append(fig_element)

    report = validate_layout(layout, strict=False)
    assert report.is_valid is False
    assert any("missing source_figure_id" in err for err in report.errors)


def test_validator_figure_aspect_ratio_warning():
    layout = _build_base_layout()
    # Extremely deformed figure (width 1000, height 20 -> ratio 50.0)
    fig_element = LayoutElement(
        element_id="el_fig_deformed",
        element_type=ElementType.FIGURE,
        geometry=Rect(x=64.0, y=260.0, width=1000.0, height=20.0),
        content={"source_figure_id": "fig_1", "caption": "Deformed"},
    )
    layout.elements.append(fig_element)

    report = validate_layout(layout, strict=False)
    # Warnings do not invalidate the layout if there are no errors
    assert report.is_valid is True
    assert any("aspect ratio" in w for w in report.warnings)


def test_constraint_minimum_margin_and_text_overflow():
    from backend.layout.constraints import check_minimum_margin, check_text_overflow

    canvas = Canvas(width=1280.0, height=720.0)
    el = LayoutElement(
        element_id="el_margin_violation",
        element_type=ElementType.TEXT,
        geometry=Rect(x=5.0, y=5.0, width=200.0, height=50.0),
        content="Near border",
    )
    c_margin = check_minimum_margin(el, canvas, min_margin=24.0)
    assert c_margin.satisfied is False

    # Text overflow check with massive text in tiny box
    el_overflow = LayoutElement(
        element_id="el_overflow",
        element_type=ElementType.TEXT,
        geometry=Rect(x=64.0, y=140.0, width=100.0, height=20.0),
        content="This is a very long paragraph that will definitely exceed twenty pixels of vertical space when wrapped onto multiple lines in a narrow container.",
    )
    c_overflow = check_text_overflow(el_overflow)
    assert c_overflow.satisfied is False

