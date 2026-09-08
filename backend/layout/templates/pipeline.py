"""PIPELINE_ARCHITECTURE Layout Template (PR10).

Synthesizes geometry for system workflows, multi-stage pipelines, and architecture
diagrams (left text explanation stages + right visual architecture figure).
"""

from __future__ import annotations

from typing import Any, Dict, List

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
from .base import BaseLayoutTemplate, compute_layout_zones, create_header_elements


class PipelineArchitectureTemplate(BaseLayoutTemplate):
    """Layout template for VisualIntent.PIPELINE_ARCHITECTURE."""

    def layout(self, slide: SlideSpec, canvas: Canvas) -> LayoutSpec:
        elements: List[LayoutElement] = []
        zones = compute_layout_zones(canvas)
        omitted_blocks: List[str] = []

        # 1. Header Elements
        elements.extend(create_header_elements(slide, canvas=canvas))

        # 2. Body Partitioning
        figures = [b for b in slide.blocks if isinstance(b, FigureBlock)]
        tables = [b for b in slide.blocks if isinstance(b, TableBlock)]
        texts = [b for b in slide.blocks if isinstance(b, TextBlock)]

        if figures or tables:
            # Asymmetric 2-column: Left = Explanations (~40%), Right = Diagram/Table (~60%)
            gutter = 24.0 * (canvas.width / 1280.0)
            left_w = (zones.body_width - gutter) * 0.41
            right_w = zones.body_width - left_w - gutter
            right_x = zones.body_x + left_w + gutter

            # Left column: Text blocks with adaptive spacing to prevent overflow
            if texts:
                n_texts = len(texts)
                gap = max(6.0, min(16.0, (zones.body_height / n_texts) * 0.2)) if n_texts > 1 else 0.0
                total_gaps = (n_texts - 1) * gap
                avail_h = zones.body_height - total_gaps
                item_h = max(32.0, avail_h / n_texts)

                if item_h < 50.0:
                    font_sz = 14.0
                    pad = 6.0
                elif item_h < 65.0:
                    font_sz = 15.0
                    pad = 10.0
                else:
                    font_sz = 16.0 if n_texts > 3 else 17.0
                    pad = 12.0 if any(t.emphasis for t in texts) else 6.0

                curr_y = zones.body_y
                for idx, t in enumerate(texts):
                    elements.append(
                        LayoutElement(
                            element_id=f"slide_{slide.index}_text_{idx + 1}",
                            source_block_id=f"text_{idx + 1}",
                            element_type=ElementType.TEXT,
                            role=t.role,
                            geometry=Rect(x=zones.body_x, y=curr_y, width=left_w, height=item_h),
                            style=ElementStyle(
                                background_color="#F8FAFC" if t.emphasis else None,
                                border_color="#E2E8F0" if t.emphasis else None,
                                border_width=1.0 if t.emphasis else 0.0,
                                corner_radius=6.0 if t.emphasis else 0.0,
                                padding=pad if t.emphasis else 4.0,
                                text=TextStyle(
                                    font_size=font_sz,
                                    font_weight="bold" if t.emphasis else "normal",
                                    line_height=1.25,
                                    color="#1E293B",
                                ),
                            ),
                            content=t.content,
                            z_index=1,
                        )
                    )
                    curr_y += item_h + gap

            # Right column: Primary visual asset (Figure prioritized over Table)
            if figures:
                fig = figures[0]
                # Track any omitted additional figures or tables
                for f in figures[1:]:
                    omitted_blocks.append(f.source_figure_id)
                for tb in tables:
                    omitted_blocks.append(tb.source_table_id)

                has_caption = bool(fig.caption or fig.xref_label)
                cap_h = 52.0 if has_caption else 0.0
                fig_h = zones.body_height - cap_h - (8.0 if has_caption else 0.0)
                fig_geo = Rect(x=right_x, y=zones.body_y, width=right_w, height=fig_h)

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
                            geometry=Rect(x=right_x, y=zones.body_y + fig_h + 8.0, width=right_w, height=cap_h),
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
                for tb in tables[1:]:
                    omitted_blocks.append(tb.source_table_id)

                has_caption = bool(tbl.caption or tbl.xref_label)
                cap_h = 52.0 if has_caption else 0.0
                tbl_h = zones.body_height - cap_h - (8.0 if has_caption else 0.0)

                elements.append(
                    LayoutElement(
                        element_id=f"slide_{slide.index}_table_1",
                        source_block_id=tbl.source_table_id,
                        element_type=ElementType.TABLE,
                        role=BlockRole.CALLOUT,
                        geometry=Rect(x=right_x, y=zones.body_y, width=right_w, height=tbl_h),
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
                            geometry=Rect(x=right_x, y=zones.body_y + tbl_h + 8.0, width=right_w, height=cap_h),
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
            gap = max(6.0, min(16.0, (zones.body_height / n_texts) * 0.2)) if n_texts > 1 else 0.0
            total_gaps = (n_texts - 1) * gap
            avail_h = zones.body_height - total_gaps
            item_h = max(32.0, avail_h / n_texts)

            if item_h < 50.0:
                font_sz = 14.0
                pad = 8.0
            elif item_h < 65.0:
                font_sz = 15.0
                pad = 12.0
            else:
                font_sz = 17.0
                pad = 16.0

            curr_y = zones.body_y
            for idx, t in enumerate(texts):
                elements.append(
                    LayoutElement(
                        element_id=f"slide_{slide.index}_stage_{idx + 1}",
                        source_block_id=f"text_{idx + 1}",
                        element_type=ElementType.TEXT,
                        role=t.role,
                        geometry=Rect(x=zones.body_x, y=curr_y, width=zones.body_width, height=item_h),
                        style=ElementStyle(
                            background_color="#F8FAFC",
                            border_color="#E2E8F0",
                            border_width=1.0,
                            corner_radius=8.0,
                            padding=pad,
                            text=TextStyle(
                                font_size=font_sz,
                                font_weight="bold" if t.emphasis else "normal",
                                line_height=1.3,
                                color="#1E293B",
                            ),
                        ),
                        content=t.content,
                        z_index=1,
                    )
                )
                curr_y += item_h + gap

        metadata: Dict[str, Any] = {"template": "PipelineArchitectureTemplate"}
        if omitted_blocks:
            metadata["omitted_blocks"] = omitted_blocks

        return LayoutSpec(
            slide_id=f"slide_{slide.index}",
            slide_index=slide.index,
            visual_intent=slide.visual_intent,
            canvas=canvas,
            elements=elements,
            speaker_notes=slide.speaker_notes,
            metadata=metadata,
        )
