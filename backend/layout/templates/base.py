"""Base Layout Template and Common Spatial Operators (PR10).

Provides standardized geometry zones, header layout generation,
and typography style presets for academic presentation slides.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from ...slidespec.schema import BlockRole, SlideSpec
from ..schema import (
    Canvas,
    ElementStyle,
    ElementType,
    LayoutConstraint,
    LayoutElement,
    LayoutSpec,
    Rect,
    TextStyle,
)

# Standard Academic 16:9 Canvas Zones (1280x720)
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


def create_header_elements(slide: SlideSpec) -> List[LayoutElement]:
    """Generate standardized top header elements for non-title slides."""
    elements: List[LayoutElement] = []

    # Slide Title
    title_text = slide.title.strip() if slide.title else "Untitled Slide"
    title_geo = Rect(
        x=HEADER_X,
        y=HEADER_Y,
        width=HEADER_WIDTH,
        height=HEADER_TITLE_HEIGHT,
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
            x=HEADER_X,
            y=HEADER_Y + HEADER_TITLE_HEIGHT + HEADER_SPACING,
            width=HEADER_WIDTH,
            height=HEADER_SUBTITLE_HEIGHT,
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
