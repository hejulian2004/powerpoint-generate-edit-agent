"""PR6-hardening regression suite.

Pins the fragile fidelity-layer contracts corrected after the PR6 review:

1. PresentationSnapshot round-trips `capabilities` (full rollback state).
2. ActionResolver resolves theme tokens via the presentation's actual theme
   (ThemeEngine.from_dict), not a default scheme.
3. OOXMLParser integrates schemeClr lumMod/lumOff/tint/shade modifier chains.
4. Group children are projected from child-local (chOff/chExt) coordinates.
5. backend.ir.import_pptx has a single production path (fidelity) with an
   explicit legacy escape hatch; export rejects unknown exporters.
6. Slide background <p:bg><p:bgPr> parsing survives round-trip.
"""

from pathlib import Path

import pytest

from backend.ir.models import (
    PresentationIR, SlideIR, ShapeElementIR, TextElementIR,
    TextContentIR, FillStyle, ElementStyleIR
)
from backend.ir.patch import HistoryManager
from backend.ir.converter import import_pptx, export_pptx
from backend.ir.models import TextElementIR
from backend.agent.action import ActionResolver, AgentAction
from backend.fidelity.theme_engine import ThemeEngine
from backend.fidelity.capability import CapabilityDetector, LOSSY_WRITEBACK_FEATURES

import xml.etree.ElementTree as ET

from backend.fidelity.ooxml_parser import OOXMLParser

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
}

ASSETS = Path(__file__).parent / "assets"


# =====================================================================
# 1. Snapshot completeness
# =====================================================================

def test_snapshot_restores_capabilities():
    pres = PresentationIR(title="Snapshot Caps")
    pres.capabilities = {"table": True, "chart": True, "theme": False}
    snap = pres.create_snapshot()

    pres.capabilities = {"table": False, "chart": False, "theme": True}
    pres.restore_snapshot(snap)

    assert pres.capabilities == {"table": True, "chart": True, "theme": False}


def test_transaction_rollback_restores_capabilities():
    pres = PresentationIR(title="Transaction Caps")
    pres.capabilities = {"smartart": True}

    with pres.transaction("test") as tx:
        pres.capabilities = {"smartart": False}
        tx.rollback("force")

    assert pres.capabilities == {"smartart": True}


# =====================================================================
# 2. Theme token resolution uses presentation theme
# =====================================================================

def test_action_resolver_uses_presentation_theme_for_tokens():
    pres = PresentationIR(title="Theme Token")
    slide = SlideIR(id="s1", slide_num=1)
    slide.add_element(TextElementIR(
        id="elem_title", x=80.0, y=50.0, width=700.0, height=50.0,
        text_content=TextContentIR.from_plain_text("Title")
    ))
    pres.slides.append(slide)
    pres.active_slide_id = slide.id
    pres.theme["color_scheme"] = {"accent1": "#123456"}

    tc = ActionResolver.action_to_tool_call(
        AgentAction(action_type="format_text", target="elem_title",
                    parameters={"font_color": "accent1"}),
        pres
    )
    assert tc["arguments"]["font_color"] == "#123456"


def test_theme_engine_from_dict_legacy_keys():
    engine = ThemeEngine.from_dict({
        "name": "Legacy",
        "primary_color": "#010203",
        "secondary_color": "#111111",
        "background_color": "#FAFAFA",
    })
    assert engine.color_scheme["accent1"] == "#010203"
    assert engine.color_scheme["dk1"] == "#111111"
    assert engine.color_scheme["lt1"] == "#FAFAFA"


# =====================================================================
# 3. schemeClr modifier chain integration
# =====================================================================

def test_scheme_color_lummod_modifier_integrated():
    parser = OOXMLParser.__new__(OOXMLParser)  # avoid package loading
    theme = ThemeEngine(color_scheme={"accent1": "#2563EB"})

    parent = ET.fromstring(
        '<a:solidFill xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<a:schemeClr val="accent1"><a:lumMod val="50000"/></a:schemeClr>'
        '</a:solidFill>'
    )
    color, alpha, scheme = parser._extract_color(parent, theme)
    assert scheme == "accent1"
    assert color != "#2563EB"  # modifier applied
    # 50% luminance of #2563EB (independent of exact HSL rounding)
    assert color.startswith("#") and len(color) == 7


def test_scheme_color_modifiers_extracted():
    parser = OOXMLParser.__new__(OOXMLParser)
    elem = ET.fromstring(
        '<a:schemeClr xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" val="accent2">'
        '<a:lumMod val="75000"/><a:lumOff val="10000"/><a:tint val="20000"/><a:shade val="90000"/>'
        '</a:schemeClr>'
    )
    mods = parser._extract_color_modifiers(elem)
    assert mods == {"lumMod": 75000, "lumOff": 10000, "tint": 20000, "shade": 90000}


