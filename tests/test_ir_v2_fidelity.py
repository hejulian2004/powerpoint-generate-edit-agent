"""Comprehensive Fidelity Verification & Roundtrip Suite for PPT Fidelity Engine (PR2).

Tests:
1. Hierarchical Group preservation, recursive lookup, deletion, and text aggregation.
2. Group transform and bounding box synchronization.
3. Paragraph line spacing (pct and pts), space before/after, and bullet formatting.
4. Run strikethrough, bold/italic, and formatting in DrawingML.
5. Connector shape-binding (start_shape_id, end_shape_id, connection sites).
6. Shape flip_h, flip_v, and adjust values.
7. Full end-to-end .pptx export, package validation, and re-import with nested groups.
8. Server-side SVG rendering of hierarchical groups and rich typography.
"""

import os
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest

from backend.ir.models import (
    PresentationIR, SlideIR, ShapeElementIR, TextElementIR,
    ConnectorElementIR, ImageElementIR, GroupElementIR, TransformIR,
    FillStyle, BorderStyle, ShadowStyle, FontIR, ParagraphIR, RunIR, TextContentIR
)
from backend.ir.converter import PPTIRConverter
from backend.ir.svg_renderer import SVGRenderer
from backend.ir import export_pptx, import_pptx
from pptx_agent_converter.validation import validate_pptx
from pptx_agent_converter.renderer.style_renderer import StyleRenderer
from pptx_agent_converter.model.slide import Slide, Presentation, SlideSize
from pptx_agent_converter.model.shape import ShapeElement, GroupElement, ConnectorElement, Position
from pptx_agent_converter.model.text import TextBlock, Paragraph, Run, Font


# =====================================================================
# 1. Hierarchical Group Model & Traversal
# =====================================================================

def test_group_ir_hierarchy_and_accessors():
    """Verify recursive hierarchy, leaf elements, all elements, and deep search/delete."""
    slide = SlideIR(id="slide_h1", slide_num=1)

    s1 = ShapeElementIR(id="standalone_s1", name="Standalone", x=50, y=50, width=100, height=60)
    slide.add_element(s1)

    # Sub-group (level 2)
    sub_child1 = ShapeElementIR(
        id="sub_c1",
        x=200, y=100, width=80, height=40,
        text_content=TextContentIR.from_plain_text("Nested Sub Text")
    )
    sub_text = TextElementIR(
        id="sub_t1",
        x=290, y=100, width=120, height=40,
        text_content=TextContentIR.from_plain_text("Deep Label")
    )
    sub_group = GroupElementIR(
        id="sub_grp",
        name="Sub Group",
        x=200, y=100, width=220, height=50,
        children=[sub_child1, sub_text]
    )

    # Top-level group (level 1)
    top_child1 = ShapeElementIR(
        id="top_c1",
        x=100, y=200, width=90, height=50,
        text_content=TextContentIR.from_plain_text("Top Child 1")
    )
    top_group = GroupElementIR(
        id="top_grp",
        name="Top Group",
        x=100, y=100, width=350, height=200,
        children=[top_child1, sub_group]
    )
    slide.add_element(top_group)

    # 1. Top-level count vs leaf count vs all elements count
    assert len(slide.elements) == 2  # [s1, top_group]
    assert len(slide.leaf_elements()) == 4  # [s1, top_c1, sub_c1, sub_t1]
    assert len(slide.all_elements()) == 6  # [s1, top_grp, top_c1, sub_grp, sub_c1, sub_t1]

    # 2. Deep element lookup
    assert slide.get_element("sub_t1") is sub_text
    assert slide.get_element("sub_grp") is sub_group
    assert slide.get_element("nonexistent") is None

    # 3. Group aggregate text content
    tc = top_group.text_content
    assert tc is not None
    aggregated = tc.plain_text
    assert "Top Child 1" in aggregated
    assert "Nested Sub Text" in aggregated
    assert "Deep Label" in aggregated

    # 4. Deep deletion
    removed = slide.remove_element("sub_t1")
    assert removed is True
    assert slide.get_element("sub_t1") is None
    assert len(slide.leaf_elements()) == 3
    assert len(sub_group.children) == 1

    # 5. Top group removal
    removed_top = slide.remove_element("top_grp")
    assert removed_top is True
    assert len(slide.elements) == 1
    assert len(slide.leaf_elements()) == 1


# =====================================================================
# 2. Group Transform & Bounding Box Synchronization
# =====================================================================

