"""BENCHMARK_COMPARISON Layout Template (PR10).

Synthesizes geometry for empirical results, benchmark comparisons, and experimental setups
(Left asset: Table / Figure + Right analytical takeaway cards).
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


class BenchmarkComparisonTemplate(BaseLayoutTemplate):
    """Layout template for VisualIntent.BENCHMARK_COMPARISON."""

    def layout(self, slide: SlideSpec, canvas: Canvas) -> LayoutSpec:
        elements: List[LayoutElement] = []
        zones = compute_layout_zones(canvas)
        omitted_blocks: List[str] = []

        # 1. Header Elements
        elements.extend(create_header_elements(slide, canvas=canvas))

        # 2. Extract content blocks
        tables = [b for b in slide.blocks if isinstance(b, TableBlock)]
        figures = [b for b in slide.blocks if isinstance(b, FigureBlock)]
        texts = [b for b in slide.blocks if isinstance(b, TextBlock)]

        has_visual_asset = bool(tables or figures)

        if has_visual_asset:
            # 60% Left Asset, 40% Right Insights
            gutter = 28.0 * (canvas.width / 1280.0)
            left_w = (zones.body_width - gutter) * 0.60
            right_w = zones.body_width - left_w - gutter
            right_x = zones.body_x + left_w + gutter

            # Layout the primary visual asset on the left (Table prioritized over Figure)
            if tables:
                tbl = tables[0]
                for tb in tables[1:]:
                    omitted_blocks.append(tb.source_table_id)
                for f in figures:
                    omitted_blocks.append(f.source_figure_id)

                has_cap = bool(tbl.caption or tbl.xref_label)
                cap_h = 52.0 if has_cap else 0.0
                tbl_h = zones.body_height - cap_h - (8.0 if has_cap else 0.0)

                elements.append(
                    LayoutElement(
                        element_id=f"slide_{slide.index}_table_1",
                        source_block_id=tbl.source_table_id,
                        element_type=ElementType.TABLE,
                        role=BlockRole.CALLOUT,
                        geometry=Rect(x=zones.body_x, y=zones.body_y, width=left_w, height=tbl_h),
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
                            "columns": getattr(tbl, "columns", []),
                            "rows": getattr(tbl, "rows", []),
                            "placeholder": getattr(tbl, "placeholder", False),
                            "source_page": getattr(tbl, "source_page", None),
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
                            geometry=Rect(x=zones.body_x, y=zones.body_y + tbl_h + 8.0, width=left_w, height=cap_h),
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
                for f in figures[1:]:
                    omitted_blocks.append(f.source_figure_id)

                has_cap = bool(fig.caption or fig.xref_label)
                cap_h = 52.0 if has_cap else 0.0
                fig_h = zones.body_height - cap_h - (8.0 if has_cap else 0.0)

                elements.append(
                    LayoutElement(
                        element_id=f"slide_{slide.index}_figure_1",
                        source_block_id=fig.source_figure_id,
                        element_type=ElementType.FIGURE,
                        role=BlockRole.CALLOUT,
                        geometry=Rect(x=zones.body_x, y=zones.body_y, width=left_w, height=fig_h),
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
                            "placeholder": getattr(fig, "placeholder", True),
                            "source_page": getattr(fig, "source_page", None),
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
                            geometry=Rect(x=zones.body_x, y=zones.body_y + fig_h + 8.0, width=left_w, height=cap_h),
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

            # Layout takeaways / insights on the right column with adaptive height
            if texts:
                n_texts = len(texts)
                gap = max(6.0, min(14.0, (zones.body_height / n_texts) * 0.2)) if n_texts > 1 else 0.0
                total_gaps = (n_texts - 1) * gap
                avail_h = zones.body_height - total_gaps
                card_h = max(32.0, avail_h / n_texts)

                if card_h < 50.0:
                    font_sz = 14.0
                    pad = 6.0
                elif card_h < 65.0:
                    font_sz = 15.0
                    pad = 10.0
                else:
                    font_sz = 15.0 if n_texts > 3 else 16.0
                    pad = 12.0

                curr_y = zones.body_y
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
                                padding=pad,
                                text=TextStyle(
                                    font_size=font_sz,
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
            gap = max(6.0, min(16.0, (zones.body_height / n_texts) * 0.2)) if n_texts > 1 else 0.0
            total_gaps = (n_texts - 1) * gap
            avail_h = zones.body_height - total_gaps
            card_h = max(32.0, avail_h / n_texts)

            if card_h < 50.0:
                font_sz = 14.0
                pad = 8.0
            elif card_h < 65.0:
                font_sz = 15.0
                pad = 12.0
            else:
                font_sz = 17.0
                pad = 16.0

            curr_y = zones.body_y
            for idx, t in enumerate(texts):
                elements.append(
                    LayoutElement(
                        element_id=f"slide_{slide.index}_result_{idx + 1}",
                        source_block_id=f"text_{idx + 1}",
                        element_type=ElementType.TEXT,
                        role=t.role,
                        geometry=Rect(x=zones.body_x, y=curr_y, width=zones.body_width, height=card_h),
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
                curr_y += card_h + gap

        metadata: Dict[str, Any] = {"template": "BenchmarkComparisonTemplate"}
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
