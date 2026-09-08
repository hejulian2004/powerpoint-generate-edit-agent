"""OOXML namespaces, unit conversions, and geometry constants."""

from typing import Tuple, Dict

# OOXML Namespaces
NS = {
    'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'pr': 'http://schemas.openxmlformats.org/package/2006/relationships',
    'ct': 'http://schemas.openxmlformats.org/package/2006/content-types',
}

# English Metric Units conversions
EMU_PER_INCH = 914400
EMU_PER_PT = 12700
EMU_PER_CM = 360000
DEGREE_MULTIPLIER = 60000  # 60000 units per degree in DrawingML


def emu_to_inches(emu: int | float) -> float:
    """Convert EMUs to inches, rounded to 4 decimal places."""
    return round(float(emu) / EMU_PER_INCH, 4)


def inches_to_emu(inches: float) -> int:
    """Convert inches to EMUs."""
    return int(round(inches * EMU_PER_INCH))


def emu_to_pt(emu: int | float) -> float:
    """Convert EMUs to points."""
    return round(float(emu) / EMU_PER_PT, 2)


def pt_to_emu(pt: float) -> int:
    """Convert points to EMUs."""
    return int(round(pt * EMU_PER_PT))


def angle_to_degrees(ooxml_angle: int | float) -> float:
    """Convert OOXML angle (1/60000th of degree) to degrees."""
    return round(float(ooxml_angle) / DEGREE_MULTIPLIER, 2)


def degrees_to_angle(degrees: float) -> int:
    """Convert degrees to OOXML angle."""
    return int(round(degrees * DEGREE_MULTIPLIER))


# Shape type mapping: OOXML presetGeom -> normalized name
PRESET_GEOM_MAP: Dict[str, str] = {
    "rect": "rectangle",
    "roundRect": "roundRect",
    "ellipse": "ellipse",
    "diamond": "diamond",
    "triangle": "triangle",
    "rightTriangle": "rightTriangle",
    "parallelogram": "parallelogram",
    "trapezoid": "trapezoid",
    "hexagon": "hexagon",
    "octagon": "octagon",
    "star5": "star5",
    "rightArrow": "arrow",
    "leftArrow": "leftArrow",
    "upArrow": "upArrow",
    "downArrow": "downArrow",
    "line": "line",
    "straightConnector1": "line",
    "bentConnector2": "bentLine",
    "bentConnector3": "bentLine",
    "curvedConnector3": "curvedLine",
}

# Reverse mapping: normalized name -> OOXML presetGeom
REVERSE_GEOM_MAP: Dict[str, str] = {
    "rectangle": "rect",
    "rect": "rect",
    "roundRect": "roundRect",
    "round_rect": "roundRect",
    "roundrectangle": "roundRect",
    "ellipse": "ellipse",
    "circle": "ellipse",
    "diamond": "diamond",
    "triangle": "triangle",
    "rightTriangle": "rightTriangle",
    "parallelogram": "parallelogram",
    "trapezoid": "trapezoid",
    "hexagon": "hexagon",
    "octagon": "octagon",
    "star5": "star5",
    "arrow": "rightArrow",
    "rightArrow": "rightArrow",
    "leftArrow": "leftArrow",
    "upArrow": "upArrow",
    "downArrow": "downArrow",
    "line": "line",
    "straightConnector1": "straightConnector1",
    "bentConnector3": "bentConnector3",
    "curvedConnector3": "curvedConnector3",
}

# Standard preset colors in DrawingML
PRESET_COLORS: Dict[str, str] = {
    "black": "#000000",
    "white": "#FFFFFF",
    "red": "#FF0000",
    "green": "#00FF00",
    "blue": "#0000FF",
    "yellow": "#FFFF00",
    "cyan": "#00FFFF",
    "magenta": "#FF00FF",
    "gray": "#808080",
    "lightGray": "#D3D3D3",
    "darkGray": "#A9A9A9",
}


def hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    """Convert hex #RRGGBB or RRGGBB to (r, g, b) tuple."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return (0, 0, 0)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def rgb_to_hex(r: int, g: int, b: int) -> str:
    """Convert (r, g, b) tuple to #RRGGBB hex string."""
    r = max(0, min(255, int(r)))
    g = max(0, min(255, int(g)))
    b = max(0, min(255, int(b)))
    return f"#{r:02X}{g:02X}{b:02X}"


def apply_color_modifiers(base_hex: str, lum_mod: float | None = None, lum_off: float | None = None,
                           tint: float | None = None, shade: float | None = None) -> str:
    """Apply DrawingML color modifiers (lumMod, lumOff, tint, shade) to hex color."""
    r, g, b = hex_to_rgb(base_hex)
    
    if tint is not None:
        # tint = blend with white
        factor = tint / 100000.0
        r = int(r * factor + 255 * (1.0 - factor))
        g = int(g * factor + 255 * (1.0 - factor))
        b = int(b * factor + 255 * (1.0 - factor))
        
    if shade is not None:
        # shade = blend with black
        factor = shade / 100000.0
        r = int(r * factor)
        g = int(g * factor)
        b = int(b * factor)
        
    if lum_mod is not None:
        factor = lum_mod / 100000.0
        r = int(r * factor)
        g = int(g * factor)
        b = int(b * factor)
        
    if lum_off is not None:
        offset = int(255 * (lum_off / 100000.0))
        r = r + offset
        g = g + offset
        b = b + offset
        
    return rgb_to_hex(r, g, b)
