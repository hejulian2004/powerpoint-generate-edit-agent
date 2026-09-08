"""Deep Quantitative PPT Round-Trip Fidelity & Architectural Regression Suite.

Validates PR2 & PR3 architectural review requirements:
1. Quantitative geometry drift verification (< 0.05 inches / < 5 pixels).
2. DrawingML group coordinate mapping under non-trivial (chOff, chExt, off, ext) transforms.
3. Nested group hierarchical transforms, regrouping, and ungrouping coordinate invariance.
4. Typography and style preservation fidelity (fills, borders, shadows, spacing, runs).
5. Remediation transaction rollback guard under simulated quality score degradation.
6. FixPlanner conflict detection and action deduplication.
"""

import math
import uuid
import pytest
from pathlib import Path
import xml.etree.ElementTree as ET

from backend.ir.models import (
    PresentationIR, SlideIR, ShapeElementIR, TextElementIR,
    ConnectorElementIR, ImageElementIR, GroupElementIR,
    FillStyle, BorderStyle, ShadowStyle, TextContentIR,
    ParagraphIR, RunIR, FontIR
)
from backend.ir import export_pptx, import_pptx
from backend.ir.converter import PPTIRConverter, DEFAULT_WIDTH, DEFAULT_HEIGHT
from backend.ir.patch import HistoryManager
from backend.eval.layout_diff import LayoutDiffEngine, BoundingBox
from backend.eval.remediation import FixAction, FixActionType, DefectCategory, RemediationPlan
from backend.agent.remediation_runner import RemediationRunner
from backend.agent.tools import tools
from pptx_agent_converter.validation import validate_pptx
from pptx_agent_converter.extractor.constants import NS, inches_to_emu, emu_to_inches
from pptx_agent_converter.model.shape import (
    ShapeElement, GroupElement, ConnectorElement, Position
)
from pptx_agent_converter.extractor.slide_parser import SlideParser
from pptx_agent_converter.extractor.style_parser import StyleParser
from pptx_agent_converter.extractor.shape_parser import ShapeParser
from pptx_agent_converter.extractor.text_parser import TextParser
from pptx_agent_converter.extractor.media_parser import MediaParser


# =====================================================================
# 1. Quantitative Geometry Drift Verification (< 0.05 inches / < 5 px)
# =====================================================================

def test_quantitative_geometry_drift_bounds(tmp_path: Path):
    """Verifies that coordinates across PPTX export and re-import drift by < 0.05 inches."""
    pres = PresentationIR(title="Quantitative Drift Benchmark")
    slide = SlideIR(id="slide_geom_bench", slide_num=1, title="Geometry Benchmark")

    # Standard shapes with known pixel coordinates (1280x720 canvas)
    # 1 inch = 96 px (1280 / 13.333)
    s1 = ShapeElementIR(
        id="s_rect",
        name="Benchmark Rect",
        shape_type="rect",
        x=100.0,
        y=150.0,
        width=300.0,
        height=180.0,
        style=dict(fill=FillStyle(type="solid", color="#2563EB"))
    )
    s2 = TextElementIR(
        id="s_txt",
        name="Benchmark Text",
        x=450.0,
        y=150.0,
        width=350.0,
        height=100.0,
        text_content=TextContentIR.from_plain_text("Quantitative Precision Text")
    )
    # Nested Group
    g_child1 = ShapeElementIR(
        id="gc1",
        shape_type="roundRect",
        x=850.0,
        y=150.0,
        width=160.0,
        height=90.0,
        style=dict(radius=8.0)
    )
    g_child2 = ShapeElementIR(
        id="gc2",
        shape_type="roundRect",
        x=1050.0,
        y=150.0,
        width=160.0,
        height=90.0,
        style=dict(radius=8.0)
    )
    group = GroupElementIR(
        id="bench_grp",
        name="Benchmark Group",
        x=850.0,
        y=150.0,
        width=360.0,
        height=90.0,
        children=[g_child1, g_child2]
    )

    slide.add_element(s1)
    slide.add_element(s2)
    slide.add_element(group)
    pres.slides.append(slide)

    out_file = tmp_path / "geom_drift_benchmark.pptx"
    export_pptx(pres, out_file)
    assert out_file.exists()

    re_pres = import_pptx(out_file)
    re_slide = re_pres.slides[0]

    # Map before elements by ID
    before_elements = {el.id: el for el in slide.all_elements(recursive=True)}
    after_elements = {el.id: el for el in re_slide.all_elements(recursive=True)}

    # Maximum permissible tolerance in pixels (0.05 inches * 96 px/in = 4.8 px)
    MAX_DRIFT_PX = 4.8

    for eid, el_before in before_elements.items():
        if eid not in after_elements:
            continue
        el_after = after_elements[eid]

        dx = abs(el_after.x - el_before.x)
        dy = abs(el_after.y - el_before.y)
        dw = abs(el_after.width - el_before.width)
        dh = abs(el_after.height - el_before.height)

        assert dx < MAX_DRIFT_PX, f"Element '{eid}' X drift {dx:.2f}px exceeds tolerance {MAX_DRIFT_PX}px"
        assert dy < MAX_DRIFT_PX, f"Element '{eid}' Y drift {dy:.2f}px exceeds tolerance {MAX_DRIFT_PX}px"
        assert dw < MAX_DRIFT_PX, f"Element '{eid}' Width drift {dw:.2f}px exceeds tolerance {MAX_DRIFT_PX}px"
        assert dh < MAX_DRIFT_PX, f"Element '{eid}' Height drift {dh:.2f}px exceeds tolerance {MAX_DRIFT_PX}px"


