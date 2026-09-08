"""Typography resolution and formatting utilities (PR11).

Bridges LayoutSpec visual styles and AcademicTheme tokens to python-pptx typography attributes.
"""

from __future__ import annotations

from typing import Optional, Tuple
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Pt

from ..layout.schema import BlockRole, ElementType, LayoutElement, TextStyle
from .schema import EMU_PER_PX, PT_PER_PX
from .theme import AcademicTheme, FontToken, hex_to_rgb


def px_to_emu(px: float) -> int:
    """Convert canvas pixels to OOXML English Metric Units (EMUs)."""
    return int(round(px * EMU_PER_PX))


def pt_to_emu(pt: float) -> int:
    """Convert points to EMUs."""
    return int(round(pt * 12700))


def resolve_alignment(align_str: Optional[str]) -> PP_ALIGN:
    """Convert string alignment to python-pptx PP_ALIGN enum."""
    if not align_str:
        return PP_ALIGN.LEFT
    norm = align_str.lower().strip()
    if norm == "center":
        return PP_ALIGN.CENTER
    if norm == "right":
        return PP_ALIGN.RIGHT
    if norm == "justify":
        return PP_ALIGN.JUSTIFY
    return PP_ALIGN.LEFT


def resolve_vertical_alignment(v_align_str: Optional[str]) -> MSO_ANCHOR:
    """Convert string vertical alignment to python-pptx MSO_ANCHOR enum."""
    if not v_align_str:
        return MSO_ANCHOR.TOP
    norm = v_align_str.lower().strip()
    if norm == "middle" or norm == "center":
        return MSO_ANCHOR.MIDDLE
    if norm == "bottom":
        return MSO_ANCHOR.BOTTOM
    return MSO_ANCHOR.TOP


def resolve_element_typography(
    element: LayoutElement,
    theme: AcademicTheme,
) -> Tuple[float, str, bool, bool, Tuple[int, int, int]]:
    """Determine effective (font_size, font_family, bold, italic, color_rgb) from element style & theme.

    Guarantees no arbitrary hardcoded font sizes appear in renderer dispatch.
    """
    token = theme.resolve_font_for_role(element.role, element.element_type)
    text_style: Optional[TextStyle] = element.style.text if element.style else None
    fields_set = text_style.model_fields_set if text_style else set()

    # 1. Font Size
    if "font_size" in fields_set and text_style and text_style.font_size:
        font_size = text_style.font_size
    else:
        font_size = token.size

    # 2. Font Family
    if "font_family" in fields_set and text_style and text_style.font_family:
        font_family = text_style.font_family
    else:
        font_family = token.font_family

    # 3. Bold & Italic
    if "font_weight" in fields_set and text_style:
        bold = (text_style.font_weight == "bold")
    else:
        bold = token.bold

    if "italic" in fields_set and text_style:
        italic = text_style.italic
    else:
        italic = token.italic

    # 4. Color
    if text_style and text_style.color:
        color_rgb = hex_to_rgb(text_style.color)
    else:
        if element.element_type == ElementType.BADGE:
            color_rgb = hex_to_rgb(theme.colors.badge_primary_text)
        elif element.role in (BlockRole.HEADING, BlockRole.SUBHEADING, BlockRole.LEAD_SUMMARY):
            color_rgb = hex_to_rgb(theme.colors.text_primary)
        elif element.role == BlockRole.CAPTION:
            color_rgb = hex_to_rgb(theme.colors.text_muted)
        else:
            color_rgb = hex_to_rgb(theme.colors.text_primary)

    return font_size, font_family, bold, italic, color_rgb


def apply_paragraph_style(
    paragraph,
    text: str,
    font_size: float,
    font_family: str,
    bold: bool,
    italic: bool,
    color_rgb: Tuple[int, int, int],
    alignment: PP_ALIGN = PP_ALIGN.LEFT,
    line_spacing: Optional[float] = None,
    space_after: Optional[float] = None,
) -> None:
    """Format a python-pptx paragraph run with typographic rules."""
    paragraph.text = text
    paragraph.alignment = alignment
    if line_spacing:
        paragraph.line_spacing = line_spacing
    if space_after is not None:
        paragraph.space_after = Pt(space_after)

    # Format run
    for run in paragraph.runs:
        run.font.name = font_family
        run.font.size = Pt(font_size)
        run.font.bold = bold
        run.font.italic = italic
        run.font.color.rgb = RGBColor(*color_rgb)
