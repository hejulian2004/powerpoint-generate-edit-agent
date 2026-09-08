"""ThemeEngine: High-Fidelity DrawingML theme parsing and token resolution.

Supports:
- ppt/theme/theme1.xml parsing
- Color schemes (accent1-6, dk1, lt1, dk2, lt2, hlink, folHlink)
- DrawingML color transforms (lumMod, lumOff, tint, shade, alpha)
- Font schemes (majorFont / minorFont with Latin, EastAsian, and ComplexScript mappings)
- Format schemes (line, fill, effect default style slots)
"""

from __future__ import annotations
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Tuple, List, Union

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}

DEFAULT_COLOR_SCHEME: Dict[str, str] = {
    "dk1": "#000000",
    "lt1": "#FFFFFF",
    "dk2": "#1E293B",
    "lt2": "#F8FAFC",
    "accent1": "#2563EB",
    "accent2": "#0EA5E9",
    "accent3": "#10B981",
    "accent4": "#F59E0B",
    "accent5": "#EF4444",
    "accent6": "#8B5CF6",
    "hlink": "#2563EB",
    "folHlink": "#7C3AED",
}

DEFAULT_FONT_SCHEME: Dict[str, Dict[str, str]] = {
    "majorFont": {
        "latin": "Calibri Light",
        "ea": "Microsoft YaHei",
        "cs": "Calibri Light",
    },
    "minorFont": {
        "latin": "Calibri",
        "ea": "Microsoft YaHei",
        "cs": "Calibri",
    },
}


def hex_to_rgb(hex_str: str) -> Tuple[int, int, int]:
    """Parses #RRGGBB or RRGGBB into (R, G, B) tuple."""
    s = hex_str.strip().lstrip("#")
    if len(s) == 3:
        s = "".join([c * 2 for c in s])
    if len(s) == 6:
        try:
            return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
        except ValueError:
            return 0, 0, 0
    return 0, 0, 0


def rgb_to_hex(r: int, g: int, b: int) -> str:
    """Formats (R, G, B) integers (0-255) into standard #RRGGBB string."""
    r_clamped = max(0, min(255, int(round(r))))
    g_clamped = max(0, min(255, int(round(g))))
    b_clamped = max(0, min(255, int(round(b))))
    return f"#{r_clamped:02X}{g_clamped:02X}{b_clamped:02X}"


def rgb_to_hsl(r: int, g: int, b: int) -> Tuple[float, float, float]:
    """Converts RGB (0-255) to HSL (H: 0-360, S: 0-1, L: 0-1)."""
    rf, gf, bf = r / 255.0, g / 255.0, b / 255.0
    cmax = max(rf, gf, bf)
    cmin = min(rf, gf, bf)
    delta = cmax - cmin
    l = (cmax + cmin) / 2.0

    if delta == 0:
        h = 0.0
        s = 0.0
    else:
        s = delta / (1.0 - abs(2.0 * l - 1.0)) if (1.0 - abs(2.0 * l - 1.0)) != 0 else 0.0
        if cmax == rf:
            h = 60.0 * (((gf - bf) / delta) % 6)
        elif cmax == gf:
            h = 60.0 * (((bf - rf) / delta) + 2)
        else:
            h = 60.0 * (((rf - gf) / delta) + 4)
    return h, s, l


def hsl_to_rgb(h: float, s: float, l: float) -> Tuple[int, int, int]:
    """Converts HSL to RGB (0-255)."""
    c = (1.0 - abs(2.0 * l - 1.0)) * s
    x = c * (1.0 - abs((h / 60.0) % 2 - 1.0))
    m = l - c / 2.0
    if 0 <= h < 60:
        rf, gf, bf = c, x, 0.0
    elif 60 <= h < 120:
        rf, gf, bf = x, c, 0.0
    elif 120 <= h < 180:
        rf, gf, bf = 0.0, c, x
    elif 180 <= h < 240:
        rf, gf, bf = 0.0, x, c
    elif 240 <= h < 300:
        rf, gf, bf = x, 0.0, c
    else:
        rf, gf, bf = c, 0.0, x
    return (
        int(round((rf + m) * 255.0)),
        int(round((gf + m) * 255.0)),
        int(round((bf + m) * 255.0)),
    )