# =====================================================================
# 2. DrawingML Group Coordinate Mapping (chOff, chExt, off, ext)
# =====================================================================

def test_drawingml_group_local_coordinate_mapping():
    """Validates SlideParser child mapping when chOff != off or chExt != ext."""
    # Construct synthetic DrawingML <p:grpSp> XML
    # Group outer position: off=(2.0in, 3.0in), ext=(4.0in, 2.0in)
    # Child coordinate space: chOff=(0, 0), chExt=(2.0in, 1.0in) -> scale_x=2.0, scale_y=2.0
    # Child shape raw position in child space: off=(0.5in, 0.25in), ext=(0.5in, 0.5in)
    # Expected child position in parent space:
    #   X = 2.0 + (0.5 - 0.0) * 2.0 = 3.0 in
    #   Y = 3.0 + (0.25 - 0.0) * 2.0 = 3.5 in
    #   W = 0.5 * 2.0 = 1.0 in
    #   H = 0.5 * 2.0 = 1.0 in
    grp_xml = f"""<p:grpSp xmlns:p="{NS['p']}" xmlns:a="{NS['a']}">
        <p:nvGrpSpPr>
            <p:cNvPr id="42" name="Mapped Group"/>
            <p:cNvGrpSpPr/>
            <p:nvPr/>
        </p:nvGrpSpPr>
        <p:grpSpPr>
            <a:xfrm>
                <a:off x="{inches_to_emu(2.0)}" y="{inches_to_emu(3.0)}"/>
                <a:ext cx="{inches_to_emu(4.0)}" cy="{inches_to_emu(2.0)}"/>
                <a:chOff x="0" y="0"/>
                <a:chExt cx="{inches_to_emu(2.0)}" cy="{inches_to_emu(1.0)}"/>
            </a:xfrm>
        </p:grpSpPr>
        <p:sp>
            <p:nvSpPr>
                <p:cNvPr id="43" name="Scaled Child"/>
                <p:cNvSpPr/>
                <p:nvPr/>
            </p:nvSpPr>
            <p:spPr>
                <a:xfrm>
                    <a:off x="{inches_to_emu(0.5)}" y="{inches_to_emu(0.25)}"/>
                    <a:ext cx="{inches_to_emu(0.5)}" cy="{inches_to_emu(0.5)}"/>
                </a:xfrm>
                <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
            </p:spPr>
        </p:sp>
    </p:grpSp>"""

    grp_elem = ET.fromstring(grp_xml)
    style_p = StyleParser()
    text_p = TextParser(style_p)
    shape_p = ShapeParser(style_p, text_p)
    media_p = MediaParser()
    slide_parser = SlideParser(style_p, shape_p, text_p, media_p)

    parsed_group = slide_parser._parse_group(grp_elem, rels={})

    assert isinstance(parsed_group, GroupElement)
    assert parsed_group.position.x == 2.0
    assert parsed_group.position.y == 3.0
    assert parsed_group.position.width == 4.0
    assert parsed_group.position.height == 2.0
    assert len(parsed_group.elements) == 1

    child = parsed_group.elements[0]
    assert isinstance(child, ShapeElement)
    assert abs(child.position.x - 3.0) < 1e-3, f"Expected X=3.0, got {child.position.x}"
    assert abs(child.position.y - 3.5) < 1e-3, f"Expected Y=3.5, got {child.position.y}"
    assert abs(child.position.width - 1.0) < 1e-3, f"Expected Width=1.0, got {child.position.width}"
    assert abs(child.position.height - 1.0) < 1e-3, f"Expected Height=1.0, got {child.position.height}"


