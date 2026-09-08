"""Style parser for OOXML themes, colors, fills, borders, and effects."""

from __future__ import annotations
from typing import Optional, Dict, Any, Tuple
import xml.etree.ElementTree as ET

from ..model.style import Color, Fill, Line, Shadow, GradientStop, Font, ParagraphStyle
from .constants import (
    NS,
    emu_to_pt,
    angle_to_degrees,
    PRESET_COLORS,
    apply_color_modifiers,
    rgb_to_hex
)


class StyleParser:
    """Parses styles, colors, fills, lines, and shadows from OOXML elements."""

    def __init__(self, theme_colors: Optional[Dict[str, str]] = None, theme_fonts: Optional[Dict[str, str]] = None):
        self.theme_colors = theme_colors or {}
        self.theme_fonts = theme_fonts or {}

    def parse_color_element(self, parent_elem: ET.Element) -> Optional[Tuple[str, float, Optional[str]]]:
        """
        Parses color and alpha from any element that may contain a color child
        (e.g., srgbClr, schemeClr, prstClr, sysClr).
        Returns: (hex_color, alpha_percent, scheme_name)
        """
        if parent_elem is None:
            return None

        # Search for color tags in DrawingML namespace (direct or descendant)
        srgb = parent_elem if parent_elem.tag == f"{{{NS['a']}}}srgbClr" else parent_elem.find(".//a:srgbClr", NS)
        if srgb is not None:
            val = srgb.get("val", "000000")
            alpha = self._parse_alpha(srgb)
            return f"#{val.upper()}", alpha, None

        scheme = parent_elem if parent_elem.tag == f"{{{NS['a']}}}schemeClr" else parent_elem.find(".//a:schemeClr", NS)
        if scheme is not None:
            scheme_val = scheme.get("val", "")
            base_hex = self.theme_colors.get(scheme_val, "#000000")
            
            # Check modifiers
            lum_mod = self._get_attr_int(scheme, "a:lumMod", "val")
            lum_off = self._get_attr_int(scheme, "a:lumOff", "val")
            tint = self._get_attr_int(scheme, "a:tint", "val")
            shade = self._get_attr_int(scheme, "a:shade", "val")
            
            resolved_hex = apply_color_modifiers(base_hex, lum_mod, lum_off, tint, shade)
            alpha = self._parse_alpha(scheme)
            return resolved_hex, alpha, scheme_val

        prst = parent_elem if parent_elem.tag == f"{{{NS['a']}}}prstClr" else parent_elem.find(".//a:prstClr", NS)
        if prst is not None:
            val = prst.get("val", "black")
            hex_color = PRESET_COLORS.get(val, "#000000")
            alpha = self._parse_alpha(prst)
            return hex_color, alpha, None

        sys = parent_elem if parent_elem.tag == f"{{{NS['a']}}}sysClr" else parent_elem.find(".//a:sysClr", NS)
        if sys is not None:
            last_clr = sys.get("lastClr", "000000")
            alpha = self._parse_alpha(sys)
            return f"#{last_clr.upper()}", alpha, None

        return None

    def _parse_alpha(self, elem: ET.Element) -> float:
        """Parse alpha tag inside color element, OOXML: 100000 = 100%."""
        alpha_elem = elem.find("a:alpha", NS)
        if alpha_elem is not None:
            val = alpha_elem.get("val")
            if val is not None:
                try:
                    return round(float(val) / 1000.0, 2)  # 100000 -> 100.0
                except ValueError:
                    pass
        return 100.0

    def _get_attr_int(self, elem: ET.Element, child_tag: str, attr_name: str) -> Optional[int]:
        child = elem.find(child_tag, NS)
        if child is not None:
            val = child.get(attr_name)
            if val is not None:
                try:
                    return int(val)
                except ValueError:
                    pass
        return None

    def parse_fill(self, parent_elem: ET.Element) -> Fill:
        """Parses fill properties from an element containing solidFill, gradFill, noFill, etc."""
        if parent_elem is None:
            return Fill(type="none")

        if parent_elem.find("a:noFill", NS) is not None:
            return Fill(type="none")

        solid = parent_elem.find("a:solidFill", NS)
        if solid is not None:
            color_res = self.parse_color_element(solid)
            if color_res:
                color_hex, alpha, scheme_val = color_res
                return Fill(
                    type="solid",
                    color=color_hex,
                    alpha=alpha,
                    scheme_color=scheme_val
                )
            return Fill(type="solid", color="#000000")

        grad = parent_elem.find("a:gradFill", NS)
        if grad is not None:
            angle = 90.0
            lin = grad.find("a:lin", NS)
            if lin is not None:
                ang_val = lin.get("ang")
                if ang_val:
                    try:
                        angle = angle_to_degrees(int(ang_val))
                    except ValueError:
                        pass

            stops = []
            gs_lst = grad.find("a:gsLst", NS)
            if gs_lst is not None:
                for gs in gs_lst.findall("a:gs", NS):
                    pos_val = gs.get("pos", "0")
                    try:
                        pos = float(pos_val) / 100000.0
                    except ValueError:
                        pos = 0.0
                    c_res = self.parse_color_element(gs)
                    if c_res:
                        hex_c, alpha_c, _ = c_res
                        stops.append(GradientStop(position=pos, color=hex_c, alpha=alpha_c))
            return Fill(type="gradient", angle=angle, stops=stops)

        blip = parent_elem.find("a:blipFill", NS)
        if blip is not None:
            return Fill(type="picture")

        return Fill(type="none")

    def parse_line(self, parent_elem: ET.Element) -> Optional[Line]:
        """Parses line/border properties from <a:ln> child element."""
        if parent_elem is None:
            return None

        ln = parent_elem.find("a:ln", NS) if parent_elem.tag != f"{{{NS['a']}}}ln" else parent_elem
        if ln is None:
            return None

        if ln.find("a:noFill", NS) is not None:
            return None

        w_val = ln.get("w")
        width_pt = emu_to_pt(int(w_val)) if w_val and w_val.isdigit() else 1.0

        color_hex = "#000000"
        alpha = 100.0
        c_res = self.parse_color_element(ln)
        if c_res:
            color_hex, alpha, _ = c_res

        # Dash style
        style = "solid"
        prst_dash = ln.find("a:prstDash", NS)
        if prst_dash is not None:
            style = prst_dash.get("val", "solid")

        # Head / Tail arrow ends
        arrow_start = None
        tail_end = ln.find("a:tailEnd", NS)
        if tail_end is not None:
            arrow_start = tail_end.get("type")
            if arrow_start == "none":
                arrow_start = None

        arrow_end = None
        head_end = ln.find("a:headEnd", NS)
        if head_end is not None:
            arrow_end = head_end.get("type")
            if arrow_end == "none":
                arrow_end = None

        return Line(
            color=color_hex,
            width=width_pt,
            alpha=alpha,
            style=style,
            arrow_start=arrow_start,
            arrow_end=arrow_end
        )

    def parse_shadow(self, parent_elem: ET.Element) -> Optional[Shadow]:
        """Parses shadow effect from <a:effectLst>."""
        if parent_elem is None:
            return None

        effects = parent_elem.find("a:effectLst", NS)
        if effects is None:
            return None

        shdw = effects.find("a:outerShdw", NS)
        if shdw is None:
            return None

        blur_rad = shdw.get("blurRad", "0")
        dist = shdw.get("dist", "0")
        dir_val = shdw.get("dir", "0")

        blur_pt = emu_to_pt(int(blur_rad)) if blur_rad.isdigit() else 4.0
        dist_pt = emu_to_pt(int(dist)) if dist.isdigit() else 3.0
        dir_deg = angle_to_degrees(int(dir_val)) if dir_val.isdigit() else 45.0

        color_hex = "#000000"
        alpha = 40.0
        c_res = self.parse_color_element(shdw)
        if c_res:
            color_hex, alpha, _ = c_res

        return Shadow(
            enabled=True,
            color=color_hex,
            alpha=alpha,
            blur=blur_pt,
            distance=dist_pt,
            direction=dir_deg
        )

    @classmethod
    def parse_theme_xml(cls, theme_root: ET.Element) -> Tuple[Dict[str, str], Dict[str, str]]:
        """
        Parses color scheme and font scheme from ppt/theme/theme1.xml.
        Returns: (color_scheme_dict, font_scheme_dict)
        """
        colors: Dict[str, str] = {}
        fonts: Dict[str, str] = {}

        if theme_root is None:
            return colors, fonts

        # Parse clrScheme
        clr_scheme = theme_root.find(".//a:themeElements/a:clrScheme", NS)
        if clr_scheme is not None:
            for child in clr_scheme:
                tag_name = child.tag.split("}")[-1]
                srgb = child.find("a:srgbClr", NS)
                if srgb is not None:
                    colors[tag_name] = f"#{srgb.get('val', '000000').upper()}"
                else:
                    sys_clr = child.find("a:sysClr", NS)
                    if sys_clr is not None:
                        colors[tag_name] = f"#{sys_clr.get('lastClr', '000000').upper()}"

        # Standard theme mappings (e.g. dk1, lt1)
        if "dk1" in colors and "dark1" not in colors:
            colors["dark1"] = colors["dk1"]
        if "lt1" in colors and "light1" not in colors:
            colors["light1"] = colors["lt1"]
        if "dk2" in colors and "dark2" not in colors:
            colors["dark2"] = colors["dk2"]
        if "lt2" in colors and "light2" not in colors:
            colors["light2"] = colors["lt2"]

        # Parse fontScheme
        font_scheme = theme_root.find(".//a:themeElements/a:fontScheme", NS)
        if font_scheme is not None:
            major = font_scheme.find("a:majorFont/a:latin", NS)
            if major is not None:
                fonts["major"] = major.get("typeface", "Calibri")
            major_ea = font_scheme.find("a:majorFont/a:ea", NS)
            if major_ea is not None:
                fonts["major_ea"] = major_ea.get("typeface", "")

            minor = font_scheme.find("a:minorFont/a:latin", NS)
            if minor is not None:
                fonts["minor"] = minor.get("typeface", "Calibri")
            minor_ea = font_scheme.find("a:minorFont/a:ea", NS)
            if minor_ea is not None:
                fonts["minor_ea"] = minor_ea.get("typeface", "")

        return colors, fonts
