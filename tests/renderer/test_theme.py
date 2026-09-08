"""Unit tests for Academic Theme System (PR11)."""

from backend.layout.schema import BlockRole, ElementType
from backend.renderer.theme import AcademicTheme, FontToken, hex_to_rgb


def test_theme_defaults():
    theme = AcademicTheme()
    assert theme.name == "academic_modern"
    assert theme.fonts.title.size == 28.0
    assert theme.fonts.title.bold is True
    assert theme.fonts.body.size == 16.0
    assert theme.fonts.caption.italic is True
    assert theme.colors.primary == "#0F172A"
    assert theme.colors.accent == "#2563EB"


def test_hex_to_rgb():
    assert hex_to_rgb("#FFFFFF") == (255, 255, 255)
    assert hex_to_rgb("#000000") == (0, 0, 0)
    assert hex_to_rgb("2563EB") == (37, 99, 235)
    assert hex_to_rgb("#FFF") == (255, 255, 255)
    assert hex_to_rgb(None) == (15, 23, 42)
    assert hex_to_rgb("invalid_hex") == (15, 23, 42)


def test_resolve_font_for_role():
    theme = AcademicTheme()

    # Heading
    t_font = theme.resolve_font_for_role(role=BlockRole.HEADING)
    assert t_font.size == 28.0
    assert t_font.bold is True

    # Subheading
    s_font = theme.resolve_font_for_role(role=BlockRole.SUBHEADING)
    assert s_font.size == 20.0

    # Caption
    c_font = theme.resolve_font_for_role(role=BlockRole.CAPTION)
    assert c_font.size == 12.0
    assert c_font.italic is True

    # Badge Element
    b_font = theme.resolve_font_for_role(element_type=ElementType.BADGE)
    assert b_font.size == 11.0
    assert b_font.bold is True

    # Table Element
    tbl_font = theme.resolve_font_for_role(element_type=ElementType.TABLE)
    assert tbl_font.size == 12.0


def test_custom_theme_overrides():
    theme = AcademicTheme(
        name="custom_academic",
        fonts={"title": FontToken(size=32.0, bold=True, font_family="Arial")},
        colors={"primary": "#1E293B", "accent": "#10B981"},
    )
    assert theme.fonts.title.size == 32.0
    assert theme.fonts.title.font_family == "Arial"
    assert theme.colors.accent == "#10B981"
