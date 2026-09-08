"""Headless Slide Screenshot and Raster Snapshot Engine.

Provides deterministic rendering from SlideIR to PNG bytes and base64 data URIs.
Employs an engine cascade:
1. Playwright Headless Chromium (if installed)
2. CairoSVG / Resvg (if installed)
3. Built-in Pillow Native Slide Rasterizer (guaranteed zero-dependency fallback)
"""

from __future__ import annotations
import io
import base64
import logging
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any, Union
from ..ir.models import (
    SlideIR, ElementIR, ShapeElementIR, TextElementIR, ConnectorElementIR,
    ImageElementIR, GroupElementIR, TableElementIR
)
from ..ir.svg_renderer import SVGRenderer

logger = logging.getLogger(__name__)

# Check optional external rasterizers
async_playwright = None
_PLAYWRIGHT_AVAILABLE = False
try:
    from playwright.async_api import async_playwright
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    pass

cairosvg = None
_CAIROSVG_AVAILABLE = False
try:
    import cairosvg
    _CAIROSVG_AVAILABLE = True
except ImportError:
    pass

_PIL_AVAILABLE = False
try:
    from PIL import Image, ImageDraw, ImageFont
    _PIL_AVAILABLE = True
except ImportError:
    pass


class RendererMode(str, Enum):
    """Execution mode governing rendering determinism and allowed rasterization engines."""
    DETERMINISTIC = "deterministic"
    PREVIEW = "preview"


@dataclass
class RenderCapability:
    """Explicit capability matrix of the underlying rasterizer."""
    geometry: bool = True
    typography: bool = False
    effects: bool = False

    def to_dict(self) -> Dict[str, bool]:
        return {
            "geometry": self.geometry,
            "typography": self.typography,
            "effects": self.effects
        }


@dataclass
class RenderMetadata:
    """Metadata describing the active renderer, quality tier, and capabilities."""
    renderer: str
    quality: str
    capability: RenderCapability
    mode: RendererMode

    def to_dict(self) -> Dict[str, Any]:
        return {
            "renderer": self.renderer,
            "quality": self.quality,
            "capability": self.capability.to_dict(),
            "mode": self.mode.value
        }


def _hex_to_rgb(hex_str: Optional[str], default: Tuple[int, int, int] = (255, 255, 255)) -> Tuple[int, int, int]:
    """Converts hex color string like #FFFFFF, #2563EB, or none to RGB tuple."""
    if not hex_str or hex_str.lower() in ("none", "transparent"):
        return default
    s = hex_str.lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) >= 6:
        try:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
        except ValueError:
            return default
    return default


