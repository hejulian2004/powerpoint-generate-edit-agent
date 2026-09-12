"""BENCHMARK_COMPARISON Layout Template (PR10).

Synthesizes geometry for empirical results, benchmark comparisons, and experimental setups
(Left asset: Table / Figure + Right analytical takeaway cards).
"""

from __future__ import annotations

from typing import Any, Dict, List

from ...slidespec.schema import BadgeBlock, BlockRole, FigureBlock, SlideSpec, TableBlock, TextBlock
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


def _badge_style(variant: str) -> ElementStyle:
    if variant == "success":
        bg, border, color = "#F0FDF4", "#22C55E", "#15803D"
    elif variant == "accent":
        bg, border, color = "#FDF4FF", "#C084FC", "#7E22CE"
    elif variant == "neutral":
        bg, border, color = "#F1F5F9", "#94A3B8", "#334155"
    else:  # primary
        bg, border, color = "#EFF6FF", "#3B82F6", "#1D4ED8"
    return ElementStyle(
        background_color=bg,
        border_color=border,
        border_width=1.0,
        corner_radius=6.0,
        padding=8.0,
        text=TextStyle(
            font_size=14.0,
            font_weight="bold",
            alignment="center",
            line_height=1.2,
            color=color,
        ),
    )


class BenchmarkComparisonTemplate(BaseLayoutTemplate):
    """Layout template for VisualIntent.BENCHMARK_COMPARISON."""

    def layout(self, slide: SlideSpec, canvas: Canvas) -> LayoutSpec:
        elements: List[LayoutElement] = []
        zones = compute_layout_zones(canvas)

        # 1. Header Elements
        elements.extend(create_header_elements(slide, canvas=canvas))

        # 2. Extract content blocks
        tables = [b for b in slide.blocks if isinstance(b, TableBlock)]
        figures = [b for b in slide.blocks if isinstance(b, FigureBlock)]
        texts = [b for b in slide.blocks if isinstance(b, TextBlock)]
        badges = [b for b in slide.blocks if isinstance(b, BadgeBlock)]

        has_visual_asset = bool(tables or figures)

        if has_visual_asset:
            # 60% Left Asset, 40% Right Insights
            gutter = 28.0 * (canvas.width / 1280.0)
            left_w = (zones.body_width - gutter) * 0.60
            right_w = zones.body_width - left_w - gutter
            right_x = zones.body_x + left_w + gutter

            # Left column: every visual source asset (figures + tables) is stacked so
            # none is silently omitted (compiled to an asset or explicit placeholder).
            visual_assets = [
                b for b in slide.blocks if isinstance(b, (FigureBlock, TableBlock))
            ]
            elements.extend(
                stack_visual_assets(
                    slide,
                    visual_assets,
                    Rect(
                        x=zones.body_x,
                        y=zones.body_y,
                        width=left_w,
                        height=zones.body_height,
                    ),
                    canvas=canvas,
                )
            )

            # Layout takeaways / insights on the right column with adaptive height
            right_body_y = zones.body_y
            right_body_h = zones.body_height

            if badges:
                b_h = 36.0 * (canvas.height / 720.0)
                b_gap = 8.0 * (canvas.width / 1280.0)
                n_b = len(badges)
                b_w = (right_w - (n_b - 1) * b_gap) / n_b
                bx = right_x
                for b_idx, b in enumerate(badges):
                    elements.append(
                        LayoutElement(
                            element_id=f"slide_{slide.index}_badge_{b_idx + 1}",
                            source_block_id=b.block_id or f"badge_{b_idx + 1}",
                            source_evidence_ids=list(getattr(b, "source_evidence_ids", [])),
                            element_type=ElementType.BADGE,
                            role=BlockRole.CALLOUT,
                            geometry=Rect(x=bx, y=right_body_y, width=b_w, height=b_h),
                            style=_badge_style(b.variant),
                            content=b.text,
                            z_index=1,
                        )
                    )
                    bx += b_w + b_gap
                right_body_y += b_h + 12.0
                right_body_h = max(40.0, right_body_h - (b_h + 12.0))

            if texts:
                n_texts = len(texts)
                gap = max(6.0, min(14.0, (right_body_h / n_texts) * 0.2)) if n_texts > 1 else 0.0
                total_gaps = (n_texts - 1) * gap
                avail_h = right_body_h - total_gaps
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

                curr_y = right_body_y
                for idx, t in enumerate(texts):
                    elements.append(
                        LayoutElement(
                            element_id=f"slide_{slide.index}_takeaway_{idx + 1}",
                            source_block_id=t.block_id or f"text_{idx + 1}",
                            source_evidence_ids=list(getattr(t, "source_evidence_ids", [])),
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
            body_y = zones.body_y
            body_h = zones.body_height

            if badges:
                b_h = 40.0 * (canvas.height / 720.0)
                b_gap = 12.0 * (canvas.width / 1280.0)
                n_b = len(badges)
                b_w = (zones.body_width - (n_b - 1) * b_gap) / n_b
                bx = zones.body_x
                for b_idx, b in enumerate(badges):
                    elements.append(
                        LayoutElement(
                            element_id=f"slide_{slide.index}_badge_{b_idx + 1}",
                            source_block_id=b.block_id or f"badge_{b_idx + 1}",
                            source_evidence_ids=list(getattr(b, "source_evidence_ids", [])),
                            element_type=ElementType.BADGE,
                            role=BlockRole.CALLOUT,
                            geometry=Rect(x=bx, y=body_y, width=b_w, height=b_h),
                            style=_badge_style(b.variant),
                            content=b.text,
                            z_index=1,
                        )
                    )
                    bx += b_w + b_gap
                body_y += b_h + 14.0
                body_h = max(40.0, body_h - (b_h + 14.0))

            if texts:
                n_texts = max(1, len(texts))
                gap = max(6.0, min(16.0, (body_h / n_texts) * 0.2)) if n_texts > 1 else 0.0
                total_gaps = (n_texts - 1) * gap
                avail_h = body_h - total_gaps
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

                curr_y = body_y
                for idx, t in enumerate(texts):
                    elements.append(
                        LayoutElement(
                            element_id=f"slide_{slide.index}_result_{idx + 1}",
                            source_block_id=t.block_id or f"text_{idx + 1}",
                            source_evidence_ids=list(getattr(t, "source_evidence_ids", [])),
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

        return LayoutSpec(
            slide_id=f"slide_{slide.index}",
            slide_index=slide.index,
            visual_intent=slide.visual_intent,
            canvas=canvas,
            elements=elements,
            speaker_notes=slide.speaker_notes,
            metadata=metadata,
        )
