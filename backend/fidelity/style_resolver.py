"""StyleResolver: Resolves style references, theme inheritance, and visual attributes.

Handles:
- FillStyle / BorderStyle / ShadowStyle resolution against ThemeEngine
- OOXML DrawingML style references (<a:fillRef>, <a:lnRef>, <a:fontRef>, <a:effectRef>)
- Conversion between PPT-IR ElementStyleIR and physical DrawingML attributes
"""

from __future__ import annotations
import copy
from typing import Dict, Any, Optional, Union
from .theme_engine import ThemeEngine, DEFAULT_COLOR_SCHEME
from ..ir.models import (
    ElementStyleIR, FillStyle, BorderStyle, ShadowStyle,
    GradientFill, GradientStop, FontIR
)


class StyleResolver:
    """Resolves abstract theme and style references into concrete visual properties."""

    def __init__(self, theme_engine: Optional[ThemeEngine] = None):
        self.theme = theme_engine or ThemeEngine()

    def resolve_fill(self, fill: Optional[FillStyle]) -> FillStyle:
        """Dereferences theme_color tokens on FillStyle into concrete RGB hex."""
        if fill is None:
            return FillStyle(type="none", color=None, alpha=0.0)

        resolved = copy.deepcopy(fill)
        if resolved.type == "theme" or resolved.theme_color:
            token = resolved.theme_color or resolved.color or "accent1"
            resolved_color = self.theme.resolve_color(token, default="#2563EB")
            resolved.color = resolved_color
            if resolved.type == "theme":
                resolved.type = "solid"

        elif resolved.type == "gradient" and resolved.gradient and resolved.gradient.stops:
            for stop in resolved.gradient.stops:
                if stop.color and not stop.color.startswith("#"):
                    stop.color = self.theme.resolve_color(stop.color, default="#2563EB")

        return resolved

    def resolve_border(self, border: Optional[BorderStyle]) -> BorderStyle:
        """Dereferences theme_color tokens on BorderStyle into concrete RGB hex."""
        if border is None:
            return BorderStyle(color=None, width=0.0, style="none", alpha=0.0)

        resolved = copy.deepcopy(border)
        if resolved.theme_color:
            resolved.color = self.theme.resolve_color(resolved.theme_color, default="#1E293B")
        elif resolved.color and not resolved.color.startswith("#"):
            resolved.color = self.theme.resolve_color(resolved.color, default="#1E293B")

        return resolved

    def resolve_font(self, font: Optional[FontIR]) -> FontIR:
        """Resolves font theme color and major/minor font scheme references."""
        if font is None:
            return FontIR(name="Segoe UI", size=18.0, color="#000000")

        resolved = copy.deepcopy(font)
        # Theme color resolution
        if resolved.theme_color:
            resolved.color = self.theme.resolve_color(resolved.theme_color, default="#000000")
        elif resolved.color and not resolved.color.startswith("#"):
            resolved.color = self.theme.resolve_color(resolved.color, default="#000000")

        # Font family scheme resolution (e.g. "+mj-lt", "+mn-lt", "majorFont", "minorFont")
        lower_name = resolved.name.lower().strip()
        if lower_name in ("+mj-lt", "+mj-ea", "majorfont", "heading", "title"):
            resolved.name = self.theme.get_major_font()
        elif lower_name in ("+mn-lt", "+mn-ea", "minorfont", "body"):
            resolved.name = self.theme.get_minor_font()

        return resolved

    def resolve_element_style(self, style: Optional[ElementStyleIR]) -> ElementStyleIR:
        """Resolves all style slots on an ElementStyleIR object."""
        if style is None:
            return ElementStyleIR()

        resolved = copy.deepcopy(style)
        if resolved.fill:
            resolved.fill = self.resolve_fill(resolved.fill)
        if resolved.border:
            resolved.border = self.resolve_border(resolved.border)
        return resolved

    def create_theme_fill(self, theme_token: str, alpha: float = 1.0) -> FillStyle:
        """Helper to create a theme-bound FillStyle."""
        color = self.theme.resolve_color(theme_token, default="#2563EB")
        return FillStyle(
            type="solid",
            color=color,
            alpha=alpha,
            theme_color=theme_token
        )

    def create_theme_border(self, theme_token: str, width: float = 1.0) -> BorderStyle:
        """Helper to create a theme-bound BorderStyle."""
        color = self.theme.resolve_color(theme_token, default="#1E293B")
        return BorderStyle(
            color=color,
            width=width,
            style="solid",
            alpha=1.0,
            theme_color=theme_token
        )