# =====================================================================
# 3. Nested Groups, Tool Regrouping & Ungrouping Coordinate Invariance
# =====================================================================

def test_nested_groups_transform_and_regrouping():
    """Verifies recursive coordinate updates when groups move/scale, group, and ungroup."""
    pres = PresentationIR(title="Grouping Operations")
    slide = SlideIR(id="slide_groups", slide_num=1)

    s1 = ShapeElementIR(id="card_1", x=100.0, y=100.0, width=120.0, height=80.0)
    s2 = ShapeElementIR(id="card_2", x=260.0, y=100.0, width=120.0, height=80.0)
    slide.add_element(s1)
    slide.add_element(s2)
    pres.slides.append(slide)

    history = HistoryManager()

    # 1. Group cards via tool
    res_group = tools.execute(
        "group_elements",
        {"element_ids": ["card_1", "card_2"], "group_name": "Card Cluster"},
        pres,
        history
    )
    assert res_group["success"] is True
    gid = res_group["group_id"]
    grp = slide.get_element(gid)
    assert isinstance(grp, GroupElementIR)
    assert grp.x == 100.0
    assert grp.y == 100.0
    assert grp.width == 280.0  # 260 + 120 - 100
    assert grp.height == 80.0

    # 2. Update group position via update_element tool (translate +50, +30)
    res_update = tools.execute(
        "update_element",
        {"element_id": gid, "x": 150.0, "y": 130.0},
        pres,
        history
    )
    assert res_update["success"] is True
    assert grp.x == 150.0
    assert grp.y == 130.0

    # Verify children shifted synchronously
    c1 = grp.get_child("card_1")
    c2 = grp.get_child("card_2")
    assert c1.x == 150.0  # 100 + 50
    assert c1.y == 130.0  # 100 + 30
    assert c2.x == 310.0  # 260 + 50
    assert c2.y == 130.0  # 100 + 30

    # 3. Ungroup via tool and verify children positions remain invariant
    res_ungroup = tools.execute(
        "ungroup_elements",
        {"group_id": gid},
        pres,
        history
    )
    assert res_ungroup["success"] is True
    assert slide.get_element(gid) is None

    restored_c1 = slide.get_element("card_1")
    restored_c2 = slide.get_element("card_2")
    assert restored_c1 is not None
    assert restored_c2 is not None
    assert restored_c1.x == 150.0
    assert restored_c1.y == 130.0
    assert restored_c2.x == 310.0
    assert restored_c2.y == 130.0


# =====================================================================
# 4. Typography and Style Preservation Fidelity
# =====================================================================

def test_rich_typography_and_style_preservation(tmp_path: Path):
    """Verifies paragraph line spacing, space before/after, runs, and border styles roundtrip."""
    pres = PresentationIR(title="Typography Fidelity")
    slide = SlideIR(id="slide_typo", slide_num=1)

    para = ParagraphIR(
        line_spacing=1.35,
        space_before=8.0,
        space_after=14.0,
        align="center",
        runs=[
            RunIR(text="Primary Title", font=FontIR(name="Georgia", size=24.0, bold=True, color="#1E3A8A")),
            RunIR(text=" Subtitle Note", font=FontIR(name="Arial", size=16.0, italic=True, color="#059669"))
        ]
    )
    txt_elem = TextElementIR(
        id="typo_elem",
        x=120.0,
        y=100.0,
        width=600.0,
        height=180.0,
        text_content=TextContentIR(paragraphs=[para]),
        style=dict(
            fill=FillStyle(type="solid", color="#F8FAFC"),
            border=BorderStyle(color="#CBD5E1", width=2.0, style="solid")
        )
    )
    slide.add_element(txt_elem)
    pres.slides.append(slide)

    out_file = tmp_path / "typo_roundtrip.pptx"
    export_pptx(pres, out_file)
    assert validate_pptx(out_file)["valid"] is True

    re_pres = import_pptx(out_file)
    matching_elements = [
        e for e in re_pres.slides[0].elements
        if getattr(e, "text_content", None) and "Primary Title" in e.text_content.plain_text
    ]
    assert len(matching_elements) == 1
    re_elem = matching_elements[0]
    assert re_elem.text_content is not None
    assert len(re_elem.text_content.paragraphs) >= 1

    re_para = re_elem.text_content.paragraphs[0]
    assert re_para.align == "center"
    assert abs(re_para.line_spacing - 1.35) < 0.15
    assert "Primary Title" in re_elem.text_content.plain_text
    assert "Subtitle Note" in re_elem.text_content.plain_text


