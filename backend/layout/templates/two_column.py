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
from .base import (
    BODY_HEIGHT,
    BODY_WIDTH,
    BODY_X,
    BODY_Y,
    BaseLayoutTemplate,
    create_header_elements,
)


class TwoColumnContrastTemplate(BaseLayoutTemplate):
    """Layout template for VisualIntent.TWO_COLUMN_CONTRAST."""

    def layout(self, slide: SlideSpec, canvas: Canvas) -> LayoutSpec:
        elements: List[LayoutElement] = []

        # 1. Header Elements
        elements.extend(create_header_elements(slide))

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
                    # Alternating assignment if not explicitly tagged
                    if len(left_blocks) <= len(right_blocks):
                        left_blocks.append(b)
                    else:
                        right_blocks.append(b)
        else:
            mid = (len(texts) + 1) // 2
            left_blocks = texts[:mid]
            right_blocks = texts[mid:]

        # Column geometry
        gutter = 32.0
        col_w = (BODY_WIDTH - gutter) / 2.0  # 560.0
        left_x = BODY_X
        right_x = BODY_X + col_w + gutter

        # Helper to layout a column stack
        def _layout_column(
            items: List[TextBlock],
            col_x: float,
            side: str,
        ) -> None:
            if not items:
                return
            n = len(items)
            gap = 14.0
            total_gaps = (n - 1) * gap
            item_h = max(60.0, (BODY_HEIGHT - total_gaps) / n)

            curr_y = BODY_Y
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
                            padding=14.0,
                            text=TextStyle(
                                font_size=16.0 if n > 3 else 17.0,
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
