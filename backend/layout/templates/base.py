"""Base Layout Template and Common Spatial Operators (PR10).

Provides standardized geometry zones, header layout generation,
and typography style presets for academic presentation slides.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

from ...slidespec.schema import BlockRole, SlideSpec
from ..schema import (
    Canvas,
    ElementStyle,
    ElementType,
    LayoutElement,
    LayoutSpec,
    Rect,
    TextStyle,
)

# Standard Academic 16:9 Canvas Zones (1280x720 defaults)
MARGIN_LEFT = 64.0
MARGIN_RIGHT = 64.0
MARGIN_TOP = 40.0
MARGIN_BOTTOM = 40.0

CANVAS_WIDTH = 1280.0
CANVAS_HEIGHT = 720.0

HEADER_X = MARGIN_LEFT
HEADER_Y = MARGIN_TOP
HEADER_WIDTH = CANVAS_WIDTH - MARGIN_LEFT - MARGIN_RIGHT  # 1152.0
HEADER_TITLE_HEIGHT = 48.0
HEADER_SUBTITLE_HEIGHT = 30.0
HEADER_SPACING = 6.0

BODY_X = MARGIN_LEFT
BODY_Y = 132.0
BODY_WIDTH = 1152.0
BODY_HEIGHT = CANVAS_HEIGHT - BODY_Y - MARGIN_BOTTOM  # 548.0


@dataclass(frozen=True)
class LayoutZones:
    """Resolved spatial zones for a given canvas dimensions."""

    canvas_width: float
    canvas_height: float
    margin_left: float
    margin_right: float
    margin_top: float
    margin_bottom: float
    header_x: float
    header_y: float
    header_width: float
    header_title_height: float
    header_subtitle_height: float
    header_spacing: float
    body_x: float
    body_y: float
    body_width: float
    body_height: float


def compute_layout_zones(canvas: Optional[Canvas] = None) -> LayoutZones:
    """Dynamically compute bounding zones for any canvas resolution."""
    c = canvas or Canvas()
    cw = c.width
    ch = c.height

    # Scale margins slightly for larger/smaller resolutions while retaining minimums
    m_left = max(32.0, MARGIN_LEFT * (cw / CANVAS_WIDTH))
    m_right = max(32.0, MARGIN_RIGHT * (cw / CANVAS_WIDTH))
    m_top = max(24.0, MARGIN_TOP * (ch / CANVAS_HEIGHT))
    m_bottom = max(24.0, MARGIN_BOTTOM * (ch / CANVAS_HEIGHT))

    h_x = m_left
    h_y = m_top
    h_w = cw - m_left - m_right
    h_title_h = HEADER_TITLE_HEIGHT * (ch / CANVAS_HEIGHT)
    h_sub_h = HEADER_SUBTITLE_HEIGHT * (ch / CANVAS_HEIGHT)
    h_spacing = HEADER_SPACING * (ch / CANVAS_HEIGHT)

    b_x = m_left
    b_y = h_y + h_title_h + h_sub_h + (h_spacing * 2.5)
    b_w = h_w
    b_h = ch - b_y - m_bottom

    return LayoutZones(
        canvas_width=cw,
        canvas_height=ch,
        margin_left=m_left,
        margin_right=m_right,
        margin_top=m_top,
        margin_bottom=m_bottom,
        header_x=h_x,
        header_y=h_y,
        header_width=h_w,
        header_title_height=h_title_h,
        header_subtitle_height=h_sub_h,
        header_spacing=h_spacing,
        body_x=b_x,
        body_y=b_y,
        body_width=b_w,
        body_height=b_h,
    )


def create_header_elements(
    slide: SlideSpec, canvas: Optional[Canvas] = None
) -> List[LayoutElement]:
    """Generate standardized top header elements for non-title slides."""
    elements: List[LayoutElement] = []
    zones = compute_layout_zones(canvas)

    # Slide Title
    title_text = slide.title.strip() if slide.title else "Untitled Slide"
    title_geo = Rect(
        x=zones.header_x,
        y=zones.header_y,
        width=zones.header_width,
        height=zones.header_title_height,
    )
    title_style = ElementStyle(
        text=TextStyle(
            font_size=26.0,
            font_weight="bold",
            alignment="left",
            line_height=1.15,
            color="#0F172A",
        )
    )
    elements.append(
        LayoutElement(
            element_id=f"slide_{slide.index}_header_title",
            source_block_id="header_title",
            element_type=ElementType.TEXT,
            role=BlockRole.HEADING,
            geometry=title_geo,
            style=title_style,
            content=title_text,
            z_index=1,
        )
    )

    # Slide Subtitle (if available)
    if slide.subtitle and slide.subtitle.strip():
        sub_geo = Rect(
            x=zones.header_x,
            y=zones.header_y + zones.header_title_height + zones.header_spacing,
            width=zones.header_width,
            height=zones.header_subtitle_height,
        )
        sub_style = ElementStyle(
            text=TextStyle(
                font_size=15.0,
                font_weight="normal",
                alignment="left",
                line_height=1.2,
                color="#64748B",
            )
        )
        elements.append(
            LayoutElement(
                element_id=f"slide_{slide.index}_header_subtitle",
                source_block_id="header_subtitle",
                element_type=ElementType.TEXT,
                role=BlockRole.SUBHEADING,
                geometry=sub_geo,
                style=sub_style,
                content=slide.subtitle.strip(),
                z_index=1,
            )
        )

    return elements


class BaseLayoutTemplate(ABC):
    """Abstract layout template strategy."""

    @abstractmethod
    def layout(self, slide: SlideSpec, canvas: Canvas) -> LayoutSpec:
        """Resolve geometry and synthesize LayoutSpec for a SlideSpec."""
        raise NotImplementedError