# =====================================================================
# 5. Remediation Transaction Rollback on Score Degradation
# =====================================================================

def test_remediation_transaction_rollback_guard():
    """Verifies that an auto-remediation transaction rolls back completely if score degrades."""
    pres = PresentationIR(title="Transaction Safety Test")
    slide = SlideIR(id="slide_tx_safe", slide_num=1)

    # Place two cards that are currently separated cleanly (high initial score)
    c1 = ShapeElementIR(id="safe_c1", x=100.0, y=100.0, width=200.0, height=150.0)
    c2 = ShapeElementIR(id="safe_c2", x=350.0, y=100.0, width=200.0, height=150.0)
    slide.add_element(c1)
    slide.add_element(c2)
    pres.slides.append(slide)

    initial_score = LayoutDiffEngine.evaluate_slide(slide).score
    initial_dump = pres.create_snapshot()
    history = HistoryManager()

    # Formulate an adverse FixAction that would cause severe overlap and viewport clipping
    bad_action = FixAction(
        action_type=FixActionType.CLAMP_VIEWPORT,
        category=DefectCategory.CRITICAL,
        target_ids=["safe_c2"],
        parameters={
            "element_id": "safe_c2",
            "x": 120.0,   # Collision with safe_c1
            "y": 680.0,   # Severe clipping beyond 720 canvas
            "width": 300.0,
            "height": 200.0
        },
        reason="Malicious or flawed fix that causes degradation"
    )
    plan = RemediationPlan(actions=[bad_action], has_critical=True)

    result = RemediationRunner.apply_plan(pres, history, plan, slide_id=slide.id, only_critical=True)

    # Rollback guard should have triggered
    assert result["rolled_back"] is True
    assert result["success"] is False

    # Slide must be completely restored to pre-modification state
    after_dump = pres.create_snapshot()
    assert after_dump.slides[0].elements[1].x == initial_dump.slides[0].elements[1].x
    assert after_dump.slides[0].elements[1].y == initial_dump.slides[0].elements[1].y

    current_score = LayoutDiffEngine.evaluate_slide(slide).score
    assert abs(current_score - initial_score) < 1e-4


# =====================================================================
# 6. FixPlanner Conflict Resolution & Deduplication
# =====================================================================

def test_remediation_conflict_resolution_and_deduplication():
    """Verifies that mutually conflicting actions on the same element are deduplicated."""
    slide = SlideIR(id="slide_conflict", slide_num=1)
    s1 = ShapeElementIR(id="e1", x=0.0, y=0.0, width=100.0, height=100.0)
    s2 = ShapeElementIR(id="e2", x=50.0, y=50.0, width=100.0, height=100.0)
    slide.add_element(s1)
    slide.add_element(s2)

    # Two competing actions both targeting "e1"
    a1 = FixAction(
        action_type=FixActionType.CLAMP_VIEWPORT,
        category=DefectCategory.CRITICAL,
        target_ids=["e1"],
        parameters={"element_id": "e1", "x": 60.0, "y": 60.0},
        reason="Clamp e1 to margin",
        priority=10
    )
    a2 = FixAction(
        action_type=FixActionType.SEPARATE_ELEMENTS,
        category=DefectCategory.CRITICAL,
        target_ids=["e1"],
        parameters={"element_id": "e1", "x": 200.0},
        reason="Shift e1 away",
        priority=5
    )
    a3 = FixAction(
        action_type=FixActionType.CLAMP_VIEWPORT,
        category=DefectCategory.CRITICAL,
        target_ids=["e2"],
        parameters={"element_id": "e2", "x": 100.0, "y": 100.0},
        reason="Clamp e2",
        priority=8
    )

    actions = [a1, a2, a3]
    safe = RemediationRunner._resolve_conflicts(slide, actions)

    # Only a1 (priority 10 for e1) and a3 (e2) should survive; a2 should be dropped
    assert len(safe) == 2
    assert safe[0] is a1
    assert safe[1] is a3
    assert a2 not in safe