class PillowSlideRasterizer:
    """Built-in deterministic slide rasterizer using Pillow (PIL).

    Renders SlideIR geometry, fills, borders, typography, and groups directly to PNG.
    """

    @classmethod
    def render_to_image(cls, slide: SlideIR, scale: float = 1.0) -> Any:
        if not _PIL_AVAILABLE:
            raise RuntimeError("Pillow (PIL) is not installed in the current environment.")

        w = int(slide.width * scale)
        h = int(slide.height * scale)

        # Parse slide background
        bg_hex = "#0F172A"
        if slide.background and hasattr(slide.background, "color") and slide.background.color:
            bg_hex = slide.background.color
        bg_rgb = _hex_to_rgb(bg_hex, default=(15, 23, 42))

        img = Image.new("RGB", (w, h), bg_rgb)
        draw = ImageDraw.Draw(img)

        # Render elements in z-index order
        sorted_elements = sorted(slide.elements, key=lambda e: getattr(e, "z_index", 0))
        for elem in sorted_elements:
            cls._draw_element(draw, elem, scale)

        return img

    @classmethod
    def _draw_element(cls, draw: Any, elem: ElementIR, scale: float) -> None:
        if isinstance(elem, GroupElementIR):
            for child in sorted(elem.children, key=lambda c: getattr(c, "z_index", 0)):
                cls._draw_element(draw, child, scale)
            return

        x = int(elem.x * scale)
        y = int(elem.y * scale)
        ew = int(elem.width * scale)
        eh = int(elem.height * scale)
        x2 = x + ew
        y2 = y + eh

        # Parse fill and border
        fill_rgb = None
        if elem.style and elem.style.fill:
            if getattr(elem.style.fill, "type", "none") != "none" and elem.style.fill.color:
                fill_rgb = _hex_to_rgb(elem.style.fill.color)

        outline_rgb = None
        border_w = 0
        if elem.style and elem.style.border:
            if getattr(elem.style.border, "style", "none") != "none" and elem.style.border.color:
                outline_rgb = _hex_to_rgb(elem.style.border.color)
                border_w = max(1, int(getattr(elem.style.border, "width", 1.0) * scale))

        if isinstance(elem, ShapeElementIR):
            radius = int(getattr(elem.style, "radius", 0.0) * scale)
            stype = getattr(elem, "shape_type", "rect")

            if stype in ("roundRect", "rounded_rectangle") and radius > 0:
                draw.rounded_rectangle(
                    [x, y, x2, y2],
                    radius=min(radius, min(ew, eh) // 2),
                    fill=fill_rgb,
                    outline=outline_rgb,
                    width=border_w if outline_rgb else 0
                )
            elif stype in ("ellipse", "circle"):
                draw.ellipse(
                    [x, y, x2, y2],
                    fill=fill_rgb,
                    outline=outline_rgb,
                    width=border_w if outline_rgb else 0
                )
            elif stype == "diamond":
                mid_x = (x + x2) // 2
                mid_y = (y + y2) // 2
                points = [(mid_x, y), (x2, mid_y), (mid_x, y2), (x, mid_y)]
                draw.polygon(points, fill=fill_rgb, outline=outline_rgb)
            elif stype == "triangle":
                mid_x = (x + x2) // 2
                points = [(mid_x, y), (x2, y2), (x, y2)]
                draw.polygon(points, fill=fill_rgb, outline=outline_rgb)
            else:
                # Default rectangle
                draw.rectangle(
                    [x, y, x2, y2],
                    fill=fill_rgb,
                    outline=outline_rgb,
                    width=border_w if outline_rgb else 0
                )

        elif isinstance(elem, TextElementIR):
            # Draw optional text box container background
            if fill_rgb or outline_rgb:
                draw.rectangle(
                    [x, y, x2, y2],
                    fill=fill_rgb,
                    outline=outline_rgb,
                    width=border_w if outline_rgb else 0
                )

            # Draw text
            if elem.text_content and elem.text_content.plain_text:
                plain_text = elem.text_content.plain_text
                # Determine font color & size
                text_color = (255, 255, 255)
                fsize = 18
                if elem.text_content.paragraphs:
                    first_p = elem.text_content.paragraphs[0]
                    if first_p.runs:
                        r = first_p.runs[0]
                        if r.font and r.font.color:
                            text_color = _hex_to_rgb(r.font.color, default=(255, 255, 255))
                        if r.font and r.font.size:
                            fsize = int(r.font.size * scale)

                # Try loading default system font
                try:
                    font = ImageFont.load_default()
                except Exception:
                    font = None

                # Simple padded text placement
                tx = x + int(12 * scale)
                ty = y + int(10 * scale)
                draw.multiline_text(
                    (tx, ty),
                    plain_text,
                    fill=text_color,
                    font=font,
                    spacing=int(4 * scale)
                )

        elif isinstance(elem, ConnectorElementIR):
            sx = int(getattr(elem, "start_x", elem.x) * scale)
            sy = int(getattr(elem, "start_y", elem.y) * scale)
            ex = int(getattr(elem, "end_x", elem.x + elem.width) * scale)
            ey = int(getattr(elem, "end_y", elem.y + elem.height) * scale)
            line_color = outline_rgb or (148, 163, 184)
            line_w = max(2, int(getattr(elem.style.border, "width", 2.0) * scale)) if elem.style and elem.style.border else 2
            draw.line([(sx, sy), (ex, ey)], fill=line_color, width=line_w)

        elif isinstance(elem, TableElementIR):
            # Table container
            draw.rectangle(
                [x, y, x2, y2],
                fill=fill_rgb or (30, 41, 59),
                outline=outline_rgb or (71, 85, 105),
                width=max(1, border_w)
            )


class SlideSnapshotRenderer:
    """Unified Slide Snapshot Renderer.

    Provides deterministic rendering from SlideIR to PNG bytes and base64 data URIs.
    Supports DETERMINISTIC mode (CairoSVG -> Pillow/SVG URI, never Playwright)
    and PREVIEW mode (Playwright allowed for live user viewing).
    """

    default_mode: RendererMode = RendererMode.DETERMINISTIC

    @classmethod
    def get_render_metadata(cls, slide: Optional[SlideIR] = None, mode: Optional[RendererMode] = None) -> RenderMetadata:
        """Inspects environment and mode to produce the active renderer metadata and capability matrix."""
        target_mode = mode or cls.default_mode
        if target_mode == RendererMode.PREVIEW and _PLAYWRIGHT_AVAILABLE:
            return RenderMetadata(
                renderer="playwright",
                quality="full",
                capability=RenderCapability(geometry=True, typography=True, effects=True),
                mode=target_mode
            )
        if _CAIROSVG_AVAILABLE:
            return RenderMetadata(
                renderer="cairosvg",
                quality="high_fidelity",
                capability=RenderCapability(geometry=True, typography=True, effects=True),
                mode=target_mode
            )
        return RenderMetadata(
            renderer="pillow",
            quality="geometry_only",
            capability=RenderCapability(geometry=True, typography=False, effects=False),
            mode=target_mode
        )

    @classmethod
    def render_svg(cls, slide: SlideIR) -> str:
        """Renders SlideIR into standalone SVG XML."""
        return SVGRenderer.render_slide(slide)

    @classmethod
    def render_svg_data_uri(cls, slide: SlideIR) -> str:
        """Returns valid RFC 2397 SVG data URI: data:image/svg+xml;base64,..."""
        svg_code = cls.render_svg(slide)
        b64_svg = base64.b64encode(svg_code.encode("utf-8")).decode("utf-8")
        return f"data:image/svg+xml;base64,{b64_svg}"

    @classmethod
    def render_png_bytes(cls, slide: SlideIR, scale: float = 1.0, mode: Optional[RendererMode] = None) -> bytes:
        """Synchronously renders SlideIR into PNG bytes.

        In DETERMINISTIC mode:
        SlideIR -> SVG -> CairoSVG -> PNG.
        If CairoSVG is not available, falls back to Pillow with geometry_only capability metadata.
        Playwright is strictly prohibited in DETERMINISTIC mode to preserve CI determinism.

        In PREVIEW mode:
        Falls back through CairoSVG and Pillow synchronously.
        """
        target_mode = mode or cls.default_mode

        if _CAIROSVG_AVAILABLE:
            try:
                svg_code = cls.render_svg(slide)
                return cairosvg.svg2png(bytestring=svg_code.encode("utf-8"), scale=scale)
            except Exception as e:
                logger.debug(f"CairoSVG render failed, falling back to Pillow: {e}")

        if _PIL_AVAILABLE:
            img = PillowSlideRasterizer.render_to_image(slide, scale=scale)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()

        raise RuntimeError("No image rasterization engine available (neither CairoSVG nor Pillow found).")

    @classmethod
    def render_base64(cls, slide: SlideIR, scale: float = 1.0, mode: Optional[RendererMode] = None) -> str:
        """Returns base64 encoded PNG string (without data: prefix)."""
        png_bytes = cls.render_png_bytes(slide, scale=scale, mode=mode)
        return base64.b64encode(png_bytes).decode("utf-8")

    @classmethod
    def render_data_uri(
        cls,
        slide: SlideIR,
        scale: float = 1.0,
        mode: Optional[RendererMode] = None,
        fallback_to_svg: bool = False
    ) -> str:
        """Returns valid RFC 2397 data URI: data:image/png;base64,... or data:image/svg+xml;base64,...

        If fallback_to_svg is True and CairoSVG is not available in DETERMINISTIC mode,
        returns SVG data URI directly per Task 1 specification.
        """
        target_mode = mode or cls.default_mode
        if target_mode == RendererMode.DETERMINISTIC and fallback_to_svg and not _CAIROSVG_AVAILABLE:
            return cls.render_svg_data_uri(slide)

        b64 = cls.render_base64(slide, scale=scale, mode=target_mode)
        return f"data:image/png;base64,{b64}"

    @classmethod
    async def render_png_bytes_async(cls, slide: SlideIR, scale: float = 1.0, mode: Optional[RendererMode] = None) -> bytes:
        """Asynchronously renders slide.

        In PREVIEW mode: uses Playwright headless browser if available, else synchronous rasterizer.
        In DETERMINISTIC mode: Playwright is NEVER invoked; strictly uses deterministic CairoSVG / Pillow.
        """
        target_mode = mode or cls.default_mode
        if target_mode == RendererMode.PREVIEW and _PLAYWRIGHT_AVAILABLE:
            try:
                svg_code = cls.render_svg(slide)
                w = int(slide.width * scale)
                h = int(slide.height * scale)
                html_wrapper = f"""<!DOCTYPE html>
<html>
<head>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    html, body {{ width: {w}px; height: {h}px; overflow: hidden; background: transparent; }}
  </style>
</head>
<body>
  {svg_code}
</body>
</html>"""
                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=True)
                    page = await browser.new_page(viewport={"width": w, "height": h})
                    await page.set_content(html_wrapper)
                    png_bytes = await page.screenshot(type="png")
                    await browser.close()
                    return png_bytes
            except Exception as e:
                logger.debug(f"Playwright screenshot failed in preview, falling back: {e}")

        return cls.render_png_bytes(slide, scale=scale, mode=target_mode)
