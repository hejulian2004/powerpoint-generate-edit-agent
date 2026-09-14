"""Backend SVG Renderer for PPT-IR Slides.

Renders high-fidelity, standalone, standard SVG (1280x720 viewBox) with:
- Gradients, drop-shadow filters, marker arrowheads
- Precise geometry for roundRect, ellipse, diamond, triangle, arrow, connectors
- Formatted multiline text with font schemes, colors, and alignments
- Safe XML DOM construction (lxml.etree) immune to XML/attribute injection attacks.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Tuple
import lxml.etree as etree

from .models import (
    BorderStyle,
    ConnectorElementIR,
    ElementIR,
    ElementStyleIR,
    FillStyle,
    GroupElementIR,
    ImageElementIR,
    ParagraphIR,
    ShadowStyle,
    ShapeElementIR,
    SlideIR,
    TableElementIR,
    TextContentIR,
    TextElementIR,
)

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
NSMAP = {None: SVG_NS, "xlink": XLINK_NS}

_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")
_SAFE_COLOR_RE = re.compile(
    r"^(#[0-9a-fA-F]{3,8}|rgba?\([0-9.,\s%]+\)|hsla?\([0-9.,\s%]+\)|none|currentColor|[a-zA-Z0-9_\-]+)$"
)
_ALLOWED_DATA_IMAGE_RE = re.compile(
    r"^data:image\/(png|jpeg|jpg|webp|gif|svg\+xml);base64,[A-Za-z0-9+/=]+$",
    re.IGNORECASE,
)
_ALLOWED_URL_RE = re.compile(
    r"^(https?://|/assets/|assets/|data/)[a-zA-Z0-9_.\-/%?=&#+]+$",
    re.IGNORECASE,
)


def safe_id(val: Any, default: str = "elem") -> str:
    s = str(val or "").strip()
    if _SAFE_ID_RE.match(s):
        return s
    cleaned = re.sub(r"[^a-zA-Z0-9_\-]", "_", s)
    return cleaned or default


def safe_color(val: Optional[str], default: str = "#3B82F6") -> str:
    if not val:
        return default
    s = str(val).strip()
    if (
        _SAFE_COLOR_RE.match(s)
        and "<" not in s
        and ">" not in s
        and '"' not in s
        and "'" not in s
    ):
        return s
    return default


def safe_font_family(name: Optional[str], default: str = "Segoe UI") -> str:
    if not name:
        return default
    s = str(name).strip()
    s = re.sub(r'[<>"\'\r\n;\\]', "", s).strip()
    if not s or len(s) > 64:
        return default
    return s


def safe_image_src(src: Optional[str]) -> str:
    if not src:
        return ""
    s = str(src).strip()
    if _ALLOWED_DATA_IMAGE_RE.match(s) or _ALLOWED_URL_RE.match(s):
        return s
    return ""


def _q(tag: str) -> str:
    return f"{{{SVG_NS}}}{tag}"


class SVGRenderer:
    """Renders SlideIR to standalone SVG string using safe XML DOM construction."""

    @classmethod
    def render_slide(cls, slide: SlideIR) -> str:
        root = etree.Element(
            _q("svg"),
            nsmap=NSMAP,
            attrib={
                "viewBox": f"0 0 {slide.width} {slide.height}",
                "width": str(slide.width),
                "height": str(slide.height),
            },
        )

        defs = etree.SubElement(root, _q("defs"))

        # Standard marker for connector arrows (end)
        marker_end = etree.SubElement(
            defs,
            _q("marker"),
            attrib={
                "id": "marker-arrow-end",
                "viewBox": "0 0 12 12",
                "refX": "10",
                "refY": "6",
                "markerWidth": "7",
                "markerHeight": "7",
                "orient": "auto-start-reverse",
            },
        )
        etree.SubElement(
            marker_end,
            _q("path"),
            attrib={"d": "M 0 1 L 12 6 L 0 11 z", "fill": "context-stroke"},
        )

        # Standard marker for connector arrows (start)
        marker_start = etree.SubElement(
            defs,
            _q("marker"),
            attrib={
                "id": "marker-arrow-start",
                "viewBox": "0 0 12 12",
                "refX": "2",
                "refY": "6",
                "markerWidth": "7",
                "markerHeight": "7",
                "orient": "auto-start-reverse",
            },
        )
        etree.SubElement(
            marker_start,
            _q("path"),
            attrib={"d": "M 12 1 L 0 6 L 12 11 z", "fill": "context-stroke"},
        )

        # Default drop shadow filter
        filter_elem = etree.SubElement(
            defs,
            _q("filter"),
            attrib={
                "id": "default-drop-shadow",
                "x": "-20%",
                "y": "-20%",
                "width": "140%",
                "height": "140%",
            },
        )
        etree.SubElement(
            filter_elem,
            _q("feDropShadow"),
            attrib={
                "dx": "2",
                "dy": "4",
                "stdDeviation": "4",
                "flood-opacity": "0.15",
            },
        )

        # Slide group
        slide_g = etree.SubElement(root, _q("g"), attrib={"id": safe_id(slide.id, "slide")})

        # Background
        bg_fill = cls._render_fill_attribute(
            slide.background, f"bg_{safe_id(slide.id)}", defs
        )
        etree.SubElement(
            slide_g,
            _q("rect"),
            attrib={
                "width": str(slide.width),
                "height": str(slide.height),
                "fill": bg_fill,
            },
        )

        # Elements sorted by z-index
        sorted_elements = sorted(slide.elements, key=lambda e: e.z_index)
        for elem in sorted_elements:
            cls._render_element(elem, defs, slide_g)

        return etree.tostring(root, encoding="unicode", pretty_print=True).strip()

    @classmethod
    def _render_element(cls, elem: ElementIR, defs: etree._Element, parent: etree._Element) -> None:
        transform_attr = {}
        if elem.rotation != 0.0:
            cx = elem.x + elem.width / 2.0
            cy = elem.y + elem.height / 2.0
            transform_attr["transform"] = f"rotate({elem.rotation} {cx} {cy})"

        opacity_attr = {}
        if elem.style.opacity < 1.0:
            opacity_attr["opacity"] = str(elem.style.opacity)

        shadow_url = (
            "url(#default-drop-shadow)"
            if (elem.style.shadow and elem.style.shadow.enabled)
            else None
        )

        if isinstance(elem, ConnectorElementIR):
            cls._render_connector(elem, parent)

        elif isinstance(elem, ImageElementIR):
            img_attrs = {
                "id": safe_id(elem.id, "img"),
                "x": str(elem.x),
                "y": str(elem.y),
                "width": str(elem.width),
                "height": str(elem.height),
                "preserveAspectRatio": "xMidYMid meet",
            }
            img_attrs.update(transform_attr)
            img_attrs.update(opacity_attr)

            src = safe_image_src(elem.src)
            img_attrs["href"] = src

            if elem.style and elem.style.radius > 0:
                clip_id = f"clip_{safe_id(elem.id)}"
                clip_elem = etree.SubElement(defs, _q("clipPath"), attrib={"id": clip_id})
                etree.SubElement(
                    clip_elem,
                    _q("rect"),
                    attrib={
                        "x": str(elem.x),
                        "y": str(elem.y),
                        "width": str(elem.width),
                        "height": str(elem.height),
                        "rx": str(elem.style.radius),
                        "ry": str(elem.style.radius),
                    },
                )
                img_attrs["clip-path"] = f"url(#{clip_id})"

            etree.SubElement(parent, _q("image"), attrib=img_attrs)

        elif isinstance(elem, TextElementIR):
            g_attrs = {"id": safe_id(elem.id, "text_elem")}
            g_attrs.update(transform_attr)
            g_attrs.update(opacity_attr)
            g = etree.SubElement(parent, _q("g"), attrib=g_attrs)

            fill_val = cls._render_fill_attribute(
                elem.style.fill, f"fill_{safe_id(elem.id)}", defs
            )
            stroke_val, stroke_w, stroke_dash = cls._render_stroke_attributes(
                elem.style.border
            )

            if fill_val != "none" or stroke_val != "none":
                box_attrs = {
                    "x": str(elem.x),
                    "y": str(elem.y),
                    "width": str(elem.width),
                    "height": str(elem.height),
                    "fill": fill_val,
                    "stroke": stroke_val,
                    "stroke-width": str(stroke_w),
                }
                if stroke_dash:
                    box_attrs["stroke-dasharray"] = stroke_dash
                if shadow_url:
                    box_attrs["filter"] = shadow_url
                etree.SubElement(g, _q("rect"), attrib=box_attrs)

            cls._render_text(
                elem.text_content,
                elem.x,
                elem.y,
                elem.width,
                elem.height,
                elem.style.padding,
                g,
            )

        elif isinstance(elem, ShapeElementIR):
            g_attrs = {"id": safe_id(elem.id, "shape_elem")}
            g_attrs.update(transform_attr)
            g_attrs.update(opacity_attr)
            g = etree.SubElement(parent, _q("g"), attrib=g_attrs)

            fill_val = cls._render_fill_attribute(
                elem.style.fill, f"fill_{safe_id(elem.id)}", defs
            )
            stroke_val, stroke_w, stroke_dash = cls._render_stroke_attributes(
                elem.style.border
            )

            cls._render_shape_geometry(
                elem.shape_type,
                elem.x,
                elem.y,
                elem.width,
                elem.height,
                elem.style.radius,
                fill_val,
                stroke_val,
                stroke_w,
                stroke_dash,
                shadow_url,
                g,
            )

            if elem.text_content and elem.text_content.paragraphs:
                cls._render_text(
                    elem.text_content,
                    elem.x,
                    elem.y,
                    elem.width,
                    elem.height,
                    elem.style.padding,
                    g,
                )

        elif isinstance(elem, TableElementIR):
            cls._render_table(elem, defs, parent)

        elif isinstance(elem, GroupElementIR):
            g_attrs = {
                "id": safe_id(elem.id, "grp"),
                "class": "group-container",
            }
            g_attrs.update(transform_attr)
            g_attrs.update(opacity_attr)
            grp = etree.SubElement(parent, _q("g"), attrib=g_attrs)
            for child in elem.children:
                cls._render_element(child, defs, grp)

    @classmethod
    def _render_table(cls, table: TableElementIR, defs: etree._Element, parent: etree._Element) -> None:
        t_grp = etree.SubElement(
            parent,
            _q("g"),
            attrib={"id": safe_id(table.id, "table"), "class": "table-container"},
        )
        c_w = table.width / max(table.cols, 1)
        c_h = table.height / max(table.rows, 1)

        for r_idx, row in enumerate(table.cells):
            for c_idx, cell in enumerate(row):
                cx = table.x + c_idx * c_w
                cy = table.y + r_idx * c_h
                fill_color = "#FFFFFF"
                border_color = "#CBD5E1"
                border_w = 1.0
                if cell.style and cell.style.fill and cell.style.fill.color:
                    fill_color = safe_color(cell.style.fill.color, "#FFFFFF")
                if cell.style and cell.style.border and cell.style.border.color:
                    border_color = safe_color(cell.style.border.color, "#CBD5E1")
                    border_w = cell.style.border.width

                etree.SubElement(
                    t_grp,
                    _q("rect"),
                    attrib={
                        "x": str(cx),
                        "y": str(cy),
                        "width": str(c_w),
                        "height": str(c_h),
                        "fill": fill_color,
                        "stroke": border_color,
                        "stroke-width": str(border_w),
                    },
                )
                cls._render_text(cell.text_content, cx, cy, c_w, c_h, 6.0, t_grp)

    @classmethod
    def _render_connector(cls, conn: ConnectorElementIR, parent: etree._Element) -> None:
        stroke_color = "#1E293B"
        stroke_width = 2.0
        stroke_dash = ""
        if conn.style.border:
            stroke_color = safe_color(conn.style.border.color, stroke_color)
            stroke_width = conn.style.border.width or stroke_width
            if conn.style.border.style == "dashed":
                stroke_dash = "6,4"
            elif conn.style.border.style == "dotted":
                stroke_dash = "2,2"

        if conn.line_type == "elbow":
            mid_x = (conn.start_x + conn.end_x) / 2.0
            d = f"M {conn.start_x} {conn.start_y} H {mid_x} V {conn.end_y} H {conn.end_x}"
        else:
            d = f"M {conn.start_x} {conn.start_y} L {conn.end_x} {conn.end_y}"

        attrs = {
            "id": safe_id(conn.id, "conn"),
            "d": d,
            "stroke": stroke_color,
            "stroke-width": str(stroke_width),
            "fill": "none",
        }
        if stroke_dash:
            attrs["stroke-dasharray"] = stroke_dash
        if conn.arrow_start != "none":
            attrs["marker-start"] = "url(#marker-arrow-start)"
        if conn.arrow_end != "none":
            attrs["marker-end"] = "url(#marker-arrow-end)"

        etree.SubElement(parent, _q("path"), attrib=attrs)

    @classmethod
    def _render_shape_geometry(
        cls,
        stype: str,
        x: float,
        y: float,
        w: float,
        h: float,
        radius: float,
        fill: str,
        stroke: str,
        stroke_w: float,
        stroke_dash: str,
        filter_str: Optional[str],
        parent: etree._Element,
    ) -> None:
        common_attrs = {
            "fill": fill,
            "stroke": stroke,
            "stroke-width": str(stroke_w),
        }
        if stroke_dash:
            common_attrs["stroke-dasharray"] = stroke_dash
        if filter_str:
            common_attrs["filter"] = filter_str

        if stype in ["roundRect", "rounded_rectangle"]:
            rx = radius * min(w, h) if (0 < radius <= 0.5) else (radius if radius > 0 else 12.0)
            attrs = dict(common_attrs)
            attrs.update({
                "x": str(x),
                "y": str(y),
                "width": str(w),
                "height": str(h),
                "rx": str(rx),
                "ry": str(rx),
            })
            etree.SubElement(parent, _q("rect"), attrib=attrs)

        elif stype in ["ellipse", "circle"]:
            cx = x + w / 2.0
            cy = y + h / 2.0
            attrs = dict(common_attrs)
            attrs.update({
                "cx": str(cx),
                "cy": str(cy),
                "rx": str(w / 2.0),
                "ry": str(h / 2.0),
            })
            etree.SubElement(parent, _q("ellipse"), attrib=attrs)

        elif stype == "diamond":
            cx = x + w / 2.0
            cy = y + h / 2.0
            points = f"{cx},{y} {x+w},{cy} {cx},{y+h} {x},{cy}"
            attrs = dict(common_attrs)
            attrs["points"] = points
            etree.SubElement(parent, _q("polygon"), attrib=attrs)

        elif stype in ["triangle", "upArrow"]:
            points = f"{x + w/2.0},{y} {x + w},{y + h} {x},{y + h}"
            attrs = dict(common_attrs)
            attrs["points"] = points
            etree.SubElement(parent, _q("polygon"), attrib=attrs)

        elif stype in ["rightArrow", "arrow"]:
            y_mid = y + h / 2.0
            head_len = min(w * 0.4, 40.0)
            shaft_h = h * 0.4
            y_top = y_mid - shaft_h / 2.0
            y_bot = y_mid + shaft_h / 2.0
            head_x = x + w - head_len
            points = f"{x},{y_top} {head_x},{y_top} {head_x},{y} {x+w},{y_mid} {head_x},{y+h} {head_x},{y_bot} {x},{y_bot}"
            attrs = dict(common_attrs)
            attrs["points"] = points
            etree.SubElement(parent, _q("polygon"), attrib=attrs)

        else:
            # Default rectangle
            attrs = dict(common_attrs)
            attrs.update({
                "x": str(x),
                "y": str(y),
                "width": str(w),
                "height": str(h),
            })
            etree.SubElement(parent, _q("rect"), attrib=attrs)

    @classmethod
    def _render_text(
        cls,
        tc: Optional[TextContentIR],
        x: float,
        y: float,
        w: float,
        h: float,
        padding: float,
        parent: etree._Element,
    ) -> None:
        if not tc or not tc.paragraphs:
            return

        curr_y = y + padding

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

            runs_with_text = [r for r in p.runs if r.text]
            if not runs_with_text:
                continue

            text_elem = etree.SubElement(
                parent,
                _q("text"),
                attrib={
                    "x": str(tx),
                    "y": str(curr_y),
                    "text-anchor": anchor,
                },
            )

            for r in runs_with_text:
                font = r.font
                font_family = safe_font_family(font.name if font else None, "Segoe UI")
                font_size = font.size if font else 16.0
                font_color = safe_color(font.color if font else None, "#1E293B")
                weight = "bold" if (font and font.bold) else "normal"
                italic = "italic" if (font and font.italic) else "normal"

                tspan = etree.SubElement(
                    text_elem,
                    _q("tspan"),
                    attrib={
                        "font-family": f"{font_family}, sans-serif",
                        "font-size": f"{font_size}px",
                        "font-weight": weight,
                        "font-style": italic,
                        "fill": font_color,
                    },
                )
                tspan.text = r.text

    @classmethod
    def _render_fill_attribute(
        cls, fill: Optional[FillStyle], grad_id: str, defs: etree._Element
    ) -> str:
        if not fill or fill.type == "none":
            return "none"
        if fill.type == "solid":
            color = safe_color(fill.color, "#3B82F6")
            if fill.alpha < 1.0:
                return cls._hex_to_rgba(color, fill.alpha)
            return color
        if fill.type == "gradient" and fill.gradient:
            grad = fill.gradient
            rad = math.radians(grad.angle)
            x1 = round(50 - 50 * math.cos(rad), 2)
            y1 = round(50 - 50 * math.sin(rad), 2)
            x2 = round(50 + 50 * math.cos(rad), 2)
            y2 = round(50 + 50 * math.sin(rad), 2)

            safe_gid = safe_id(grad_id, "grad")
            grad_elem = etree.SubElement(
                defs,
                _q("linearGradient"),
                attrib={
                    "id": safe_gid,
                    "x1": f"{x1}%",
                    "y1": f"{y1}%",
                    "x2": f"{x2}%",
                    "y2": f"{y2}%",
                },
            )

            for s in grad.stops:
                pct = int(s.position * 100)
                etree.SubElement(
                    grad_elem,
                    _q("stop"),
                    attrib={
                        "offset": f"{pct}%",
                        "stop-color": safe_color(s.color, "#3B82F6"),
                        "stop-opacity": str(s.alpha),
                    },
                )

            return f"url(#{safe_gid})"
        return "#3B82F6"

    @classmethod
    def _render_stroke_attributes(
        cls, border: Optional[BorderStyle]
    ) -> Tuple[str, float, str]:
        if not border or border.style == "none" or border.width <= 0:
            return "none", 0.0, ""

        color = safe_color(border.color, "#1E293B")
        if border.alpha < 1.0:
            color = cls._hex_to_rgba(color, border.alpha)

        dash = ""
        if border.style == "dashed":
            dash = "6,4"
        elif border.style == "dotted":
            dash = "2,2"

        return color, border.width, dash

    @staticmethod
    def _hex_to_rgba(hex_color: str, alpha: float) -> str:
        h = hex_color.lstrip("#")
        if len(h) == 6:
            try:
                r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
                return f"rgba({r},{g},{b},{alpha:.2f})"
            except ValueError:
                return hex_color
        return hex_color