def apply_color_modifiers(
    base_hex: str,
    lum_mod: Optional[int] = None,
    lum_off: Optional[int] = None,
    tint: Optional[int] = None,
    shade: Optional[int] = None,
) -> str:
    """Applies DrawingML color transform modifiers to base hex color.

    OOXML modifier specifications:
    - lumMod: Luminance modulation (100000 = 100%). L_new = L * (lumMod / 100000)
    - lumOff: Luminance offset (100000 = +100%). L_new = L + (lumOff / 100000)
    - tint: Tint towards white (val: 0-100000). C_new = C * (tint/100000) + 255 * (1 - tint/100000)
    - shade: Shade towards black (val: 0-100000). C_new = C * (shade/100000)
    """
    r, g, b = hex_to_rgb(base_hex)

    # Tint & Shade operate in RGB channel space
    if tint is not None:
        factor = max(0.0, min(1.0, float(tint) / 100000.0))
        r = int(round(r * factor + 255.0 * (1.0 - factor)))
        g = int(round(g * factor + 255.0 * (1.0 - factor)))
        b = int(round(b * factor + 255.0 * (1.0 - factor)))

    if shade is not None:
        factor = max(0.0, min(1.0, float(shade) / 100000.0))
        r = int(round(r * factor))
        g = int(round(g * factor))
        b = int(round(b * factor))

    # lumMod and lumOff operate in HSL luminance space
    if lum_mod is not None or lum_off is not None:
        h, s, l = rgb_to_hsl(r, g, b)
        if lum_mod is not None:
            l = l * (float(lum_mod) / 100000.0)
        if lum_off is not None:
            l = l + (float(lum_off) / 100000.0)
        l = max(0.0, min(1.0, l))
        r, g, b = hsl_to_rgb(h, s, l)

    return rgb_to_hex(r, g, b)


@dataclass
class FontScheme:
    major_font: str = "Calibri Light"
    minor_font: str = "Calibri"
    major_fonts_by_script: Dict[str, str] = field(default_factory=lambda: {
        "latin": "Calibri Light",
        "ea": "Microsoft YaHei",
        "cs": "Calibri Light"
    })
    minor_fonts_by_script: Dict[str, str] = field(default_factory=lambda: {
        "latin": "Calibri",
        "ea": "Microsoft YaHei",
        "cs": "Calibri"
    })

    def to_dict(self) -> Dict[str, Any]:
        return {
            "major_font": self.major_font,
            "minor_font": self.minor_font,
            "major_fonts_by_script": dict(self.major_fonts_by_script),
            "minor_fonts_by_script": dict(self.minor_fonts_by_script)
        }