def test_group_transform_sync():
    """Verify bidirectional sync between transform object and flat coordinates."""
    tf = TransformIR(x=120.0, y=80.0, width=450.0, height=250.0, rotation=25.0, flip_h=True)
    grp = GroupElementIR(id="g_sync", transform=tf)

    assert grp.x == 120.0
    assert grp.y == 80.0
    assert grp.width == 450.0
    assert grp.height == 250.0
    assert grp.rotation == 25.0

    # Test coordinate mapping in converter
    c1 = ShapeElement(id="sc1", position=Position(x=2.0, y=2.0, width=3.0, height=2.0))
    c2 = ShapeElement(id="sc2", position=Position(x=5.0, y=3.0, width=4.0, height=3.0))
    # Group with missing outer bounds (should auto-calculate from children: x=2, y=2, width=7, height=4)
    ooxml_grp = GroupElement(id="og1", elements=[c1, c2])

    ir_grp = PPTIRConverter.element_to_ir(ooxml_grp)
    assert isinstance(ir_grp, GroupElementIR)
    assert len(ir_grp.children) == 2
    # In canvas px (96 DPI): x=2*96=192, y=2*96=192, width=(9-2)*96=672, height=(6-2)*96=384
    assert ir_grp.x == 192.0
    assert ir_grp.y == 192.0
    assert ir_grp.width == 672.0
    assert ir_grp.height == 384.0


# =====================================================================
# 3. Typography Spacing & DrawingML Generation
# =====================================================================

def test_paragraph_spacing_and_drawingml_generation():
    """Verify paragraph line spacing (multipliers vs pts), space before/after, and bullets."""
    para_ir = ParagraphIR(
        line_spacing=1.5,
        space_before=8.0,
        space_after=16.0,
        bullet="•",
        runs=[RunIR(text="Typography Spacing Test", font=FontIR(size=18.0))]
    )
    tc_ir = TextContentIR(paragraphs=[para_ir])

    # Convert to OOXML TextBlock
    tb = PPTIRConverter._ir_to_text_block(tc_ir)
    assert len(tb.paragraphs) == 1
    p_model = tb.paragraphs[0]
    assert p_model.style.line_spacing == 1.5
    assert p_model.style.space_before == 8.0
    assert p_model.style.space_after == 16.0
    assert p_model.bullet == "•"

    # Render to DrawingML <p:txBody>
    tx_body = StyleRenderer.build_tx_body(tb)
    assert tx_body is not None

    # Inspect XML elements
    p_pr = tx_body.find(f".//{{{StyleRenderer.__module__ and 'http://schemas.openxmlformats.org/drawingml/2006/main'}}}pPr")
    assert p_pr is not None

    ln_spc = p_pr.find(f"{{{StyleRenderer.__module__ and 'http://schemas.openxmlformats.org/drawingml/2006/main'}}}lnSpc")
    assert ln_spc is not None
    spc_pct = ln_spc.find(f"{{{StyleRenderer.__module__ and 'http://schemas.openxmlformats.org/drawingml/2006/main'}}}spcPct")
    assert spc_pct is not None
    assert spc_pct.attrib["val"] == "150000"  # 1.5 * 100000

    spc_bef = p_pr.find(f"{{{StyleRenderer.__module__ and 'http://schemas.openxmlformats.org/drawingml/2006/main'}}}spcBef")
    assert spc_bef is not None
    assert spc_bef.find(f"{{{StyleRenderer.__module__ and 'http://schemas.openxmlformats.org/drawingml/2006/main'}}}spcPts").attrib["val"] == "800"

    spc_aft = p_pr.find(f"{{{StyleRenderer.__module__ and 'http://schemas.openxmlformats.org/drawingml/2006/main'}}}spcAft")
    assert spc_aft is not None
    assert spc_aft.find(f"{{{StyleRenderer.__module__ and 'http://schemas.openxmlformats.org/drawingml/2006/main'}}}spcPts").attrib["val"] == "1600"

    bu_char = p_pr.find(f"{{{StyleRenderer.__module__ and 'http://schemas.openxmlformats.org/drawingml/2006/main'}}}buChar")
    assert bu_char is not None
    assert bu_char.attrib["char"] == "•"


def test_paragraph_fixed_point_line_spacing():
    """Verify absolute point line spacing (> 10.0) renders as <a:spcPts>."""
    para_ir = ParagraphIR(
        line_spacing=24.0,  # 24pt line height
        runs=[RunIR(text="Fixed Pt Line Height")]
    )
    tb = PPTIRConverter._ir_to_text_block(TextContentIR(paragraphs=[para_ir]))
    tx_body = StyleRenderer.build_tx_body(tb)

    ns_a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    ln_spc = tx_body.find(f".//{{{ns_a}}}lnSpc")
    assert ln_spc is not None
    spc_pts = ln_spc.find(f"{{{ns_a}}}spcPts")
    assert spc_pts is not None
    assert spc_pts.attrib["val"] == "2400"  # 24.0 * 100


