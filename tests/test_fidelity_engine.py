"""Unit tests for PR6.1 OOXML Fidelity Engine."""

import pytest
import io
import zipfile
from backend.fidelity import (
    ThemeEngine, FontEngine, StyleResolver,
    RelationshipGraph, AssetManager, OOXMLParser,
    FidelityDiffEngine, FidelityDiffReport
)
from backend.ir.models import (
    PresentationIR, SlideIR, ShapeElementIR, TextElementIR,
    FillStyle, BorderStyle, FontIR, TextContentIR, RunIR, ParagraphIR
)


def test_theme_engine_color_resolution_and_modifiers():
    theme = ThemeEngine(
        name="Test Corporate",
        color_scheme={
            "accent1": "#2563EB",
            "accent2": "#10B981",
            "dk1": "#0F172A",
            "lt1": "#FFFFFF"
        }
    )

    # 1. Direct scheme token
    assert theme.resolve_color("accent1") == "#2563EB"
    assert theme.resolve_color("accent2") == "#10B981"

    # 2. Case insensitive
    assert theme.resolve_color("ACCENT1") == "#2563EB"

    # 3. Raw hex passthrough
    assert theme.resolve_color("#FF5500") == "#FF5500"

    # 4. Modifiers: tint & shade
    tinted = theme.resolve_color("accent1", modifiers={"tint": 50000})
    assert tinted != "#2563EB"
    assert tinted.startswith("#")

    shaded = theme.resolve_color("accent1", modifiers={"shade": 50000})
    assert shaded != "#2563EB"
    assert shaded.startswith("#")

    # 5. Modifiers: lumMod & lumOff
    modded = theme.resolve_color("accent1", modifiers={"lumMod": 80000, "lumOff": 20000})
    assert modded.startswith("#")


def test_font_engine_discovery_and_cascade():
    idx = FontEngine.get_index()
    assert len(idx) > 0, "FontEngine should index at least some system fonts"

    # Arial / Calibri resolution
    arial_path = FontEngine.resolve_font_path("Arial")
    assert arial_path is not None
    assert "arial" in arial_path.lower()

    # Bold variant
    bold_path = FontEngine.resolve_font_path("Arial", bold=True)
    assert bold_path is not None

    # Fallback for unknown font
    fallback_path = FontEngine.resolve_font_path("CompletelyNonExistentFontFamily123")
    assert fallback_path is not None, "FontEngine should cascade to a valid system font"

    # Pillow font object
    pil_font = FontEngine.get_pil_font("Segoe UI", size=24.0, bold=True)
    assert pil_font is not None


def test_style_resolver():
    theme = ThemeEngine(color_scheme={"accent1": "#3B82F6", "accent2": "#EC4899"})
    resolver = StyleResolver(theme)

    # Resolve FillStyle with theme_color
    fill = FillStyle(type="solid", color=None, theme_color="accent1")
    resolved_fill = resolver.resolve_fill(fill)
    assert resolved_fill.color == "#3B82F6"

    # Resolve BorderStyle
    border = BorderStyle(color=None, width=2.0, style="solid", theme_color="accent2")
    resolved_border = resolver.resolve_border(border)
    assert resolved_border.color == "#EC4899"

    # Resolve FontIR with theme slot
    font = FontIR(name="majorFont", size=20.0, color="accent1", theme_color="accent1")
    resolved_font = resolver.resolve_font(font)
    assert resolved_font.color == "#3B82F6"
    assert resolved_font.name == theme.get_major_font()


def test_relationship_and_asset_deduplication():
    # RelationshipGraph
    rg = RelationshipGraph()
    r1 = rg.add_image_relationship("../media/img1.png")
    r2 = rg.add_image_relationship("../media/img1.png")  # Duplicate
    assert r1 == r2, "Duplicate relationship should return same rId"

    r3 = rg.add_hyperlink("https://example.com")
    assert r3 != r1
    xml_str = rg.to_xml_string()
    assert "Relationship" in xml_str
    assert "TargetMode=\"External\"" in xml_str

    # AssetManager
    img_bytes = b"fake_png_binary_data"
    media = {
        "image1.png": img_bytes,
        "image2.png": img_bytes,  # exact duplicate
        "image3.png": b"different_data"
    }
    unique_media, remap = AssetManager.deduplicate_assets(media)
    assert len(unique_media) == 2
    assert remap["image1.png"] == "image1.png"
    assert remap["image2.png"] == "image1.png"


def test_fidelity_diff_engine():
    slide1 = SlideIR(id="s1", slide_num=1)
    slide1.add_element(ShapeElementIR(
        id="shape1", x=100.0, y=100.0, width=200.0, height=100.0,
        style=dict(fill=FillStyle(type="solid", color="#2563EB"))
    ))
    slide1.add_element(TextElementIR(
        id="text1", x=350.0, y=100.0, width=200.0, height=50.0,
        text_content=TextContentIR.from_plain_text("Test Header")
    ))

    # Reconstructed with tiny 1px coordinate drift
    slide2 = SlideIR(id="s1", slide_num=1)
    slide2.add_element(ShapeElementIR(
        id="shape1", x=101.0, y=100.5, width=200.0, height=100.0,
        style=dict(fill=FillStyle(type="solid", color="#2563EB"))
    ))
    slide2.add_element(TextElementIR(
        id="text1", x=350.0, y=100.0, width=200.0, height=50.0,
        text_content=TextContentIR.from_plain_text("Test Header")
    ))

    report = FidelityDiffEngine.compare_slides(slide1, slide2)
    assert report.is_lossless_geometry
    assert report.is_lossless_typography
    assert report.max_geom_error_px == 1.0
    assert report.font_match_rate == 1.0
    assert report.text_match_rate == 1.0
