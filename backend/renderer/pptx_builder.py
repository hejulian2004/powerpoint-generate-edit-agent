"""PPTX Builder Layer (PR11).

Strictly encapsulates python-pptx operations into high-level presentation and shape builders.
Ensures no application logic directly touches OOXML or low-level shape APIs.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

from ..layout.schema import BlockRole, Canvas, ElementType, LayoutElement, LayoutSpec, Rect
from .schema import EMU_PER_PX
from .theme import AcademicTheme, hex_to_rgb
from .typography import (
    apply_paragraph_style,
    px_to_emu,
    resolve_alignment,
    resolve_element_typography,
    resolve_vertical_alignment,
)


class PPTXBuilder:
    """Encapsulates python-pptx presentation construction, shape generation, and saving."""

    def __init__(self, canvas: Optional[Canvas] = None):
        self.canvas = canvas or Canvas(width=1280.0, height=720.0)
        self.prs = Presentation()

        # Compute slide width and height in EMUs matching the canvas
        self.slide_width_emu = int(round(self.canvas.width * EMU_PER_PX))
        self.slide_height_emu = int(round(self.canvas.height * EMU_PER_PX))
        self.prs.slide_width = self.slide_width_emu
        self.prs.slide_height = self.slide_height_emu

        # Use the completely blank slide layout (index 6 in default template)
        self.blank_layout = self.prs.slide_layouts[6]

        self._current_slide = None
        self._current_slide_spec: Optional[LayoutSpec] = None

    def add_slide(self, slide_spec: LayoutSpec) -> Any:
        """Instantiate a new blank slide for the given LayoutSpec."""
        self._current_slide = self.prs.slides.add_slide(self.blank_layout)
        self._current_slide_spec = slide_spec

        if slide_spec.speaker_notes:
            self.set_speaker_notes(slide_spec.speaker_notes)

        return self._current_slide

    def set_speaker_notes(self, notes: str) -> None:
        """Attach speaker notes to current slide."""
        if not self._current_slide or not notes:
            return
        notes_slide = self._current_slide.notes_slide
        tf = notes_slide.notes_text_frame
        tf.text = notes.strip()

    def _geo_to_emu(self, geo: Rect) -> Tuple[int, int, int, int]:
        """Convert a canvas Rect into PowerPoint (left, top, width, height) in EMUs."""
        left = int(round(geo.x * (self.slide_width_emu / self.canvas.width)))
        top = int(round(geo.y * (self.slide_height_emu / self.canvas.height)))
        width = int(round(geo.width * (self.slide_width_emu / self.canvas.width)))
        height = int(round(geo.height * (self.slide_height_emu / self.canvas.height)))
        return left, top, width, height

    def add_shape(self, element: LayoutElement, theme: AcademicTheme) -> Any:
        """Add a geometric shape or container (card, panel, badge) to the slide."""
        if not self._current_slide:
            raise RuntimeError("No active slide. Call add_slide() before adding elements.")

        left, top, width, height = self._geo_to_emu(element.geometry)

        # Decide shape type: rounded rectangle for badges and cards with corner radius
        is_rounded = (
            element.element_type == ElementType.BADGE
            or (element.style and element.style.corner_radius > 0.0)
        )
        shape_type = MSO_SHAPE.ROUNDED_RECTANGLE if is_rounded else MSO_SHAPE.RECTANGLE

        shape = self._current_slide.shapes.add_shape(shape_type, left, top, width, height)

        # 1. Fill
        bg_color = element.style.background_color if element.style else None
        if bg_color:
            shape.fill.solid()
            shape.fill.fore_color.rgb = RGBColor(*hex_to_rgb(bg_color))
        elif element.element_type == ElementType.BADGE:
            shape.fill.solid()
            shape.fill.fore_color.rgb = RGBColor(*hex_to_rgb(theme.colors.badge_primary_bg))
        else:
            shape.fill.solid()
            shape.fill.fore_color.rgb = RGBColor(*hex_to_rgb(theme.colors.surface))

        # 2. Border Line
        border_width = element.style.border_width if element.style else 0.0
        border_color = element.style.border_color if element.style else None
        if border_width > 0.0 and border_color:
            shape.line.color.rgb = RGBColor(*hex_to_rgb(border_color))
            shape.line.width = Pt(border_width)
        else:
            shape.line.fill.background()

        # 3. Badge Text inside Shape (if BADGE element)
        if element.element_type == ElementType.BADGE and element.content:
            tf = shape.text_frame
            tf.word_wrap = False
            tf.margin_left = Pt(4.0)
            tf.margin_top = Pt(2.0)
            tf.margin_right = Pt(4.0)
            tf.margin_bottom = Pt(2.0)
            tf.vertical_anchor = MSO_ANCHOR.MIDDLE

            badge_text = str(element.content).strip()
            font_size = (
                element.style.text.font_size
                if element.style and element.style.text
                else theme.fonts.badge.size
            )
            text_color_hex = (
                element.style.text.color
                if element.style and element.style.text and element.style.text.color
                else theme.colors.badge_primary_text
            )
            p = tf.paragraphs[0]
            apply_paragraph_style(
                paragraph=p,
                text=badge_text,
                font_size=font_size,
                font_family=theme.fonts.badge.font_family,
                bold=theme.fonts.badge.bold,
                italic=False,
                color_rgb=hex_to_rgb(text_color_hex),
                alignment=PP_ALIGN.CENTER,
            )

        return shape

    def add_text(self, element: LayoutElement, theme: AcademicTheme) -> Any:
        """Add a text box with precise typography and padding to the slide."""
        if not self._current_slide:
            raise RuntimeError("No active slide. Call add_slide() before adding elements.")

        left, top, width, height = self._geo_to_emu(element.geometry)
        shape = self._current_slide.shapes.add_textbox(left, top, width, height)
        tf = shape.text_frame
        tf.word_wrap = True

        # Inset padding
        pad = element.style.padding if element.style else 0.0
        tf.margin_left = Pt(pad)
        tf.margin_top = Pt(pad)
        tf.margin_right = Pt(pad)
        tf.margin_bottom = Pt(pad)

        # Vertical alignment
        v_align = (
            element.style.text.vertical_alignment
            if element.style and element.style.text
            else "top"
        )
        tf.vertical_anchor = resolve_vertical_alignment(v_align)

        # Typography resolution via theme
        font_size, font_family, bold, italic, color_rgb = resolve_element_typography(element, theme)

        align_str = (
            element.style.text.alignment
            if element.style and element.style.text
            else "left"
        )
        alignment = resolve_alignment(align_str)
        line_spacing = (
            element.style.text.line_height
            if element.style and element.style.text
            else theme.spacing.line_spacing
        )

        content = element.content
        if isinstance(content, list):
            lines = [str(x) for x in content]
        elif isinstance(content, str):
            lines = content.split("\n")
        elif content is None:
            lines = [""]
        else:
            lines = [str(content)]

        for idx, line in enumerate(lines):
            p = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
            # If multi-line bullet item, apply paragraph spacing
            space_after = theme.spacing.paragraph_after if len(lines) > 1 else 0.0
            apply_paragraph_style(
                paragraph=p,
                text=line,
                font_size=font_size,
                font_family=font_family,
                bold=bold,
                italic=italic,
                color_rgb=color_rgb,
                alignment=alignment,
                line_spacing=line_spacing,
                space_after=space_after,
            )

        return shape

    def add_image(self, element: LayoutElement, image_path: Union[str, Path], theme: AcademicTheme) -> Any:
        """Place an image onto the slide matching LayoutSpec geometry."""
        if not self._current_slide:
            raise RuntimeError("No active slide. Call add_slide() before adding elements.")

        left, top, width, height = self._geo_to_emu(element.geometry)
        img_str = str(Path(image_path).resolve())

        # python-pptx add_picture: geometry is strictly mapped from LayoutSpec
        picture = self._current_slide.shapes.add_picture(
            img_str,
            left=left,
            top=top,
            width=width,
            height=height,
        )
        return picture

    def add_table(self, element: LayoutElement, table_data: Dict[str, Any], theme: AcademicTheme) -> Any:
        """Render a structured academic presentation table."""
        if not self._current_slide:
            raise RuntimeError("No active slide. Call add_slide() before adding elements.")

        header: List[str] = table_data.get("header", [])
        rows: List[List[str]] = table_data.get("rows", [])
        highlight_cells: List[str] = table_data.get("highlight_cells", [])

        has_header = bool(header)
        total_rows = len(rows) + (1 if has_header else 0)
        total_cols = max(len(header) if has_header else 0, max((len(r) for r in rows), default=1))

        if total_rows == 0 or total_cols == 0:
            return None

        left, top, width, height = self._geo_to_emu(element.geometry)
        table_shape = self._current_slide.shapes.add_table(total_rows, total_cols, left, top, width, height)
        table = table_shape.table

        # Distribute column widths proportionally
        col_w = width // total_cols
        for c in range(total_cols):
            table.columns[c].width = col_w

        row_offset = 0

        # 1. Format Header Row
        if has_header:
            row_offset = 1
            for c_idx in range(total_cols):
                cell_text = header[c_idx] if c_idx < len(header) else ""
                cell = table.cell(0, c_idx)
                cell.fill.solid()
                cell.fill.fore_color.rgb = RGBColor(*hex_to_rgb(theme.colors.table_header_bg))
                cell.vertical_anchor = MSO_ANCHOR.MIDDLE

                p = cell.text_frame.paragraphs[0]
                align = PP_ALIGN.LEFT if c_idx == 0 else PP_ALIGN.CENTER
                apply_paragraph_style(
                    paragraph=p,
                    text=str(cell_text),
                    font_size=theme.fonts.table_header.size,
                    font_family=theme.fonts.table_header.font_family,
                    bold=theme.fonts.table_header.bold,
                    italic=False,
                    color_rgb=hex_to_rgb(theme.colors.table_header_text),
                    alignment=align,
                )

        # 2. Format Body Rows
        # Pre-parse and normalize highlight directives
        import re

        target_coords = set()
        target_rows = set()
        text_matchers = []

        for h in highlight_cells:
            if not isinstance(h, str) or not h.strip():
                continue
            item = h.strip()
            # Check "r1c2" or "R1C2"
            rc_match = re.match(r"^[rR](\d+)[cC](\d+)$", item)
            if rc_match:
                target_coords.add((int(rc_match.group(1)), int(rc_match.group(2))))
                continue
            # Check "1,2"
            if "," in item:
                parts = item.split(",")
                if len(parts) == 2 and parts[0].strip().isdigit() and parts[1].strip().isdigit():
                    target_coords.add((int(parts[0].strip()), int(parts[1].strip())))
                    continue
            # Check single digit row index
            if item.isdigit():
                target_rows.add(int(item))
                continue
            # Substring match (e.g. "Ours")
            text_matchers.append(item.lower())

        for r_idx, row in enumerate(rows):
            actual_row_idx = r_idx + row_offset
            is_alt = (r_idx % 2 == 1)
            row_bg = theme.colors.table_row_alt_bg if is_alt else theme.colors.background

            for c_idx in range(total_cols):
                cell_val = str(row[c_idx]) if c_idx < len(row) else ""
                cell = table.cell(actual_row_idx, c_idx)

                # Check if highlighted
                is_highlighted = (
                    (r_idx, c_idx) in target_coords
                    or (actual_row_idx, c_idx) in target_coords
                    or r_idx in target_rows
                    or actual_row_idx in target_rows
                    or any(tm in cell_val.lower() for tm in text_matchers)
                )

                cell.fill.solid()
                if is_highlighted:
                    cell.fill.fore_color.rgb = RGBColor(*hex_to_rgb(theme.colors.table_highlight_bg))
                    text_color = theme.colors.table_highlight_text
                    bold = True
                else:
                    cell.fill.fore_color.rgb = RGBColor(*hex_to_rgb(row_bg))
                    text_color = theme.colors.text_primary
                    bold = (c_idx == 0)  # Make first column bold by default for method names

                cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                p = cell.text_frame.paragraphs[0]
                align = PP_ALIGN.LEFT if c_idx == 0 else PP_ALIGN.CENTER
                apply_paragraph_style(
                    paragraph=p,
                    text=cell_val,
                    font_size=theme.fonts.table_body.size,
                    font_family=theme.fonts.table_body.font_family,
                    bold=bold,
                    italic=False,
                    color_rgb=hex_to_rgb(text_color),
                    alignment=align,
                )

        return table_shape

    def save(self, output_path: Union[str, Path]) -> Path:
        """Save presentation to disk."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        self.prs.save(str(out))
        return out
