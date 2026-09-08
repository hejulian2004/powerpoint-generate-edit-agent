"""Backend SVG Renderer for PPT-IR Slides.

Renders high-fidelity, standalone, standard SVG (1280x720 viewBox) with:
- Gradients, drop-shadow filters, marker arrowheads
- Precise geometry for roundRect, ellipse, diamond, triangle, arrow, connectors
- Formatted multiline text with font schemes, colors, and alignments
"""

from __future__ import annotations
import html
import math
from typing import List, Dict, Any, Optional
from .models import (
    SlideIR, ElementIR, ShapeElementIR, TextElementIR, ConnectorElementIR,
    ImageElementIR, TableElementIR, ElementStyleIR, FillStyle, BorderStyle,
    ShadowStyle, TextContentIR, ParagraphIR
)


class SVGRenderer:
    """Renders SlideIR to standalone SVG string."""

    @classmethod
    def render_slide(cls, slide: SlideIR) -> str:
        defs: List[str] = []
        body: List[str] = []

        # Standard marker for connector arrows
        defs.append("""
        <marker id="marker-arrow-end" viewBox="0 0 12 12" refX="10" refY="6" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 0 1 L 12 6 L 0 11 z" fill="context-stroke" />
        </marker>
        <marker id="marker-arrow-start" viewBox="0 0 12 12" refX="2" refY="6" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 12 1 L 0 6 L 12 11 z" fill="context-stroke" />
        </marker>
        <filter id="default-drop-shadow" x="-20%" y="-20%" width="140%" height="140%">
            <feDropShadow dx="2" dy="4" stdDeviation="4" flood-opacity="0.15" />
        </filter>
        """)

        # Background
        bg_fill = cls._render_fill_attribute(slide.background, f"bg_{slide.id}", defs)
        body.append(f'<rect width="{slide.width}" height="{slide.height}" fill="{bg_fill}" />')

        # Elements sorted by z-index
        sorted_elements = sorted(slide.elements, key=lambda e: e.z_index)
        for elem in sorted_elements:
            elem_svg = cls._render_element(elem, defs)
            if elem_svg:
                body.append(elem_svg)

        defs_str = "\n".join(defs)
        body_str = "\n".join(body)

        return f"""<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
    viewBox="0 0 {slide.width} {slide.height}" width="{slide.width}" height="{slide.height}">
  <defs>
    {defs_str}
  </defs>
  <g id="{slide.id}">
    {body_str}
  </g>
</svg>"""

    @classmethod
    def _render_element(cls, elem: ElementIR, defs: List[str]) -> str:
        transform = ""
        if elem.rotation != 0.0:
            cx = elem.x + elem.width / 2.0
            cy = elem.y + elem.height / 2.0
            transform = f' transform="rotate({elem.rotation} {cx} {cy})"'

        opacity_attr = f' opacity="{elem.style.opacity}"' if elem.style.opacity < 1.0 else ""
        shadow_filter = ' filter="url(#default-drop-shadow)"' if (elem.style.shadow and elem.style.shadow.enabled) else ""

        if isinstance(elem, ConnectorElementIR):
            return cls._render_connector(elem)

        elif isinstance(elem, ImageElementIR):
            return f'<image href="{elem.src}" x="{elem.x}" y="{elem.y}" width="{elem.width}" height="{elem.height}"{transform}{opacity_attr} preserveAspectRatio="xMidYMid meet" />'

        elif isinstance(elem, TextElementIR):
            fill_val = cls._render_fill_attribute(elem.style.fill, f"fill_{elem.id}", defs)
            stroke_val, stroke_w, stroke_dash = cls._render_stroke_attributes(elem.style.border)
            
            box_svg = ""
            if fill_val != "none" or stroke_val != "none":
                box_svg = f'<rect x="{elem.x}" y="{elem.y}" width="{elem.width}" height="{elem.height}" fill="{fill_val}" stroke="{stroke_val}" stroke-width="{stroke_w}" {stroke_dash}{shadow_filter} />'
            
            text_svg = cls._render_text(elem.text_content, elem.x, elem.y, elem.width, elem.height, elem.style.padding)
            return f'<g id="{elem.id}"{transform}{opacity_attr}>{box_svg}{text_svg}</g>'

        elif isinstance(elem, ShapeElementIR):
            fill_val = cls._render_fill_attribute(elem.style.fill, f"fill_{elem.id}", defs)
            stroke_val, stroke_w, stroke_dash = cls._render_stroke_attributes(elem.style.border)
            
            shape_geom = cls._render_shape_geometry(
                elem.shape_type, elem.x, elem.y, elem.width, elem.height,
                elem.style.radius, fill_val, stroke_val, stroke_w, stroke_dash, shadow_filter
            )
            
            text_svg = ""
            if elem.text_content and elem.text_content.paragraphs:
                text_svg = cls._render_text(elem.text_content, elem.x, elem.y, elem.width, elem.height, elem.style.padding)

            return f'<g id="{elem.id}"{transform}{opacity_attr}>{shape_geom}{text_svg}</g>'

        return ""

    @classmethod
    def _render_connector(cls, conn: ConnectorElementIR) -> str:
        stroke_color = "#1E293B"
        stroke_width = 2.0
        stroke_dash = ""
        if conn.style.border:
            stroke_color = conn.style.border.color or stroke_color
            stroke_width = conn.style.border.width or stroke_width
            if conn.style.border.style == "dashed":
                stroke_dash = 'stroke-dasharray="6,4"'
            elif conn.style.border.style == "dotted":
                stroke_dash = 'stroke-dasharray="2,2"'

        marker_end = ' marker-end="url(#marker-arrow-end)"' if conn.arrow_end != "none" else ""
        marker_start = ' marker-start="url(#marker-arrow-start)"' if conn.arrow_start != "none" else ""

        if conn.line_type == "elbow":
            mid_x = (conn.start_x + conn.end_x) / 2.0
            d = f"M {conn.start_x} {conn.start_y} H {mid_x} V {conn.end_y} H {conn.end_x}"
        else:
            d = f"M {conn.start_x} {conn.start_y} L {conn.end_x} {conn.end_y}"

        return f'<path id="{conn.id}" d="{d}" stroke="{stroke_color}" stroke-width="{stroke_width}" fill="none"{stroke_dash}{marker_start}{marker_end} />'

    @classmethod
    def _render_shape_geometry(
        cls,
        stype: str, x: float, y: float, w: float, h: float,
        radius: float, fill: str, stroke: str, stroke_w: float, stroke_dash: str, filter_str: str
    ) -> str:
        common_attrs = f'fill="{fill}" stroke="{stroke}" stroke-width="{stroke_w}" {stroke_dash}{filter_str}'
        
        if stype in ["roundRect", "rounded_rectangle"]:
            rx = radius * min(w, h) if (0 < radius <= 0.5) else (radius if radius > 0 else 12.0)
            return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" ry="{rx}" {common_attrs} />'

        elif stype in ["ellipse", "circle"]:
            cx = x + w / 2.0
            cy = y + h / 2.0
            return f'<ellipse cx="{cx}" cy="{cy}" rx="{w/2.0}" ry="{h/2.0}" {common_attrs} />'

        elif stype == "diamond":
            cx = x + w / 2.0
            cy = y + h / 2.0
            points = f"{cx},{y} {x+w},{cy} {cx},{y+h} {x},{cy}"
            return f'<polygon points="{points}" {common_attrs} />'

        elif stype in ["triangle", "upArrow"]:
            points = f"{x + w/2.0},{y} {x + w},{y + h} {x},{y + h}"
            return f'<polygon points="{points}" {common_attrs} />'

        elif stype in ["rightArrow", "arrow"]:
            y_mid = y + h / 2.0
            head_len = min(w * 0.4, 40.0)
            shaft_h = h * 0.4
            y_top = y_mid - shaft_h / 2.0
            y_bot = y_mid + shaft_h / 2.0
            head_x = x + w - head_len
            points = f"{x},{y_top} {head_x},{y_top} {head_x},{y} {x+w},{y_mid} {head_x},{y+h} {head_x},{y_bot} {x},{y_bot}"
            return f'<polygon points="{points}" {common_attrs} />'

        # Default rectangle
        return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" {common_attrs} />'

    @classmethod
    def _render_text(cls, tc: Optional[TextContentIR], x: float, y: float, w: float, h: float, padding: float) -> str:
        if not tc or not tc.paragraphs:
            return ""

        text_nodes: List[str] = []
        curr_y = y + padding

        # Estimate line heights
        for p in tc.paragraphs:
            align = p.align
            if align == "center":
                anchor = "middle"
                tx = x + w / 2.0
            elif align == "right":
                anchor = "end"
                tx = x + w - padding
            else:
                anchor = "start"
                tx = x + padding

            # Calculate largest font size in this paragraph
            max_size = 16.0
            for r in p.runs:
                if r.font and r.font.size > max_size:
                    max_size = r.font.size

            line_height = max_size * p.line_spacing
            curr_y += line_height

            span_items: List[str] = []
            for r in p.runs:
                if not r.text:
                    continue
                font = r.font
                font_family = font.name if font else "Segoe UI"
                font_size = font.size if font else 16.0
                font_color = font.color if font else "#1E293B"
                weight = "bold" if (font and font.bold) else "normal"
                italic = "italic" if (font and font.italic) else "normal"
                escaped_text = html.escape(r.text)

                span_items.append(
                    f'<tspan font-family="{font_family}, sans-serif" font-size="{font_size}px" font-weight="{weight}" font-style="{italic}" fill="{font_color}">{escaped_text}</tspan>'
                )

            if span_items:
                text_nodes.append(
                    f'<text x="{tx}" y="{curr_y}" text-anchor="{anchor}">{"".join(span_items)}</text>'
                )

        return "\n".join(text_nodes)

    @classmethod
    def _render_fill_attribute(cls, fill: Optional[FillStyle], grad_id: str, defs: List[str]) -> str:
        if not fill or fill.type == "none":
            return "none"
        if fill.type == "solid":
            color = fill.color or "#3B82F6"
            if fill.alpha < 1.0:
                return cls._hex_to_rgba(color, fill.alpha)
            return color
        if fill.type == "gradient" and fill.gradient:
            grad = fill.gradient
            # Linear gradient angle to SVG x1, y1, x2, y2
            rad = math.radians(grad.angle)
            x1 = round(50 - 50 * math.cos(rad), 2)
            y1 = round(50 - 50 * math.sin(rad), 2)
            x2 = round(50 + 50 * math.cos(rad), 2)
            y2 = round(50 + 50 * math.sin(rad), 2)

            stops_xml = []
            for s in grad.stops:
                pct = int(s.position * 100)
                stops_xml.append(f'<stop offset="{pct}%" stop-color="{s.color}" stop-opacity="{s.alpha}" />')

            defs.append(f'<linearGradient id="{grad_id}" x1="{x1}%" y1="{y1}%" x2="{x2}%" y2="{y2}%">{"".join(stops_xml)}</linearGradient>')
            return f"url(#{grad_id})"
        return "#3B82F6"

    @classmethod
    def _render_stroke_attributes(cls, border: Optional[BorderStyle]) -> tuple[str, float, str]:
        if not border or border.style == "none" or border.width <= 0:
            return "none", 0.0, ""
        
        color = border.color or "#1E293B"
        if border.alpha < 1.0:
            color = cls._hex_to_rgba(color, border.alpha)

        dash = ""
        if border.style == "dashed":
            dash = 'stroke-dasharray="6,4"'
        elif border.style == "dotted":
            dash = 'stroke-dasharray="2,2"'

        return color, border.width, dash

    @staticmethod
    def _hex_to_rgba(hex_color: str, alpha: float) -> str:
        h = hex_color.lstrip("#")
        if len(h) == 6:
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            return f"rgba({r},{g},{b},{alpha:.2f})"
        return hex_color
