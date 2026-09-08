"""DrawingML theme generator and updater for valid Office PowerPoint themes."""

from __future__ import annotations
import os
from typing import Optional, Dict
import xml.etree.ElementTree as ET

from ..model.slide import ThemeInfo
from ..extractor.constants import NS


_DEFAULT_THEME_PATH = os.path.join(os.path.dirname(__file__), "default_theme.xml")


def get_base_theme_bytes() -> bytes:
    """Returns raw bytes of the authentic standard Office theme."""
    if os.path.exists(_DEFAULT_THEME_PATH):
        with open(_DEFAULT_THEME_PATH, "rb") as f:
            return f.read()
    raise FileNotFoundError(f"Missing default_theme.xml at {_DEFAULT_THEME_PATH}")


def build_theme_xml(
    theme: Optional[ThemeInfo] = None,
    base_theme_bytes: Optional[bytes] = None
) -> str:
    """
    Builds a fully Office-compliant theme XML string.
    If base_theme_bytes is provided, it updates the colorScheme and fontScheme in it.
    Otherwise, it uses the standard Office default theme base.
    """
    raw_bytes = base_theme_bytes or get_base_theme_bytes()
    tree = ET.fromstring(raw_bytes)

    # Register DrawingML namespace
    ET.register_namespace("a", NS["a"])

    if theme is not None:
        # Update theme name
        if theme.name:
            tree.set("name", theme.name)

        # Update Color Scheme if customized
        if theme.color_scheme:
            clr_scheme = tree.find(f".//{{{NS['a']}}}clrScheme")
            if clr_scheme is not None:
                for slot_name, hex_color in theme.color_scheme.items():
                    clean_slot = slot_name.strip()
                    clean_hex = hex_color.lstrip("#").upper()
                    slot_elem = clr_scheme.find(f"{{{NS['a']}}}{clean_slot}")
                    if slot_elem is not None:
                        srgb = slot_elem.find(f"{{{NS['a']}}}srgbClr")
                        if srgb is not None:
                            srgb.set("val", clean_hex)
                        else:
                            sys_clr = slot_elem.find(f"{{{NS['a']}}}sysClr")
                            if sys_clr is not None:
                                sys_clr.set("lastClr", clean_hex)

        # Update Font Scheme if customized
        if theme.font_scheme:
            font_scheme = tree.find(f".//{{{NS['a']}}}fontScheme")
            if font_scheme is not None:
                major_font = theme.font_scheme.get("major")
                minor_font = theme.font_scheme.get("minor")
                if major_font:
                    maj_latin = font_scheme.find(f".//{{{NS['a']}}}majorFont/{{{NS['a']}}}latin")
                    if maj_latin is not None:
                        maj_latin.set("typeface", major_font)
                if minor_font:
                    min_latin = font_scheme.find(f".//{{{NS['a']}}}minorFont/{{{NS['a']}}}latin")
                    if min_latin is not None:
                        min_latin.set("typeface", minor_font)

    # Clean any accidental manual xmlns attributes from root
    for k in list(tree.attrib.keys()):
        if k.startswith("xmlns"):
            del tree.attrib[k]

    return ET.tostring(tree, encoding="utf-8", xml_declaration=True).decode("utf-8")
