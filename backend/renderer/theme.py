"""Academic Theme System (PR11).

Defines the theme tokens for academic presentations: typography scales,
color palettes, and spacing rules. Ensures rendering logic never uses magic font sizes
or ad-hoc colors.
"""

from __future__ import annotations

from typing import Optional, Tuple
from pydantic import BaseModel, Field

from ..layout.schema import BlockRole, ElementType


def hex_to_rgb(hex_code: Optional[str], default: Tuple[int, int, int] = (15, 23, 42)) -> Tuple[int, int, int]:
    """Convert a hex color string ('#RRGGBB' or 'RRGGBB') to an (r, g, b) tuple."""
    if not hex_code:
        return default
    clean = hex_code.strip().lstrip("#")
    if len(clean) == 3:
        clean = "".join([c * 2 for c in clean])
    if len(clean) != 6:
        return default
    try:
        r = int(clean[0:2], 16)
        g = int(clean[2:4], 16)
        b = int(clean[4:6], 16)
        return (r, g, b)
    except ValueError:
        return default


class FontToken(BaseModel):
    """Specification for a typographic scale level."""

    size: float = Field(..., description="Font size in points (Pt)")
    bold: bool = Field(False, description="Whether bold font weight is active")
    italic: bool = Field(False, description="Whether italic is active")
    font_family: str = Field("Calibri", description="Font family name")


class ThemeFonts(BaseModel):
    """Typographic scale across academic hierarchy."""

    title: FontToken = Field(
        default_factory=lambda: FontToken(size=28.0, bold=True, font_family="Calibri")
    )
    subtitle: FontToken = Field(
        default_factory=lambda: FontToken(size=20.0, bold=False, font_family="Calibri")
    )
    section: FontToken = Field(
        default_factory=lambda: FontToken(size=22.0, bold=True, font_family="Calibri")
    )
    body: FontToken = Field(
        default_factory=lambda: FontToken(size=16.0, bold=False, font_family="Calibri")
    )
    caption: FontToken = Field(
        default_factory=lambda: FontToken(size=12.0, bold=False, italic=True, font_family="Calibri")
    )
    badge: FontToken = Field(
        default_factory=lambda: FontToken(size=11.0, bold=True, font_family="Calibri")
    )
    table_header: FontToken = Field(
        default_factory=lambda: FontToken(size=13.0, bold=True, font_family="Calibri")
    )
    table_body: FontToken = Field(
        default_factory=lambda: FontToken(size=12.0, bold=False, font_family="Calibri")
    )
    code: FontToken = Field(
        default_factory=lambda: FontToken(size=12.0, bold=False, font_family="Consolas")
    )


class ThemeColors(BaseModel):
    """Academic presentation color palette."""

    primary: str = Field("#0F172A", description="Primary brand / dominant text color (Deep Slate)")
    secondary: str = Field("#334155", description="Secondary supporting tone")
    accent: str = Field("#2563EB", description="Academic accent color (Royal Blue)")
    background: str = Field("#FFFFFF", description="Canvas background")
    surface: str = Field("#F8FAFC", description="Card / container fill color")
    surface_border: str = Field("#E2E8F0", description="Card / container border stroke")
    text_primary: str = Field("#0F172A", description="Primary body and heading text")
    text_secondary: str = Field("#475569", description="Secondary explanatory text")
    text_muted: str = Field("#64748B", description="Captions, footers, meta text")
    badge_primary_bg: str = Field("#DBEAFE", description="Primary badge fill")
    badge_primary_text: str = Field("#1E40AF", description="Primary badge text")
    badge_success_bg: str = Field("#DCFCE7", description="Success badge fill")
    badge_success_text: str = Field("#166534", description="Success badge text")
    badge_accent_bg: str = Field("#FEF3C7", description="Accent badge fill")
    badge_accent_text: str = Field("#92400E", description="Accent badge text")
    table_header_bg: str = Field("#1E293B", description="Table header row background")
    table_header_text: str = Field("#FFFFFF", description="Table header row text")
    table_row_alt_bg: str = Field("#F8FAFC", description="Table alternating row background")
    table_highlight_bg: str = Field("#FEF3C7", description="Table highlighted cell background")
    table_highlight_text: str = Field("#92400E", description="Table highlighted cell text")
    table_border: str = Field("#CBD5E1", description="Table gridline border color")


class ThemeSpacing(BaseModel):
    """Spacing and padding rules."""

    paragraph_after: float = Field(4.0, description="Space below paragraphs in points")
    line_spacing: float = Field(1.15, description="Line height multiplier")
    cell_padding: float = Field(4.0, description="Internal table cell padding in points")


class AcademicTheme(BaseModel):
    """Unified theme specification for academic presentations."""

    name: str = Field("academic_modern", description="Theme name identifier")
    fonts: ThemeFonts = Field(default_factory=ThemeFonts)
    colors: ThemeColors = Field(default_factory=ThemeColors)
    spacing: ThemeSpacing = Field(default_factory=ThemeSpacing)

    def resolve_font_for_role(
        self,
        role: Optional[BlockRole] = None,
        element_type: Optional[ElementType] = None,
    ) -> FontToken:
        """Resolve the appropriate FontToken from theme based on semantic role or element type."""
        if element_type == ElementType.BADGE:
            return self.fonts.badge
        if element_type == ElementType.TABLE:
            return self.fonts.table_body

        if role == BlockRole.HEADING:
            return self.fonts.title
        if role == BlockRole.SUBHEADING:
            return self.fonts.subtitle
        if role == BlockRole.LEAD_SUMMARY:
            return self.fonts.section
        if role == BlockRole.CAPTION:
            return self.fonts.caption
        if role in (BlockRole.BULLET_ITEM, BlockRole.CALLOUT):
            return self.fonts.body

        return self.fonts.body
