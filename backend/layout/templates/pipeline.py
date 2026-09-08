"""PIPELINE_ARCHITECTURE Layout Template (PR10).

Synthesizes geometry for system workflows, multi-stage pipelines, and architecture
diagrams (left text explanation stages + right visual architecture figure).
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


class PipelineArchitectureTemplate(BaseLayoutTemplate):
    """Layout template for VisualIntent.PIPELINE_ARCHITECTURE."""

    def layout(self, slide: SlideSpec, canvas: Canvas) -> LayoutSpec:
        elements: List[LayoutElement] = []

        # 1. Header Elements
        elements.extend(create_header_elements(slide))

        # 2. Body Partitioning
        figures = [b for b in slide.blocks if isinstance(b, FigureBlock)]
        tables = [b for b in slide.blocks if isinstance(b, TableBlock)]
        texts = [b for b in slide.blocks if isinstance(b, TextBlock)]

        if figures or tables:
            # Asymmetric 2-column: Left = Explanations (460px), Right = Diagram/Table (668px)
            left_w = 460.0
            gutter = 24.0
            right_w = BODY_WIDTH - left_w - gutter  # 668.0
            right_x = BODY_X + left_w + gutter

            # Left column: Text blocks
            if texts:
                n_texts = len(texts)
                item_gap = 16.0
                total_gaps = (n_texts - 1) * item_gap
                item_h = max(60.0, (BODY_HEIGHT - total_gaps) / n_texts)

                curr_y = BODY_Y
                for idx, t in enumerate(texts):
                    elements.append(
                        LayoutElement(
                            element_id=f"slide_{slide.index}_text_{idx + 1}",
                            source_block_id=f"text_{idx + 1}",
                            element_type=ElementType.TEXT,
                            role=t.role,
                            geometry=Rect(x=BODY_X, y=curr_y, width=left_w, height=item_h),
                            style=ElementStyle(
                                background_color="#F8FAFC" if t.emphasis else None,
                                border_color="#E2E8F0" if t.emphasis else None,
                                border_width=1.0 if t.emphasis else 0.0,
                                corner_radius=6.0 if t.emphasis else 0.0,
                                padding=12.0 if t.emphasis else 4.0,
                                text=TextStyle(
                                    font_size=16.0 if n_texts > 3 else 17.0,
                                    font_weight="bold" if t.emphasis else "normal",
                                    line_height=1.25,
                                    color="#1E293B",
                                ),
                            ),
                            content=t.content,
                            z_index=1,
                        )
                    )
                    curr_y += item_h + item_gap

            # Right column: Visual Asset (Figure or Table)
            if figures:
                fig = figures[0]
                has_caption = bool(fig.caption or fig.xref_label)
                fig_h = BODY_HEIGHT - 60.0 if has_caption else BODY_HEIGHT
                fig_geo = Rect(x=right_x, y=BODY_Y, width=right_w, height=fig_h)

                elements.append(
                    LayoutElement(
                        element_id=f"slide_{slide.index}_figure_1",
                        source_block_id=fig.source_figure_id,
                        element_type=ElementType.FIGURE,
                        role=BlockRole.CALLOUT,
                        geometry=fig_geo,
                        style=ElementStyle(
                            background_color="#F1F5F9",
                            border_color="#CBD5E1",
                            border_width=1.0,
                            corner_radius=8.0,
                        ),
                        content={
                            "source_figure_id": fig.source_figure_id,
                            "caption": fig.caption,
                            "xref_label": fig.xref_label,
                        },
                        z_index=1,
                    )
                )

                if has_caption:
                    caption_text = f"{fig.xref_label}: {fig.caption}".strip(" :")
                    elements.append(
                        LayoutElement(
                            element_id=f"slide_{slide.index}_fig_caption_1",
                            source_block_id=f"{fig.source_figure_id}_caption",
                            element_type=ElementType.TEXT,
                            role=BlockRole.CAPTION,
                            geometry=Rect(x=right_x, y=BODY_Y + fig_h + 8.0, width=right_w, height=52.0),
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

            elif tables:
                tbl = tables[0]
                has_caption = bool(tbl.caption or tbl.xref_label)
                tbl_h = BODY_HEIGHT - 60.0 if has_caption else BODY_HEIGHT

                elements.append(
                    LayoutElement(
                        element_id=f"slide_{slide.index}_table_1",
                        source_block_id=tbl.source_table_id,
                        element_type=ElementType.TABLE,
                        role=BlockRole.CALLOUT,
                        geometry=Rect(x=right_x, y=BODY_Y, width=right_w, height=tbl_h),
                        style=ElementStyle(
                            background_color="#FFFFFF",
                            border_color="#E2E8F0",
                            border_width=1.0,
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

                if has_caption:
                    caption_text = f"{tbl.xref_label}: {tbl.caption}".strip(" :")
                    elements.append(
                        LayoutElement(
                            element_id=f"slide_{slide.index}_tbl_caption_1",
                            source_block_id=f"{tbl.source_table_id}_caption",
                            element_type=ElementType.TEXT,
                            role=BlockRole.CAPTION,
                            geometry=Rect(x=right_x, y=BODY_Y + tbl_h + 8.0, width=right_w, height=52.0),
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

        else:
            # Fallback when no visual assets: Full-width stacked stages
            n_texts = max(1, len(texts))
            item_gap = 16.0
            total_gaps = (n_texts - 1) * item_gap
            item_h = max(60.0, (BODY_HEIGHT - total_gaps) / n_texts)

            curr_y = BODY_Y
            for idx, t in enumerate(texts):
                elements.append(
                    LayoutElement(
                        element_id=f"slide_{slide.index}_stage_{idx + 1}",
                        source_block_id=f"text_{idx + 1}",
                        element_type=ElementType.TEXT,
                        role=t.role,
                        geometry=Rect(x=BODY_X, y=curr_y, width=BODY_WIDTH, height=item_h),
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
                curr_y += item_h + item_gap

        return LayoutSpec(
            slide_id=f"slide_{slide.index}",
            slide_index=slide.index,
            visual_intent=slide.visual_intent,
            canvas=canvas,
            elements=elements,
            speaker_notes=slide.speaker_notes,
            metadata={"template": "PipelineArchitectureTemplate"},
        )
