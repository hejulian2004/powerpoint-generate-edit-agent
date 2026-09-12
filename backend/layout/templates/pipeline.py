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
from .base import (
    BaseLayoutTemplate,
    compute_layout_zones,
    create_header_elements,
    stack_visual_assets,
)


class PipelineArchitectureTemplate(BaseLayoutTemplate):
    """Layout template for VisualIntent.PIPELINE_ARCHITECTURE."""

    def layout(self, slide: SlideSpec, canvas: Canvas) -> LayoutSpec:
        elements: List[LayoutElement] = []
        zones = compute_layout_zones(canvas)

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
                            source_block_id=t.block_id or f"text_{idx + 1}",
                            source_evidence_ids=list(getattr(t, "source_evidence_ids", [])),
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

            # Right column: All visual assets. Every figure/table is stacked so
            # none is silently omitted (compiled to an asset or explicit placeholder).
            visual_assets = [
                b for b in slide.blocks if isinstance(b, (FigureBlock, TableBlock))
            ]
            elements.extend(
                stack_visual_assets(
                    slide,
                    visual_assets,
                    Rect(
                        x=right_x,
                        y=zones.body_y,
                        width=right_w,
                        height=zones.body_height,
                    ),
                    canvas=canvas,
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
                        source_block_id=t.block_id or f"text_{idx + 1}",
                        source_evidence_ids=list(getattr(t, "source_evidence_ids", [])),
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

        return LayoutSpec(
            slide_id=f"slide_{slide.index}",
            slide_index=slide.index,
            visual_intent=slide.visual_intent,
            canvas=canvas,
            elements=elements,
            speaker_notes=slide.speaker_notes,
            metadata=metadata,
        )