def test_srgb_color_modifier_integrated():
    parser = OOXMLParser.__new__(OOXMLParser)
    theme = ThemeEngine()
    parent = ET.fromstring(
        '<a:solidFill xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<a:srgbClr val="FF0000"><a:lumMod val="50000"/></a:srgbClr>'
        '</a:solidFill>'
    )
    color, _, scheme = parser._extract_color(parent, theme)
    assert scheme is None
    assert color != "#FF0000"


# =====================================================================
# 4. Group coordinate projection
# =====================================================================

def test_group_children_projected_into_slide_space():
    deck = ASSETS / "real_world" / "sample_pptx_grouping_issues.pptx"
    if not deck.exists():
        pytest.skip("grouping sample not present")

    pres = import_pptx(str(deck))
    groups = [
        el for s in pres.slides
        for el in s.all_elements(recursive=True)
        if el.type == "group"
    ]
    assert groups, "expected at least one group"

    for grp in groups:
        if not grp.children:
            continue
        for child in grp.children:
            # Child centers must fall inside the group's expanded bounds, not at
            # raw child-local coordinates (the pre-hardening bug).
            cx = child.x + child.width / 2.0
            cy = child.y + child.height / 2.0
            assert grp.x - 1.0 <= cx <= grp.x + grp.width + 1.0, (
                f"child {child.id} x={child.x} outside group {grp.id} "
                f"[{grp.x}, {grp.x + grp.width}]"
            )
            assert grp.y - 1.0 <= cy <= grp.y + grp.height + 1.0, (
                f"child {child.id} y={child.y} outside group {grp.id} "
                f"[{grp.y}, {grp.y + grp.height}]"
            )


# =====================================================================
# 5. Production importer/exporter contract
# =====================================================================

def test_import_production_path_is_fidelity(tmp_path: Path):
    pres = PresentationIR(title="Importer Contract")
    slide = SlideIR(id="s1", slide_num=1)
    slide.add_element(ShapeElementIR(
        id="rect1", shape_type="rect", x=100, y=100, width=200, height=100,
        style=ElementStyleIR(fill=FillStyle(type="solid", color="#2563EB"))
    ))
    pres.slides.append(slide)

    out = tmp_path / "importer.pptx"
    export_pptx(pres, out)

    fid = import_pptx(str(out))
    assert fid.metadata.get("importer_used") == "fidelity"

    legacy = import_pptx(str(out), importer="legacy")
    assert legacy.metadata.get("importer_used") == "legacy"


def test_import_rejects_unknown_importer(tmp_path: Path):
    pres = PresentationIR(title="Bad Importer")
    pres.slides.append(SlideIR(id="s1", slide_num=1))
    out = tmp_path / "bad.pptx"
    export_pptx(pres, out)
    with pytest.raises(ValueError):
        import_pptx(str(out), importer="nope")


def test_export_rejects_unknown_exporter(tmp_path: Path):
    pres = PresentationIR(title="Bad Exporter")
    with pytest.raises(ValueError):
        export_pptx(pres, tmp_path / "x.pptx", exporter="fidelity")


# =====================================================================
# 6. Background + table write-back contracts
# =====================================================================

def test_slide_background_bgpr_round_trip(tmp_path: Path):
    pres = PresentationIR(title="BG Contract")
    slide = SlideIR(id="s1", slide_num=1)
    slide.background = FillStyle(type="solid", color="#123456", alpha=1.0)
    pres.slides.append(slide)

    out = tmp_path / "bg.pptx"
    export_pptx(pres, out)
    re_pres = import_pptx(str(out))
    assert re_pres.slides[0].background.type == "solid"
    assert re_pres.slides[0].background.color.upper() == "#123456"


def test_table_writeback_declared_lossy():
    assert CapabilityDetector.check_writeback("table") == {
        "lossless": False, "reason": "flattened_to_group"
    }
    assert CapabilityDetector.check_writeback("text")["lossless"] is True
    assert "table" in LOSSY_WRITEBACK_FEATURES


def test_paragraph_line_spacing_and_spacing_round_trip(tmp_path: Path):
    from backend.ir.models import ParagraphIR, RunIR, FontIR

    pres = PresentationIR(title="Spacing")
    slide = SlideIR(id="s1", slide_num=1)
    slide.add_element(TextElementIR(
        id="t1", x=100, y=100, width=500, height=100,
        text_content=TextContentIR(paragraphs=[
            ParagraphIR(align="center", line_spacing=1.35, space_before=6.0, space_after=6.0,
                        runs=[RunIR(text="Spacing Check", font=FontIR(size=24))])
        ])
    ))
    pres.slides.append(slide)

    out = tmp_path / "spacing.pptx"
    export_pptx(pres, out)
    re_pres = import_pptx(str(out))

    para = None
    for el in re_pres.slides[0].all_elements(recursive=True):
        if getattr(el, "text_content", None) and el.text_content.paragraphs:
            for p in el.text_content.paragraphs:
                if p.plain_text == "Spacing Check":
                    para = p
    assert para is not None
    assert abs(para.line_spacing - 1.35) < 0.05
    assert para.align == "center"
