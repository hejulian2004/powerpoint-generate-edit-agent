"""BENCHMARK_COMPARISON Layout Template (PR10).

Synthesizes geometry for empirical results, benchmark comparisons, and experimental setups
(Left asset: Table / Figure + Right analytical takeaway cards).
"""

from __future__ import annotations

from typing import List

from ...slidespec.schema import BlockRole, FigureBlock, SlideSpec, TableBlock, TextBlock
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


class BenchmarkComparisonTemplate(BaseLayoutTemplate):
    """Layout template for VisualIntent.BENCHMARK_COMPARISON."""

    def layout(self, slide: SlideSpec, canvas: Canvas) -> LayoutSpec:
        elements: List[LayoutElement] = []

        # 1. Header Elements
        elements.extend(create_header_elements(slide))

        # 2. Extract content blocks
        tables = [b for b in slide.blocks if isinstance(b, TableBlock)]
        figures = [b for b in slide.blocks if isinstance(b, FigureBlock)]
        texts = [b for b in slide.blocks if isinstance(b, TextBlock)]

        has_visual_asset = bool(tables or figures)

        if has_visual_asset:
            # 60% Left Asset, 40% Right Insights
            left_w = 680.0
            gutter = 28.0
            right_w = BODY_WIDTH - left_w - gutter  # 444.0
            right_x = BODY_X + left_w + gutter

            # Layout the primary visual asset on the left
            if tables:
                tbl = tables[0]
                has_cap = bool(tbl.caption or tbl.xref_label)
                tbl_h = BODY_HEIGHT - 60.0 if has_cap else BODY_HEIGHT

                elements.append(
                    LayoutElement(
                        element_id=f"slide_{slide.index}_table_1",
                        source_block_id=tbl.source_table_id,
                        element_type=ElementType.TABLE,
                        role=BlockRole.CALLOUT,
                        geometry=Rect(x=BODY_X, y=BODY_Y, width=left_w, height=tbl_h),
                        style=ElementStyle(
                            background_color="#FFFFFF",
                            border_color="#CBD5E1",
                            border_width=1.0,
                            corner_radius=4.0,
                        ),
                        content={
                            "source_table_id": tbl.source_table_id,
                            "caption": tbl.caption,
                            "xref_label": tbl.xref_label,
                            "highlight_cells": tbl.highlight_cells,
                        },
                        z_index=1,
                    )
                )

                if has_cap:
                    cap_text = f"{tbl.xref_label}: {tbl.caption}".strip(" :")
                    elements.append(
                        LayoutElement(
                            element_id=f"slide_{slide.index}_tbl_caption_1",
                            source_block_id=f"{tbl.source_table_id}_caption",
                            element_type=ElementType.TEXT,
                            role=BlockRole.CAPTION,
                            geometry=Rect(x=BODY_X, y=BODY_Y + tbl_h + 8.0, width=left_w, height=52.0),
                            style=ElementStyle(
                                text=TextStyle(
                                    font_size=13.0,
                                    font_weight="normal",
                                    alignment="center",
                                    color="#64748B",
                                    italic=True,
                                )
                            ),
                            content=cap_text,
                            z_index=1,
                        )
                    )

            elif figures:
                fig = figures[0]
                has_cap = bool(fig.caption or fig.xref_label)
                fig_h = BODY_HEIGHT - 60.0 if has_cap else BODY_HEIGHT

                elements.append(
                    LayoutElement(
                        element_id=f"slide_{slide.index}_figure_1",
                        source_block_id=fig.source_figure_id,
                        element_type=ElementType.FIGURE,
                        role=BlockRole.CALLOUT,
                        geometry=Rect(x=BODY_X, y=BODY_Y, width=left_w, height=fig_h),
                        style=ElementStyle(
                            background_color="#F8FAFC",
                            border_color="#CBD5E1",
                            border_width=1.0,
                            corner_radius=6.0,
                        ),
                        content={
                            "source_figure_id": fig.source_figure_id,
                            "caption": fig.caption,
                            "xref_label": fig.xref_label,
                        },
                        z_index=1,
                    )
                )

                if has_cap:
                    cap_text = f"{fig.xref_label}: {fig.caption}".strip(" :")
                    elements.append(
                        LayoutElement(
                            element_id=f"slide_{slide.index}_fig_caption_1",
                            source_block_id=f"{fig.source_figure_id}_caption",
                            element_type=ElementType.TEXT,
                            role=BlockRole.CAPTION,
                            geometry=Rect(x=BODY_X, y=BODY_Y + fig_h + 8.0, width=left_w, height=52.0),
                            style=ElementStyle(
                                text=TextStyle(
                                    font_size=13.0,
                                    font_weight="normal",
                                    alignment="center",
                                    color="#64748B",
                                    italic=True,
                                )
                            ),
                            content=cap_text,
                            z_index=1,
                        )
                    )

            # Layout takeaways / insights on the right column
            if texts:
                n_texts = len(texts)
                gap = 14.0
                total_gaps = (n_texts - 1) * gap
                card_h = max(70.0, (BODY_HEIGHT - total_gaps) / n_texts)

                curr_y = BODY_Y
                for idx, t in enumerate(texts):
                    elements.append(
                        LayoutElement(
                            element_id=f"slide_{slide.index}_takeaway_{idx + 1}",
                            source_block_id=f"text_{idx + 1}",
                            element_type=ElementType.TEXT,
                            role=t.role,
                            geometry=Rect(x=right_x, y=curr_y, width=right_w, height=card_h),
                            style=ElementStyle(
                                background_color="#EFF6FF" if t.emphasis else "#F8FAFC",
                                border_color="#BFDBFE" if t.emphasis else "#E2E8F0",
                                border_width=1.0,
                                corner_radius=6.0,
                                padding=12.0,
                                text=TextStyle(
                                    font_size=15.0 if n_texts > 3 else 16.0,
                                    font_weight="bold" if t.emphasis else "normal",
                                    line_height=1.25,
                                    color="#1E3A8A" if t.emphasis else "#1E293B",
                                ),
                            ),
                            content=t.content,
                            z_index=1,
                        )
                    )
                    curr_y += card_h + gap

        else:
            # Fallback when no visual assets: Full-width stacked comparison cards
            n_texts = max(1, len(texts))
            gap = 16.0
            total_gaps = (n_texts - 1) * gap
            card_h = max(70.0, (BODY_HEIGHT - total_gaps) / n_texts)

            curr_y = BODY_Y
            for idx, t in enumerate(texts):
                elements.append(
                    LayoutElement(
                        element_id=f"slide_{slide.index}_result_{idx + 1}",
                        source_block_id=f"text_{idx + 1}",
                        element_type=ElementType.TEXT,
                        role=t.role,
                        geometry=Rect(x=BODY_X, y=curr_y, width=BODY_WIDTH, height=card_h),
                        style=ElementStyle(
                            background_color="#F8FAFC",
                            border_color="#E2E8F0",
                            border_width=1.0,
                            corner_radius=8.0,
                            padding=16.0,
                            text=TextStyle(
                                font_size=17.0,
                                font_weight="bold" if t.emphasis else "normal",
                                line_height=1.3,
                                color="#1E293B",
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
            metadata={"template": "BenchmarkComparisonTemplate"},
        )