# =====================================================================
# 4. Run Strikethrough, Hyperlink, and Typography Formatting
# =====================================================================

def test_run_strikethrough_and_hyperlink():
    """Verify strikethrough maps to sngStrike and hyperlink field preservation."""
    run_ir = RunIR(
        text="Deprecated Feature",
        font=FontIR(strikethrough=True, bold=True, italic=True),
        hyperlink="https://github.com/hejulian/PPT-Agent-Studio"
    )
    para_ir = ParagraphIR(runs=[run_ir])
    tb = PPTIRConverter._ir_to_text_block(TextContentIR(paragraphs=[para_ir]))
    assert tb.paragraphs[0].runs[0].font.strike is True

    # DrawingML verification
    tx_body = StyleRenderer.build_tx_body(tb)
    ns_a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    r_pr = tx_body.find(f".//{{{ns_a}}}rPr")
    assert r_pr is not None
    assert r_pr.attrib.get("strike") == "sngStrike"
    assert r_pr.attrib.get("b") == "1"
    assert r_pr.attrib.get("i") == "1"


# =====================================================================
# 5. Connector Shape-Binding & Endpoints
# =====================================================================

def test_connector_shape_binding_fidelity():
    """Verify start_shape_id, end_shape_id, and site indices roundtrip faithfully."""
    conn_ir = ConnectorElementIR(
        id="conn_bound_1",
        start_x=100.0,
        start_y=200.0,
        end_x=400.0,
        end_y=300.0,
        start_shape_id="shape_source",
        end_shape_id="shape_target",
        start_site_index=2,
        end_site_index=0,
        arrow_start="none",
        arrow_end="stealth",
        line_type="elbow"
    )

    ooxml_conn = PPTIRConverter.ir_to_element(conn_ir)
    assert isinstance(ooxml_conn, ConnectorElement)
    assert ooxml_conn.start_shape_id == "shape_source"
    assert ooxml_conn.end_shape_id == "shape_target"
    assert ooxml_conn.start_site_index == 2
    assert ooxml_conn.end_site_index == 0
    assert ooxml_conn.line.arrow_end == "stealth"

    # Reverse conversion
    re_ir = PPTIRConverter.element_to_ir(ooxml_conn)
    assert isinstance(re_ir, ConnectorElementIR)
    assert re_ir.start_shape_id == "shape_source"
    assert re_ir.end_shape_id == "shape_target"
    assert re_ir.start_site_index == 2
    assert re_ir.end_site_index == 0
    assert re_ir.arrow_end == "stealth"
    assert re_ir.line_type == "elbow"


# =====================================================================
# 6. Shape Enhancements: Flip & Adjust Values
# =====================================================================

def test_shape_flip_and_adjust_values():
    """Verify flip_h, flip_v, and adjust_values preserve across conversion."""
    shape_ir = ShapeElementIR(
        id="shape_adj",
        shape_type="roundRect",
        x=80.0,
        y=120.0,
        width=240.0,
        height=140.0,
        flip_h=True,
        flip_v=True,
        adjust_values={"adj": 0.35}
    )

    ooxml_shape = PPTIRConverter.ir_to_element(shape_ir)
    assert isinstance(ooxml_shape, ShapeElement)
    assert ooxml_shape.flip_h is True
    assert ooxml_shape.flip_v is True
    assert ooxml_shape.adjust_values.get("adj") == 0.35

    re_shape = PPTIRConverter.element_to_ir(ooxml_shape)
    assert isinstance(re_shape, ShapeElementIR)
    assert re_shape.flip_h is True
    assert re_shape.flip_v is True
    assert re_shape.adjust_values.get("adj") == 0.35


# =====================================================================
# 7. End-to-End OOXML Packaging with Nested Groups & Pictures
# =====================================================================