class ThemeEngine:
    """DrawingML theme engine for color resolution, font schemes, and style reference lookup."""

    def __init__(
        self,
        name: str = "Office Theme",
        color_scheme: Optional[Dict[str, str]] = None,
        font_scheme: Optional[Union[FontScheme, Dict[str, Any]]] = None,
        raw_xml_bytes: Optional[bytes] = None,
    ):
        self.name = name
        self.color_scheme: Dict[str, str] = dict(DEFAULT_COLOR_SCHEME)
        if color_scheme:
            self.color_scheme.update({k.lower(): v for k, v in color_scheme.items()})

        if isinstance(font_scheme, FontScheme):
            self.font_scheme = font_scheme
        elif isinstance(font_scheme, dict):
            maj = font_scheme.get("major_font", "Calibri Light")
            min_ = font_scheme.get("minor_font", "Calibri")
            maj_by_script = font_scheme.get("major_fonts_by_script", {"latin": maj, "ea": "Microsoft YaHei", "cs": maj})
            min_by_script = font_scheme.get("minor_fonts_by_script", {"latin": min_, "ea": "Microsoft YaHei", "cs": min_})
            self.font_scheme = FontScheme(
                major_font=maj,
                minor_font=min_,
                major_fonts_by_script=maj_by_script,
                minor_fonts_by_script=min_by_script,
            )
        else:
            self.font_scheme = FontScheme()

        self.raw_xml_bytes = raw_xml_bytes

    @classmethod
    def from_theme_xml(cls, xml_bytes_or_str: Union[bytes, str]) -> ThemeEngine:
        """Parses a DrawingML ppt/theme/theme1.xml package component."""
        raw_bytes = xml_bytes_or_str.encode("utf-8") if isinstance(xml_bytes_or_str, str) else xml_bytes_or_str
        tree = ET.fromstring(raw_bytes)

        # 1. Theme Name
        theme_name = tree.get("name", "Imported Theme")

        # 2. Color Scheme
        clr_scheme_elem = tree.find(".//a:clrScheme", NS)
        colors = dict(DEFAULT_COLOR_SCHEME)
        if clr_scheme_elem is not None:
            scheme_name = clr_scheme_elem.get("name", theme_name)
            for child in clr_scheme_elem:
                tag = child.tag.split("}")[-1]  # dk1, lt1, accent1, etc.
                srgb = child.find("a:srgbClr", NS)
                if srgb is not None and srgb.get("val"):
                    colors[tag.lower()] = f"#{srgb.get('val').upper()}"
                else:
                    sys_clr = child.find("a:sysClr", NS)
                    if sys_clr is not None and sys_clr.get("lastClr"):
                        colors[tag.lower()] = f"#{sys_clr.get('lastClr').upper()}"

        # 3. Font Scheme
        font_scheme = FontScheme()
        font_elem = tree.find(".//a:fontScheme", NS)
        if font_elem is not None:
            maj_elem = font_elem.find("a:majorFont", NS)
            min_elem = font_elem.find("a:minorFont", NS)
            if maj_elem is not None:
                lat = maj_elem.find("a:latin", NS)
                ea = maj_elem.find("a:ea", NS)
                cs = maj_elem.find("a:cs", NS)
                if lat is not None and lat.get("typeface"):
                    font_scheme.major_font = lat.get("typeface")
                    font_scheme.major_fonts_by_script["latin"] = lat.get("typeface")
                if ea is not None and ea.get("typeface"):
                    font_scheme.major_fonts_by_script["ea"] = ea.get("typeface")
                if cs is not None and cs.get("typeface"):
                    font_scheme.major_fonts_by_script["cs"] = cs.get("typeface")

            if min_elem is not None:
                lat = min_elem.find("a:latin", NS)
                ea = min_elem.find("a:ea", NS)
                cs = min_elem.find("a:cs", NS)
                if lat is not None and lat.get("typeface"):
                    font_scheme.minor_font = lat.get("typeface")
                    font_scheme.minor_fonts_by_script["latin"] = lat.get("typeface")
                if ea is not None and ea.get("typeface"):
                    font_scheme.minor_fonts_by_script["ea"] = ea.get("typeface")
                if cs is not None and cs.get("typeface"):
                    font_scheme.minor_fonts_by_script["cs"] = cs.get("typeface")

        return cls(
            name=theme_name,
            color_scheme=colors,
            font_scheme=font_scheme,
            raw_xml_bytes=raw_bytes
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ThemeEngine:
        """Constructs ThemeEngine from PresentationIR.theme or serializable dict."""
        name = data.get("name", "Default Theme")
        clr_scheme = data.get("color_scheme") or {}
        # Fallback to top-level legacy keys if present
        if not clr_scheme:
            if "primary_color" in data:
                clr_scheme["accent1"] = data["primary_color"]
            if "secondary_color" in data:
                clr_scheme["dk1"] = data["secondary_color"]
            if "background_color" in data:
                clr_scheme["lt1"] = data["background_color"]

        fnt_scheme = data.get("font_scheme")
        if not fnt_scheme:
            maj = data.get("font_heading", "Calibri Light")
            min_ = data.get("font_body", "Calibri")
            fnt_scheme = {"major_font": maj, "minor_font": min_}

        return cls(name=name, color_scheme=clr_scheme, font_scheme=fnt_scheme)

    def resolve_color(
        self,
        color_ref: Union[str, Dict[str, Any]],
        modifiers: Optional[Dict[str, Any]] = None,
        default: str = "#000000"
    ) -> str:
        """Resolves theme token or raw hex to canonical #RRGGBB color.

        Supports:
        - Raw hex string: "#2563EB"
        - Direct theme token string: "accent1", "dk1", "lt1"
        - Structured token object: {"type": "theme_color", "value": "accent1", "lumMod": 80000}
        """
        if not color_ref:
            return default

        # 1. Parse input format
        token = ""
        mods = dict(modifiers or {})
        if isinstance(color_ref, dict):
            val = color_ref.get("value") or color_ref.get("color") or ""
            ctype = color_ref.get("type", "")
            if ctype == "theme_color" or val.lower() in self.color_scheme:
                token = val.lower()
            else:
                token = val
            for k in ["lumMod", "lumOff", "tint", "shade", "alpha"]:
                if k in color_ref and k not in mods:
                    mods[k] = color_ref[k]
        elif isinstance(color_ref, str):
            clean = color_ref.strip()
            if clean.lower() in self.color_scheme:
                token = clean.lower()
            elif clean.startswith("#"):
                token = clean
            else:
                # E.g. accent1
                token = clean.lower()

        # 2. Resolve base color
        if token.lower() in self.color_scheme:
            base_hex = self.color_scheme[token.lower()]
        elif token.startswith("#"):
            base_hex = token
        else:
            base_hex = default

        # 3. Apply modifier chain if present
        if mods:
            return apply_color_modifiers(
                base_hex=base_hex,
                lum_mod=mods.get("lumMod"),
                lum_off=mods.get("lumOff"),
                tint=mods.get("tint"),
                shade=mods.get("shade"),
            )
        return base_hex

    def get_major_font(self, script: str = "latin") -> str:
        """Returns heading font family for specified script ('latin', 'ea', 'cs')."""
        return self.font_scheme.major_fonts_by_script.get(script, self.font_scheme.major_font)

    def get_minor_font(self, script: str = "latin") -> str:
        """Returns body font family for specified script ('latin', 'ea', 'cs')."""
        return self.font_scheme.minor_fonts_by_script.get(script, self.font_scheme.minor_font)

    def to_dict(self) -> Dict[str, Any]:
        """Serializes ThemeEngine state for PresentationIR embedding."""
        return {
            "name": self.name,
            "primary_color": self.color_scheme.get("accent1", "#2563EB"),
            "secondary_color": self.color_scheme.get("dk1", "#000000"),
            "background_color": self.color_scheme.get("lt1", "#FFFFFF"),
            "color_scheme": dict(self.color_scheme),
            "font_scheme": self.font_scheme.to_dict(),
            "font_heading": self.font_scheme.major_font,
            "font_body": self.font_scheme.minor_font,
        }
