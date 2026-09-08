"""TWO_COLUMN_CONTRAST Layout Template (PR10).

Synthesizes geometry for balanced comparative analysis
(Problem vs Solution, Baseline vs Proposed Approach, Ablation A vs B).
"""

from __future__ import annotations

from typing import List

from ...slidespec.schema import SlideSpec, TextBlock
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


class TwoColumnContrastTemplate(BaseLayoutTemplate):
    """Layout template for VisualIntent.TWO_COLUMN_CONTRAST."""

    def layout(self, slide: SlideSpec, canvas: Canvas) -> LayoutSpec:
        elements: List[LayoutElement] = []
        zones = compute_layout_zones(canvas)

        # 1. Header Elements
        elements.extend(create_header_elements(slide, canvas=canvas))

        # 2. Split Blocks into Left and Right Columns
        texts = [b for b in slide.blocks if isinstance(b, TextBlock)]
        left_blocks: List[TextBlock] = []
        right_blocks: List[TextBlock] = []

        explicit_tagged = any(b.column in ("left", "right") for b in texts)
        if explicit_tagged:
            for b in texts:
                if b.column == "left":
                    left_blocks.append(b)
                elif b.column == "right":
                    right_blocks.append(b)
                else:
                    if len(left_blocks) <= len(right_blocks):
                        left_blocks.append(b)
                    else:
                        right_blocks.append(b)
        else:
            mid = (len(texts) + 1) // 2
            left_blocks = texts[:mid]
            right_blocks = texts[mid:]

        # Column geometry
        gutter = 32.0 * (canvas.width / 1280.0)
        col_w = (zones.body_width - gutter) / 2.0
        left_x = zones.body_x
        right_x = zones.body_x + col_w + gutter

        # Helper to layout a column stack with overflow protection
        def _layout_column(
            items: List[TextBlock],
            col_x: float,
            side: str,
        ) -> None:
            if not items:
                return
            n = len(items)
            gap = max(6.0, min(14.0, (zones.body_height / n) * 0.2)) if n > 1 else 0.0
            total_gaps = (n - 1) * gap
            avail_h = zones.body_height - total_gaps
            item_h = max(32.0, avail_h / n)

            if item_h < 50.0:
                font_sz = 14.0
                pad = 6.0
            elif item_h < 65.0:
                font_sz = 15.0
                pad = 10.0
            else:
                font_sz = 16.0 if n > 3 else 17.0
                pad = 14.0

            curr_y = zones.body_y
            for idx, item in enumerate(items):
                is_right = side == "right"
                bg_color = "#EFF6FF" if (item.emphasis or is_right) else "#F8FAFC"
                border_color = "#BFDBFE" if (item.emphasis or is_right) else "#E2E8F0"
                text_color = "#1E3A8A" if item.emphasis else "#0F172A"

                elements.append(
                    LayoutElement(
                        element_id=f"slide_{slide.index}_{side}_col_{idx + 1}",
                        source_block_id=f"{side}_text_{idx + 1}",
                        element_type=ElementType.TEXT,
                        role=item.role,
                        geometry=Rect(x=col_x, y=curr_y, width=col_w, height=item_h),
                        style=ElementStyle(
                            background_color=bg_color,
                            border_color=border_color,
                            border_width=1.0,
                            corner_radius=8.0,
                            padding=pad,
                            text=TextStyle(
                                font_size=font_sz,
                                font_weight="bold" if item.emphasis else "normal",
                                line_height=1.25,
                                color=text_color,
                            ),
                        ),
                        content=item.content,
                        z_index=1,
                    )
                )
                curr_y += item_h + gap

        _layout_column(left_blocks, left_x, "left")
        _layout_column(right_blocks, right_x, "right")

        return LayoutSpec(
            slide_id=f"slide_{slide.index}",
            slide_index=slide.index,
            visual_intent=slide.visual_intent,
            canvas=canvas,
            elements=elements,
            speaker_notes=slide.speaker_notes,
            metadata={"template": "TwoColumnContrastTemplate"},
        )