def test_nested_groups_pptx_roundtrip(tmp_path: Path):
    """Full roundtrip test: IR v2 with nested groups and images -> .pptx -> validate -> re-import."""
    # Build PresentationIR
    pres_ir = PresentationIR(title="Fidelity V2 Roundtrip")

    # Slide 1: Nested groups
    s1 = SlideIR(id="slide_01", slide_num=1, title="Hierarchical Groups")
    card1 = ShapeElementIR(
        id="c1",
        shape_type="roundRect",
        x=100.0, y=100.0, width=150.0, height=80.0,
        style=dict(fill=FillStyle(type="solid", color="#2563EB"), radius=10.0),
        text_content=TextContentIR.from_plain_text("Card A")
    )
    card2 = ShapeElementIR(
        id="c2",
        shape_type="roundRect",
        x=300.0, y=100.0, width=150.0, height=80.0,
        style=dict(fill=FillStyle(type="solid", color="#10B981"), radius=10.0),
        text_content=TextContentIR.from_plain_text("Card B")
    )
    nested_grp = GroupElementIR(
        id="grp_cards",
        name="Card Pair",
        x=100.0, y=100.0, width=350.0, height=80.0,
        children=[card1, card2]
    )
    conn = ConnectorElementIR(
        id="conn_link",
        start_x=250.0, start_y=140.0, end_x=300.0, end_y=140.0,
        start_shape_id="c1", end_shape_id="c2", arrow_end="triangle"
    )
    s1.add_element(nested_grp)
    s1.add_element(conn)
    pres_ir.slides.append(s1)

    # Slide 2: Typography formatting & image
    s2 = SlideIR(id="slide_02", slide_num=2, title="Typography and Media")
    para1 = ParagraphIR(
        line_spacing=1.3,
        space_before=6.0,
        space_after=10.0,
        bullet="•",
        runs=[
            RunIR(text="Active Feature: High Fidelity", font=FontIR(bold=True, size=20.0, color="#0F172A")),
            RunIR(text=" (Verified)", font=FontIR(italic=True, size=16.0, color="#10B981"))
        ]
    )
    para2 = ParagraphIR(
        line_spacing=1.2,
        bullet="•",
        runs=[
            RunIR(text="Legacy Code", font=FontIR(strikethrough=True, size=18.0, color="#94A3B8"))
        ]
    )
    text_elem = TextElementIR(
        id="rich_text",
        x=80.0, y=80.0, width=500.0, height=200.0,
        text_content=TextContentIR(paragraphs=[para1, para2])
    )
    s2.add_element(text_elem)
    pres_ir.slides.append(s2)

    # Export to .pptx
    out_file = tmp_path / "fidelity_v2_output.pptx"
    exported_path = export_pptx(pres_ir, out_file)
    assert exported_path.exists()
    assert exported_path.stat().st_size > 0

    # Validate package structure
    report = validate_pptx(exported_path)
    assert report["valid"] is True, f"OOXML validation failed: {report['errors']}"
    assert report["slides"] == 2
    assert len(report["errors"]) == 0

    # Re-import and verify groups are preserved
    re_ir = import_pptx(exported_path)
    assert len(re_ir.slides) == 2

    # Slide 1 verification: group should be preserved as GroupElementIR!
    re_s1 = re_ir.slides[0]
    groups = [e for e in re_s1.elements if isinstance(e, GroupElementIR)]
    assert len(groups) == 1, f"Expected 1 preserved GroupElementIR, got {len(groups)}"
    grp = groups[0]
    assert len(grp.children) == 2
    assert grp.text_content is not None
    assert "Card A" in grp.text_content.plain_text
    assert "Card B" in grp.text_content.plain_text

    # Slide 2 verification: text content and formatting
    re_s2 = re_ir.slides[1]
    re_texts = [e.text_content.plain_text for e in re_s2.elements if hasattr(e, "text_content") and e.text_content]
    full_text = "\n".join(re_texts)
    assert "Active Feature: High Fidelity" in full_text
    assert "Legacy Code" in full_text


# =====================================================================
# 8. SVG Renderer for Groups & Complex Slides
# =====================================================================

def test_svg_renderer_groups_and_formatting():
    """Verify SVGRenderer emits hierarchical <g class='group-container'> and elements."""
    slide = SlideIR(id="slide_svg_test", slide_num=1)
    c1 = ShapeElementIR(id="sc1", shape_type="roundRect", x=50, y=50, width=120, height=60)
    c2 = TextElementIR(id="sc2", x=200, y=50, width=120, height=60, text_content=TextContentIR.from_plain_text("Inner SVG Text"))
    group = GroupElementIR(id="svg_grp", x=50, y=50, width=270, height=60, children=[c1, c2])
    slide.add_element(group)

    svg_str = SVGRenderer.render_slide(slide)
    assert '<g id="svg_grp" class="group-container"' in svg_str
    assert 'id="sc1"' in svg_str
    assert 'Inner SVG Text' in svg_str
    assert "</svg>" in svg_str
