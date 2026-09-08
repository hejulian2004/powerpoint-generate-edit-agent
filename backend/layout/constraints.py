"""Layout Constraints and Evaluation System (PR10).

Provides formal definitions and evaluators for spatial and geometric constraints,
including:
- Canvas Bounds
- Non-overlap between foreground elements
- Figure aspect ratio preservation
- Minimum margin enforcement
- Text overflow estimation
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from .schema import Canvas, ElementType, LayoutConstraint, LayoutElement, Rect


def check_canvas_bounds(
    element: LayoutElement,
    canvas: Canvas,
    margin: float = 0.0,
    eps: float = 1e-4,
) -> LayoutConstraint:
    """Ensure an element lies completely inside the canvas within allowed margin."""
    geo = element.geometry
    in_bounds = (
        geo.x >= margin - eps
        and geo.y >= margin - eps
        and geo.right <= (canvas.width - margin) + eps
        and geo.bottom <= (canvas.height - margin) + eps
    )
    msg = None
    if not in_bounds:
        msg = (
            f"Element '{element.element_id}' out of canvas bounds: "
            f"x={geo.x:.1f}, y={geo.y:.1f}, r={geo.right:.1f}, b={geo.bottom:.1f} "
            f"(canvas: {canvas.width}x{canvas.height}, margin: {margin})"
        )
    return LayoutConstraint(
        constraint_type="CANVAS_BOUNDS",
        target_element_ids=[element.element_id],
        parameters={"margin": margin, "canvas_w": canvas.width, "canvas_h": canvas.height},
        satisfied=in_bounds,
        message=msg,
    )


def check_no_overlap(
    element_a: LayoutElement,
    element_b: LayoutElement,
    eps: float = 1e-4,
) -> LayoutConstraint:
    """Ensure two non-container elements do not overlap."""
    # Allow container with its child or two containers to overlap
    if element_a.element_type == ElementType.CONTAINER or element_b.element_type == ElementType.CONTAINER:
        return LayoutConstraint(
            constraint_type="NO_OVERLAP",
            target_element_ids=[element_a.element_id, element_b.element_id],
            satisfied=True,
        )

    # Check intersection
    intersect = element_a.geometry.intersects(element_b.geometry, eps=eps)
    msg = None
    if intersect:
        intersection = element_a.geometry.intersection(element_b.geometry)
        iw = intersection.width if intersection else 0.0
        ih = intersection.height if intersection else 0.0
        msg = (
            f"Collision detected between '{element_a.element_id}' and '{element_b.element_id}': "
            f"overlap area={iw:.1f}x{ih:.1f}"
        )

    return LayoutConstraint(
        constraint_type="NO_OVERLAP",
        target_element_ids=[element_a.element_id, element_b.element_id],
        satisfied=not intersect,
        message=msg,
    )


def check_figure_aspect_ratio(
    element: LayoutElement,
    expected_ratio: Optional[float] = None,
    min_ratio: float = 0.2,
    max_ratio: float = 5.0,
    tolerance: float = 0.35,
) -> LayoutConstraint:
    """Ensure figure bounding box preserves plausible aspect ratio without extreme deformation."""
    if element.element_type != ElementType.FIGURE:
        return LayoutConstraint(
            constraint_type="KEEP_FIGURE_RATIO",
            target_element_ids=[element.element_id],
            satisfied=True,
        )

    ratio = element.geometry.aspect_ratio
    satisfied = True
    msg = None

    if ratio < min_ratio or ratio > max_ratio:
        satisfied = False
        msg = (
            f"Figure '{element.element_id}' aspect ratio {ratio:.2f} outside sensible bounds "
            f"[{min_ratio}, {max_ratio}]"
        )
    elif expected_ratio is not None and expected_ratio > 0:
        diff = abs(ratio - expected_ratio) / expected_ratio
        if diff > tolerance:
            satisfied = False
            msg = (
                f"Figure '{element.element_id}' ratio {ratio:.2f} deviates from expected "
                f"{expected_ratio:.2f} by {diff:.1%}"
            )

    return LayoutConstraint(
        constraint_type="KEEP_FIGURE_RATIO",
        target_element_ids=[element.element_id],
        parameters={"actual_ratio": ratio, "expected_ratio": expected_ratio},
        satisfied=satisfied,
        message=msg,
    )


def check_minimum_margin(
    element: LayoutElement,
    canvas: Canvas,
    min_margin: float = 24.0,
) -> LayoutConstraint:
    """Ensure element maintains minimum clearance from the slide boundaries."""
    return check_canvas_bounds(element, canvas, margin=min_margin)


def estimate_text_lines(
    text: str,
    box_width: float,
    font_size: float,
    padding: float = 0.0,
    char_width_ratio: float = 0.55,
) -> int:
    """Rough heuristic estimation of text lines given bounding width and font size."""
    usable_width = max(10.0, box_width - 2 * padding)
    # Average character width in proportional fonts is roughly char_width_ratio * font_size
    char_width = max(3.0, font_size * char_width_ratio)
    chars_per_line = max(1, int(usable_width / char_width))

    total_lines = 0
    for paragraph in text.split("\n"):
        if not paragraph:
            total_lines += 1
        else:
            lines_in_para = (len(paragraph) + chars_per_line - 1) // chars_per_line
            total_lines += max(1, lines_in_para)

    return total_lines


def check_text_overflow(
    element: LayoutElement,
    line_height_multiplier: float = 1.25,
) -> LayoutConstraint:
    """Estimate if text content can fit inside the element geometry."""
    if element.element_type not in (ElementType.TEXT, ElementType.BADGE):
        return LayoutConstraint(
            constraint_type="TEXT_OVERFLOW_CHECK",
            target_element_ids=[element.element_id],
            satisfied=True,
        )

    text = str(element.content or "")
    if not text.strip():
        return LayoutConstraint(
            constraint_type="TEXT_OVERFLOW_CHECK",
            target_element_ids=[element.element_id],
            satisfied=False,
            message=f"Text element '{element.element_id}' contains empty text content",
        )

    style = element.style.text
    font_size = style.font_size if style else 18.0
    line_h = font_size * (style.line_height if style else line_height_multiplier)
    est_lines = estimate_text_lines(text, element.geometry.width, font_size, element.style.padding)
    required_height = est_lines * line_h

    # Allow 25% tolerance for layout flexibility
    tolerated_height = element.geometry.height * 1.25
    fits = required_height <= tolerated_height
    msg = None
    if not fits:
        msg = (
            f"Potential text overflow in '{element.element_id}': estimated height {required_height:.1f}px "
            f"exceeds box height {element.geometry.height:.1f}px ({est_lines} lines)"
        )

    return LayoutConstraint(
        constraint_type="TEXT_OVERFLOW_CHECK",
        target_element_ids=[element.element_id],
        parameters={"est_lines": est_lines, "required_height": required_height, "box_height": element.geometry.height},
        satisfied=fits,
        message=msg,
    )
