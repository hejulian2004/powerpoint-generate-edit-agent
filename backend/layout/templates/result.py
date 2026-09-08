"""KEY_TAKEAWAY_LIST & METRIC_CARD_GRID Layout Template (PR10).

Synthesizes geometry for key conclusions, core contributions, future work,
and metric card grids.
"""

from __future__ import annotations

from typing import List

from ...slidespec.schema import BlockRole, SlideSpec, TextBlock, VisualIntent
from ..schema import (
    Canvas,
    ElementStyle,
    ElementType,
    LayoutElement,
    LayoutSpec,
    Rect,
    TextStyle,
)
from .base import BaseLayoutTemplate, compute_layout_zones, create_header_elements


class TakeawayListTemplate(BaseLayoutTemplate):
    """Layout template for VisualIntent.KEY_TAKEAWAY_LIST and METRIC_CARD_GRID."""

    def layout(self, slide: SlideSpec, canvas: Canvas) -> LayoutSpec:
        elements: List[LayoutElement] = []
        zones = compute_layout_zones(canvas)

        # 1. Header Elements
        elements.extend(create_header_elements(slide, canvas=canvas))

        # 2. Extract Text Content Blocks
        texts = [b for b in slide.blocks if isinstance(b, TextBlock)]
        if not texts:
            # Fallback text if slide has no blocks (using valid BlockRole)
            texts = [
                TextBlock(
                    role=BlockRole.BULLET_ITEM,
                    content=slide.title or "Summary",
                )
            ]

        n = len(texts)

        # If METRIC_CARD_GRID and items count is 2, 3, or 4: use multi-column card grid
        if slide.visual_intent == VisualIntent.METRIC_CARD_GRID and 2 <= n <= 4:
            if n == 2 or n == 3:
                # 1 row, N columns
                gap = 24.0 * (canvas.width / 1280.0)
                col_w = (zones.body_width - (n - 1) * gap) / n
                col_h = min(360.0 * (canvas.height / 720.0), zones.body_height - 40.0)
                card_y = zones.body_y + (zones.body_height - col_h) / 2.0

                curr_x = zones.body_x
                for idx, t in enumerate(texts):
                    elements.append(
                        LayoutElement(
                            element_id=f"slide_{slide.index}_metric_card_{idx + 1}",
                            source_block_id=f"metric_{idx + 1}",
                            element_type=ElementType.TEXT,
                            role=t.role,
                            geometry=Rect(x=curr_x, y=card_y, width=col_w, height=col_h),
                            style=ElementStyle(
                                background_color="#EFF6FF" if t.emphasis else "#F8FAFC",
                                border_color="#3B82F6" if t.emphasis else "#E2E8F0",
                                border_width=2.0 if t.emphasis else 1.0,
                                corner_radius=10.0,
                                padding=18.0,
                                text=TextStyle(
                                    font_size=18.0,
                                    font_weight="bold" if t.emphasis else "normal",
                                    alignment="center",
                                    line_height=1.35,
                                    color="#1E3A8A" if t.emphasis else "#0F172A",
                                ),
                            ),
                            content=t.content,
                            z_index=1,
                        )
                    )
                    curr_x += col_w + gap

            else:  # n == 4 -> 2x2 grid
                gap_x = 24.0 * (canvas.width / 1280.0)
                gap_y = 20.0 * (canvas.height / 720.0)
                card_w = (zones.body_width - gap_x) / 2.0
                card_h = (zones.body_height - gap_y) / 2.0

                for idx, t in enumerate(texts):
                    row = idx // 2
                    col = idx % 2
                    cx = zones.body_x + col * (card_w + gap_x)
                    cy = zones.body_y + row * (card_h + gap_y)

                    elements.append(
                        LayoutElement(
                            element_id=f"slide_{slide.index}_grid_card_{idx + 1}",
                            source_block_id=f"grid_{idx + 1}",
                            element_type=ElementType.TEXT,
                            role=t.role,
                            geometry=Rect(x=cx, y=cy, width=card_w, height=card_h),
                            style=ElementStyle(
                                background_color="#EFF6FF" if t.emphasis else "#F8FAFC",
                                border_color="#BFDBFE" if t.emphasis else "#E2E8F0",
                                border_width=1.0,
                                corner_radius=8.0,
                                padding=16.0,
                                text=TextStyle(
                                    font_size=16.0,
                                    font_weight="bold" if t.emphasis else "normal",
                                    line_height=1.3,
                                    color="#1E3A8A" if t.emphasis else "#0F172A",
                                ),
                            ),
                            content=t.content,
                            z_index=1,
                        )
                    )

        else:
            # Standard KEY_TAKEAWAY_LIST: Vertical Card Stack
            gap = max(6.0, min(16.0, (zones.body_height / n) * 0.2)) if n > 1 else 0.0
            total_gaps = (n - 1) * gap
            avail_h = zones.body_height - total_gaps
            card_h = max(32.0, avail_h / n)

            if card_h < 50.0:
                font_sz = 14.0
                pad = 8.0
            elif card_h < 65.0:
                font_sz = 15.0
                pad = 12.0
            else:
                font_sz = 17.0
                pad = 18.0

            curr_y = zones.body_y
            for idx, t in enumerate(texts):
                elements.append(
                    LayoutElement(
                        element_id=f"slide_{slide.index}_takeaway_card_{idx + 1}",
                        source_block_id=f"text_{idx + 1}",
                        element_type=ElementType.TEXT,
                        role=t.role,
                        geometry=Rect(x=zones.body_x, y=curr_y, width=zones.body_width, height=card_h),
                        style=ElementStyle(
                            background_color="#EFF6FF" if t.emphasis else "#F8FAFC",
                            border_color="#3B82F6" if t.emphasis else "#E2E8F0",
                            border_width=1.5 if t.emphasis else 1.0,
                            corner_radius=8.0,
                            padding=pad,
                            text=TextStyle(
                                font_size=font_sz,
                                font_weight="bold" if t.emphasis else "normal",
                                line_height=1.3,
                                color="#1E3A8A" if t.emphasis else "#0F172A",
                            ),
                        ),
                        content=t.content,
                        z_index=1,
                    )
                )
                curr_y += card_h + gap

        return LayoutSpec(
            slide_id=f"slide_{slide.index}",
            slide_index=slide.index,
            visual_intent=slide.visual_intent,
            canvas=canvas,
            elements=elements,
            speaker_notes=slide.speaker_notes,
            metadata={"template": "TakeawayListTemplate"},
        )
