"""TITLE_HERO Layout Template (PR10).

Synthesizes geometry for title / hero slides with centered academic typography,
author & affiliation metadata, and conference / venue pill badges.
"""

from __future__ import annotations

from typing import List

from ...slidespec.schema import BadgeBlock, BlockRole, SlideSpec, TextBlock
from ..schema import (
    Canvas,
    ElementStyle,
    ElementType,
    LayoutElement,
    LayoutSpec,
    Rect,
    TextStyle,
)
from .base import BaseLayoutTemplate


class TitleHeroTemplate(BaseLayoutTemplate):
    """Layout template for VisualIntent.TITLE_HERO."""

    def layout(self, slide: SlideSpec, canvas: Canvas) -> LayoutSpec:
        elements: List[LayoutElement] = []
        center_x = canvas.width / 2.0

        # 1. Main Paper Title
        title_text = slide.title.strip() if slide.title else "Academic Research Presentation"
        title_w = 1100.0
        title_h = 160.0
        title_x = center_x - (title_w / 2.0)
        title_y = 160.0

        elements.append(
            LayoutElement(
                element_id=f"slide_{slide.index}_title_hero",
                source_block_id="title",
                element_type=ElementType.TEXT,
                role=BlockRole.HEADING,
                geometry=Rect(x=title_x, y=title_y, width=title_w, height=title_h),
                style=ElementStyle(
                    text=TextStyle(
                        font_size=36.0,
                        font_weight="bold",
                        alignment="center",
                        line_height=1.2,
                        color="#0F172A",
                    )
                ),
                content=title_text,
                z_index=1,
            )
        )

        # 2. Subtitle / Authors / Affiliations
        curr_y = title_y + title_h + 20.0
        sub_text = slide.subtitle.strip() if slide.subtitle else ""
        if not sub_text:
            # Check if any lead summary or subtitle text block exists
            for b in slide.blocks:
                if isinstance(b, TextBlock) and b.role in (BlockRole.SUBHEADING, BlockRole.LEAD_SUMMARY):
                    sub_text = b.content.strip()
                    break

        if sub_text:
            sub_w = 1000.0
            sub_h = 70.0
            sub_x = center_x - (sub_w / 2.0)
            elements.append(
                LayoutElement(
                    element_id=f"slide_{slide.index}_subtitle",
                    source_block_id="subtitle",
                    element_type=ElementType.TEXT,
                    role=BlockRole.SUBHEADING,
                    geometry=Rect(x=sub_x, y=curr_y, width=sub_w, height=sub_h),
                    style=ElementStyle(
                        text=TextStyle(
                            font_size=18.0,
                            font_weight="normal",
                            alignment="center",
                            line_height=1.25,
                            color="#475569",
                        )
                    ),
                    content=sub_text,
                    z_index=1,
                )
            )
            curr_y += sub_h + 24.0
        else:
            curr_y += 24.0

        # 3. Badges (e.g., Conference / Venue / Year)
        badges = [b for b in slide.blocks if isinstance(b, BadgeBlock)]
        if badges:
            badge_h = 36.0
            badge_spacing = 16.0
            badge_widths = [
                max(110.0, min(300.0, len(b.text) * 11.0 + 36.0))
                for b in badges
            ]
            total_badges_w = sum(badge_widths) + (len(badges) - 1) * badge_spacing
            start_x = max(64.0, center_x - (total_badges_w / 2.0))

            cur_bx = start_x
            for idx, badge in enumerate(badges):
                bw = badge_widths[idx]
                elements.append(
                    LayoutElement(
                        element_id=f"slide_{slide.index}_badge_{idx + 1}",
                        source_block_id=f"badge_{idx + 1}",
                        element_type=ElementType.BADGE,
                        role=BlockRole.BADGE,
                        geometry=Rect(x=cur_bx, y=curr_y, width=bw, height=badge_h),
                        style=ElementStyle(
                            background_color="#F1F5F9",
                            border_color="#CBD5E1",
                            border_width=1.0,
                            corner_radius=18.0,
                            padding=8.0,
                            text=TextStyle(
                                font_size=13.0,
                                font_weight="bold",
                                alignment="center",
                                vertical_alignment="middle",
                                color="#0F172A",
                            ),
                        ),
                        content=badge.text,
                        z_index=2,
                    )
                )
                cur_bx += bw + badge_spacing

        return LayoutSpec(
            slide_id=f"slide_{slide.index}",
            slide_index=slide.index,
            visual_intent=slide.visual_intent,
            canvas=canvas,
            elements=elements,
            speaker_notes=slide.speaker_notes,
            metadata={"template": "TitleHeroTemplate"},
        )
