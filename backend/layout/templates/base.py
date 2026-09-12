"""Base Layout Template and Common Spatial Operators (PR10).

Provides standardized geometry zones, header layout generation,
and typography style presets for academic presentation slides.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, List, Optional

from ...slidespec.schema import BlockRole, FigureBlock, SlideSpec, TableBlock
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


def stack_visual_assets(
    slide: SlideSpec,
    assets: List[Any],
    region: Rect,
    canvas: Optional[Canvas] = None,
) -> List[LayoutElement]:
    """Render every Figure/Table block inside ``region`` as a stacked slot.

    Every visual source asset maps to a FIGURE/TABLE element (later compiled to a
    resolved asset or an explicit placeholder), so deterministic fallback templates
    can never silently omit a FigureBlock/TableBlock. A single asset keeps the exact
    legacy geometry/id contract; multiple assets are split into equal vertical slots.
    """
    elements: List[LayoutElement] = []
    assets = list(assets)
    if not assets:
        return elements

    gap = 8.0
    n = len(assets)
    slot_h = (region.height - (n - 1) * gap) / n

    for idx, block in enumerate(assets):
        slot_y = region.y + idx * (slot_h + gap)
        is_figure = isinstance(block, FigureBlock)
        ref = block.block_id or (
            block.source_figure_id if is_figure else block.source_table_id
        )
        has_caption = bool(
            getattr(block, "caption", None) or getattr(block, "xref_label", None)
        )
        cap_h = 52.0 if has_caption else 0.0
        if n > 1 and (slot_h - cap_h - gap) < 48.0:
            cap_h = 0.0
        asset_h = max(8.0, slot_h - cap_h - (gap if cap_h else 0.0))
        asset_rect = Rect(x=region.x, y=slot_y, width=region.width, height=asset_h)

        if is_figure:
            elements.append(
                LayoutElement(
                    element_id=f"slide_{slide.index}_figure_{idx + 1}",
                    source_block_id=ref,
                    source_evidence_ids=list(getattr(block, "source_evidence_ids", [])),
                    element_type=ElementType.FIGURE,
                    role=BlockRole.CALLOUT,
                    geometry=asset_rect,
                    style=ElementStyle(
                        background_color="#F1F5F9",
                        border_color="#CBD5E1",
                        border_width=1.0,
                        corner_radius=8.0,
                    ),
                    content={
                        "source_figure_id": block.source_figure_id,
                        "caption": block.caption,
                        "xref_label": block.xref_label,
                        "placeholder": getattr(block, "placeholder", True),
                        "source_page": getattr(block, "source_page", None),
                    },
                    z_index=1,
                )
            )
            cap_id = f"slide_{slide.index}_fig_caption_{idx + 1}"
        else:
            elements.append(
                LayoutElement(
                    element_id=f"slide_{slide.index}_table_{idx + 1}",
                    source_block_id=ref,
                    source_evidence_ids=list(getattr(block, "source_evidence_ids", [])),
                    element_type=ElementType.TABLE,
                    role=BlockRole.CALLOUT,
                    geometry=asset_rect,
                    style=ElementStyle(
                        background_color="#FFFFFF",
                        border_color="#E2E8F0",
                        border_width=1.0,
                    ),
                    content={
                        "source_table_id": block.source_table_id,
                        "caption": block.caption,
                        "xref_label": block.xref_label,
                        "highlight_cells": getattr(block, "highlight_cells", []),
                        "columns": getattr(block, "columns", []),
                        "rows": getattr(block, "rows", []),
                        "placeholder": getattr(block, "placeholder", False),
                        "source_page": getattr(block, "source_page", None),
                    },
                    z_index=1,
                )
            )
            cap_id = f"slide_{slide.index}_tbl_caption_{idx + 1}"

        if cap_h > 0:
            caption_text = (
                f"{getattr(block, 'xref_label', None) or ''}: "
                f"{getattr(block, 'caption', None) or ''}"
            ).strip(" :")
            elements.append(
                LayoutElement(
                    element_id=cap_id,
                    source_block_id=f"{ref}_caption",
                    source_evidence_ids=list(getattr(block, "source_evidence_ids", [])),
                    element_type=ElementType.TEXT,
                    role=BlockRole.CAPTION,
                    geometry=Rect(
                        x=region.x,
                        y=slot_y + asset_h + gap,
                        width=region.width,
                        height=cap_h,
                    ),
                    style=ElementStyle(
                        text=TextStyle(
                            font_size=13.0,
                            font_weight="normal",
                            alignment="center",
                            color="#64748B",
                            italic=True,
                        )
                    ),
                    content=caption_text,
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
